# main.py
import threading
import time
import logging
from datetime import datetime
import ccxt

import config
from logger_setup import setup_logger
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade
from telegram_bot import start_tg, register_main_objects, send_message

logger = setup_logger()

bot_state = {
    "active_trades": {},
    "running": False,
    "settings": {
        "stop_loss_percent": config.DEFAULT_STOP_LOSS_PERCENT,
        "take_profit_percent": config.DEFAULT_TAKE_PROFIT_PERCENT,
    }
}
t_lock = threading.Lock()

exchange = ccxt.bybit({
    'apiKey': config.BYBIT_API_KEY,
    'secret': config.BYBIT_API_SECRET,
    'options': {'defaultType': 'spot'},
})

# --- ИЗМЕНЕНИЕ ЗДЕСЬ: ПОЛНОСТЬЮ ПЕРЕРАБОТАННАЯ ФУНКЦИЯ СКАНЕРА ---
def run_scanner():
    send_message("▶️ Поток сканера запущен")
    
    while bot_state.get('running', False):
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            # --- НОВАЯ ЛОГИКА ---
            # ЕСЛИ ВСЕ СЛОТЫ ЗАНЯТЫ, ПРОСТО ЖДЕМ И ПРОВЕРЯЕМ СНОВА
            if active_trades_count >= config.MAX_CONCURRENT_TRADES:
                logger.info(f"Все {config.MAX_CONCURRENT_TRADES} слота заняты. Ожидаю освобождения...")
                time.sleep(15) # Короткая пауза перед следующей проверкой
                continue # Переходим к следующей итерации цикла, пропуская сканирование

            # ЕСЛИ ЕСТЬ СВОБОДНЫЕ СЛОТЫ, ЗАПУСКАЕМ СКАНИРОВАНИЕ
            logger.info(
                f"Свободных слотов: {config.MAX_CONCURRENT_TRADES - active_trades_count}. "
                f"Начинаю сканирование {len(config.my_symbols)} монет..."
            )
            
            for symbol in config.my_symbols:
                # Проверяем на каждой итерации, не поступила ли команда /stop
                if not bot_state.get('running', False): 
                    break

                with t_lock:
                    # Пропускаем монету, если она уже в сделке
                    if symbol in bot_state['active_trades']:
                        continue
                
                df = get_historical_data(exchange, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        with t_lock:
                            # Еще одна проверка, на случай если слот заняли во время сканирования
                            if len(bot_state['active_trades']) >= config.MAX_CONCURRENT_TRADES:
                                logger.warning(f"[{symbol}] Найден сигнал, но слоты уже заняты.")
                                break # Прерываем сканирование, т.к. слотов больше нет

                            logger.info(f"!!! [{symbol}] НАЙДЕН СИГНАЛ: {entry_price} !!!")
                            send_message(f"🔥 *Сигнал на покупку:*\n`{symbol}` по цене `{entry_price}`")

                            bot_state['active_trades'][symbol] = { "status": "pending" }
                        
                        trade_thread = threading.Thread(
                            target=manage_trade, 
                            args=(symbol, entry_price, bot_state, t_lock)
                        )
                        trade_thread.start()
                
                time.sleep(1) # Небольшая пауза между запросами к API
            
            # Если бот все еще работает после полного цикла сканирования, ждем 5 минут
            if not bot_state.get('running', False):
                break

            logger.info("Сканирование завершено. Следующая проверка через ~5 минут.")
            # Прерываемый сон на 300 секунд (5 минут)
            for _ in range(30):
                if not bot_state.get('running', False):
                    break
                time.sleep(10)

        except Exception as e:
            error_message = f"КРИТИЧЕСКАЯ ОШИБКА в сканере: {e}"
            logger.critical(error_message, exc_info=True)
            send_message(f"🔴 {error_message}")
            time.sleep(60)

    logger.info("Поток сканера остановлен.")
    send_message("⏹️ Поток сканера завершил свою работу.")


if __name__ == "__main__":
    # Эта часть остается без изменений
    register_main_objects(bot_state, t_lock, run_scanner, exchange)
    logger.info("Запуск Telegram бота...")
    start_tg()
    logger.info("Бот запущен.")