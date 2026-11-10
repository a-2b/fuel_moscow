from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from presentation_service.api.routers import dashboard_api
from shared.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Fuel Monitoring IACS - Presentation Service")

# Монтируем статические файлы (JS, CSS)
app.mount("/static", StaticFiles(directory="presentation_service/static"), name="static")

# Подключаем роутер
app.include_router(dashboard_api.router)

@app.on_event("startup")
def startup_event():
    logger.info("Presentation Service успешно запущен.")