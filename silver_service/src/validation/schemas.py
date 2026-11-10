from pydantic import BaseModel, Field, validator
from typing import Dict, Optional

class CoordinatesSchema(BaseModel):
    lat: float = Field(..., description="Широта")
    lon: float = Field(..., description="Долгота")

class AzsRawSchema(BaseModel):
    """Схема ожидаемых данных от сборщика real_azs_retail."""
    station_brand: str
    address_raw: str
    coordinates: Optional[CoordinatesSchema] = None
    prices: Dict[str, float]
    timestamp_unix: int
    is_fallback: bool = False

    @validator("prices")
    def validate_prices(cls, prices):
        """Базовая фильтрация экстремальных выбросов (Quality Check)."""
        clean_prices = {}
        for fuel_type, price in prices.items():
            # Отсекаем явный мусор (цена меньше 30 или больше 100 руб)
            if 30.0 <= price <= 100.0:
                clean_prices[fuel_type] = price
        return clean_prices