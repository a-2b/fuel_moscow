from shapely.geometry import Point
from shared.logger import get_logger

logger = get_logger(__name__)

class GeoProcessor:
    # Приблизительный Bounding Box Москвы и ближнего Подмосковья
    MIN_LAT, MAX_LAT = 55.4, 56.0
    MIN_LON, MAX_LON = 37.1, 38.0

    @classmethod
    def is_valid_moscow_location(cls, lat: float, lon: float) -> bool:
        """Проверка попадания координат в заданный квадрат."""
        return (cls.MIN_LAT <= lat <= cls.MAX_LAT) and (cls.MIN_LON <= lon <= cls.MAX_LON)

    @classmethod
    def to_wkt(cls, lat: float, lon: float) -> str:
        """Преобразует координаты в формат Well-Known Text для PostGIS."""
        # Обратите внимание: WKT использует формат POINT(lon lat)
        pt = Point(lon, lat)
        return pt.wkt