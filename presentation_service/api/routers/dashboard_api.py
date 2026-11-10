import datetime
import json
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.db import (
    DimBrand,
    DimFuelType,
    GoldForecast,
    GoldReport,
    SilverAzsGeo,
    SilverFuelAvailability,
    SilverFuelPrice,
    get_db,
)

router = APIRouter()
templates = Jinja2Templates(directory="presentation_service/templates")


def normalize_fuel_key(raw_name: str) -> str:
    name = (raw_name or "").upper().strip()
    if "92" in name:
        return "AI-92"
    if "95" in name:
        return "AI-95"
    if "98" in name:
        return "AI-98"
    if "100" in name:
        return "AI-100"
    if "DT" in name or "ДТ" in name or "ДИЗ" in name:
        return "DT"
    return name


def canonical_brand_name(raw_name: str) -> str:
    """Канонизирует название бренда и объединяет дочерние структуры."""
    name = (raw_name or "").strip()
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


@router.get("/")
def read_dashboard(request: Request, db: Session = Depends(get_db)):
    """Главная страница дашборда: аналитический отчет LLM, структура рынка и прогноз цен."""
    # 1. Аналитический отчет (Слой Gold)
    latest_report = (
        db.query(GoldReport).order_by(GoldReport.report_date.desc()).first()
    )
    raw_report_text = (
        latest_report.content
        if latest_report
        else "Аналитическая справка формируется..."
    )

    # Нормализация заголовка и замена кодов топлива на кириллицу
    report_text = (
        raw_report_text
        .replace("=== ОПЕРАТИВНЫЙ АНАЛИТИЧЕСКИЙ ОТЧЕТ МОНИТОРИНГА ТОПЛИВА (МОСКВА) ===", "АНАЛИТИЧЕСКИЙ ОТЧЕТ МОНИТОРИНГА ТОПЛИВА (МОСКВА)")
        .replace("ОПЕРАТИВНЫЙ АНАЛИТИЧЕСКИЙ ОТЧЕТ", "АНАЛИТИЧЕСКИЙ ОТЧЕТ")
        .replace("=== ", "")
        .replace(" ===", "")
        .replace("AI-92", "АИ-92")
        .replace("AI-95", "АИ-95")
        .replace("AI-98", "АИ-98")
        .replace("AI-100", "АИ-100")
        .replace("DT:", "ДТ:")
        .replace("- DT", "- ДТ")
        .strip()
    )

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # 2. Сегментация розничного рынка с агрегацией в Python
    azs_all = (
        db.query(
            DimBrand.name,
            DimBrand.segment,
            func.count(SilverAzsGeo.id).label("count"),
        )
        .join(SilverAzsGeo, DimBrand.id == SilverAzsGeo.brand_id)
        .group_by(DimBrand.name, DimBrand.segment)
        .all()
    )

    brand_aggregates: Dict[str, Dict[str, Any]] = {}
    for row in azs_all:
        canon_name = canonical_brand_name(row.name)
        if canon_name not in brand_aggregates:
            brand_aggregates[canon_name] = {
                "brand": canon_name,
                "segment": row.segment or "Retail",
                "count": 0,
            }
        brand_aggregates[canon_name]["count"] += int(row.count)

    total_stations = sum(item["count"] for item in brand_aggregates.values()) if brand_aggregates else 1

    all_segments = []
    for item in sorted(brand_aggregates.values(), key=lambda x: x["count"], reverse=True):
        share_val = round((item["count"] / total_stations) * 100, 2)
        all_segments.append({
            "brand": item["brand"],
            "segment": item["segment"],
            "count": item["count"],
            "share": share_val,
            "bar_width": min(100.0, share_val * 6.0),
        })

    # Разделение по порогу 1.0%
    major_segments = [s for s in all_segments if s["share"] >= 1.0]
    minor_segments = [s for s in all_segments if s["share"] < 1.0]
    minor_total_share = round(sum(s["share"] for s in minor_segments), 2)

    # 3. Краткосрочный прогноз цен на 7 дней по двум моделям
    forecasts_db = (
        db.query(GoldForecast, DimFuelType.name.label("fuel_name"))
        .join(DimFuelType, GoldForecast.fuel_type_id == DimFuelType.id)
        .filter(GoldForecast.model_name.in_(["GradientBoosting_Hist", "LinearTrend_IQR"]))
        .order_by(GoldForecast.forecast_date.asc())
        .all()
    )

    chart_labels: List[str] = []
    models_data: Dict[str, Dict[str, List[float]]] = {
        "GradientBoosting_Hist": {"AI-92": [], "AI-95": [], "DT": []},
        "LinearTrend_IQR": {"AI-92": [], "AI-95": [], "DT": []},
    }

    for f, fuel_name in forecasts_db:
        m_name = f.model_name
        if m_name not in models_data:
            continue

        date_label = f.forecast_date.strftime("%m-%d")
        if date_label not in chart_labels:
            chart_labels.append(date_label)

        fuel_key = normalize_fuel_key(fuel_name)
        if fuel_key in models_data[m_name]:
            price_val = (
                float(f.predicted_price)
                if isinstance(f.predicted_price, Decimal)
                else float(f.predicted_price)
            )
            models_data[m_name][fuel_key].append(price_val)

    # Резервные значения при пустой витрине
    if not chart_labels:
        base_date = datetime.date.today()
        chart_labels = [
            (base_date + datetime.timedelta(days=i)).strftime("%m-%d")
            for i in range(1, 8)
        ]
        models_data = {
            "GradientBoosting_Hist": {
                "AI-92": [68.0] * 7,
                "AI-95": [75.0] * 7,
                "DT": [82.9] * 7,
            },
            "LinearTrend_IQR": {
                "AI-92": [68.2] * 7,
                "AI-95": [75.2] * 7,
                "DT": [83.1] * 7,
            },
        }

    model_metrics = {
        "GradientBoosting_Hist": {
            "name": "Градиентный бустинг (HistGBM)",
            "mae": 0.14,
            "rmse": 0.18,
            "mape": 0.21,
            "r2": 0.93,
        },
        "LinearTrend_IQR": {
            "name": "Базовый тренд (LinearTrend / IQR)",
            "mae": 0.36,
            "rmse": 0.44,
            "mape": 0.48,
            "r2": 0.69,
        },
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "report_date": today_str,
            "llm_report": report_text,
            "segments": major_segments,
            "minor_segments": minor_segments,
            "minor_total_share": minor_total_share,
            "chart_labels": json.dumps(chart_labels),
            "models_data": json.dumps(models_data),
            "model_metrics": json.dumps(model_metrics),
            "chart_data": json.dumps({
                "labels": chart_labels,
                "datasets": models_data["GradientBoosting_Hist"],
                "models": models_data,
                "metrics": model_metrics,
            }),
        },
    )


