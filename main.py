# main.py
import threading
import time
import logging
from datetime import datetime
import ccxt

from config import *
from logger_setup import setup_logger
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade
# Обрати внимание на новые импорты из telegram_bot
from telegram_bot import start_tg, register_main_objects, send_message

logger = setup_logger()

# Общие объекты, доступные для всех потоков
bot_state = {
    "active_trades": {},
    "running": False  # Изначально сканер выключен
}
t_lock = threading.Lock()

def run_scanner():
    """Главный цикл сканирования рынка. Работает в отдельном потоке."""
    
    # Сообщаем в Telegram о запуске потока
    send_message("▶️ Поток сканера запущен. Ожидаю команды /start...")
    
    exchange = ccxt.bybit({
        'apiKey': BYBIT_API_KEY,
        'secret': BYBIT_API_SECRET,
        'options': {'defaultType': 'spot'},
    })
    
    # Главный цикл теперь зависит от флага 'running'
    while bot_state.get('running', False):
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            if active_trades_count >= MAX_CONCURRENT_TRADES:
                logger.info("Достигнут лимит сделок. Ожидание...")
                time.sleep(30)
                continue
            
            logger.info(f"Свободных слотов: {MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in my_symbols:
                # Проверяем флаг после каждого токена для быстрой остановки
                if not bot_state.get('running', False):
                    break

                with t_lock:
                    if symbol in bot_state['active_trades']:
                        continue
                
                df = get_historical_data(exchange, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        with t_lock:
                            if len(bot_state['active_trades']) >= MAX_CONCURRENT_TRADES:
                                logger.warning(f"[{symbol}] Найден сигнал, но слоты уже заняты.")
                                break

                            logger.info(f"!!! [{symbol}] НАЙДЕН СИГНАЛ: {entry_price} !!!")
                            send_message(f"🔥 *Сигнал на покупку:*\n`{symbol}` по цене `{entry_price}`")
                            
                            bot_state['active_trades'][symbol] = {
                                "entry_price": entry_price,
                                "entry_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            }

                        trade_thread = threading.Thread(
                            target=manage_trade, 
                            args=(symbol, entry_price, bot_state, t_lock)
                        )
                        trade_thread.start()
                
                time.sleep(1) # Небольшая пауза между токенами
            
            if not bot_state.get('running', False):
                break

            logger.info("Сканирование завершено. Следующая проверка через ~5 минут.")
            # Цикл ожидания с проверкой флага каждые 10 секунд
            for _ in range(30):
                if not bot_state.get('running', False): break
                time.sleep(10)

        except Exception as e:
            error_message = f"КРИТИЧЕСКАЯ ОШИБКА в сканере: {e}"
            logger.critical(error_message, exc_info=True)
            send_message(f"🔴 {error_message}")
            time.sleep(60)

    logger.info("Поток сканера остановлен.")
    send_message("⏹️ Поток сканера завершил свою работу.")


if __name__ == "__main__":
    # 1. Передаем общие объекты в модуль telegram_bot
    register_main_objects(bot_state, t_lock, run_scanner)
    
    # 2. Запускаем Telegram бота. Он будет работать в основном потоке.
    logger.info("Запуск Telegram бота...")
    start_tg()
    
    # Программа будет работать, пока запущен Telegram бот.
    logger.info("Бот запущен. Для начала работы отправьте команду /start")