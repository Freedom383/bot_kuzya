import pandas as pd
import pandas_ta as ta
from pybit.unified_trading import HTTP
import time
import pytz
from datetime import datetime

# Настройте сессию с Bybit
session = HTTP(testnet=False)

def get_historical_data(symbol, timeframe='5', limit=200):
    """
    Получает исторические данные для символа, рассчитывает MACD и 
    конвертирует время в екатеринбургское.
    """
    try:
        response = session.get_kline(
            category="spot", 
            symbol=symbol,
            interval=timeframe,
            limit=limit
        )

        if response['retCode'] == 0 and response['result']['list']:
            data = response['result']['list']
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            
            for col in df.columns:
                df[col] = pd.to_numeric(df[col])

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp')
            
            df.sort_index(ascending=True, inplace=True)
            
            df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
            
            df.dropna(inplace=True)
            
            df.index = df.index.tz_localize('UTC').tz_convert('Asia/Yekaterinburg')
            
            return df
        else:
            return None
    except Exception as e:
        print(f"Ошибка при получении данных для {symbol}: {e}")
        return None

def check_entry_signal(df, symbol):
    if len(df) < 61: 
        return

    # <<< ИЗМЕНЕНИЕ 1: Работаем с ГИСТОГРАММОЙ для сигнала входа >>>
    # Используем колонку 'MACDh_12_26_9' - это и есть гистограмма
    last_closed_histogram = df['MACDh_12_26_9'].iloc[-2]
    prev_histogram = df['MACDh_12_26_9'].iloc[-3]

    # Условие "гистограмма пересекла ноль снизу вверх"
    if prev_histogram < 0 and last_closed_histogram > 0:
        print(f"[{symbol}] !!! СИГНАЛ: Гистограмма пересекла ноль. Ищу дивергенцию...")
        
        # --- Поиск дивергенции (остается по ЛИНИИ MACD, как в классической стратегии) ---
        # Свеча 1 и Свеча 2 ищутся по минимумам ЛИНИИ 'MACD_12_26_9'
        last_10_candles = df.iloc[-12:-2] 
        neg_macd_10 = last_10_candles[last_10_candles['MACD_12_26_9'] < 0]

        if neg_macd_10.empty:
            print(f"[{symbol}] Поиск дивергенции прерван: не найдено отрицательных MACD в последних 10 свечах.")
            return

        candle1_index = neg_macd_10['MACD_12_26_9'].idxmin()
        candle1 = df.loc[candle1_index]
        macd1 = candle1['MACD_12_26_9'] # Берем значение ЛИНИИ
        low1 = candle1['low']
        
        candle1_loc = df.index.get_loc(candle1_index)
        if candle1_loc < 50:
            return
        
        prev_50_candles = df.iloc[candle1_loc - 50 : candle1_loc]
        neg_macd_50 = prev_50_candles[prev_50_candles['MACD_12_26_9'] < 0]

        if neg_macd_50.empty:
            print(f"[{symbol}] Поиск дивергенции прерван: не найдено отрицательных MACD в предыдущих 50 свечах.")
            return

        candle2_index = neg_macd_50['MACD_12_26_9'].idxmin()
        candle2 = df.loc[candle2_index]
        macd2 = candle2['MACD_12_26_9'] # Берем значение ЛИНИИ
        low2 = candle2['low']

        price_diff_percent = ((low2 - low1) / low2) * 100
        
        print(f"[{symbol}] Кандидат на дивергенцию:")
        print(f"  Свеча 1 ({candle1.name.strftime('%Y-%m-%d %H:%M')}): MACD_Line={macd1:.8f}, Low={low1}")
        print(f"  Свеча 2 ({candle2.name.strftime('%Y-%m-%d %H:%M')}): MACD_Line={macd2:.8f}, Low={low2}")
        print(f"  Условия: MACD1 > MACD2 ({macd1 > macd2}), Low1 < Low2 ({low1 < low2}), Разница цен > 3% ({price_diff_percent:.2f}%)")
        
        if macd1 > macd2 and low1 < low2 and price_diff_percent > 3.0:
            print("="*50)
            print(f"!!! НАЙДЕНА ТОЧКА ВХОДА В ЛОНГ ДЛЯ {symbol} !!!")
            print(f"Время сигнала (ЕКБ): {df.index[-2].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Цена входа (Close): {df['close'].iloc[-2]}")
            print("="*50)

def main():
    print("Запуск торгового робота...")
    my_symbols = [
    'ADAUSDT', 'AEVOUSDT', 'ALGOUSDT', 'ARUSDT', 'ARKMUSDT', 'ATOMUSDT', 'AVAXUSDT',
    'BBUSDT', 'BICOUSDT', 'BLURUSDT', 'BNBUSDT', 'BOMEUSDT', 'BONKUSDT', 'C98USDT', 'CAKEUSDT',
    'CYBERUSDT', 'DOGEUSDT', 'DOTUSDT', 'DYDXUSDT',
    'DYMUSDT', 'EGLDUSDT', 'ETCUSDT', 'FIDAUSDT', 'FLOKIUSDT', 'GLMRUSDT', 
    'HBARUSDT', 'HOOKUSDT', 'ICPUSDT', 'INJUSDT', 'IOUSDT',
    'JTOUSDT', 'JUPUSDT', 'KAVAUSDT', 'KSMUSDT', 'LTCUSDT', 'MANTAUSDT', 'MASKUSDT',
    'MBOXUSDT', 'MEMEUSDT', 'MINAUSDT', 'MOVRUSDT', 'NEARUSDT', 'NOTUSDT', 'OMUSDT', 'ONEUSDT',
    'OPUSDT', 'PERPUSDT', 'PORTALUSDT', 'PYTHUSDT', 'QNTUSDT', 'QTUMUSDT',
    'SEIUSDT', 'SHIBUSDT', 'TIAUSDT', 'TNSRUSDT', 'TONUSDT',
    'TWTUSDT', 'WUSDT', 'WIFUSDT', 'WLDUSDT', 'XRPUSDT', 'ZENUSDT', 'ZILUSDT'
    ]
    
    print(f"Будет отслеживаться {len(my_symbols)} токенов.")

    while True:
        ekb_tz = pytz.timezone('Asia/Yekaterinburg')
        print(f"\n--- Новая проверка. Время (ЕКБ): {datetime.now(ekb_tz).strftime('%Y-%m-%d %H:%M:%S')} ---")
        
        for symbol in my_symbols:
            df = get_historical_data(symbol)
            if df is not None and not df.empty:
                check_entry_signal(df, symbol)
            time.sleep(0.5)

        now = datetime.now()
        minutes_to_wait = 5 - (now.minute % 5)
        seconds_to_wait = minutes_to_wait * 60 - now.second
        print(f"Проверка всех токенов завершена. Жду {seconds_to_wait} секунд до следующей свечи...")
        time.sleep(5)

if __name__ == "__main__":
    main()