# trade_manager.py
import os
import csv
import time
import logging
from datetime import datetime
from pybit.unified_trading import WebSocket
from websocket._exceptions import WebSocketConnectionClosedException
import config

logger = logging.getLogger("bot_logger")

def record_trade(data, lock):
    file_path = 'trades.csv'
    with lock:
        file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['token', 'purchase_time', 'sale_time', 'purchase_price', 'sale_price', 'result']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)
    logger.info(f"[{data['token']}] Сделка записана в trades.csv")

def manage_trade(symbol, entry_price, bot_state, t_lock):
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ. Цена входа: {entry_price}")
    
    stop_loss_price = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
    take_profit_price = entry_price * (1 + config.TAKE_PROFIT_PERCENT / 100)
    
    logger.info(f"[{symbol}] Цели: Take Profit = {take_profit_price:.4f}, Stop Loss = {stop_loss_price:.4f}")

    ws = WebSocket(testnet=False, channel_type="spot")

    def handle_message(message):
        try:
            # <<< ГЛАВНОЕ ИСПРАВЛЕНИЕ ЗДЕСЬ >>>
            # 1. Получаем СЛОВАРЬ с данными, а не список
            data = message.get("data")
            
            # 2. Проверяем, что это не служебное сообщение и в нем есть данные
            if not data or not isinstance(data, dict):
                return
            
            # 3. Берем цену напрямую из этого словаря
            last_price_str = data.get("lastPrice")
            if not last_price_str: 
                return
            # <<< КОНЕЦ ИСПРАВЛЕНИЯ >>>
            
            last_price = float(last_price_str)
            exit_price = 0
            result = ""

            if last_price <= stop_loss_price:
                exit_price = last_price
                result = "Stop Loss"
            elif last_price >= take_profit_price:
                exit_price = last_price
                result = "Take Profit"
            
            if exit_price > 0:
                logger.info("="*50)
                logger.info(f"!!! [{symbol}] СИМУЛЯЦИЯ: Сработал {result} по цене {exit_price} !!!")
                logger.info(f"!!! [{symbol}] СИМУЛЯЦИЯ: Размещаю рыночный ордер на ПРОДАЖУ...")
                logger.info("="*50)

                with t_lock:
                    entry_time = bot_state['active_trades'][symbol]['entry_time']
                
                trade_data = {
                    'token': symbol, 'purchase_time': entry_time,
                    'sale_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'purchase_price': entry_price, 'sale_price': exit_price, 'result': result
                }
                record_trade(trade_data, t_lock)

                with t_lock:
                    if symbol in bot_state['active_trades']:
                        del bot_state['active_trades'][symbol]
                logger.info(f"[{symbol}] Депозит освобожден.")
                
                ws.exit()

        except Exception as e:
            logger.error(f"[{symbol}] ОШИБКА в WebSocket обработчике: {e}", exc_info=True)
            ws.exit()

    try:
        ws.ticker_stream(symbol=symbol, callback=handle_message)
    except WebSocketConnectionClosedException:
        logger.info(f"[{symbol}] Соединение WebSocket было закрыто штатно по завершению сделки.")
    
    logger.info(f"[{symbol}] Менеджер сделки завершил работу.")
