# telegram_bot.py
import logging
import asyncio
import threading
import os
import pandas as pd
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import ccxt.async_support as ccxt_async
import config

# --- Глобальные переменные для связи между модулями ---
bot = None
main_loop = None
bot_state = None
t_lock = None
run_scanner_func = None
scanner_thread = None
exchange = None

router = Router()
logger = logging.getLogger("bot_logger")

def get_main_loop():
    return main_loop

def register_main_objects(state_obj, lock_obj, scanner_func, ex_obj):
    global bot_state, t_lock, run_scanner_func, exchange
    bot_state = state_obj
    t_lock = lock_obj
    run_scanner_func = scanner_func
    exchange = ex_obj

async def send_message_async(text: str):
    if not bot: return
    try:
        await bot.send_message(config.TELEGRAM_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[TG] Ошибка отправки: {e}")

def send_message(text: str):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(send_message_async(text), main_loop)

# --- Обработчики команд ---
# (Весь код обработчиков команд от @router.message(Command('help')) до ...config_handler... остается БЕЗ ИЗМЕНЕНИЙ)
# Я его опущу для краткости, просто скопируй все свои хендлеры как есть.

@router.message(Command('help'))
async def help_handler(msg: types.Message):
    help_text = (
        "🤖 *Список доступных команд:*\n\n"
        "*/start* - Запустить сканер\n"
        "*/stop* - Остановить сканер\n"
        "*/status* - Показать текущий статус\n"
        "*/profit* - Показать статистику PnL\n"
        "*/config* - Показать/изменить настройки\n"
        "*/balance* - Показать баланс USDT\n"
        "*/sell <SYMBOL>* - Продать позицию по рынку\n"
        "*/history* - Прислать `trades.csv`\n"
        "*/logs* - Прислать последние логи"
    )
    await msg.answer(help_text, parse_mode="Markdown")
    
@router.message(Command('status'))
async def status_handler(msg: types.Message):
    with t_lock:
        is_running = bot_state.get('running', False)
        active_trades = bot_state['active_trades'].copy()

    status_text = "🟢 *Работает*" if is_running else "🔴 *Остановлен*"
    msg_text = f"📊 *Статус бота:* {status_text}\n\n"
    
    if not active_trades:
        msg_text += f"Свободных слотов: *{config.MAX_CONCURRENT_TRADES}*. Нет активных сделок."
    else:
        msg_text += f"Занято слотов: *{len(active_trades)} / {config.MAX_CONCURRENT_TRADES}*\n\n"
        for symbol, data in active_trades.items():
            msg_text += f"🪙 *Токен:* `{symbol}`\n"
            msg_text += f"   *Цена входа:* `{data['entry_price']}`\n"
            msg_text += f"   *Время входа:* `{data['entry_time']}`\n\n"
            
    await msg.answer(msg_text, parse_mode="Markdown")

@router.message(Command("stop"))
async def stop_handler(msg: types.Message):
    global scanner_thread
    if not bot_state.get('running', False):
        await msg.answer("⛔️ Сканер уже был остановлен.")
        return

    logger.info("Получена команда /stop. Останавливаю сканер...")
    bot_state['running'] = False
    await msg.answer("⛔️ *Команда на остановку принята.* Ожидаю завершения текущего цикла...")

@router.message(Command("start"))
async def start_handler(msg: types.Message):
    global scanner_thread
    if bot_state.get('running', False):
        await msg.answer("✅ Сканер уже запущен.")
        return

    logger.info("Получена команда /start. Запускаю сканер...")
    bot_state['running'] = True
    scanner_thread = threading.Thread(target=run_scanner_func, daemon=True)
    scanner_thread.start()
    await msg.answer("✅ *Сканер запущен!*")

@router.message(Command('profit'))
async def profit_handler(msg: types.Message):
    file_path = 'trades.csv'
    if not os.path.exists(file_path):
        await msg.answer("📂 Файл `trades.csv` еще не создан. Нет данных для анализа.")
        return

    try:
        df = pd.read_csv(file_path)
        if df.empty:
            await msg.answer("Файл `trades.csv` пуст.")
            return
        total_trades = len(df)
        df['pnl_percent'] = ((df['sale_price'] / df['purchase_price']) - 1) * 100
        wins = df[df['pnl_percent'] > 0]
        losses = df[df['pnl_percent'] <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
        avg_win_percent = wins['pnl_percent'].mean() if win_count > 0 else 0
        avg_loss_percent = losses['pnl_percent'].mean() if loss_count > 0 else 0
        profit_text = (
            f"📊 *Статистика торговли:*\n\n"
            f"Всего сделок: *{total_trades}*\n"
            f"🟢 Выигрышных: *{win_count}*\n"
            f"🔴 Проигрышных: *{loss_count}*\n"
            f"📈 Винрейт: *{win_rate:.2f}%*\n\n"
            f"💰 Средний профит: *{avg_win_percent:+.2f}%*\n"
            f"💸 Средний убыток: *{avg_loss_percent:.2f}%*\n\n"
            f"_{'Для расчета профита в USDT необходимо добавить в логику запись объема сделки.'}_"
        )
        await msg.answer(profit_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при расчете профита: {e}")
        await msg.answer(f"🔴 Не удалось рассчитать профит. Ошибка: `{e}`")

@router.message(Command('config'))
async def config_handler(msg: types.Message):
    args = msg.text.split()
    if len(args) == 1:
        with t_lock:
            sl = bot_state['settings']['stop_loss_percent']
            tp = bot_state['settings']['take_profit_percent']
        config_text = (
            f"⚙️ *Текущие настройки (live):*\n\n"
            f"Стоп-лосс: `{sl}%`\n"
            f"Тейк-профит: `{tp}%`\n"
            f"Макс. сделок: `{config.MAX_CONCURRENT_TRADES}` (не меняется)\n\n"
            f"Для изменения используйте:\n"
            f"`/config stop_loss 1.5`\n"
            f"`/config take_profit 3.0`"
        )
        await msg.answer(config_text, parse_mode="Markdown")
        return
    if len(args) == 3:
        key_to_change = args[1].lower()
        new_value_str = args[2]
        try:
            new_value = float(new_value_str)
        except ValueError:
            await msg.answer("❗️Значение должно быть числом.")
            return
        setting_key_map = {
            "stop_loss": "stop_loss_percent",
            "take_profit": "take_profit_percent"
        }
        if key_to_change not in setting_key_map:
            await msg.answer("❗️Неверный ключ. Доступные: `stop_loss`, `take_profit`.")
            return
        internal_key = setting_key_map[key_to_change]
        with t_lock:
            old_value = bot_state['settings'][internal_key]
            bot_state['settings'][internal_key] = new_value
        logger.warning(f"Настройка '{internal_key}' изменена пользователем с {old_value} на {new_value}")
        await msg.answer(f"✅ Настройка *{key_to_change}* изменена на `{new_value}%`")
    else:
        await msg.answer("❗️Неверный формат. Используйте `/config` для просмотра или `/config <ключ> <значение>` для изменения.")

def start_tg():
    """Главная функция запуска бота"""
    global bot, main_loop
    
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Убираем всю логику прокси, подключаемся напрямую.
    logger.info("Подключаюсь к Telegram напрямую, без прокси.")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    # -----------------------

    dp = Dispatcher()
    dp.include_router(router)

    async def main_polling():
        global main_loop
        main_loop = asyncio.get_running_loop()
        await send_message_async("🤖 *Бот запущен и готов к работе.*")
        await dp.start_polling(bot)

    try:
        asyncio.run(main_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")