import requests
from time import sleep
from textwrap import indent

BASE_URL = "https://api.bybit.com"
ONLY_TRADING = True         # только активные пары
QUOTE_FILTER = "USDT"       # фильтр по котировке: "USDT" или None для всех
CHUNK = 8                   # сколько символов в строке при печати

def fetch_all_spot_instruments():
    url = f"{BASE_URL}/v5/market/instruments-info"
    cursor = None
    all_items = []

    while True:
        params = {"category": "spot"}
        if cursor:
            params["cursor"] = cursor

        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error: {data}")

        result = data.get("result", {})
        items = result.get("list", []) or []
        all_items.extend(items)

        cursor = result.get("nextPageCursor")
        if not cursor:
            break

        sleep(0.1)  # легкая пауза

    return all_items

def main():
    items = fetch_all_spot_instruments()

    symbols = []
    for it in items:
        status = it.get("status")
        quote = it.get("quoteCoin")
        symbol = it.get("symbol")

        if ONLY_TRADING and status != "Trading":
            continue
        if QUOTE_FILTER and quote != QUOTE_FILTER:
            continue

        symbols.append(symbol)

    # уникализируем и сортируем
    symbols = sorted(set(symbols))

    # Печать в формате:
    # my_symbols = [
    #     'ADAUSDT', 'AEVOUSDT', ...
    # ]
    print("my_symbols = [")
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i+CHUNK]
        line = ", ".join(f"'{s}'" for s in chunk)
        print(f"    {line},")
    print("]")

if __name__ == "__main__":
    main()