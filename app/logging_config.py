import logging
import sys
from loguru import logger
from app.config import get_settings

settings = get_settings()


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logger.remove()
if settings.LOG_JSON:
    logger.add(sys.stdout, level=settings.LOG_LEVEL, serialize=True)
else:
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

logging.basicConfig(handlers=[InterceptHandler()], level=settings.LOG_LEVEL)
