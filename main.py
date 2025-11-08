# main.py
import threading
import time
from datetime import datetime, timezone, timedelta
from config import *
from pybit.unified_trading import HTTP
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade

# Часовой пояс Екатеринбурга
try:
    from zoneinfo import ZoneInfo
    YKT = ZoneInfo("Asia/Yekaterinburg")
except Exception:
    # Фолбэк: фиксированный UTC+5 (без переходов на летнее/зимнее время)
    YKT = timezone(timedelta(hours=5))

# Глобальное состояние бота и замок для потокобезопасности
bot_state = {
    "active_trades": {},
}
t_lock = threading.Lock()

def run_scanner():
    print("="*30)
    print("Запуск торгового робота (режим симуляции)...")
    print(f"Количество депозитов: {MAX_CONCURRENT_TRADES}")
    # Печатаем текущее время Екатеринбурга
    print("Текущее время (Екатеринбург):", datetime.now(YKT).strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("="*30)

    session = HTTP(testnet=False, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    
    while True:
        try:
            with t_lock:
                active_trades_count = len(bot_state['active_trades'])
            
            if active_trades_count >= MAX_CONCURRENT_TRADES:
                print(f"Все {MAX_CONCURRENT_TRADES} депозита заняты. Ожидание...")
                time.sleep(30)
                continue
            
            now_local = datetime.now(YKT)
            print(f"\n--- {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
            print(f"Свободных депозитов: {MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in my_symbols:
                with t_lock:
                    if symbol in bot_state['active_trades']:
                        continue
                
                print(f"  -> Сканирую {symbol}...")
                df = get_historical_data(session, symbol)
                if df is not None and not df.empty:
                    signal_found, entry_price = check_divergence_signal(df, symbol)
                    
                    if signal_found:
                        print("="*50)
                        print(f"!!! [{symbol}] НАЙДЕН СИГНАЛ ДЛЯ ПОКУПКИ !!!")
                        print(f"!!! [{symbol}] Цена входа: {entry_price}")
                        print(f"!!! [{symbol}] СИМУЛЯЦИЯ: Покупаю токен и занимаю депозит...")
                        print("="*50)
                        
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

            # Ожидание до следующей 5-минутной свечи по времени Екатеринбурга
            now_local = datetime.now(YKT)
            minutes_to_wait = 5 - (now_local.minute % 5)
            seconds_to_wait = minutes_to_wait * 60 - now_local.second
            if seconds_to_wait < 0:
                seconds_to_wait = 0
            print(f"\nСканирование завершено. Следующая проверка через {int(seconds_to_wait)} сек. "
                  f"(сейчас {now_local.strftime('%H:%M:%S %Z')})")
            time.sleep(seconds_to_wait)

        except Exception as e:
            print(f"\nКРИТИЧЕСКАЯ ОШИБКА в главном цикле: {e}")
            print("Перезапуск через 60 секунд...")
            time.sleep(60)

if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        print("\nПрограмма остановлена вручную.")