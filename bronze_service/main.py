import json
import os
import sys
import uuid
from datetime import datetime

# 1. Добавляем каталог bronze_service в sys.path для разрешения локальных модулей src и fuel_parser
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

# 2. Добавляем корневой каталог проекта в sys.path для доступа к модулю shared
ROOT_DIR = os.path.abspath(os.path.join(SERVICE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from shared.db import BronzeAzsRaw, get_db_session, init_db
from shared.logger import get_logger
from src.collectors.generate_mock_data import MockAzsCollector
from src.collectors.real_azs import RealAzsCollector
from fuel_parser import get_consolidated_market_snapshot

# Лог-файл сохраняется в корне слоя bronze_service
LOG_FILE_PATH = os.path.join(SERVICE_DIR, "bronze_service.log")
logger = get_logger("BronzeService", log_filename=LOG_FILE_PATH)

LAKE_DATA_DIR = os.getenv("LAKE_DATA_DIR", "/app/data")


def save_to_bronze(data: list, market_snapshot: dict = None) -> None:
    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()

    payload = {
        "stations": data,
        "count": len(data),
        "market_snapshot": market_snapshot or {}
    }

    # 1. Запись сырых данных в PostgreSQL (таблица bronze_azs_raw)
    try:
        init_db()
        with get_db_session() as session:
            record = BronzeAzsRaw(
                batch_id=batch_id,
                source_type="market_and_azs_collector",
                raw_payload=payload,
                ingested_at=now,
            )
            session.add(record)
        logger.info(f"Успешно сохранен batch_id='{batch_id}' ({len(data)} записей) в таблицу bronze_azs_raw.")
    except Exception as e:
        logger.error(f"Не удалось записать в PostgreSQL bronze_azs_raw: {e}", exc_info=True)
        raise

    # 2. Сохранение снимка в смонтированный том озера данных
    try:
        os.makedirs(LAKE_DATA_DIR, exist_ok=True)
        
        # Исторический файл партии
        batch_file_path = os.path.join(LAKE_DATA_DIR, f"bronze_{batch_id[:8]}.json")
        with open(batch_file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # Стабильный указатель для silver_service
        latest_file_path = os.path.join(LAKE_DATA_DIR, "bronze_latest.json")
        with open(latest_file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"Снимки данных озера сохранены: {batch_file_path} и {latest_file_path}")
    except Exception as e:
        logger.warning(f"Не удалось записать файлы в {LAKE_DATA_DIR}: {e}")

    logger.info(f"Успешно сохранено {len(data)} станций и рыночный срез цен в слой Bronze.")


def main():
    env = os.getenv("APP_ENV", "development").lower()
    logger.info(f"Запуск конвейера Bronze. Режим: {env.upper()}")

    # 1. Сбор станций (гео/инвентарь)
    if env == "production":
        collector = RealAzsCollector()
    else:
        collector = MockAzsCollector()

    try:
        raw_stations = collector.collect()
        logger.info("Собрано %d станций через %s.", len(raw_stations), collector.__class__.__name__)
    except Exception as e:
        logger.error(f"Сбой сбора станций: {e}", exc_info=True)
        sys.exit(1)

    # 2. Сбор цен и доступности топлива с МТА и Бензонавта
    try:
        logger.info("Запуск парсера рыночных цен (МТА + Бензонавт)...")
        market_snapshot = get_consolidated_market_snapshot()
        logger.info("Рыночный срез успешно сформирован: %s", market_snapshot.get("city_medians"))
    except Exception as e:
        logger.warning(f"Сбой парсера рыночных цен: {e}. Продолжение с пустым срезом.")
        market_snapshot = {}

    # 3. Сохранение сырых данных в Bronze
    try:
        save_to_bronze(data=raw_stations, market_snapshot=market_snapshot)
    except Exception as e:
        logger.error(f"Сбой сохранения в Bronze: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()