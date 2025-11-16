# trade_manager.py
import os
import csv
import logging
import asyncio
from datetime import datetime
import ccxt.pro as ccxt_pro

import config
from telegram_bot import get_main_loop, send_message

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
    with t_lock:
        stop_loss_percent = bot_state['settings']['stop_loss_percent']
        take_profit_percent = bot_state['settings']['take_profit_percent']

    stop_loss_price = entry_price * (1 - stop_loss_percent / 100)
    take_profit_price = entry_price * (1 + take_profit_percent / 100)
    
    logger.info(f"[{symbol}] Цели (SL={stop_loss_percent}%, TP={take_profit_percent}%): TP={take_profit_price:.4f}, SL={stop_loss_price:.4f}")
    
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Убираем всю логику прокси, подключаемся к бирже напрямую.
    exchange = ccxt_pro.bybit()
    # -----------------------

    exit_price = 0  
    result = "" 

    try:
        while symbol in bot_state['active_trades'] and bot_state.get('running', False):
            ticker = await exchange.watch_ticker(symbol)
            last_price = ticker.get('last')

            if last_price is None: 
                continue
            
            logger.debug(f"[{symbol}] Отслеживаю... Цена: {last_price}")
            
            if last_price <= stop_loss_price:
                exit_price, result = last_price, "Stop Loss"
                break
            elif last_price >= take_profit_price:
                exit_price, result = last_price, "Take Profit"
                break
        
    except asyncio.CancelledError:
        logger.warning(f"[{symbol}] Задача отслеживания отменена командой /sell.")
        ticker = await exchange.fetch_ticker(symbol)
        exit_price = ticker['last']
        result = "Manual Sell"
    
    except Exception as e:
        error_msg = f"ОШИБКА в WebSocket для {symbol}: {e}"
        logger.error(error_msg, exc_info=True)
        send_message(f"🔴 {error_msg}")
        exit_price = 0
    finally:
        if exit_price > 0:
            profit_pct = (exit_price / entry_price - 1) * 100
            if result == "Manual Sell":
                msg = f" manually *Сделка закрыта вручную: {symbol}*\nЦена продажи: `{exit_price}` ({profit_pct:+.2f}%)"
            else:
                msg = f"✅ *Сделка закрыта: {symbol}*\nРезультат: *{result}* ({profit_pct:+.2f}%)"
            send_message(msg)
            
            with t_lock:
                if symbol in bot_state['active_trades']:
                    entry_time = bot_state['active_trades'][symbol]['entry_time']
                    trade_data = {
                        'token': symbol, 'purchase_time': entry_time,
                        'sale_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'purchase_price': entry_price, 'sale_price': exit_price, 'result': result
                    }
                    record_trade(trade_data, t_lock)
                    del bot_state['active_trades'][symbol]
            logger.info(f"[{symbol}] Слот освобожден.")
            
        await exchange.close()
        logger.info(f"[{symbol}] Соединение WebSocket закрыто.")


def manage_trade(symbol, entry_price, bot_state, t_lock):
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ.")
    loop = get_main_loop() 
    if loop and loop.is_running():
        task = loop.create_task(watch_loop(symbol, entry_price, bot_state, t_lock))
        with t_lock:
            if symbol in bot_state['active_trades']:
                bot_state['active_trades'][symbol]['task'] = task
        logger.info(f"[{symbol}] Задача отслеживания передана в главный цикл.")
    else:
        logger.error(f"[{symbol}] Не удалось запустить отслеживание: главный event loop не найден.")