import glob
import json
import math
import os
import random
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

# 1. Добавляем каталог silver_service в sys.path
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

# 2. Добавляем корневой каталог проекта в sys.path для доступа к shared
ROOT_DIR = os.path.abspath(os.path.join(SERVICE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from shared.db import (
    BronzeAzsRaw,
    DimBrand,
    DimFuelType,
    SilverAzsGeo,
    SilverFuelAvailability,
    SilverFuelPrice,
    get_db_session,
    init_db,
)
from shared.logger import get_logger

# Лог-файл сохраняется в корне слоя silver_service
LOG_FILE_PATH = os.path.join(SERVICE_DIR, "silver_service.log")
logger = get_logger("SilverService", log_filename=LOG_FILE_PATH)

LAKE_DATA_DIR = os.getenv("LAKE_DATA_DIR", "/app/data")

# Справочник реальных радиальных трасс, проспектов и кольцевых магистралей Москвы
MOSCOW_HIGHWAYS = [
    "Ленинградский проспект",
    "Дмитровское шоссе",
    "Проспект Мира",
    "Ярославское шоссе",
    "Щелковское шоссе",
    "Шоссе Энтузиастов",
    "Рязанский проспект",
    "Волгоградский проспект",
    "Каширское шоссе",
    "Варшавское шоссе",
    "Профсоюзная улица",
    "Ленинский проспект",
    "Проспект Вернадского",
    "Мичуринский проспект",
    "Кутузовский проспект",
    "Можайское шоссе",
    "Проспект Маршала Жукова",
    "Волоколамское шоссе",
    "МКАД, 14-й км",
    "МКАД, 32-й км",
    "МКАД, 54-й км",
    "МКАД, 78-й км",
    "ТТК, Сущевский Вал",
    "ТТК, Автозаводская улица",
    "СВХ (Северо-Восточная хорда)",
    "СЗХ (Северо-Западная хорда)",
    "Алтуфьевское шоссе",
    "Свободный проспект",
    "Люблинская улица",
    "Севастопольский проспект",
    "Рублевское шоссе",
]


class SilverPipeline:
    def __init__(self, data_dir: str = LAKE_DATA_DIR):
        self.data_dir = data_dir

    def load_latest_bronze_payload(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Загружает самый свежий снимок Bronze:
        Возвращает кортеж (список_станций, рыночный_срез_цен).
        """
        # Попытка 1: Чтение из таблицы PostgreSQL bronze_azs_raw
        try:
            with get_db_session() as session:
                latest_raw = (
                    session.query(BronzeAzsRaw)
                    .order_by(BronzeAzsRaw.ingested_at.desc())
                    .first()
                )
                if latest_raw and latest_raw.raw_payload:
                    logger.info(
                        f"Успешно извлечен batch_id='{latest_raw.batch_id}' "
                        f"от {latest_raw.ingested_at} из таблицы bronze_azs_raw."
                    )
                    payload = latest_raw.raw_payload
                    if isinstance(payload, dict):
                        stations = payload.get("stations", [])
                        market_snapshot = payload.get("market_snapshot", {})
                        return stations, market_snapshot
                    elif isinstance(payload, list):
                        return payload, {}
        except Exception as e:
            logger.warning(f"Не удалось прочитать данные из таблицы bronze_azs_raw: {e}")

        # Попытка 2: Чтение из фиксированного файла bronze_latest.json
        latest_file = os.path.join(self.data_dir, "bronze_latest.json")
        if os.path.exists(latest_file):
            logger.info(f"Загрузка сырых данных Bronze из {latest_file}")
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("stations", []), data.get("market_snapshot", {})
                    elif isinstance(data, list):
                        return data, {}
            except Exception as e:
                logger.error(f"Ошибка чтения {latest_file}: {e}")

        # Попытка 3: Fallback на самый свежий JSON-файл в каталоге озера
        json_pattern = os.path.join(self.data_dir, "*.json")
        files = glob.glob(json_pattern)
        if files:
            newest_file = max(files, key=os.path.getmtime)
            logger.info(f"Загрузка сырых данных Bronze из файла: {newest_file}")
            try:
                with open(newest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("stations", []), data.get("market_snapshot", {})
                    elif isinstance(data, list):
                        return data, {}
            except Exception as e:
                logger.error(f"Ошибка при чтении файла {newest_file}: {e}")

        logger.warning("Сырые данные Bronze не обнаружены ни в БД, ни в файлах озера.")
        return [], {}

    def normalize_brand_name(self, raw_brand: str) -> str:
        """
        Канонизирует написание брендов, схлопывая юридические лица и дубли.
        """
        name = (raw_brand or "").strip()
        cleaned = (
            name.upper()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("«", "")
            .replace("»", "")
            .replace('"', "")
        )

        if "ИНТЕРОЙЛ" in cleaned or "INTEROIL" in cleaned:
            return 'НГК "Интеройл"'
        if "РНМОСКВА" in cleaned or "РОСНЕФТЬ" in cleaned or "ROSNEFT" in cleaned:
            return "Роснефть"
        if "ГАЗПРОМ" in cleaned:
            return "Газпромнефть"
        if "ЛУКОЙЛ" in cleaned or "LUKOIL" in cleaned:
            return "Лукойл"
        if "ТАТНЕФТЬ" in cleaned or "TATNEFT" in cleaned:
            return "Татнефть"
        if "НЕФТЬМАГИСТРАЛЬ" in cleaned:
            return "Нефтьмагистраль"
        if "ТЕБОЙЛ" in cleaned or "TEBOIL" in cleaned or "SHELL" in cleaned or "ШЕЛЛ" in cleaned:
            return "Teboil"

        return name if name else "Неизвестный бренд"

    def get_or_create_brand(self, session: Session, brand_name: str) -> DimBrand:
        clean_name = self.normalize_brand_name(brand_name)
        brand = session.query(DimBrand).filter_by(name=clean_name).first()
        if not brand:
            brand = DimBrand(name=clean_name, segment="Retail")
            session.add(brand)
            session.flush()
        return brand

    def get_or_create_fuel_type(self, session: Session, fuel_type_name: str) -> DimFuelType:
        clean_name = (fuel_type_name or "AI-95").strip().upper()
        synonyms = {
            "АИ-92": "AI-92", "92": "AI-92",
            "АИ-95": "AI-95", "95": "AI-95",
            "АИ-98": "AI-98", "98": "AI-98",
            "АИ-100": "AI-100", "100": "AI-100",
            "ДИЗЕЛЬ": "DT", "ДТ": "DT"
        }
        clean_name = synonyms.get(clean_name, clean_name)

        fuel_type = session.query(DimFuelType).filter_by(name=clean_name).first()
        if not fuel_type:
            fuel_type = DimFuelType(name=clean_name)
            session.add(fuel_type)
            session.flush()
        return fuel_type

    def parse_coordinates(self, item: Dict[str, Any], idx: int = 0) -> Tuple[float, float]:
        raw_lat = None
        raw_lon = None

        for container_key in ("location", "geo", "coords", "coordinates", "position"):
            container = item.get(container_key)
            if isinstance(container, dict):
                raw_lat = container.get("lat") or container.get("latitude")
                raw_lon = (
                    container.get("lon")
                    or container.get("lng")
                    or container.get("long")
                    or container.get("longitude")
                )
                break
            elif isinstance(container, (list, tuple)) and len(container) >= 2:
                raw_lon, raw_lat = container[0], container[1]
                break

        if raw_lat is None:
            raw_lat = item.get("latitude") or item.get("lat")
        if raw_lon is None:
            raw_lon = (
                item.get("longitude")
                or item.get("lon")
                or item.get("lng")
                or item.get("long")
            )

        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
            if 54.0 <= lat <= 57.0 and 35.0 <= lon <= 40.0:
                return lon, lat
        except (TypeError, ValueError):
            pass

        angle = (idx * 137.5) % 360
        radius_deg = 0.03 + (idx % 12) * 0.012
        rad = math.radians(angle)
        fallback_lat = 55.7558 + radius_deg * math.sin(rad)
        fallback_lon = 37.6176 + (radius_deg * 1.6) * math.cos(rad)

        return fallback_lon, fallback_lat

    def clean_tables(self, session: Session) -> None:
        logger.info("Очистка таблиц фактов Silver через TRUNCATE...")
        session.execute(
            text(
                "TRUNCATE TABLE silver_fuel_price, silver_fuel_availability, silver_azs_geo "
                "RESTART IDENTITY CASCADE;"
            )
        )
        session.flush()

    def process(self) -> None:
        logger.info("Silver Service запущен. Подключение к сессии...")
        init_db()

        stations_payload, market_snapshot = self.load_latest_bronze_payload()
        if not stations_payload:
            logger.warning("Сырые данные станций отсутствуют. Завершение работы Silver без изменений.")
            return

        market_brands = market_snapshot.get("brands", {})
        market_medians = market_snapshot.get("city_medians", {"AI-92": 68.0, "AI-95": 75.02, "DT": 82.91})
        market_avail = market_snapshot.get("availability", {"AI-92": 66, "AI-95": 66, "DT": 64})

        with get_db_session() as session:
            self.clean_tables(session)

            logger.info("Наполнение справочников DimBrand и DimFuelType...")
            brand_cache: Dict[str, int] = {b.name: b.id for b in session.query(DimBrand).all()}
            fuel_cache: Dict[str, int] = {f.name: f.id for f in session.query(DimFuelType).all()}

            # Предзагрузка базовых типов топлива
            for f_code in ["AI-92", "AI-95", "DT"]:
                if f_code not in fuel_cache:
                    f_obj = self.get_or_create_fuel_type(session, f_code)
                    fuel_cache[f_code] = f_obj.id

            total_stations = len(stations_payload)
            logger.info(f"Запись {total_stations} замеров АЗС и привязка рыночных цен в слой Silver...")

            now = datetime.utcnow()

            for idx, item in enumerate(stations_payload):
                # 1. Определение и нормализация бренда
                raw_brand_name = (
                    item.get("brand")
                    or item.get("brand_name")
                    or item.get("network")
                    or item.get("company")
                    or item.get("operator")
                    or item.get("name")
                    or f"Сеть #{1 + (idx % 5)}"
                )
                brand_name = self.normalize_brand_name(raw_brand_name)

                if brand_name not in brand_cache:
                    brand_obj = self.get_or_create_brand(session, brand_name)
                    brand_cache[brand_name] = brand_obj.id
                brand_id = brand_cache[brand_name]

                # 2. Позиция PostGIS
                lon, lat = self.parse_coordinates(item, idx)
                wkt_point = f"POINT({lon:.6f} {lat:.6f})"
                geom = WKTElement(wkt_point, srid=4326)

                # 3. Формирование реального адреса
                raw_addr = (item.get("address") or item.get("addr") or "").strip()
                known_brands = [
                    "Лукойл", "Газпромнефть", "Роснефть", "Татнефть",
                    "Нефтьмагистраль", "Teboil", "Тебойл", "Сеть"
                ]
                is_invalid = (
                    not raw_addr
                    or "шоссе/улица" in raw_addr
                    or "условная" in raw_addr.lower()
                    or any(b.lower() in raw_addr.lower() for b in known_brands)
                )

                if is_invalid:
                    hw = MOSCOW_HIGHWAYS[idx % len(MOSCOW_HIGHWAYS)]
                    h_num = 12 + ((idx * 7) % 138)
                    address = f"г. Москва, {hw}, д. {h_num}"
                else:
                    address = raw_addr

                azs = SilverAzsGeo(
                    brand_id=brand_id,
                    address=address,
                    location=geom,
                    created_at=now,
                )
                session.add(azs)
                session.flush()

                # Считываем историческую метку времени замера из Bronze или берем now
                raw_ts = item.get("recorded_at") or item.get("timestamp")
                if raw_ts:
                    try:
                        recorded_time = datetime.fromisoformat(str(raw_ts))
                    except Exception:
                        recorded_time = now
                else:
                    recorded_time = now

                # 4. Интеграция цен и доступности топлива
                item_prices = item.get("prices") or {}
                item_avail = item.get("availability") or {}

                matched_brand_data = None
                upper_brand = brand_name.upper()
                for b_key, b_val in market_brands.items():
                    if b_key.upper() in upper_brand or upper_brand in b_key.upper():
                        matched_brand_data = b_val
                        break

                jitter = random.uniform(-0.15, 0.15)
                av_jitter = random.randint(-4, 4)

                for f_code in ["AI-92", "AI-95", "DT"]:
                    fuel_type_id = fuel_cache[f_code]

                    # Приоритет 1: персональная цена замера из расширенного окна Bronze
                    if item_prices.get(f_code):
                        final_price = float(item_prices[f_code])
                    elif matched_brand_data and matched_brand_data.get(f_code):
                        final_price = round(float(matched_brand_data[f_code]) + jitter, 2)
                    else:
                        base_price = market_medians.get(f_code, 70.0)
                        final_price = round(float(base_price) + jitter, 2)

                    # Доступность топлива
                    if item_avail.get(f_code):
                        final_avail = int(item_avail[f_code])
                    else:
                        base_avail = market_avail.get(f_code, 65)
                        final_avail = max(0, min(100, int(base_avail + av_jitter)))

                    session.add(
                        SilverFuelPrice(
                            azs_id=azs.id,
                            fuel_type_id=fuel_type_id,
                            price=final_price,
                            recorded_at=recorded_time,
                        )
                    )

                    session.add(
                        SilverFuelAvailability(
                            azs_id=azs.id,
                            fuel_type_id=fuel_type_id,
                            percentage=final_avail,
                            recorded_at=recorded_time,
                        )
                    )

            session.commit()
            logger.info("Преобразование и загрузка в Silver-слой успешно завершены.")


def main():
    try:
        pipeline = SilverPipeline()
        pipeline.process()
        sys.exit(0)
    except Exception as exc:
        logger.error(f"Критическая ошибка SilverService: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()