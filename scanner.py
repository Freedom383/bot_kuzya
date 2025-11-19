# scanner.py
import pandas as pd
import pandas_ta as ta
import logging
import ccxt

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
        
        df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(append=True) 
        
        df.dropna(inplace=True)
        return df

    except Exception as e:
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
    Ищет дивергенцию и, в случае успеха, проводит дополнительный анализ.
    Возвращает (Сигнал, Цена входа, Словарь с аналитикой).
    """
    if len(df) < 61: return False, None, None

    last_closed_hist = df['MACDh_12_26_9'].iloc[-2]
    prev_hist = df['MACDh_12_26_9'].iloc[-3]
    
    if not (prev_hist < 0 and last_closed_hist > 0):
        return False, None, None
    
    logger.info(f"[{symbol}] Триггер! Гистограмма пересекла 0. Ищу дивергенцию...")

    last_15_candles = df.iloc[-17:-2]
    candle1_idx = last_15_candles['MACDh_12_26_9'].idxmin()
    candle1 = df.loc[candle1_idx]
    macd1, low1 = candle1['MACDh_12_26_9'], candle1['low']
    
    candle1_loc = df.index.get_loc(candle1_idx)
    
    prev_50_candles = df.iloc[max(0, candle1_loc - 50) : candle1_loc]
    if prev_50_candles.empty: return False, None, None
        
    candle2_idx = prev_50_candles['MACDh_12_26_9'].idxmin()
    candle2 = df.loc[candle2_idx]
    macd2, low2 = candle2['MACDh_12_26_9'], candle2['low']

    is_divergence = low1 < low2 
    #is_divergence = low1 < low2 and macd1 > macd2
    
    if not is_divergence:
        return False, None, None
        
    logger.info(f"[{symbol}] Найдена дивергенция: low1({low1}) < low2({low2}) и macd1({macd1:.6f}) > macd2({macd2:.6f})")
    
    # --- НАЧАЛО ДОПОЛНИТЕЛЬНОГО АНАЛИЗА ---
    entry_price = df['close'].iloc[-2]
    
    # 1. Анализ объемов
    avg_volume_20 = df['volume'].iloc[-22:-2].mean()
    last_3_volumes = df['volume'].iloc[-4:-1].tolist()
    
    # 2. Анализ SMA 200
    sma_200 = df['SMA_200'].iloc[-2]
    price_above_sma200 = entry_price > sma_200
    
    # 3. Поиск паттернов
    hammer_found = False
    bullish_engulfing_found = False
    for i in range(3):
        idx_to_check = candle1_loc + i
        if idx_to_check >= len(df) or idx_to_check == 0: continue
        current_candle = df.iloc[idx_to_check]
        prev_candle = df.iloc[idx_to_check - 1]
        if is_hammer(current_candle): hammer_found = True
        if is_bullish_engulfing(current_candle, prev_candle): bullish_engulfing_found = True
        
    # 4. <-- НОВОЕ ИЗМЕНЕНИЕ ЗДЕСЬ -->
    # Рассчитываем процентную разницу между минимумами
    lows_diff_percent = ((low2 - low1) / low2) * 100 if low2 > 0 else 0
    
    rsi_value = df['RSI_14'].iloc[-2]
    # Собираем все данные в один словарь
    analysis_data = {
        'avg_volume_20': round(avg_volume_20, 2),
        'vol_minus_3': last_3_volumes[0],
        'vol_minus_2': last_3_volumes[1],
        'vol_minus_1': last_3_volumes[2],
        'price_above_sma200': price_above_sma200,
        'hammer_found': hammer_found,
        'bullish_engulfing_found': bullish_engulfing_found,
        'lows_diff_percent': round(lows_diff_percent, 4),
        'rsi_value': round(rsi_value, 2) 
    }

    logger.info(f"[{symbol}] Аналитика сигнала: {analysis_data}")
    
    return True, entry_price, analysis_data