import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from shared.logger import get_logger

logger = get_logger(__name__)

class BaseCollector(ABC):
    """
    Абстрактный класс с реализацией паттерна Template Method
    и механизма отказоустойчивости (Graceful Fallback).
    """
    
    def __init__(self, source_name: str, target_url: str):
        self.source_name = source_name
        self.target_url = target_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch_data(self) -> List[Dict[str, Any]]:
        """Шаблонный метод: HTTP-запрос -> Парсинг (или Fallback при сбое)."""
        logger.info(f"Сборщик [{self.source_name}] обращается к {self.target_url}")
        try:
            response = requests.get(self.target_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # Если запрос успешен, передаем HTML в абстрактный метод парсинга
            parsed_data = self.parse_html(response.text)
            logger.info(f"[{self.source_name}] Успешно получено {len(parsed_data)} записей.")
            return parsed_data
            
        except Exception as e:
            logger.warning(
                f"[{self.source_name}] Сбой источника ({e}). "
                f"Активация механизма Graceful Fallback."
            )
            return self.get_fallback_data()

    @abstractmethod
    def parse_html(self, html_content: str) -> List[Dict[str, Any]]:
        """Абстрактный метод извлечения данных из HTML DOM."""
        pass

    @abstractmethod
    def get_fallback_data(self) -> List[Dict[str, Any]]:
        """Абстрактный метод возврата калиброванного резервного снимка."""
        pass