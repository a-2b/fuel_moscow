import random
import time
from typing import Dict, Any, List
from .base import BaseCollector

class AzsMockCollector(BaseCollector):
    """Сборщик-заглушка, имитирующий получение данных об АЗС и ценах."""
    
    def __init__(self):
        super().__init__(source_name="azs_mock_api")
        self.brands = [
            {"name": "РОСНЕФТЬ", "segment": "Premium"},
            {"name": "ЛУКОЙЛ", "segment": "Premium"},
            {"name": "ГАЗПРОМНЕФТЬ", "segment": "Premium"},
            {"name": "ТАТНЕФТЬ", "segment": "Medium"},
            {"name": "НЕФТЬМАГИСТРАЛЬ", "segment": "Medium"},
            {"name": "ТЕБОЙЛ", "segment": "Medium"}
        ]
        # Границы Москвы
        self.lat_min, self.lat_max = 55.55, 55.90
        self.lon_min, self.lon_max = 37.35, 37.85

    def fetch_data(self) -> List[Dict[str, Any]]:
        """Генерирует фейковые сырые данные для 120 АЗС Москвы."""
        fuel_types = ["АИ-92", "АИ-95", "ДТ"]
        
        data = []
        for i in range(1, 121): # Генерируем 120 записей
            brand_info = random.choice(self.brands)
            
            lat = round(random.uniform(self.lat_min, self.lat_max), 6)
            lon = round(random.uniform(self.lon_min, self.lon_max), 6)
            
            record = {
                "azs_id": i,
                "station_brand": brand_info["name"],
                "segment": brand_info["segment"],
                "address_raw": f"г. Москва, ул. Примерная, д. {i}",
                "coordinates": {"lat": lat, "lon": lon},
                "prices": {
                    "АИ-92": round(random.uniform(52.50, 54.10), 2),
                    "АИ-95": round(random.uniform(57.80, 60.50), 2),
                    "ДТ": round(random.uniform(65.50, 68.20), 2)
                },
                "availability": {
                    "АИ-92": random.randint(15, 100),
                    "АИ-95": random.randint(15, 100),
                    "ДТ": random.randint(15, 100)
                },
                "status": "online",
                "timestamp_unix": int(time.time())
            }
            data.append(record)
            
        return data