"""
Единый модуль доступа к данным (DAL) и ORM-моделей Medallion Architecture.

Стек: PostgreSQL (PostGIS), SQLAlchemy 2.0+, GeoAlchemy2, Psycopg2.
Поддерживает:
- Пул соединений с auto-reconnect и healthcheck (pre-ping).
- Двунаправленную совместимость имен: recorded_at <-> timestamp, location <-> coordinates.
- Работу с физическими таблицами (Bronze, Dim, Silver, Gold).
- Автоматическое создание расширения PostGIS, физических таблиц и VIEW витрин.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Generator, List, Optional

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date as SqlDate,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    scoped_session,
    sessionmaker,
)

logger = logging.getLogger("SharedDB")

# ============================================================================
# 1. ПАРАМЕТРЫ ПОДКЛЮЧЕНИЯ И СОЗДАНИЕ ДВИЖКА (ENGINE)
# ============================================================================

POSTGRES_USER: str = os.getenv("POSTGRES_USER", "fuel_admin")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "fuel_pass")
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "moscow_fuel_postgres")
POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "fuel_moscow_db")

DEFAULT_DATABASE_URL: str = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@"
    f"{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

DATABASE_URL: str = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

# Принудительная нормализация протокола для гарантированной работы с psycopg2
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_size=int(os.getenv("DB_POOL_SIZE", "15")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "25")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,
    echo=os.getenv("DB_ECHO", "False").lower() in ("true", "1", "yes"),
)

SessionFactory = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

ScopedSession = scoped_session(SessionFactory)


# ============================================================================
# 2. МЕНЕДЖЕРЫ СЕССИЙ
# ============================================================================

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Контекстный менеджер транзакций для ETL-сервисов (Silver, Gold).
    Фиксирует транзакцию при успехе и откатывает при исключении.
    """
    session: Session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Транзакция откатана из-за ошибки: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Генератор сессии для внедрения зависимостей в FastAPI (Presentation Service)."""
    session: Session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def wait_for_db(max_retries: int = 15, delay_seconds: int = 2) -> bool:
    """Блокирует выполнение до подтверждения готовности PostgreSQL принимать запросы."""
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
            logger.info("Успешное подключение к PostgreSQL.")
            return True
        except Exception as e:
            logger.warning(
                "Ожидание запуска PostgreSQL (попытка %d/%d): %s",
                attempt,
                max_retries,
                e,
            )
            time.sleep(delay_seconds)
    raise ConnectionError("Не удалось подключиться к PostgreSQL после серии попыток.")


# ============================================================================
# 3. БАЗОВЫЙ КЛАСС И СЕРИАЛИЗАЦИЯ
# ============================================================================

class Base(DeclarativeBase):
    """Базовый декларативный класс с универсальным методом экспорта в dict."""

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for c in self.__table__.columns:
            val = getattr(self, c.name)
            if isinstance(val, (datetime, date)):
                result[c.name] = val.isoformat()
            elif isinstance(val, Decimal):
                result[c.name] = float(val)
            elif isinstance(val, WKTElement):
                result[c.name] = str(val)
            else:
                result[c.name] = val
        return result


# ============================================================================
# 4. СЛОЙ BRONZE (Сырые данные)
# ============================================================================

class BronzeAzsRaw(Base):
    __tablename__ = "bronze_azs_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_bronze_batch_ingested", "batch_id", "ingested_at"),
    )


# ============================================================================
# 5. СПРАВОЧНИКИ (DIMENSIONS)
# ============================================================================

class DimBrand(Base):
    __tablename__ = "dim_brand"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    segment: Mapped[str] = mapped_column(String(50), default="Retail", nullable=False)

    stations: Mapped[List[SilverAzsGeo]] = relationship(
        "SilverAzsGeo", back_populates="brand", cascade="all, delete-orphan"
    )


class DimFuelType(Base):
    __tablename__ = "dim_fuel_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    prices: Mapped[List[SilverFuelPrice]] = relationship(
        "SilverFuelPrice", back_populates="fuel_type", cascade="all, delete-orphan"
    )
    availabilities: Mapped[List[SilverFuelAvailability]] = relationship(
        "SilverFuelAvailability", back_populates="fuel_type", cascade="all, delete-orphan"
    )
    forecasts: Mapped[List[GoldForecast]] = relationship(
        "GoldForecast", back_populates="fuel_type", cascade="all, delete-orphan"
    )


# ============================================================================
# 6. СЛОЙ SILVER (Очищенные геоданные, Цены, Наличие)
# ============================================================================

class SilverAzsGeo(Base):
    __tablename__ = "silver_azs_geo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_brand.id", ondelete="CASCADE"), nullable=False, index=True
    )
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    location = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    brand: Mapped[DimBrand] = relationship("DimBrand", back_populates="stations")
    prices: Mapped[List[SilverFuelPrice]] = relationship(
        "SilverFuelPrice", back_populates="station", cascade="all, delete-orphan"
    )
    availabilities: Mapped[List[SilverFuelAvailability]] = relationship(
        "SilverFuelAvailability", back_populates="station", cascade="all, delete-orphan"
    )

    # Гибридный алиас coordinates для совместимости с внешними скриптами
    @hybrid_property
    def coordinates(self):
        return self.location

    @coordinates.setter
    def coordinates(self, value):
        self.location = value

    __table_args__ = (
        Index("idx_silver_azs_geo_location", "location", postgresql_using="gist"),
    )


class SilverFuelPrice(Base):
    __tablename__ = "silver_fuel_price"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    azs_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("silver_azs_geo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fuel_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_fuel_type.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    
    # recorded_at — каноническое поле времени для аналитики и временных рядов Gold
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    station: Mapped[SilverAzsGeo] = relationship("SilverAzsGeo", back_populates="prices")
    fuel_type: Mapped[DimFuelType] = relationship("DimFuelType", back_populates="prices")

    # Алиас-свойство timestamp -> recorded_at
    @hybrid_property
    def timestamp(self) -> datetime:
        return self.recorded_at

    @timestamp.setter
    def timestamp(self, val: datetime) -> None:
        self.recorded_at = val

    __table_args__ = (
        Index("idx_silver_fuel_price_lookup", "fuel_type_id", "recorded_at", "price"),
    )


class SilverFuelAvailability(Base):
    __tablename__ = "silver_fuel_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    azs_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("silver_azs_geo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fuel_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_fuel_type.id", ondelete="CASCADE"), nullable=False, index=True
    )
    percentage: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    station: Mapped[SilverAzsGeo] = relationship("SilverAzsGeo", back_populates="availabilities")
    fuel_type: Mapped[DimFuelType] = relationship("DimFuelType", back_populates="availabilities")

    @hybrid_property
    def timestamp(self) -> datetime:
        return self.recorded_at

    @timestamp.setter
    def timestamp(self, val: datetime) -> None:
        self.recorded_at = val


# ============================================================================
# 7. СЛОЙ GOLD (Оперативные отчеты и Прогнозы цен)
# ============================================================================

class GoldReport(Base):
    __tablename__ = "gold_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(SqlDate, nullable=False, unique=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class GoldForecast(Base):
    __tablename__ = "gold_forecast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fuel_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_fuel_type.id", ondelete="CASCADE"), nullable=False, index=True
    )
    forecast_date: Mapped[date] = mapped_column(SqlDate, nullable=False, index=True)
    predicted_price: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    confidence_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    confidence_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    model_name: Mapped[str] = mapped_column(String(100), default="LinearTrend_IQR", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    fuel_type: Mapped[DimFuelType] = relationship("DimFuelType", back_populates="forecasts")

    __table_args__ = (
        UniqueConstraint("forecast_date", "fuel_type_id", "model_name", name="uq_gold_forecast_date_fuel"),
        Index("idx_gold_forecast_lookup", "fuel_type_id", "forecast_date"),
    )


# ============================================================================
# 8. READ-ONLY МОДЕЛИ ПРЕДСТАВЛЕНИЙ (PRESENTATION LAYER)
# ============================================================================

class DimBrandsView(Base):
    __tablename__ = "dim_brands"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    segment: Mapped[str] = mapped_column(String(50))


class DimFuelTypesView(Base):
    __tablename__ = "dim_fuel_types"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class SilverFuelPricesView(Base):
    __tablename__ = "silver_fuel_prices"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    azs_id: Mapped[int] = mapped_column(Integer)
    fuel_type_id: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class SilverFuelAvailabilitiesView(Base):
    __tablename__ = "silver_fuel_availabilities"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    azs_id: Mapped[int] = mapped_column(Integer)
    fuel_type_id: Mapped[int] = mapped_column(Integer)
    percentage: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class GoldOperationalReportsView(Base):
    __tablename__ = "gold_operational_reports"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(SqlDate)
    content: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class GoldFuelForecastsView(Base):
    __tablename__ = "gold_fuel_forecasts"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fuel_type_id: Mapped[int] = mapped_column(Integer)
    forecast_date: Mapped[date] = mapped_column(SqlDate)
    predicted_price: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    confidence_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    confidence_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    model_name: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime)


# ============================================================================
# 9. СИНХРОНИЗАЦИЯ СХЕМЫ, ИНДЕКСОВ И ПРЕДСТАВЛЕНИЙ
# ============================================================================

VIEW_DEFINITIONS = [
    """
    DROP VIEW IF EXISTS dim_brands CASCADE;
    CREATE VIEW dim_brands AS 
    SELECT id, name, segment FROM dim_brand;
    """,
    """
    DROP VIEW IF EXISTS dim_fuel_types CASCADE;
    CREATE VIEW dim_fuel_types AS 
    SELECT id, name FROM dim_fuel_type;
    """,
    """
    DROP VIEW IF EXISTS silver_fuel_prices CASCADE;
    CREATE VIEW silver_fuel_prices AS 
    SELECT id, azs_id, fuel_type_id, price, recorded_at FROM silver_fuel_price;
    """,
    """
    DROP VIEW IF EXISTS silver_fuel_availabilities CASCADE;
    CREATE VIEW silver_fuel_availabilities AS 
    SELECT id, azs_id, fuel_type_id, percentage, recorded_at FROM silver_fuel_availability;
    """,
    """
    DROP VIEW IF EXISTS gold_fuel_forecasts CASCADE;
    CREATE VIEW gold_fuel_forecasts AS 
    SELECT id, fuel_type_id, forecast_date, predicted_price, confidence_lower, confidence_upper, model_name, created_at 
    FROM gold_forecast;
    """,
    """
    DROP VIEW IF EXISTS gold_operational_reports CASCADE;
    CREATE VIEW gold_operational_reports AS
    SELECT 
        id,
        report_date,
        content,
        CASE 
            WHEN content ILIKE '%высокий%' OR content ILIKE '%high%' THEN 'HIGH'
            WHEN content ILIKE '%критическ%' OR content ILIKE '%critical%' THEN 'CRITICAL'
            WHEN content ILIKE '%средний%' OR content ILIKE '%warning%' THEN 'WARNING'
            ELSE 'NORMAL'
        END AS risk_level,
        created_at
    FROM gold_report;
    """,
]


def init_db() -> None:
    """
    Гарантирует готовность инфраструктуры базы данных:
    1. Проверяет наличие расширения PostGIS.
    2. Создает физические таблицы ORM (исключая VIEW).
    3. Выполняет ALTER TABLE на случай, если таблицы были созданы со старой схемой.
    4. Создает / обновляет SQL-представления витрин presentation_service.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

        # 1. Создание физических таблиц
        tables_to_create = [
            table for table in Base.metadata.sorted_tables
            if not table.info.get("is_view", False)
        ]
        Base.metadata.create_all(bind=engine, tables=tables_to_create)

        # 2. Мягкая миграция колонок для уже существующих таблиц
        migration_statements = [
            "ALTER TABLE silver_azs_geo ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();",
            "ALTER TABLE silver_fuel_price ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();",
            "ALTER TABLE silver_fuel_availability ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();",
        ]
        with engine.begin() as conn:
            for stmt in migration_statements:
                try:
                    conn.execute(text(stmt))
                except Exception as m_err:
                    logger.debug("Пропуск мягкой миграции (%s): %s", stmt, m_err)

        # 3. Синхронизация представлений
        with engine.begin() as conn:
            for view_sql in VIEW_DEFINITIONS:
                conn.execute(text(view_sql))

        logger.info("Схема базы данных, индексы PostGIS и представления успешно синхронизированы.")
    except Exception as exc:
        logger.error("Критический сбой при инициализации init_db(): %s", exc, exc_info=True)
        raise