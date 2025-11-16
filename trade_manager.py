# trade_manager.py
import os
import csv
import logging
import asyncio
from datetime import datetime
import ccxt.pro as ccxt_pro
import ccxt
import pytz

import config
from telegram_bot import get_main_loop, send_message

logger = logging.getLogger("bot_logger")

def get_yekaterinburg_time_str():
    """Возвращает текущее время в Екатеринбурге в виде строки."""
    ekb_tz = pytz.timezone('Asia/Yekaterinburg')
    utc_now = datetime.now(pytz.utc)
    ekb_now = utc_now.astimezone(ekb_tz)
    return ekb_now.strftime('%Y-%m-%d %H:%M:%S')

def record_trade(data, lock):
    """Записывает данные о сделке, включая новую аналитику, в CSV файл."""
    file_path = 'trades.csv'
    
    # --- НОВОЕ ИЗМЕНЕНИЕ ЗДЕСЬ: Добавлено поле lows_diff_percent ---
    fieldnames = [
        'token', 'purchase_time', 'sale_time', 'purchase_price', 'sale_price', 'result',
        'avg_volume_20', 'vol_minus_3', 'vol_minus_2', 'vol_minus_1',
        'price_above_sma200', 'hammer_found', 'bullish_engulfing_found',
        'lows_diff_percent' # <-- ДОБАВЛЕНО
    ]
    # ---------------------------------------------------------------

    with lock:
        file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            if 'analysis_data' in data:
                analysis = data.pop('analysis_data')
                data.update(analysis)
            
            writer.writerow(data)
            
    logger.info(f"[{data['token']}] Сделка записана в trades.csv")


async def watch_loop(symbol, entry_price, bot_state, t_lock):
    """Основная функция отслеживания цены по WebSocket для SL/TP."""
    with t_lock:
        stop_loss_percent = bot_state['settings']['stop_loss_percent']
        take_profit_percent = bot_state['settings']['take_profit_percent']

    stop_loss_price = entry_price * (1 - stop_loss_percent / 100)
    take_profit_price = entry_price * (1 + take_profit_percent / 100)
    
    logger.info(f"[{symbol}] Цели (SL={stop_loss_percent}%, TP={take_profit_percent}%): TP={take_profit_price}, SL={stop_loss_price}")
    
    exchange = ccxt.pro.bybit()
    exit_price = 0
    result = "" 

    try:
        while symbol in bot_state['active_trades']:
            ticker = await exchange.watch_ticker(symbol)
            last_price = ticker.get('last')

            if last_price is None: continue
            
            logger.info(f"[{symbol}] Отслеживаю... Цена: {last_price}")
            
            if last_price <= stop_loss_price:
                exit_price, result = last_price, "Stop Loss"
                break
            elif last_price >= take_profit_price:
                exit_price, result = last_price, "Take Profit"
                break
        
    except asyncio.CancelledError:
        logger.warning(f"[{symbol}] Задача отслеживания отменена командой /sell.")
        # Для ручной продажи нужен синхронный ccxt, создадим временный экземпляр
        sync_exchange = ccxt.bybit() 
        ticker = await sync_exchange.fetch_ticker(symbol)
        await sync_exchange.close()
        exit_price = ticker['last']
        result = "Manual Sell"
    
    except Exception as e:
        error_msg = f"ОШИБКА в WebSocket для {symbol}: {e}"
        logger.error(error_msg, exc_info=True)
        send_message(f"🔴 {error_msg}")
    finally:
        if exit_price > 0:
            profit_pct = (exit_price / entry_price - 1) * 100
            if result == "Manual Sell":
                msg = f"👋 *Сделка закрыта вручную: {symbol}*\nЦена продажи: `{exit_price}` ({profit_pct:+.2f}%)"
            else:
                msg = f"✅ *Сделка закрыта: {symbol}*\nРезультат: *{result}* ({profit_pct:+.2f}%)"
            send_message(msg)
            
            with t_lock:
                if symbol in bot_state['active_trades']:
                    trade_info = bot_state['active_trades'][symbol]
                    trade_data = {
                        'token': symbol, 
                        'purchase_time': trade_info['entry_time'],
                         'sale_time': get_yekaterinburg_time_str(),
                        'purchase_price': entry_price, 
                        'sale_price': exit_price, 
                        'result': result,
                        'analysis_data': trade_info.get('analysis_data', {})
                    }
                    record_trade(trade_data, t_lock)
                    del bot_state['active_trades'][symbol]
            logger.info(f"[{symbol}] Слот освобожден.")
            
        await exchange.close()
        logger.info(f"[{symbol}] Соединение WebSocket закрыто.")


def manage_trade(symbol, entry_price, analysis_data, bot_state, t_lock):
    """
    Эта функция-обертка "покупает" монету, сохраняет аналитику и запускает отслеживание.
    """
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ.")

    logger.info(f"[{symbol}] СИМУЛЯЦИЯ ПОКУПКИ по цене {entry_price}")
    with t_lock:
        bot_state['active_trades'][symbol] = {
            "entry_price": entry_price,
            "entry_time": get_yekaterinburg_time_str(),
            "status": "active",
            "analysis_data": analysis_data
        }
    
    loop = get_main_loop() 
    if loop and loop.is_running():
        task = loop.create_task(watch_loop(symbol, entry_price, bot_state, t_lock))
        with t_lock:
            if symbol in bot_state['active_trades']:
                bot_state['active_trades'][symbol]['task'] = task
        logger.info(f"[{symbol}] Задача отслеживания WebSocket передана в главный цикл.")
    else:
        logger.error(f"[{symbol}] Не удалось запустить отслеживание: главный event loop не найден.")
        with t_lock:
            if symbol in bot_state['active_trades']:
                del bot_state['active_trades'][symbol]