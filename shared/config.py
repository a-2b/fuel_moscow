from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """Глобальные настройки приложения, загружаемые из переменных окружения."""
    
    # Настройки PostgreSQL
    POSTGRES_USER: str = Field(default="fuel_admin")
    POSTGRES_PASSWORD: str = Field(default="fuel_secret_pass")
    POSTGRES_DB: str = Field(default="fuel_moscow_db")
    POSTGRES_HOST: str = Field(default="postgres_db")
    POSTGRES_PORT: int = Field(default=5432)

    # Настройки LLM
    LLM_PROVIDER: str = Field(default="mock")
    LLM_API_KEY: str = Field(default="")
    LLM_BASE_URL: str = Field(default="http://docker.internal")

    # Внешние API (пример, можно расширить)
    PRESENTATION_PORT: int = Field(default=8000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore" # Игнорировать лишние переменные в .env
    )

    @property
    def database_url(self) -> str:
        """Формирует URL для подключения к базе данных SQLAlchemy."""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# Создаем глобальный экземпляр настроек, который будут импортировать другие сервисы
settings = Settings()