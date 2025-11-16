# logger_setup.py
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pytz 

def time_converter(timestamp):
    """Конвертирует время логгера в часовой пояс Екатеринбурга."""
    ekb_tz = pytz.timezone('Asia/Yekaterinburg')
    utc_dt = datetime.fromtimestamp(timestamp, tz=pytz.utc)
    ekb_dt = utc_dt.astimezone(ekb_tz)
    return ekb_dt.timetuple()
# ------------------------------------

def setup_logger():
    """Настраивает и возвращает кастомный логгер."""
    logger = logging.getLogger("bot_logger")
    if logger.hasHandlers():
        return logger
    
    logger.setLevel(logging.INFO)
    
    log_formatter = logging.Formatter(
        '%(asctime)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    log_formatter.converter = time_converter
    # ---------------------------------------------
    
    # Файловый обработчик с ротацией
    file_handler = RotatingFileHandler(
        'bot_error.log', 
        maxBytes=5*1024*1024, # 5 MB
        backupCount=2,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(log_formatter)
    
    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger