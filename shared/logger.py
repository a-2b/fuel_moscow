import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def get_logger(name: str, log_filename: str = None) -> logging.Logger:
    """
    Создает и настраивает логгер для сервиса:
    - Выводит логи в stdout (консоль Docker / Airflow).
    - Записывает логи в отдельный .txt файл в корне сервиса с ротацией (до 10 МБ).
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Вывод в консоль (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 2. Вывод в файл .txt (если передан путь или задана переменная LOG_FILE)
        file_path = log_filename or os.getenv("LOG_FILE")
        if file_path:
            try:
                log_dir = os.path.dirname(file_path)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)

                # Ротация: максимум 10 МБ на файл, храним до 3 резервных копий
                file_handler = RotatingFileHandler(
                    file_path,
                    maxBytes=10 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.warning(f"Не удалось инициализировать файловый лог {file_path}: {e}")

        logger.propagate = False

    return logger