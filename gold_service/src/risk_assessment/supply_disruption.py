class RiskAssessor:
    """Оценка надежности снабжения и рисков перебоев."""
    
    @staticmethod
    def calculate_risk_level(forecasts: list) -> str:
        """
        Упрощенная эвристика риска: 
        Если прогнозируется резкий скачок цен (сильный тренд), повышаем уровень риска.
        """
        if not forecasts:
            return "UNKNOWN"
            
        # Ищем максимальный ожидаемый рост цены
        max_price_diff = 0
        prices = [f['predicted_price'] for f in forecasts]
        if prices:
            max_price_diff = max(prices) - min(prices)
            
        if max_price_diff > 2.0: # Если цена вырастет более чем на 2 рубля за 7 дней
            return "HIGH"
        elif max_price_diff > 0.5:
            return "MEDIUM"
        return "LOW"