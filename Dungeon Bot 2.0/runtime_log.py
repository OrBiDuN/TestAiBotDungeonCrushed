"""Bounded, thread-safe diagnostics shared by GUI and capture worker."""
import logging
from logging.handlers import RotatingFileHandler
from app_paths import APP_DIR

logger = logging.getLogger('dungeon.runtime')
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    try:
        handler = RotatingFileHandler(APP_DIR / 'runtime.log', maxBytes=2_000_000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(message)s'))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
