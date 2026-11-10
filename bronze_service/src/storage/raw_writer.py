from typing import List, Dict, Any
from shared.db import SessionLocal, BronzeRaw
from shared.logger import get_logger

logger = get_logger(__name__)

class RawDataWriter:
    """Класс для сохранения сырых данных в базу (паттерн Repository)."""
    
    def __init__(self):
        self.db = SessionLocal()

    def save_records(self, source_name: str, records: List[Dict[str, Any]]):
        """Сохраняет список записей в таблицу bronze_raw."""
        if not records:
            logger.warning(f"Нет данных для сохранения из источника {source_name}")
            return

        try:
            db_records = [
                BronzeRaw(source_name=source_name, raw_payload=record)
                for record in records
            ]
            self.db.add_all(db_records)
            self.db.commit()
            logger.info(f"Успешно сохранено {len(records)} сырых записей из '{source_name}'.")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Ошибка при сохранении данных из '{source_name}': {e}")
        finally:
            self.db.close()