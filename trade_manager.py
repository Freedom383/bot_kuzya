# trade_manager.py
import os
import csv
import logging
import asyncio
from datetime import datetime
import ccxt.pro as ccxt_pro

import config
# Импортируем главный цикл и функцию отправки сообщений
from telegram_bot import get_main_loop, send_message

logger = logging.getLogger("bot_logger")

def record_trade(data, lock):
    file_path = 'trades.csv'
    with lock:
        # ... (код этой функции не меняется)
        file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['token', 'purchase_time', 'sale_time', 'purchase_price', 'sale_price', 'result']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)
    logger.info(f"[{data['token']}] Сделка записана в trades.csv")


async def watch_loop(symbol, entry_price, bot_state, t_lock):
    """Асинхронный цикл для отслеживания цены. Код почти не изменился."""
    stop_loss_price = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
    take_profit_price = entry_price * (1 + config.TAKE_PROFIT_PERCENT / 100)
    
    logger.info(f"[{symbol}] Цели: TP={take_profit_price:.4f}, SL={stop_loss_price:.4f}")

    exchange = ccxt_pro.bybit() # Создаем новый экземпляр для каждого потока
    try:
        while bot_state.get('running', False): # Добавили проверку, чтобы выйти при остановке бота
            ticker = await exchange.watch_ticker(symbol)
            last_price = ticker.get('last')

            if last_price is None: continue
            logger.debug(f"[{symbol}] Отслеживаю... Цена: {last_price}")
            
            exit_price, result = 0, ""
            if last_price <= stop_loss_price:
                exit_price, result = last_price, "Stop Loss"
            elif last_price >= take_profit_price:
                exit_price, result = last_price, "Take Profit"
            
            if exit_price > 0:
                profit_pct = (exit_price / entry_price - 1) * 100
                msg = f"✅ *Сделка закрыта: {symbol}*\nРезультат: *{result}* ({profit_pct:+.2f}%)"
                logger.info(f"!!! [{symbol}] {result} по цене {exit_price} !!!")
                send_message(msg)

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
                logger.info(f"[{symbol}] Слот освобожден.")
                break # Выходим из цикла while
            
            await asyncio.sleep(0.1) # Небольшая пауза

    except Exception as e:
        error_msg = f"ОШИБКА в WebSocket для {symbol}: {e}"
        logger.error(error_msg, exc_info=True)
        send_message(f"🔴 {error_msg}")
    finally:
        await exchange.close()
        logger.info(f"[{symbol}] Соединение WebSocket закрыто.")


def manage_trade(symbol, entry_price, bot_state, t_lock):
    """
    Эта функция запускается в отдельном потоке и передает
    асинхронную задачу в главный event loop телеграм-бота.
    """
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ.")
    
    loop = get_main_loop() 
    
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            watch_loop(symbol, entry_price, bot_state, t_lock),
            loop # Используем полученный цикл
        )
        logger.info(f"[{symbol}] Задача отслеживания передана в главный цикл.")
    else:
        logger.error(f"[{symbol}] Не удалось запустить отслеживание: главный event loop не найден или не запущен.")