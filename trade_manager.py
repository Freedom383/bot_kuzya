# trade_manager.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)

import os
import csv
import logging
import asyncio
from datetime import datetime
import ccxt.pro as ccxt_pro
import ccxt.async_support as ccxt_async
import pytz
import pandas as pd
import pandas_ta as ta # Добавлен импорт для pandas_ta
import ccxt

import config
from telegram_bot import get_main_loop, send_message

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("bot_logger")

def get_yekaterinburg_time_str():
    ekb_tz = pytz.timezone('Asia/Yekaterinburg')
    utc_now = datetime.now(pytz.utc)
    ekb_now = utc_now.astimezone(ekb_tz)
    return ekb_now.strftime('%Y-%m-%d %H:%M:%S')

def record_trade(data, lock):
    file_path = os.path.join(BASE_DIR, 'trades.csv')
    fieldnames = [
        'token', 'purchase_time', 'sale_time', 'purchase_price', 'sale_price', 'result',
        'trade_size_usdt', 'pnl_usdt', 'commission_paid_usdt', 'avg_volume_20', 'vol_minus_3',
        'vol_minus_2', 'vol_minus_1', 'price_above_sma200', 'hammer_found',
        'bullish_engulfing_found', 'rsi_value', 'price_above_sma50_1h',
        'price_above_sma200_1h', 'lows_diff_percent', 'volatility_percent',
    ]
    try:
        file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            if 'analysis_data' in data:
                analysis = data.pop('analysis_data')
                data.update(analysis)
            for field in fieldnames:
                data.setdefault(field, None)
            writer.writerow(data)
        logger.info(f"[{data['token']}] Сделка успешно записана в trades.csv")
    except Exception as e:
        error_msg = f"КРИТИЧЕСКАЯ ОШИБКА в record_trade для {data.get('token', 'N/A')}: {e}"
        logger.critical(error_msg, exc_info=True)
        send_message(f"🔴 {error_msg}")

async def get_1h_sma_analysis_async(symbol, entry_price):
    async with ccxt_async.bybit({'options': {'defaultType': 'spot'}}) as async_exchange:
        try:
            logger.info(f"[{symbol}] АСИНХРОННО получаю данные за 1 час...")
            ohlcv_1h = await async_exchange.fetch_ohlcv(symbol, '1h', limit=201)
            if not ohlcv_1h or len(ohlcv_1h) < 200:
                logger.warning(f"[{symbol}] Недостаточно данных за 1ч для расчета SMA.")
                return None
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1h.ta.sma(length=50, append=True)
            df_1h.ta.sma(length=200, append=True)
            analysis = {
                'price_above_sma50_1h': bool(entry_price > df_1h['SMA_50'].iloc[-1]),
                'price_above_sma200_1h': bool(entry_price > df_1h['SMA_200'].iloc[-1])
            }
            logger.info(f"[{symbol}] Анализ на 1ч: {analysis}")
            return analysis
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка при асинхронном анализе на 1ч: {e}")
            return None

def finalize_trade_sync(symbol, entry_price, exit_price, result, bot_state, t_lock):
    logger.info(f"[{symbol}] Запускаю синхронное завершение сделки...")
    try:
        with t_lock:
            if symbol not in bot_state['active_trades']:
                logger.warning(f"[{symbol}] Попытка завершить уже отсутствующую сделку.")
                return
            trade_info = bot_state['active_trades'][symbol]
            trade_size_usdt = trade_info.get('trade_size_usdt', 0)
            net_pnl_usdt = 0
            total_commission_usdt = 0
            if trade_size_usdt > 0:
                exit_value_usdt = trade_size_usdt * (exit_price / entry_price)
                buy_commission = trade_size_usdt * (config.TRADING_COMMISSION_PERCENT / 100)
                sell_commission = exit_value_usdt * (config.TRADING_COMMISSION_PERCENT / 100)
                total_commission_usdt = buy_commission + sell_commission
                gross_pnl_usdt = exit_value_usdt - trade_size_usdt
                net_pnl_usdt = gross_pnl_usdt - total_commission_usdt
                bot_state['balance_usdt'] += net_pnl_usdt
                logger.info(
                    f"[{symbol}] PnL (Net): {net_pnl_usdt:+.2f} USDT | Комиссия: {total_commission_usdt:.4f} USDT. "
                    f"Новый баланс: {bot_state['balance_usdt']:.2f} USDT"
                )
            trade_data = {
                'token': symbol,
                'purchase_time': trade_info['entry_time'],
                'sale_time': get_yekaterinburg_time_str(),
                'purchase_price': entry_price,
                'sale_price': exit_price,
                'result': result,
                'analysis_data': trade_info.get('analysis_data', {}),
                'trade_size_usdt': round(trade_size_usdt, 2),
                'pnl_usdt': round(net_pnl_usdt, 2),
                'commission_paid_usdt': round(total_commission_usdt, 4),
            }
            record_trade(trade_data, t_lock)
            del bot_state['active_trades'][symbol]
            logger.info(f"[{symbol}] Слот освобожден.")
    except Exception as e:
        error_msg = f"КРИТИЧЕСКАЯ ОШИБКА при записи сделки {symbol} в файл: {e}"
        logger.critical(error_msg, exc_info=True)
        send_message(f"🔴 {error_msg}")

