# trade_manager.py
import os
import csv
import time
from datetime import datetime
from pybit.unified_trading import WebSocket
import config

def record_trade(data, lock):
    """Потокобезопасно записывает результат сделки в CSV файл."""
    file_path = 'trades.csv'
    with lock:
        file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['token', 'purchase_time', 'sale_time', 'purchase_price', 'sale_price', 'result']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)
    print(f"[{data['token']}] Сделка записана в trades.csv")

def manage_trade(symbol, entry_price, bot_state, t_lock):
    """
    Отслеживает цену через WebSocket и симулирует закрытие сделки.
    """
    print(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ. Цена входа: {entry_price}")
    
    stop_loss_price = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
    take_profit_price = entry_price * (1 + config.TAKE_PROFIT_PERCENT / 100)
    
    print(f"[{symbol}] Цели: Take Profit = {take_profit_price:.4f}, Stop Loss = {stop_loss_price:.4f}")

    ws = WebSocket(testnet=False, channel_type="spot")

    def handle_message(message):
        try:
            data = message.get("data", [{}])[0]
            last_price = float(data.get("lastPrice", 0))
            print (last_price)
            if last_price == 0: return

            exit_price = 0
            result = ""

            if last_price <= stop_loss_price:
                exit_price = last_price
                result = "Stop Loss"
            elif last_price >= take_profit_price:
                exit_price = last_price
                result = "Take Profit"
            
            if exit_price > 0:
                print("="*50)
                print(f"!!! [{symbol}] СИМУЛЯЦИЯ: Сработал {result} по цене {exit_price} !!!")
                print("!!! [{symbol}] СИМУЛЯЦИЯ: Размещаю рыночный ордер на ПРОДАЖУ...")
                print("="*50)

                # Запись в CSV
                with t_lock:
                    entry_time = bot_state['active_trades'][symbol]['entry_time']
                
                trade_data = {
                    'token': symbol,
                    'purchase_time': entry_time,
                    'sale_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'purchase_price': entry_price,
                    'sale_price': exit_price,
                    'result': result,
                }
                record_trade(trade_data, t_lock)

                # Освобождаем "депозит"
                with t_lock:
                    if symbol in bot_state['active_trades']:
                        del bot_state['active_trades'][symbol]
                print(f"[{symbol}] Депозит освобожден.")
                
                # Закрываем WebSocket и завершаем поток
                ws.exit()

        except Exception as e:
            print(f"[{symbol}] ОШИБКА в WebSocket обработчике: {e}")
            ws.exit()

    ws.ticker_stream(symbol=symbol, callback=handle_message)
    print(f"[{symbol}] Менеджер сделки завершил работу.")
