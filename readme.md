# Мониторинг рынка топлива г. Москвы

[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![PostGIS](https://img.shields.io/badge/PostGIS-3.3+-green?logo=postgis&logoColor=white)](https://postgis.net/)
[![Apache Airflow](https://img.shields.io/badge/Apache_Airflow-2.7+-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/)

Программный прдукт для сбора, очистки, пространственного анализа и предиктивного моделирования розничных цен на моторное топливо в Москве. Архитектура решения ориентирована на методологию **Medallion Architecture**, контейнеризацию в Docker и соответствие ГОСТ 34.

---

## Архитектура системы

Обработка данных выстроена по многоуровневому конвейеру **Medallion (Bronze &rarr; Silver &rarr; Gold)** в изолированных микросервисах:

```
[Внешние источники / Реестр]
         │
         ▼
 ┌───────────────┐     DockerOperator      ┌───────────────┐
 │ Bronze Service │ ─────────────────────► │ Silver Service │
 └───────┬───────┘                         └───────┬───────┘
         │ JSONB                                   │ PostGIS (3НФ)
         ▼                                         ▼
 ┌─────────────────────────────────────────────────────────┐
 │               PostgreSQL 15 / PostGIS                   │
 └─────────────────────────────────────────────────────────┘
         ▲                                         ▲
         │ Витрины прогнозов                       │ GeoJSON
 ┌───────┴───────┐                         ┌───────┴────────────┐
 │  Gold Service │ ◄────────────────────── │Presentation Service│
 └───────────────┘      ML Pipeline        └────────────────────┘
```

1. **СУБД и геоданные (`moscow_fuel_postgres`)**:
   - PostgreSQL 15 с расширением **PostGIS** (`SRID 4326`, WGS 84).
   - Хранение геометрии 707 АЗС (`POINT`) с пространственной индексацией GiST.
   - Нормализованные таблицы (3НФ): справочники (`dim_brand`, `dim_fuel_type`), факты (`silver_fuel_price`, `silver_fuel_availability`) и витрины (`gold_forecast`, `gold_report`).
2. **Сбор данных (`moscow_fuel_bronze`)**:
   - Сбор цен и запасов топлива с агрегаторов и реестров (63 630 замеров).
   - Поддержка механизма `Graceful Fallback` (структурированный резервный сбор при недоступности внешних API).
3. **Очистка и пространственная нормализация (`moscow_fuel_silver`)**:
   - Валидация контрактов с помощью Pydantic, дедупликация и канонизация брендов.
   - Преобразование географических координат в точки PostGIS (`ST_SetSRID(ST_MakePoint(...), 4326)`).
4. **Аналитика и машинное обучение (`moscow_fuel_gold`)**:
   - Очистка от аномалий методом межквартильного размаха (IQR).
   - Двухэтапное прогнозирование на 7 суток: базовый линейный тренд (`LinearTrend_IQR`) и градиентный бустинг (`HistGradientBoostingRegressor`) с лаговыми признаками и скользящими средними (MA3, MA7).
   - Расчет метрик ($R^2$, MAE, RMSE, MAPE) и автоматическая генерация аналитических отчетов.
5. **Оркестрация конвейера (Apache Airflow)**:
   - Направленный ациклический граф `fuel_moscow_medallion_pipeline` по расписанию `@hourly`.
   - Запуск этапов через `DockerOperator` (`mount_tmp_dir=False` для стабильности на Windows/Linux) и логирование через `RotatingFileHandler`.
6. **Сервис презентации (`moscow_fuel_presentation`)**:
   - Асинхронный REST API на базе **FastAPI** и **SQLAlchemy 2.0**.
   - Веб-дашборд с картой на **Leaflet.js** (кластеризация АЗС, фильтрация по топливу, тепловые срезы цен) и визуализацией динамики на **Chart.js**.

---

## Технологический стек

| Направление | Стек технологий |
|---|---|
| **Язык разработки** | Python 3.11 |
| **Базы данных и ГИС** | PostgreSQL 15, PostGIS 3.3+, SQLAlchemy 2.0, GeoAlchemy2 |
| **Машинное обучение** | Scikit-learn (`HistGradientBoostingRegressor`), NumPy, SciPy, Pandas |
| **Веб-сервис и API** | FastAPI, Uvicorn, Pydantic v2 |
| **Интерфейс** | Jinja2, HTML5/CSS3, JavaScript (ES6+), Leaflet.js, Chart.js |
| **Оркестрация и DevOps** | Docker, Docker Compose, Apache Airflow (`DockerOperator`), Git |

---

## Структура репозитория

```text
fuel_moscow/
├── docker-compose.yml          # Спецификация межсервисного взаимодействия
├── postgres/
│   └── init/
│       ├── 01_init_postgis.sql # Инициализация расширения PostGIS
│       └── 02_create_tables.sql# Схема таблиц 3НФ, индексы GiST и витрины
├── dags/
│   └── fuel_pipeline_dag.py    # Оркестрация в Apache Airflow (@hourly)
├── bronze_service/             # Сбор первичных данных и Graceful Fallback
├── silver_service/             # Валидация, дедупликация и геопривязка PostGIS
├── gold_service/               # ML-пайплайн (IQR, GBDT), метрики и отчеты
└── presentation_service/       # Веб-дашборд и REST API
    ├── app/
    │   ├── routers/            # Эндпоинты (/api/map-data, /api/forecasts, /)
    │   ├── models/             # ORM-модели базы данных
    │   └── static/             # Стили, модули Leaflet.js и Chart.js
    └── Dockerfile
```

---

## Быстрый запуск

### Системные требования
- **Docker Engine** 24.0+
- **Docker Compose** v2 2.20+
- Свободные порты на хосте: `8000` (веб-интерфейс) и `5432` (PostgreSQL/PostGIS при внешнем подключении).

### 1. Клонирование и настройка
```bash
git clone https://github.com/a-2b/fuel_moscow.git
cd fuel_moscow
```

### 2. Сборка и развертывание
Запустите все сервисы в фоновом режиме:
```bash
docker compose up --build -d
```

### 3. Проверка статуса контейнеров
```bash
docker compose ps
```
Все контейнеры (`moscow_fuel_postgres`, `moscow_fuel_bronze`, `moscow_fuel_silver`, `moscow_fuel_gold`, `moscow_fuel_presentation`) должны находиться в состоянии `Up / running`.

---

## Использование системы

* **Веб-дашборд:** откройте в браузере [`http://localhost:8000/`](http://localhost:8000/)
  - Интерактивная карта станций Москвы с разделением по сетям и всплывающими карточками (цены АИ-92, АИ-95, АИ-100, ДТ и процент остатка).
  - Фильтры марок топлива и сортировка по экстремумам цен («Мин. цена» / «Макс. цена»).
  - 7-дневный прогноз средних цен с доверительными интервалами (95%).
  - Сводка долей рынка и оперативный аналитический отчет.

* **API пространственных данных:**
  ```http
  GET http://localhost:8000/api/map-data
  ```
  Возвращает GeoJSON с координатами станций (`EPSG:4326`), атрибутами сетей и актуальными ценами.

* **Проверка работоспособности сервиса из консоли:**
  ```bash
  docker exec -it moscow_fuel_presentation python -c "import urllib.request; res = urllib.request.urlopen('http://localhost:8000/'); print('Status:', res.status)"
  ```

---

## Управление жизненным циклом

* **Приостановка работы (с сохранением состояния БД):**
  ```bash
  docker compose stop
  ```

* **Возобновление работы:**
  ```bash
  docker compose start
  ```

* **Полная остановка с очисткой томов данных:**
  ```bash
  docker compose down -v
  ```