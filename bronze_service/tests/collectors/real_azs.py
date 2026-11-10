import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RealAzsCollector:
    """
    Коллектор реальных АЗС Москвы на основе подготовленного датасета OSM.
    """

    def __init__(self, data_path: str = None):
        possible_paths = [
            data_path,
            "/app/real_moscow_azs.json",
            "/app/data/real_moscow_azs.json",
            "real_moscow_azs.json",
        ]
        self.data_path = next((p for p in possible_paths if p and os.path.exists(p)), "/app/real_moscow_azs.json")

    def collect(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"Файл с геоданными OSM не найден: {self.data_path}")

        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_stations = data.get("stations", data) if isinstance(data, dict) else data

        stations = []
        for idx, item in enumerate(raw_stations[:120], start=1):
            coords = item.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
            else:
                lon = item.get("lon") or item.get("longitude") or 37.6176
                lat = item.get("lat") or item.get("latitude") or 55.7558

            stations.append({
                "azs_id": item.get("azs_id", idx),
                "brand": item.get("brand") or item.get("brand_name") or "РОСНЕФТЬ",
                "address": item.get("address") or item.get("addr") or f"г. Москва, шоссе {idx}",
                "coordinates": [float(lon), float(lat)],
            })

        logger.info(f"Собрано {len(stations)} реальных станций OSM из {self.data_path}.")
        return stations