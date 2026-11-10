FROM python:3.11-slim

WORKDIR /app

COPY presentation_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY presentation_service /app/presentation_service

ENV PYTHONPATH=/app

# Uvicorn запускает FastAPI на порту 8000
CMD ["uvicorn", "presentation_service.main:app", "--host", "0.0.0.0", "--port", "8000"]