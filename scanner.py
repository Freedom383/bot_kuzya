# scanner.py
import pandas as pd
import pandas_ta as ta
import logging
import ccxt

logger = logging.getLogger("bot_logger")

def get_historical_data(exchange: ccxt.Exchange, symbol: str, timeframe='5m', limit=200):
    """Получает и подготавливает исторические данные с помощью ccxt."""
    try:
        # ccxt возвращает данные в формате [[timestamp, open, high, low, close, volume]]
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            logger.warning(f"[{symbol}] Не удалось получить K-line данные (пустой ответ).")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Рассчитываем MACD
        df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
        df.dropna(inplace=True)
        return df

    except Exception as e:
        logger.error(f"[{symbol}] ОШИБКА в get_historical_data: {e}")
        return None

def check_divergence_signal(df, symbol):
    """
    Логика поиска дивергенции. Остается без изменений, так как работает с DataFrame.
    """
    if len(df) < 61: return False, None

    last_closed_hist = df['MACDh_12_26_9'].iloc[-2]
    prev_hist = df['MACDh_12_26_9'].iloc[-3]
    
    if not (prev_hist < 0 and last_closed_hist > 0):
        return False, None
    
    logger.info(f"[{symbol}] Триггер! Гистограмма пересекла 0. Ищу дивергенцию...")

    last_15_candles = df.iloc[-17:-2]
    candle1_idx = last_15_candles['MACDh_12_26_9'].idxmin()
    candle1 = df.loc[candle1_idx]
    macd1 = candle1['MACDh_12_26_9']
    low1 = candle1['low']
    
    candle1_loc = df.index.get_loc(candle1_idx)
    
    prev_50_candles = df.iloc[max(0, candle1_loc - 50) : candle1_loc]
    if prev_50_candles.empty: return False, None
        
    candle2_idx = prev_50_candles['MACDh_12_26_9'].idxmin()
    candle2 = df.loc[candle2_idx]
    macd2 = candle2['MACDh_12_26_9']
    low2 = candle2['low']

    # Твоя упрощенная логика
    is_divergence = low1 < low2 
    
    if is_divergence:
        # Проверку macd1 > macd2 оставим в логе для информации
        logger.info(f"[{symbol}] Найдена дивергенция: low1({low1}) < low2({low2}). Проверка MACD: macd1({macd1:.6f}) > macd2({macd2:.6f}) -> {macd1 > macd2}")
        if macd1 > macd2: # Добавим полную проверку для надежности сигнала
            return True, df['close'].iloc[-2]
    
    return False, None