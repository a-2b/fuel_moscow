import sys
import random
import logging
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta

# Обеспечиваем доступность модуля scripts
if '/opt/airflow' not in sys.path:
    sys.path.append('/opt/airflow')

from scripts.fuel_parser import get_consolidated_market_snapshot

logger = logging.getLogger("airflow.task")

def extract_fuel_market_data(**context):
    """Сбор консолидированных данных с МТА и Бензонавта."""
    snapshot = get_consolidated_market_snapshot()
    logger.info("Рыночный срез успешно сформирован: %s", snapshot['city_medians'])
    context['ti'].xcom_push(key='fuel_market_snapshot', value=snapshot)

def transform_and_load_silver(**context):
    """
    Привязка цен и уровней наличия к станциям silver_azs_geo 
    с сохранением в silver_fuel_price и silver_fuel_availability.
    """
    snapshot = context['ti'].xcom_pull(key='fuel_market_snapshot', task_ids='extract_fuel_market_data')
    if not snapshot:
        raise ValueError("XCom 'fuel_market_snapshot' пуст!")

    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    # Справочник типов топлива
    cursor.execute("SELECT id, name FROM dim_fuel_type;")
    fuel_map = {name: f_id for f_id, name in cursor.fetchall()}

    # Все станции из слоя Silver
    cursor.execute("""
        SELECT a.id, b.name as brand
        FROM silver_azs_geo a
        JOIN dim_brand b ON a.brand_id = b.id;
    """)
    stations = cursor.fetchall()

    brands_data = snapshot.get('brands', {})
    medians = snapshot.get('city_medians', {})
    avail_data = snapshot.get('availability', {})

    now = datetime.now()
    price_records = []
    avail_records = []

    for azs_id, brand in stations:
        clean_brand = str(brand).strip().upper()
        # Ищем бренд в спарсенных данных
        b_info = None
        for b_name, data in brands_data.items():
            if b_name in clean_brand:
                b_info = data
                break

        # Микро-разброс по конкретной станции в рамках сети
        jitter = random.uniform(-0.15, 0.15)
        av_jitter = random.randint(-6, 6)

        for fuel_code in ['AI-92', 'AI-95', 'DT']:
            fuel_id = fuel_map.get(fuel_code)
            if not fuel_id:
                continue

            # 1. Расчет цены
            if b_info and b_info.get(fuel_code):
                base_price = b_info[fuel_code]
            else:
                base_price = medians.get(fuel_code, 70.0)
            final_price = round(base_price + jitter, 2)
            price_records.append((azs_id, fuel_id, final_price, now))

            # 2. Расчет наличия топлива (%)
            city_av = avail_data.get(fuel_code, 65)
            final_avail = max(0, min(100, city_av + av_jitter))
            avail_records.append((azs_id, fuel_id, final_avail, now))

    # Пакетная вставка в silver_fuel_price
    cursor.executemany("""
        INSERT INTO silver_fuel_price (azs_id, fuel_type_id, price, recorded_at)
        VALUES (%s, %s, %s, %s);
    """, price_records)

    # Пакетная вставка в silver_fuel_availability
    cursor.executemany("""
        INSERT INTO silver_fuel_availability (azs_id, fuel_type_id, in_stock, recorded_at)
        VALUES (%s, %s, %s, %s);
    """, avail_records)

    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Сохранено %d записей цен и %d записей остатков топлива.", len(price_records), len(avail_records))