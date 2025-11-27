# scanner.py
import pandas as pd
import pandas_ta as ta
import logging
import ccxt
import config
import pytz 

logger = logging.getLogger("bot_logger")

def get_historical_data(exchange: ccxt.Exchange, symbol: str, timeframe='5m', limit=450):
    """Получает и подготавливает исторические данные, рассчитывает индикаторы."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            logger.warning(f"[{symbol}] Не удалось получить K-line данные (пустой ответ).")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # Приводим к нужному часовому поясу
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert('Asia/Yekaterinburg')
        
        # Расчет индикаторов
        df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(append=True) 
        df.ta.atr(append=True) 
        
        df.dropna(inplace=True)
        return df

    except Exception as e:
        # Игнорируем ошибку отсутствия маркета (бывает на Bybit для старых тикеров)
        if "does not have market" not in str(e).lower():
            logger.error(f"[{symbol}] ОШИБКА в get_historical_data: {e}")
        return None

def is_hammer(candle):
    """Проверяет, является ли свеча паттерном 'Молот'."""
    body = abs(candle['close'] - candle['open'])
    if body == 0: return False
    
    lower_wick = min(candle['open'], candle['close']) - candle['low']
    upper_wick = candle['high'] - max(candle['open'], candle['close'])
    
    return lower_wick > body * 2 and upper_wick < body * 0.5

def is_bullish_engulfing(current_candle, prev_candle):
    """Проверяет, является ли пара свечей паттерном 'Бычье поглощение'."""
    if not (current_candle['close'] > current_candle['open'] and prev_candle['open'] > prev_candle['close']):
        return False
    return current_candle['close'] > prev_candle['open'] and current_candle['open'] < prev_candle['close']

def check_divergence_signal(df, symbol):
    """
    Ищет дивергенцию и проводит анализ.
    """
    if len(df) < 61: 
        return False, None, None

    # Берем предпоследнюю закрытую свечу (индекс -2), так как текущая (-1) еще формируется
    last_closed_candle_idx = -2
    
    # Данные MACD
    last_closed_hist = df['MACDh_12_26_9'].iloc[last_closed_candle_idx]
    prev_hist = df['MACDh_12_26_9'].iloc[last_closed_candle_idx - 1]
    
    # 1. Триггер: Пересечение гистограммы снизу вверх через 0
    if not (prev_hist < 0 and last_closed_hist > 0):
        return False, None, None
    
    # 2. Поиск первого дна
    search_range_1 = df.iloc[-17:last_closed_candle_idx]
    if search_range_1.empty: return False, None, None
    
    candle1_idx = search_range_1['MACDh_12_26_9'].idxmin()
    candle1 = df.loc[candle1_idx]
    macd1, low1 = candle1['MACDh_12_26_9'], candle1['low']
    
    # 3. Поиск второго (дальнего) дна
    candle1_loc_in_df = df.index.get_loc(candle1_idx)
    search_range_2 = df.iloc[max(0, candle1_loc_in_df - 50) : candle1_loc_in_df]
    if search_range_2.empty: return False, None, None
        
    candle2_idx = search_range_2['MACDh_12_26_9'].idxmin()
    candle2 = df.loc[candle2_idx]
    macd2, low2 = candle2['MACDh_12_26_9'], candle2['low']
    
    # 4. Проверка условий дивергенции
    price_diff_percent = ((low2 - low1) / low2) * 100 if low2 > 0 else 0

    is_divergence = (
        low1 < low2 and            # Цена ниже (или дно ниже)
        macd1 > macd2 and          # MACD выше (сила медведей слабеет)
        price_diff_percent >= config.MIN_PRICE_DIFF_PERCENT
    )
    
    if not is_divergence:
        return False, None, None
        
    logger.info(f"[{symbol}] ДИВЕРГЕНЦИЯ НАЙДЕНА: low1({low1:.4f}) < low2({low2:.4f}), macd1({macd1:.4f}) > macd2({macd2:.4f})") 
    
    # Сбор данных
    entry_price = df['close'].iloc[last_closed_candle_idx]
    
    avg_volume_20 = df['volume'].iloc[-22:last_closed_candle_idx].mean()
    last_3_volumes = df['volume'].iloc[-4:last_closed_candle_idx + 1].tolist()
    
    sma_200 = df['SMA_200'].iloc[last_closed_candle_idx]
    price_above_sma200 = entry_price > sma_200
    
    hammer_found = False
    bullish_engulfing_found = False
    
    candle1_loc = df.index.get_loc(candle1_idx)
    for i in range(3):
        idx_to_check = candle1_loc + i
        if idx_to_check >= len(df) or idx_to_check == 0: continue
        current_candle = df.iloc[idx_to_check]
        prev_candle = df.iloc[idx_to_check - 1]
        if is_hammer(current_candle): hammer_found = True
        if is_bullish_engulfing(current_candle, prev_candle): bullish_engulfing_found = True
        
    rsi_value = df['RSI_14'].iloc[last_closed_candle_idx]
    atr_value = df['ATRr_14'].iloc[last_closed_candle_idx]

    avg_price_14 = df['close'].iloc[-15:last_closed_candle_idx].mean()
    volatility_percent = (atr_value / avg_price_14) * 100 if avg_price_14 > 0 else 0
    
    analysis_data = {
        'avg_volume_20': round(avg_volume_20, 2),
        'vol_minus_3': last_3_volumes[0],
        'vol_minus_2': last_3_volumes[1],
        'vol_minus_1': last_3_volumes[2],
        'price_above_sma200': price_above_sma200,
        'hammer_found': hammer_found,
        'bullish_engulfing_found': bullish_engulfing_found,
        'lows_diff_percent': round(price_diff_percent, 4),
        'rsi_value': round(rsi_value, 2),
        'atr_value': atr_value,
        'volatility_percent': round(volatility_percent, 2) 
    }

    logger.info(f"[{symbol}] Аналитика сигнала готова.")
    return True, entry_price, analysis_data