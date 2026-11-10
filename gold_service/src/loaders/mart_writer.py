import logging
import pandas as pd
from datetime import datetime, date
from sqlalchemy import text
from shared.db import SessionLocal

logger = logging.getLogger("GoldMartWriter")

class GoldMartWriter:
    def __init__(self):
        pass

    def get_historical_prices(self) -> pd.DataFrame:
        """Чтение очищенных исторических цен из слоя Silver"""
        session = SessionLocal()
        try:
            # Читаем напрямую из физических таблиц silver_fuel_price и dim_fuel_type
            query = text("""
                SELECT 
                    p.recorded_at AS ds,
                    d.name AS fuel_type,
                    p.price AS y
                FROM silver_fuel_price p
                JOIN dim_fuel_type d ON p.fuel_type_id = d.id
                ORDER BY p.recorded_at ASC
            """)
            result = session.execute(query).mappings().all()

            if not result:
                logger.warning("Таблица silver_fuel_price пуста или не вернула строк.")
                return pd.DataFrame()

            df = pd.DataFrame(result)
            logger.info(f"Загружено {len(df)} строк цен из Silver.")
            return df
        except Exception as e:
            logger.error(f"Ошибка при чтении цен из Silver: {e}")
            return pd.DataFrame()
        finally:
            session.close()

    def save_forecasts(self, forecasts: list):
        """Безопасное сохранение прогнозов в физическую таблицу gold_forecast"""
        if not forecasts:
            return

        session = SessionLocal()
        try:
            # Очищаем только строки предыдущих прогнозов, не удаляя саму таблицу и VIEW
            session.execute(text("TRUNCATE TABLE gold_forecast RESTART IDENTITY CASCADE;"))

            # Карта типов топлива
            fuel_rows = session.execute(text("SELECT id, name FROM dim_fuel_type")).all()
            fuel_map = {row[1]: row[0] for row in fuel_rows}

            insert_stmt = text("""
                INSERT INTO gold_forecast (
                    fuel_type_id, 
                    forecast_date, 
                    predicted_price, 
                    confidence_lower, 
                    confidence_upper, 
                    model_name, 
                    created_at
                ) VALUES (
                    :fuel_type_id, 
                    :forecast_date, 
                    :predicted_price, 
                    :confidence_lower, 
                    :confidence_upper, 
                    :model_name, 
                    NOW()
                )
            """)

            for item in forecasts:
                f_id = fuel_map.get(item.get("fuel_type"))
                if not f_id:
                    continue

                f_date = item.get("date")
                if isinstance(f_date, str):
                    f_date = datetime.strptime(f_date, "%Y-%m-%d").date()
                elif isinstance(f_date, datetime):
                    f_date = f_date.date()

                pred_p = float(item.get("predicted_price", 0.0))
                conf_low = float(item.get("confidence_lower", pred_p * 0.98))
                conf_up = float(item.get("confidence_upper", pred_p * 1.02))

                session.execute(insert_stmt, {
                    "fuel_type_id": f_id,
                    "forecast_date": f_date,
                    "predicted_price": pred_p,
                    "confidence_lower": conf_low,
                    "confidence_upper": conf_up,
                    "model_name": item.get("model_name", "LinearTrend_IQR")
                })

            session.commit()
            logger.info(f"Сохранено {len(forecasts)} прогнозов в gold_forecast.")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка сохранения прогнозов в Gold: {e}")
        finally:
            session.close()

    def save_report(self, report_date, content: str, risk_level: str):
        """Безопасное сохранение отчета в физическую таблицу gold_report"""
        session = SessionLocal()
        try:
            if isinstance(report_date, str):
                target_date = datetime.strptime(report_date, "%Y-%m-%d").date()
            elif isinstance(report_date, datetime):
                target_date = report_date.date()
            else:
                target_date = report_date

            # Безопасный upsert: удаляем запись за текущую дату (если была) и вставляем актуальную
            session.execute(
                text("DELETE FROM gold_report WHERE report_date = :target_date"),
                {"target_date": target_date}
            )

            session.execute(
                text("""
                    INSERT INTO gold_report (report_date, content, created_at)
                    VALUES (:target_date, :content, NOW())
                """),
                {"target_date": target_date, "content": content}
            )

            session.commit()
            logger.info("Оперативный отчет LLM успешно сохранен в gold_report.")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка сохранения отчета в Gold: {e}")
        finally:
            session.close()