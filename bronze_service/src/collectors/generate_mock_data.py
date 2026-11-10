import random
from datetime import datetime, timezone

class MockAzsCollector:
    """Генератор синтетических данных для режима разработки"""
    
    def __init__(self):
        self.brands = [
            {"name": "РОСНЕФТЬ", "segment": "Premium"},
            {"name": "ЛУКОЙЛ", "segment": "Premium"},
            {"name": "ГАЗПРОМНЕФТЬ", "segment": "Premium"},
            {"name": "ТАТНЕФТЬ", "segment": "Medium"},
            {"name": "НЕФТЬМАГИСТРАЛЬ", "segment": "Medium"},
            {"name": "ТЕБОЙЛ", "segment": "Medium"}
        ]
        # Границы Москвы для генерации координат
        self.lat_min, self.lat_max = 55.55, 55.90
        self.lon_min, self.lon_max = 37.35, 37.85

    def collect(self) -> list:
        data = []
        for i in range(1, 121):
            brand = random.choice(self.brands)
            
            # Генерация базовых цен с небольшим случайным отклонением
            base_92 = round(random.uniform(52.50, 54.10), 2)
            base_95 = round(random.uniform(57.80, 60.50), 2)
            base_dt = round(random.uniform(65.50, 68.20), 2)
            
            # Строгий стандарт координат [Lon, Lat] для Pydantic схемы Silver слоя
            lon = round(random.uniform(self.lon_min, self.lon_max), 6)
            lat = round(random.uniform(self.lat_min, self.lat_max), 6)

            data.append({
                "azs_id": i,
                "brand_name": brand["name"],
                "segment": brand["segment"],
                "address": f"г. Москва, условная ул., {i}",
                "coordinates": [lon, lat], 
                "prices": {
                    "АИ-92": base_92,
                    "АИ-95": base_95,
                    "ДТ": base_dt
                },
                "availability": {
                    "АИ-92": random.randint(10, 100),
                    "АИ-95": random.randint(10, 100),
                    "ДТ": random.randint(10, 100)
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        return data