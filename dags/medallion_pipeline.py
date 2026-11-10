import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

# Базовый путь проекта на хост-машине (Windows)
# Для Docker демона пути с прямыми слешами 'C:/...' являются наиболее совместимыми
HOST_PROJECT_DIR = os.getenv("HOST_PROJECT_DIR", "C:/fuel_moscow").replace("\\", "/")

# Параметры подключения к инфраструктуре Medallion
APP_ENV = os.getenv("APP_ENV", "production")
POSTGRES_USER = os.getenv("POSTGRES_USER", "fuel_admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fuel_secret_pass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "fuel_moscow_db")
POSTGRES_HOST = "moscow_fuel_postgres"

# Единый блок переменных окружения для всех контейнеров
COMMON_ENV = {
    "APP_ENV": APP_ENV,
    "POSTGRES_HOST": POSTGRES_HOST,
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": POSTGRES_USER,
    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
    "POSTGRES_DB": POSTGRES_DB,
    "DATABASE_URL": f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:5432/{POSTGRES_DB}",
    "PYTHONPATH": "/app",
    "LAKE_DATA_DIR": "/app/data",
}

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2026, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="fuel_moscow_medallion_pipeline",
    default_args=default_args,
    description="Сквозной пайплайн Medallion (Bronze -> Silver -> Gold)",
    schedule_interval="@hourly",
    catchup=False,
    max_active_runs=1,
) as dag:

    bronze_task = DockerOperator(
        task_id="bronze_collect_raw",
        image="fuel_moscow-bronze_service:latest",
        container_name="airflow_run_bronze",
        api_version="auto",
        auto_remove=True,
        mount_tmp_dir=False,
        command="python -m bronze_service.main",
        docker_url="unix://var/run/docker.sock",
        network_mode="fuel_network",
        environment=COMMON_ENV,
        mounts=[
            Mount(source="fuel_moscow_lake_data", target="/app/data", type="volume"),
            # Сквозное сохранение bronze_service.log на диск хоста
            Mount(
                source=f"{HOST_PROJECT_DIR}/bronze_service",
                target="/app/bronze_service",
                type="bind",
            ),
        ],
    )

    silver_task = DockerOperator(
        task_id="silver_transform_and_load",
        image="fuel_moscow-silver_service:latest",
        container_name="airflow_run_silver",
        api_version="auto",
        auto_remove=True,
        mount_tmp_dir=False,
        command="python -m silver_service.main",
        docker_url="unix://var/run/docker.sock",
        network_mode="fuel_network",
        environment=COMMON_ENV,
        mounts=[
            Mount(source="fuel_moscow_lake_data", target="/app/data", type="volume"),
            # Сквозное сохранение silver_service.log на диск хоста
            Mount(
                source=f"{HOST_PROJECT_DIR}/silver_service",
                target="/app/silver_service",
                type="bind",
            ),
        ],
    )

    gold_task = DockerOperator(
        task_id="gold_analytics_and_report",
        image="fuel_moscow-gold_service:latest",
        container_name="airflow_run_gold",
        api_version="auto",
        auto_remove=True,
        mount_tmp_dir=False,
        command="python -m gold_service.main",
        docker_url="unix://var/run/docker.sock",
        network_mode="fuel_network",
        environment=COMMON_ENV,
        mounts=[
            Mount(source="fuel_moscow_lake_data", target="/app/data", type="volume"),
            # Сквозное сохранение gold_service.log на диск хоста
            Mount(
                source=f"{HOST_PROJECT_DIR}/gold_service",
                target="/app/gold_service",
                type="bind",
            ),
        ],
    )

    bronze_task >> silver_task >> gold_task