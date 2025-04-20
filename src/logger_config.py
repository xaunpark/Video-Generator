# src/logger_config.py

import logging
from config import settings


def setup_logger(name=__name__):
    """
    Tạo logger chuẩn cho toàn bộ project
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Tránh tạo nhiều handler khi import nhiều lần
    if not logger.hasHandlers():
        formatter = logging.Formatter(settings.LOGGER_FORMAT)

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
