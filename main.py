# main.py
import threading
import time
from datetime import datetime
from config import *
from pybit.unified_trading import HTTP
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade

# Глобальное состояние бота и замок для потокобезопасности
bot_state = {
    "active_trades": {}, # Словарь для отслеживания активных сделок
}
# Замок нужен, чтобы основной поток и потоки сделок не мешали друг другу
t_lock = threading.Lock()

def run_scanner():
    """Основной цикл сканера, который ищет сигналы."""
    print("="*30)
    print("Запуск торгового робота (режим симуляции)...")
    print(f"Количество депозитов: {MAX_CONCURRENT_TRADES}")
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
            
            print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
            print(f"Свободных депозитов: {MAX_CONCURRENT_TRADES - active_trades_count}. Начинаю сканирование...")
            
            for symbol in my_symbols:
                # Пропускаем монету, если она уже в сделке
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
                        
                        # Занимаем "депозит"
                        with t_lock:
                            bot_state['active_trades'][symbol] = {
                                "entry_price": entry_price,
                                "entry_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            }

                        # Запускаем менеджер сделки в отдельном потоке
                        trade_thread = threading.Thread(
                            target=manage_trade, 
                            args=(symbol, entry_price, bot_state, t_lock)
                        )
                        trade_thread.start()
                
                time.sleep(1) # Небольшая пауза между монетами, чтобы не душить API

            # Ожидание до следующей 5-минутной свечи
            now = datetime.now()
            seconds_to_wait = (5 - now.minute % 5) * 60 - now.second
            print(f"\nСканирование завершено. Следующая проверка через {seconds_to_wait} сек.")
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