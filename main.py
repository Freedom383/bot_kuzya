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

# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Загружаем "живые" настройки из конфига при старте
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

def run_scanner():
    send_message("▶️ Поток сканера запущен. Ожидаю команды /start...")
    
    while bot_state.get('running', False):
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            if active_trades_count >= config.MAX_CONCURRENT_TRADES:
                logger.info("Достигнут лимит сделок. Ожидание...")
                time.sleep(30)
                continue
            
            logger.info(f"Свободных слотов: {config.MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in config.my_symbols:
                if not bot_state.get('running', False): break

                with t_lock:
                    if symbol in bot_state['active_trades']: continue
                
                df = get_historical_data(exchange, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        with t_lock:
                            if len(bot_state['active_trades']) >= config.MAX_CONCURRENT_TRADES:
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
                
                time.sleep(1)
            
            if not bot_state.get('running', False): break

            logger.info("Сканирование завершено. Следующая проверка через ~5 минут.")
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
    register_main_objects(bot_state, t_lock, run_scanner, exchange)
    
    logger.info("Запуск Telegram бота...")
    start_tg()
    
    logger.info("Бот запущен. Для начала работы отправьте команду /start")