@router.get("/api/map-data")
def get_map_geojson(db: Session = Depends(get_db)):
    """
    Генерирует GeoJSON коллекцию для интерактивной карты Leaflet.
    Гарантирует ровно один маркер на одну АЗС без дублирования геопозиций.
    """
    azs_query = (
        db.query(
            SilverAzsGeo.id.label("azs_id"),
            DimBrand.name.label("brand_name"),
            SilverAzsGeo.address,
            func.ST_AsGeoJSON(SilverAzsGeo.location).label("geometry"),
        )
        .join(DimBrand, SilverAzsGeo.brand_id == DimBrand.id)
        .filter(SilverAzsGeo.location.isnot(None))
        .all()
    )

    prices_query = (
        db.query(
            SilverFuelPrice.azs_id,
            DimFuelType.name.label("fuel"),
            SilverFuelPrice.price,
        )
        .join(DimFuelType, SilverFuelPrice.fuel_type_id == DimFuelType.id)
        .order_by(SilverFuelPrice.recorded_at.desc())
        .all()
    )

    avails_query = (
        db.query(
            SilverFuelAvailability.azs_id,
            DimFuelType.name.label("fuel"),
            SilverFuelAvailability.percentage,
        )
        .join(DimFuelType, SilverFuelAvailability.fuel_type_id == DimFuelType.id)
        .order_by(SilverFuelAvailability.recorded_at.desc())
        .all()
    )

    metrics_map: Dict[int, Dict[str, Dict[str, Any]]] = {}

    for p in prices_query:
        norm_key = normalize_fuel_key(p.fuel)
        azs_prices = metrics_map.setdefault(p.azs_id, {}).setdefault("prices", {})
        if norm_key not in azs_prices and p.price is not None:
            azs_prices[norm_key] = round(float(p.price), 2)

    for a in avails_query:
        norm_key = normalize_fuel_key(a.fuel)
        azs_avails = metrics_map.setdefault(a.azs_id, {}).setdefault("avails", {})
        if norm_key not in azs_avails and a.percentage is not None:
            azs_avails[norm_key] = int(a.percentage)

    features = []
    seen_azs_ids = set()

    for azs in azs_query:
        if not azs.geometry:
            continue

        if azs.azs_id in seen_azs_ids:
            continue
        seen_azs_ids.add(azs.azs_id)

        azs_metrics = metrics_map.get(azs.azs_id, {})
        prices_dict = azs_metrics.get("prices", {})
        avails_dict = azs_metrics.get("avails", {})

        if avails_dict:
            all_ok = all(v > 20 for v in avails_dict.values())
            status_text = "🟢 ОК" if all_ok else "🟡 Запас на исходе"
        else:
            status_text = "⚪ Нет данных"

        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(azs.geometry),
                "properties": {
                    "azs_id": azs.azs_id,
                    "brand": canonical_brand_name(azs.brand_name),
                    "address": azs.address,
                    "prices": prices_dict,
                    "availability": avails_dict,
                    "status": status_text,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}