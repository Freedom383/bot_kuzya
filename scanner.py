# scanner.py
import pandas as pd
import pandas_ta as ta
from pybit.unified_trading import HTTP

def get_historical_data(session: HTTP, symbol: str, timeframe='5', limit=200):
    """Получает и подготавливает исторические данные. БЕЗ ASYNCIO."""
    try:
        response = session.get_kline(
            category="spot", symbol=symbol, interval=timeframe, limit=limit
        )
        if response['retCode'] == 0 and response['result']['list']:
            data = response['result']['list']
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            df = df.astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp').sort_index()
            df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
            df.dropna(inplace=True)
            return df
        else:
            print(f"[{symbol}] Предупреждение: Не удалось получить K-line данные: {response.get('retMsg', 'No data')}")
            return None
    except Exception as e:
        print(f"[{symbol}] ОШИБКА в get_historical_data: {e}")
        return None

def check_divergence_signal(df, symbol):
    """
    Ищет триггер (пересечение гистограммы) и затем проверяет наличие бычьей дивергенции.
    Возвращает (bool: сигнал найден, float: цена входа)
    """
    if len(df) < 61: return False, None
    #print(symbol)
    #print(df.iloc[-5:])
    last_closed_hist = df['MACDh_12_26_9'].iloc[-2]
    prev_hist = df['MACDh_12_26_9'].iloc[-3]
    # print(f' last_closed_his {last_closed_hist}')
    #print(f'prev_hist {prev_hist}')
    
    if not (prev_hist < 0 and last_closed_hist > 0):
        return False, None
    
    print(f"[{symbol}] Триггер! Гистограмма пересекла 0. Ищу дивергенцию...")

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

    is_divergence = low1 < low2 and macd1 > macd2
    
    if is_divergence:
        print(f"[{symbol}] Найдена дивергенция: low1({low1}) < low2({low2}) И macd1({macd1}) > macd2({macd2})")
        return True, df['close'].iloc[-2]
    
    return False, None