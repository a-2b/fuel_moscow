FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY bronze_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода сервиса и общего модуля shared
COPY shared/ /app/shared/
COPY bronze_service/ /app/bronze_service/

# Копирование датасета реальных АЗС из scripts/ в корень /app контейнера
COPY scripts/real_moscow_azs.json /app/real_moscow_azs.json

ENV PYTHONPATH=/app

CMD ["python", "-m", "bronze_service.main"]