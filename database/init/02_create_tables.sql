-- ============================================================================
-- 1. СЛОЙ BRONZE (Сырые данные)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bronze_azs_raw (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    raw_payload JSONB NOT NULL,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bronze_batch_id ON bronze_azs_raw(batch_id);
CREATE INDEX IF NOT EXISTS idx_bronze_ingested_at ON bronze_azs_raw(ingested_at);

-- ============================================================================
-- 2. СПРАВОЧНИКИ (Dimensions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS dim_brand (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    segment VARCHAR(50) DEFAULT 'Retail'
);

CREATE TABLE IF NOT EXISTS dim_fuel_type (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

-- ============================================================================
-- 3. СЛОЙ SILVER (Очищенные и нормализованные данные с PostGIS)
-- ============================================================================
CREATE TABLE IF NOT EXISTS silver_azs_geo (
    id SERIAL PRIMARY KEY,
    brand_id INT NOT NULL REFERENCES dim_brand(id) ON DELETE CASCADE,
    address VARCHAR(255) NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_silver_azs_geo_location ON silver_azs_geo USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_silver_azs_geo_brand ON silver_azs_geo(brand_id);

CREATE TABLE IF NOT EXISTS silver_fuel_price (
    id SERIAL PRIMARY KEY,
    azs_id INT NOT NULL REFERENCES silver_azs_geo(id) ON DELETE CASCADE,
    fuel_type_id INT NOT NULL REFERENCES dim_fuel_type(id) ON DELETE CASCADE,
    price NUMERIC(8, 2) NOT NULL,
    recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_silver_fuel_price_azs ON silver_fuel_price(azs_id);
CREATE INDEX IF NOT EXISTS idx_silver_fuel_price_type ON silver_fuel_price(fuel_type_id);
CREATE INDEX IF NOT EXISTS idx_silver_fuel_price_date ON silver_fuel_price(recorded_at);

CREATE TABLE IF NOT EXISTS silver_fuel_availability (
    id SERIAL PRIMARY KEY,
    azs_id INT NOT NULL REFERENCES silver_azs_geo(id) ON DELETE CASCADE,
    fuel_type_id INT NOT NULL REFERENCES dim_fuel_type(id) ON DELETE CASCADE,
    percentage INT DEFAULT 100,
    recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_silver_fuel_avail_azs ON silver_fuel_availability(azs_id);

-- ============================================================================
-- 4. СЛОЙ GOLD (Базовые аналитические витрины, отчеты и прогнозы)
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold_report (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gold_forecast (
    id SERIAL PRIMARY KEY,
    fuel_type_id INT NOT NULL REFERENCES dim_fuel_type(id) ON DELETE CASCADE,
    forecast_date DATE NOT NULL,
    predicted_price NUMERIC(8, 2) NOT NULL,
    confidence_lower NUMERIC(8, 2),
    confidence_upper NUMERIC(8, 2),
    model_name VARCHAR(100) DEFAULT 'LinearTrend_IQR',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_gold_forecast_date_fuel UNIQUE (forecast_date, fuel_type_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_gold_forecast_date ON gold_forecast(forecast_date);

-- ============================================================================
-- 5. ПРЕДСТАВЛЕНИЯ-СИНОНИМЫ (Совместимость с Presentation Service)
-- ============================================================================
CREATE OR REPLACE VIEW dim_brands AS 
SELECT * FROM dim_brand;

CREATE OR REPLACE VIEW dim_fuel_types AS 
SELECT * FROM dim_fuel_type;

CREATE OR REPLACE VIEW silver_fuel_prices AS 
SELECT * FROM silver_fuel_price;

CREATE OR REPLACE VIEW silver_fuel_availabilities AS 
SELECT * FROM silver_fuel_availability;

CREATE OR REPLACE VIEW gold_fuel_forecasts AS 
SELECT * FROM gold_forecast;

CREATE OR REPLACE VIEW gold_operational_reports AS
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

-- ============================================================================
-- 6. ПРАВА ДОСТУПА
-- ============================================================================
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO fuel_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO fuel_admin;
GRANT USAGE ON SCHEMA public TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO PUBLIC;