# main.py
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from config import *
from pybit.unified_trading import HTTP
from logger_setup import setup_logger # <<< ИМПОРТ
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade

# Настраиваем логгер в самом начале
logger = setup_logger()

# Часовой пояс Екатеринбурга
try:
    from zoneinfo import ZoneInfo
    YKT = ZoneInfo("Asia/Yekaterinburg")
except Exception:
    YKT = timezone(timedelta(hours=5))

# Глобальное состояние бота и замок
bot_state = {"active_trades": {}}
t_lock = threading.Lock()

def run_scanner():
    logger.info("="*30)
    logger.info("Запуск торгового робота (режим симуляции)...")
    logger.info("="*30)

    session = HTTP(testnet=False, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    
    while True:
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            if active_trades_count >= MAX_CONCURRENT_TRADES:
                logger.info(f"Все {MAX_CONCURRENT_TRADES} депозита заняты. Ожидание...")
                time.sleep(30)
                continue
            
            now_local = datetime.now(YKT)
            logger.info(f"--- {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
            logger.info(f"Свободных депозитов: {MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in my_symbols:
                with t_lock:
                    if symbol in bot_state['active_trades']:
                        continue
                
                # Этот лог может быть слишком частым, но оставим его для детальности
                # logger.info(f"  -> Сканирую {symbol}...")
                df = get_historical_data(session, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        logger.info("="*50)
                        logger.info(f"!!! [{symbol}] НАЙДЕН СИГНАЛ ДЛЯ ПОКУПКИ !!!")
                        logger.info(f"!!! [{symbol}] Цена входа: {entry_price}")
                        logger.info(f"!!! [{symbol}] СИМУЛЯЦИЯ: Покупаю токен и занимаю депозит...")
                        logger.info("="*50)
                        
                        with t_lock:
                            bot_state['active_trades'][symbol] = {
                                "entry_price": entry_price,
                                "entry_time": datetime.now(YKT).strftime('%Y-%m-%d %H:%M:%S %Z'),
                            }

                        trade_thread = threading.Thread(
                            target=manage_trade, 
                            args=(symbol, entry_price, bot_state, t_lock)
                        )
                        trade_thread.start()
                
                time.sleep(1)

            now_local = datetime.now(YKT)
            minutes_to_wait = 5 - (now_local.minute % 5)
            seconds_to_wait = minutes_to_wait * 60 - now_local.second
            if seconds_to_wait < 0: seconds_to_wait = 0
            
            logger.info(f"Сканирование завершено. Следующая проверка через {int(seconds_to_wait)} сек.")
            time.sleep(seconds_to_wait)

        except Exception as e:
            # Используем exc_info=True, чтобы записать полный traceback ошибки в лог
            logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА в главном цикле: {e}", exc_info=True)
            logger.info("Перезапуск через 60 секунд...")
            time.sleep(60)

if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        logger.info("Программа остановлена вручную.")