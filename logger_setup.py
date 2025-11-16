# logger_setup.py
import logging
import sys

def setup_logger():
    """Настраивает и возвращает логгер."""
    log_format = logging.Formatter(
        '%(asctime)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger("bot_logger")
    # Устанавливаем общий уровень INFO, чтобы логгер обрабатывал все сообщения
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Обработчик для записи в файл 'bot.log'
    # Будет записывать ТОЛЬКО сообщения уровня ERROR и выше
    file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.ERROR) # <--- Ключевое изменение!
    logger.addHandler(file_handler)

    # Обработчик для вывода в консоль (stdout)
    # Будет выводить ВСЕ сообщения от INFO и выше
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_format)
    stream_handler.setLevel(logging.INFO) # <--- Уровень для консоли
    logger.addHandler(stream_handler)
    
    return logger