"""Настройка логирования"""
# logger_setup.py
import logging
import sys

def setup_logger():
    """Настраивает и возвращает логгер."""
    # Создаем форматтер
    log_format = logging.Formatter(
        '%(asctime)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Создаем основной логгер
    logger = logging.getLogger("bot_logger")
    logger.setLevel(logging.INFO)

    # Предотвращаем двойное логирование, если функция вызовется еще раз
    if logger.hasHandlers():
        logger.handlers.clear()

    # Обработчик для записи в файл 'bot.log'
    file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    # Обработчик для вывода в консоль (stdout)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_format)
    logger.addHandler(stream_handler)
    
    return logger