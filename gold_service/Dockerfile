FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для компиляции numpy/pandas (если потребуются)
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY gold_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем общий модуль
COPY shared /app/shared

# Копируем код самого сервиса
COPY gold_service /app/gold_service

# Указываем PYTHONPATH, чтобы Python мог найти пакет shared
ENV PYTHONPATH=/app

CMD ["python", "gold_service/main.py"]