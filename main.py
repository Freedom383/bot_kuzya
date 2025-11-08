# main.py
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
import ccxt
from config import *
from logger_setup import setup_logger
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade

logger = setup_logger()

try:
    from zoneinfo import ZoneInfo
    YKT = ZoneInfo("Asia/Yekaterinburg")
except Exception:
    YKT = timezone(timedelta(hours=5))

bot_state = {"active_trades": {}}
t_lock = threading.Lock()

def run_scanner():
    logger.info("="*30)
    logger.info("Запуск торгового робота (режим симуляции) на CCXT...")
    logger.info("="*30)

    exchange = ccxt.bybit({
        'apiKey': BYBIT_API_KEY,
        'secret': BYBIT_API_SECRET,
        'options': {'defaultType': 'spot'},
    })
    
    while True:
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            if active_trades_count >= MAX_CONCURRENT_TRADES:
                logger.info("ВСЕ ДЕПОЗИТЫ ЗАНЯТЫ АНДРЮШКА КРАСАВЧИК И МИЛЛИОНЕР!!!!!!!!!")
                time.sleep(30)
                continue
            
            now_local = datetime.now(YKT)
            logger.info(f"Свободных депозитов: {MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in my_symbols:
                with t_lock:
                    if symbol in bot_state['active_trades']:
                        continue
                
                df = get_historical_data(exchange, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        # <<< ГЛАВНОЕ ИЗМЕНЕНИЕ ЗДЕСЬ! >>>
                        # Повторно проверяем количество сделок ПЕРЕД тем, как занять новый депозит.
                        with t_lock:
                            if len(bot_state['active_trades']) >= MAX_CONCURRENT_TRADES:
                                logger.warning(f"[{symbol}] Найден сигнал, но все депозиты уже заняты в этом цикле. Прерываю сканирование.")
                                break # Прерываем цикл for, т.к. искать дальше нет смысла

                            logger.info("="*50)
                            logger.info(f"!!! [{symbol}] НАЙДЕН СИГНАЛ ДЛЯ ПОКУПКИ по цене {entry_price} !!!")
                            logger.info(f"!!! [{symbol}] СИМУЛЯЦИЯ: Занимаю депозит...")
                            logger.info("="*50)
                            
                            bot_state['active_trades'][symbol] = {
                                "entry_price": entry_price,
                                "entry_time": datetime.now(YKT).strftime('%Y-%m-%d %H:%M:%S %Z'),
                            }

                        # Поток запускаем ВНЕ блокировки, чтобы не тормозить основной цикл
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
            logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА в главном цикле: {e}", exc_info=True)
            logger.info("Перезапуск через 60 секунд...")
            time.sleep(60)

if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        logger.info("\nПрограмма остановлена вручную.")