async def watch_loop(symbol, entry_price, initial_stop_loss, bot_state, t_lock, settings, analysis_data, trade_size_usdt):
    exchange = ccxt_pro.bybit()
    exit_price = 0
    result = ""
    use_trailing = settings.get('use_trailing_stop', False)
    
    # <<< ИЗМЕНЕНИЕ 1: Определяем Take Profit сразу >>>
    take_profit_price = entry_price * (1 + settings['take_profit_percent'] / 100)

    atr_value = analysis_data.get('atr_value')
    atr_multiplier = settings.get('atr_multiplier', config.DEFAULT_ATR_MULTIPLIER)
    activation_perc = settings.get('trailing_stop_activation_percent', 1.0)
    activation_price = entry_price * (1 + activation_perc / 100)
    
    current_stop_loss = initial_stop_loss
    highest_price = entry_price
    trailing_is_active = False
    
    
    if use_trailing:
        logger.info(f"[{symbol}] Трейлинг-стоп включен. Активация по цене: {activation_price:.6f}")
    else:
        logger.info(f"[{symbol}] Тейк-профит установлен на: {take_profit_price:.6f}")
    logger.info(f"[{symbol}] Начальный стоп: {current_stop_loss:.6f}")

    while symbol in bot_state['active_trades']:
        try:
            ticker = await exchange.watch_ticker(symbol)
            last_price = ticker.get('last') or ticker.get('close')
            #print(f"последняя цена {last_price}")
            if last_price is None:
                continue
            
            # --- ОСНОВНАЯ ЛОГИКА ---
            if last_price > highest_price:
                highest_price = last_price

            # --- ЛОГИКА ТРЕЙЛИНГ-СТОПА ---
            if use_trailing:
                if not trailing_is_active and highest_price >= activation_price:
                    trailing_is_active = True
                    # <<< ИЗМЕНЕНИЕ 2: При активации трейлинга ставим стоп в безубыток >>>
                    if current_stop_loss < entry_price:
                        current_stop_loss = entry_price
                        logger.info(f"[{symbol}] Трейлинг АКТИВИРОВАН. Стоп-лосс перенесен в безубыток: {entry_price:.6f}")
                        send_message(f"📈 [{symbol}] Трейлинг-стоп АКТИВИРОВАН! Сделка в безубытке.")

                if trailing_is_active and atr_value:
                    potential_new_stop = highest_price - (atr_value * atr_multiplier)
                    if potential_new_stop > current_stop_loss:
                        logger.info(f"[{symbol}] Стоп-лосс поднят с {current_stop_loss:.6f} до {potential_new_stop:.6f}")
                        current_stop_loss = potential_new_stop
            
            # --- ЛОГИКА ВЫХОДА ИЗ СДЕЛКИ ---

            # Условие выхода по стоп-лоссу (работает всегда)
            if last_price <= current_stop_loss:
                exit_price, result = last_price, "Stop Loss"
                print(f" цена продажи >>>>>>>>>>>{exit_price}")
                send_message(f" цена продажи >>>>>>>>>>>{exit_price}")
                if trailing_is_active:
                    result = "Trailing Stop" # Если трейлинг был активен, это уже Trailing Stop
                break

            # <<< ИЗМЕНЕНИЕ 3: Добавлено условие выхода по тейк-профиту >>>
            # Срабатывает только если трейлинг-стоп НЕ используется
            if not use_trailing and last_price >= take_profit_price:
                exit_price, result = last_price, "Take Profit"
                break

        except ccxt.NetworkError as e:
            logger.warning(f"[{symbol}] СЕТЕВАЯ ОШИБКА в WebSocket: {e}. Переподключаюсь через 10 секунд...")
            await exchange.close()
            await asyncio.sleep(10)
            continue
        except asyncio.CancelledError:
            logger.warning(f"[{symbol}] Задача отслеживания отменена командой /sell.")
            async with ccxt_async.bybit() as sync_exchange:
                ticker = await sync_exchange.fetch_ticker(symbol)
                exit_price = ticker['last']
            result = "Manual Sell"
            break
        except Exception as e:
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА в WebSocket для {symbol}: {e}"
            logger.error(error_msg, exc_info=True)
            send_message(f"🔴 {error_msg}")
            exit_price, result = entry_price, "Error"
            break
        
    try:
        if exit_price > 0 and result:
            profit_pct = (exit_price / entry_price - 1) * 100
            
            # <<< ИЗМЕНЕНИЕ 4: Упрощение сообщения, PnL в USDT будет посчитан в finalize_trade_sync >>>
            base_msg = {
                "Take Profit": f"💰 *Take Profit: {symbol}*",
                "Stop Loss": f"🛡️ *Stop Loss: {symbol}*",
                "Trailing Stop": f"📈 *Trailing Stop: {symbol}*",
                "Manual Sell": f"👋 *Сделка закрыта вручную: {symbol}*",
                "Error": f"🔴 *Сделка закрыта по ошибке: {symbol}*",
            }.get(result, f"✅ *Сделка закрыта: {symbol}*")

            msg = (
                f"{base_msg}\n"
                f"Результат: *{result}* ({profit_pct:+.2f}%)"
            )
            send_message(msg)
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                finalize_trade_sync, 
                symbol, entry_price, exit_price, result, bot_state, t_lock
            )
    finally:
        await exchange.close()
        logger.info(f"[{symbol}] Соединение WebSocket окончательно закрыто.")


