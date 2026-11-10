import datetime
import numpy as np
import pandas as pd
from typing import List, Dict, Any
from abc import ABC, abstractmethod

class BaseForecaster(ABC):
    @abstractmethod
    def forecast(self, df: pd.DataFrame, days_ahead: int) -> List[Dict[str, Any]]:
        pass

class LinearTrendForecaster(BaseForecaster):
    """Модель краткосрочного прогнозирования на основе линейного тренда."""
    
    def __init__(self, model_name: str = "LinearTrend_v1"):
        self.model_name = model_name

    def forecast(self, df: pd.DataFrame, days_ahead: int = 7) -> List[Dict[str, Any]]:
        forecasts = []
        # Группируем по типу топлива
        for fuel, group in df.groupby('fuel_type'):
            # Сортируем по времени
            group = group.sort_values('recorded_at')
            if len(group) < 2:
                continue # Недостаточно данных для тренда
            
            # Представляем даты как числа (дни)
            y = group['price'].values
            x = np.arange(len(y))
            
            # Вычисляем линейный тренд (y = mx + c)
            m, c = np.polyfit(x, y, 1)
            
            last_date = group['recorded_at'].iloc[-1]
            last_x = x[-1]
            
            # Стандартное отклонение для расчета доверительного интервала
            std_dev = np.std(y)
            
            for day in range(1, days_ahead + 1):
                pred_x = last_x + day
                pred_price = round((m * pred_x) + c, 2)
                pred_date = last_date + datetime.timedelta(days=day)
                
                forecasts.append({
                    "fuel_type": fuel,
                    "forecast_date": pred_date.date(),
                    "predicted_price": pred_price,
                    "confidence_lower": round(pred_price - std_dev, 2),
                    "confidence_upper": round(pred_price + std_dev, 2),
                    "model_name": self.model_name
                })
                
        return forecasts