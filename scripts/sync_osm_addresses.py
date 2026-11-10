import time
import requests
from sqlalchemy import create_engine, text

# Параметры подключения к вашей БД PostGIS
DB_URL = "postgresql+psycopg2://fuel_admin:fuel_secret_pass@postgres_db:5432/fuel_moscow_db"
engine = create_engine(DB_URL)

headers = {
    'User-Agent': 'MoscowFuelMonitoringSystem/1.0 (academic_vkr_project)'
}

with engine.connect() as conn:
    # Извлекаем ID и реальные координаты (долгота, широта)
    query = text("""
        SELECT 
            id, 
            ST_Y(location::geometry) AS lat, 
            ST_X(location::geometry) AS lon,
            address
        FROM silver_azs_geo
        ORDER BY id;
    """)
    stations = conn.execute(query).fetchall()
    print(f"Найдено станций для геопривязки: {len(stations)}")

    update_query = text("""
        UPDATE silver_azs_geo 
        SET address = :address 
        WHERE id = :id;
    """)

    for st in stations:
        st_id, lat, lon, old_addr = st
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=ru"
        
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                address_data = data.get('address', {})
                
                # Собираем лаконичный реальный адрес
                road = address_data.get('road') or address_data.get('street') or address_data.get('pedestrian')
                house = address_data.get('house_number', '')
                suburb = address_data.get('suburb') or address_data.get('city_district', '')
                
                if road and house:
                    real_address = f"г. Москва, {road}, д. {house}"
                elif road:
                    real_address = f"г. Москва, {road}"
                elif suburb:
                    real_address = f"г. Москва, район {suburb}"
                else:
                    real_address = data.get('display_name', '').split(',')[0]
                
                # Обновляем запись в БД
                conn.execute(update_query, {"address": real_address, "id": st_id})
                conn.commit()
                print(f"[{st_id}] {lat:.4f}, {lon:.4f} -> {real_address}")
            else:
                print(f"[{st_id}] Ошибка Nominatim: {resp.status_code}")
        except Exception as e:
            print(f"[{st_id}] Ошибка запроса: {e}")

        # Пауза 1 сек для соблюдения лимитов бесплатного OSM Nominatim API
        time.sleep(1)

print("Геопривязка адресов успешно завершена!")