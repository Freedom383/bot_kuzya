# trade_manager.py
import os
import csv
import time
import logging
import asyncio
from datetime import datetime
import ccxt.pro as ccxt_pro # <<< Важно: импортируем ccxt.pro
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

async def watch_loop(symbol, entry_price, bot_state, t_lock):
    """Асинхронный цикл для отслеживания цены через WebSocket ccxt.pro."""
    
    stop_loss_price = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
    take_profit_price = entry_price * (1 + config.TAKE_PROFIT_PERCENT / 100)
    
    logger.info(f"[{symbol}] Цели: Take Profit = {take_profit_price:.4f}, Stop Loss = {stop_loss_price:.4f}")

    # Создаем экземпляр биржи внутри async функции
    exchange = ccxt_pro.bybit({
        'apiKey': config.BYBIT_API_KEY,
        'secret': config.BYBIT_API_SECRET,
        'options': {
            'defaultType': 'spot',
        },
    })

    try:
        while True:
            # watch_ticker - это асинхронный метод для получения данных по WebSocket
            ticker = await exchange.watch_ticker(symbol)
            last_price = ticker.get('last')

            if last_price is None:
                continue

            logger.info(f"[{symbol}] Отслеживаю... Текущая цена: {last_price}")
            
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
                break # Выходим из цикла while, чтобы завершить отслеживание

    except Exception as e:
        logger.error(f"[{symbol}] ОШИБКА в WebSocket цикле: {e}", exc_info=True)
    finally:
        # Важно закрыть соединение
        await exchange.close()
        logger.info(f"[{symbol}] Соединение WebSocket закрыто.")


def manage_trade(symbol, entry_price, bot_state, t_lock):
    """
    Эта функция запускается в отдельном потоке и управляет асинхронным циклом.
    """
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ. Цена входа: {entry_price}")
    try:
        asyncio.run(watch_loop(symbol, entry_price, bot_state, t_lock))
    except Exception as e:
        logger.error(f"[{symbol}] КРИТИЧЕСКАЯ ОШИБКА при запуске менеджера сделок: {e}")
    
    logger.info(f"[{symbol}] Менеджер сделки завершил работу.")
