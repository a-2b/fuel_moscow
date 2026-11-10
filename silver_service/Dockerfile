FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для сборки и геометрии (если требуется)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY silver_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем общие модули и код сервиса
COPY shared/ /app/shared/
COPY silver_service/ /app/silver_service/

ENV PYTHONPATH=/app

WORKDIR /app/silver_service
CMD ["python", "main.py"]