def manage_trade(symbol, entry_price, analysis_data, bot_state, t_lock):
    logger.info(f"[{symbol}] ЗАПУЩЕН МЕНЕДЖЕР СДЕЛКИ.")
    with t_lock:
        settings = bot_state['settings'].copy()
        current_balance = bot_state['balance_usdt']
        max_trades = settings['max_concurrent_trades']
        trade_size_usdt = current_balance / max_trades

    atr_value = analysis_data.get('atr_value')
    if config.STOP_LOSS_MODE == 'ATR' and atr_value:
        atr_multiplier = settings.get('atr_multiplier', config.DEFAULT_ATR_MULTIPLIER)
        stop_loss_price = entry_price - (atr_multiplier * atr_value)
        sl_info = f"ATR ({atr_multiplier}x)"
    else:
        stop_loss_price = entry_price * (1 - settings['stop_loss_percent'] / 100)
        sl_info = f"{settings['stop_loss_percent']}%"
    sl_percent_from_entry = ((stop_loss_price - entry_price) / entry_price) * 100
    # <<< ИЗМЕНЕНИЕ 5: Исправлен текст сообщения >>>
    message_text = (
        f"🔥 *Сигнал на покупку: {symbol}*\n\n"
        f"Цена входа: `{entry_price:.6f}`\n"
        f"Размер позиции: `{trade_size_usdt:.2f} USDT`\n\n"
        
    )
    
    if settings.get('use_trailing_stop'):
        activation_perc = settings.get('trailing_stop_activation_percent', 1.0)
        message_text += f"📈 *Трейлинг-стоп:* Активен (активация при +{activation_perc}%)\n"
    else:
        take_profit_price = entry_price * (1 + settings['take_profit_percent'] / 100)
        message_text += f"🎯 *Take Profit:* `{take_profit_price:.6f}`\n"
    
    message_text += f"🛡️ *Начальный Stop Loss:* `{stop_loss_price:.6f}` ({sl_percent_from_entry})"
    
    send_message(message_text)
    
    sma_analysis_1h = None
    loop = get_main_loop()
    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(get_1h_sma_analysis_async(symbol, entry_price), loop)
        try:
            sma_analysis_1h = future.result(timeout=60)
        except Exception as e:
            logger.error(f"[{symbol}] Не удалось получить результат анализа на 1ч: {e}")

    if sma_analysis_1h:
        analysis_data.update(sma_analysis_1h)
    else:
        analysis_data['price_above_sma50_1h'] = None
        analysis_data['price_above_sma200_1h'] = None
    
    logger.info(f"[{symbol}] СИМУЛЯЦИЯ ПОКУПКИ по цене {entry_price}")
    with t_lock:
        bot_state['active_trades'][symbol] = {
            "entry_price": entry_price,
            "entry_time": get_yekaterinburg_time_str(),
            "status": "active",
            "analysis_data": analysis_data,
            "trade_size_usdt": trade_size_usdt,
        }
    
    if loop and loop.is_running():
        task_future = asyncio.run_coroutine_threadsafe(
            watch_loop(symbol, entry_price, stop_loss_price, bot_state, t_lock, settings, analysis_data, trade_size_usdt), loop)
        with t_lock:
            if symbol in bot_state['active_trades']:
                bot_state['active_trades'][symbol]['task_future'] = task_future
        logger.info(f"[{symbol}] Задача отслеживания WebSocket передана в главный цикл.")
    else:
        logger.error(f"[{symbol}] Не удалось запустить отслеживание: главный event loop не найден.")
        with t_lock:
            if symbol in bot_state['active_trades']:
                del bot_state['active_trades'][symbol]