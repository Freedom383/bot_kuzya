# main.py
import threading
import time
import logging
from datetime import datetime
import ccxt

import config
from logger_setup import setup_logger
from scanner import get_historical_data, check_divergence_signal
from trade_manager import manage_trade
from telegram_bot import start_tg, register_main_objects, send_message

logger = setup_logger()

bot_state = {
    "active_trades": {},
    "running": False,
    "balance_usdt": config.SIMULATION_INITIAL_BALANCE,
    "settings": {
        "stop_loss_percent": config.DEFAULT_STOP_LOSS_PERCENT,
        "take_profit_percent": config.DEFAULT_TAKE_PROFIT_PERCENT,
        "max_concurrent_trades": config.DEFAULT_MAX_CONCURRENT_TRADES,
        "atr_multiplier": config.DEFAULT_ATR_MULTIPLIER,
        "use_trailing_stop": config.USE_TRAILING_STOP,
        "trailing_stop_activation_percent": config.TRAILING_STOP_ACTIVATION_PERCENT,
    }
}
t_lock = threading.Lock()

exchange = ccxt.bybit({
    'apiKey': config.BYBIT_API_KEY,
    'secret': config.BYBIT_API_SECRET,
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True,
    'timeout': 30000,
})

def run_scanner():
    """
    Основной цикл сканера. Сканирует все монеты, а затем ждет начала
    следующего 5-минутного интервала для синхронизации с закрытием свечей.
    """
    while bot_state.get('running', False):
        try:
            with t_lock:
                max_trades = bot_state['settings']['max_concurrent_trades']
                active_trades_count = len(bot_state['active_trades'])

            # 1. Проверяем, есть ли свободные слоты для торговли
            if active_trades_count >= max_trades:
                logger.info(
                    f"Все {max_trades} торговых слота заняты. "
                    f"Пропускаю сканирование и жду следующей 5-минутной свечи."
                )
            else:
                # 2. Если слоты есть, начинаем сканирование
                logger.info(
                    f"Свободных слотов: {max_trades - active_trades_count}. "
                    f"Начинаю сканирование {len(config.my_symbols)} монет..."
                )

                for symbol in config.my_symbols:
                    #print(symbol)
                    if not bot_state.get('running', False):
                        break  # Выходим из цикла, если бот был остановлен

                    with t_lock:
                        # Пропускаем монету, если по ней уже есть активная сделка
                        if symbol in bot_state['active_trades']:
                            continue

                    df = get_historical_data(exchange, symbol)
                    if df is not None and not df.empty:
                        signal_found, entry_price, analysis_data = check_divergence_signal(df, symbol)

                        if signal_found:
                            with t_lock:
                                # Еще раз проверяем количество слотов перед открытием сделки
                                if len(bot_state['active_trades']) >= bot_state['settings']['max_concurrent_trades']:
                                    logger.warning(f"[{symbol}] Найден сигнал, но все слоты уже заняты. Пропускаю.")
                                    break  # Прерываем сканирование, так как слотов больше нет

                                logger.info(f"!!! [{symbol}] НАЙДЕН СИГНАЛ: {entry_price} !!!")
                                bot_state['active_trades'][symbol] = {"status": "pending"}

                            # Запускаем управление сделкой в отдельном потоке
                            trade_thread = threading.Thread(
                                target=manage_trade,
                                args=(symbol, entry_price, analysis_data, bot_state, t_lock)
                            )
                            trade_thread.start()
                            break
                if not bot_state.get('running', False):
                    break # Выходим из основного цикла while, если бот был остановлен во время сканирования

                logger.info("Сканирование всех монет завершено.")

            # 3. Ожидание до начала следующей 5-минутной свечи
            # Этот блок выполняется всегда: и после сканирования, и когда все слоты заняты
            if not bot_state.get('running', False):
                break

            current_time = time.time()
            # Ждем до 2 секунд после начала нового 5-минутного интервала, чтобы свеча точно закрылась
            seconds_to_wait = 300 - (current_time % 300) + 2
            
            logger.info(f"Следующая проверка через ~{int(seconds_to_wait / 60)} мин ({int(seconds_to_wait)} сек).")
            
            # Ждем рассчитанное время, но с проверкой каждую секунду,
            # чтобы можно было быстро остановить бота
            for _ in range(int(seconds_to_wait)):
                if not bot_state.get('running', False):
                    break
                time.sleep(1)

        except Exception as e:
            error_message = f"КРИТИЧЕСКАЯ ОШИБКА в сканере: {e}"
            logger.critical(error_message, exc_info=True)
            send_message(f"🔴 {error_message}")
            time.sleep(60)  # Пауза в случае критической ошибки

    logger.info("Поток сканера остановлен.")
    send_message("⏹️ Поток сканера завершил свою работу.")


if __name__ == "__main__":
    register_main_objects(bot_state, t_lock, run_scanner, exchange)
    logger.info("Запуск Telegram бота...")
    start_tg()
    logger.info("Бот запущен.")