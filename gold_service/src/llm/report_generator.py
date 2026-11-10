import datetime
from openai import OpenAI
from shared.config import settings
from shared.logger import get_logger

logger = get_logger(__name__)

class LLMReportGenerator:
    """Адаптер для генерации текста с помощью LLM (OpenAI API / Ollama / Mock)."""
    
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        if self.provider != "mock":
            self.client = OpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL
            )

    def generate_report(self, date: datetime.date, forecasts: list, risk_level: str) -> str:
        # Формируем промпт из данных
        avg_prices = {}
        for f in forecasts:
            avg_prices[f['fuel_type']] = f['predicted_price']
            
        prompt = (
            f"Ты — старший аналитик рынка топлива г. Москвы.\n"
            f"Текущая дата: {date}.\n"
            f"Прогноз цен на неделю: {avg_prices}.\n"
            f"Уровень риска перебоев поставок: {risk_level}.\n"
            f"Напиши короткую оперативную справку (не более 4 пунктов) в строгом деловом стиле "
            f"о текущей ситуации и прогнозе на 7 дней."
        )

        if self.provider == "mock":
            logger.info("Генерация отчета через Mock-провайдер.")
            return (
                f"1. Мониторинговый охват: обеспечен сбор данных АЗС.\n"
                f"2. Прогноз цен на 7 дней: ожидаются на уровне {avg_prices}.\n"
                f"3. Оценка рисков: уровень {risk_level}. Перебоев не ожидается."
            )
            
        try:
            logger.info("Отправка запроса к LLM API...")
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo", # Или локальная модель
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Ошибка LLM API: {e}")
            return "Ошибка генерации отчета."