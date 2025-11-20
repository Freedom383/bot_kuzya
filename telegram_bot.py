# telegram_bot.py
import logging
import asyncio
import threading
import os
import pandas as pd
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
# --- ИЗМЕНЕНИЕ 1: ДОБАВЛЯЕМ ИМПОРТЫ ДЛЯ КЛАВИАТУРЫ ---
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# --------------------------------------------------
import ccxt.async_support as ccxt_async
import config

# Глобальные переменные и функции до обработчиков остаются без изменений
bot = None
main_loop = None
bot_state = None
t_lock = None
run_scanner_func = None
scanner_thread = None
exchange = None

class SettingsState(StatesGroup):
    waiting_for_max_trades = State()
    waiting_for_atr_multiplier = State()
    
router = Router()
logger = logging.getLogger("bot_logger")
def get_main_loop(): return main_loop
def register_main_objects(state_obj, lock_obj, scanner_func, ex_obj):
    global bot_state, t_lock, run_scanner_func, exchange
    bot_state, t_lock, run_scanner_func, exchange = state_obj, lock_obj, scanner_func, ex_obj
async def send_message_async(text: str):
    if not bot: return
    try: await bot.send_message(config.TELEGRAM_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e: logger.error(f"[TG] Ошибка отправки: {e}")
def send_message(text: str):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(send_message_async(text), main_loop)

# --- ИЗМЕНЕНИЕ 2: СОЗДАЕМ ФУНКЦИЮ ДЛЯ ГЕНЕРАЦИИ КЛАВИАТУРЫ ---
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создает и возвращает основную клавиатуру с командами."""
    builder = ReplyKeyboardBuilder()
    
    # Добавляем кнопки
    builder.row(KeyboardButton(text="/start"), KeyboardButton(text="/stop"))
    builder.row(KeyboardButton(text="/status"), KeyboardButton(text="/profit"))
    builder.row(KeyboardButton(text="/config"), KeyboardButton(text="/sell"))
    builder.row(KeyboardButton(text="/history"), KeyboardButton(text="/logs"))
    builder.row(KeyboardButton(text="/errorlog"))
    
    return builder.as_markup(resize_keyboard=True)
# -------------------------------------------------------------

# --- Обработчики команд ---

# --- ИЗМЕНЕНИЕ 3: ОБНОВЛЯЕМ /help и /start ---
@router.message(Command('help'))
async def help_handler(msg: types.Message):
    """Отправляет справку и показывает клавиатуру."""
    help_text = "🤖 *Главное меню бота.*\n\nИспользуйте кнопки ниже для взаимодействия."
    await msg.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.message(Command("start"))
async def start_handler(msg: types.Message):
    """Приветствует пользователя, запускает сканер (если он не запущен) и показывает клавиатуру."""
    global scanner_thread
    
    welcome_message = "Добро пожаловать! Главное меню к вашим услугам."
    
    if bot_state.get('running', False):
        await msg.answer(
            f"{welcome_message}\n\n✅ *Сканер уже запущен!*",
            reply_markup=get_main_keyboard()
        )
        return

    logger.info("Получена команда /start. Запускаю сканер...")
    bot_state['running'] = True
    scanner_thread = threading.Thread(target=run_scanner_func, daemon=True)
    scanner_thread.start()
    
    await msg.answer(
        f"{welcome_message}\n\n✅ *Сканер запущен!*",
        reply_markup=get_main_keyboard()
    )
# -------------------------------------------------------------

# Остальные обработчики команд остаются БЕЗ ИЗМЕНЕНИЙ,
# так как кнопки просто отправляют текст команды, который эти обработчики и ловят.

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
            entry_price_str = f"`{data.get('entry_price', 'N/A')}`"
            entry_time_str = f"`{data.get('entry_time', 'N/A')}`"
            msg_text += f"🪙 *Токен:* `{symbol}`\n"
            msg_text += f"   *Цена входа:* {entry_price_str}\n"
            msg_text += f"   *Время входа:* {entry_time_str}\n\n"
    await msg.answer(msg_text, parse_mode="Markdown")

@router.message(Command("stop"))
async def stop_handler(msg: types.Message):
    if not bot_state.get('running', False):
        await msg.answer("⛔️ Сканер уже был остановлен.")
        return
    logger.info("Получена команда /stop. Останавливаю сканер...")
    bot_state['running'] = False
    await msg.answer("⛔️ *Команда на остановку сканера принята.*\nОткрытые сделки продолжат отслеживаться.")

@router.message(Command('profit'))
async def profit_handler(msg: types.Message):
    file_path = 'trades.csv'
    if not os.path.exists(file_path):
        await msg.answer("📂 Файл `trades.csv` еще не создан.")
        return
    try:
        df = pd.read_csv(file_path)
        if df.empty:
            await msg.answer("Файл `trades.csv` пуст.")
            return
        total_trades = len(df)
        df['pnl_percent'] = ((df['sale_price'] / df['purchase_price']) - 1) * 100
        wins = df[df['pnl_percent'] > 0]
        win_count = len(wins)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
        profit_text = f"📊 *Статистика торговли:*\n\nВсего сделок: *{total_trades}*\n🟢 Выигрышных: *{win_count}*\n🔴 Проигрышных: *{len(df) - win_count}*\n📈 Винрейт: *{win_rate:.2f}%*"
        await msg.answer(profit_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при расчете профита: {e}")
        await msg.answer(f"🔴 Не удалось рассчитать профит. Ошибка: `{e}`")

@router.message(Command('config'))
async def config_handler(msg: Message):
    with t_lock:
        # Используем .get() для безопасного получения значений
        max_trades = bot_state['settings'].get('max_concurrent_trades', config.MAX_CONCURRENT_TRADES)
        atr_multiplier = bot_state['settings'].get('atr_multiplier', config.ATR_MULTIPLIER)
        
    config_text = (
        f"⚙️ *Текущая конфигурация:*\n\n"
        f"▪️ *Макс. сделок:* `{max_trades}`\n"
        f"▪️ *Множитель ATR:* `{atr_multiplier}` (для стоп-лосса)\n\n"
        f"Нажмите на кнопку, чтобы изменить значение:"
    )

    # Создаем инлайн-кнопки
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="⚙️ Изменить макс. сделок", 
        callback_data="change_max_trades"
    ))
    builder.row(InlineKeyboardButton(
        text="⚙️ Изменить множитель ATR", 
        callback_data="change_atr_multiplier"
    ))

    await msg.answer(config_text, reply_markup=builder.as_markup())

@router.message(Command('history'))
async def history_handler(msg: types.Message):
    file_path = 'trades.csv'
    if not os.path.exists(file_path):
        await msg.answer("📂 Файл `trades.csv` еще не создан.")
        return
    try:
        document = FSInputFile(file_path)
        await msg.answer_document(document, caption="История ваших сделок")
    except Exception as e:
        logger.error(f"Ошибка при отправке trades.csv: {e}")
        await msg.answer(f"🔴 Не удалось отправить файл. Ошибка: `{e}`")

@router.message(Command('logs'))
async def logs_handler(msg: types.Message):
    log_file = 'bot_error.log'
    if not os.path.exists(log_file):
        await msg.answer("📂 Файл `bot.log` не найден.")
        return
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        error_lines = [line.strip() for line in lines if '[ERROR]' in line or '[CRITICAL]' in line]
        last_10_errors = error_lines[-10:]
        if not last_10_errors:
            await msg.answer("🎉 В лог-файле не найдено записей об ошибках.")
            return
        response_text = "📋 *Последние 10 ошибок из лога:*\n\n```\n" + "\n".join(last_10_errors) + "\n```"
        await msg.answer(response_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при чтении bot.log: {e}")
        await msg.answer(f"🔴 Не удалось прочитать лог-файл. Ошибка: `{e}`")

@router.message(Command('errorlog'))
async def errorlog_handler(msg: types.Message):
    log_file = 'bot_error.log'
    if not os.path.exists(log_file):
        await msg.answer("📂 Файл `bot.log` не найден.")
        return
    try:
        document = FSInputFile(log_file, filename="bot_error.log")
        await msg.answer_document(document, caption="Полный файл с ошибками")
    except Exception as e:
        logger.error(f"Ошибка при отправке bot_error.log: {e}")
        await msg.answer(f"🔴 Не удалось отправить файл с логами. Ошибка: `{e}`")

@router.callback_query(F.data == "change_max_trades")
async def change_max_trades_callback(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer("Введите новое значение для *максимального количества сделок* (например, `1`):")
    # Устанавливаем состояние ожидания
    await state.set_state(SettingsState.waiting_for_max_trades)
    await query.answer() # Убираем "часики" с кнопки

@router.callback_query(F.data == "change_atr_multiplier")
async def change_atr_multiplier_callback(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer("Введите новый *множитель для ATR* (например, `2.5`):")
    # Устанавливаем состояние ожидания
    await state.set_state(SettingsState.waiting_for_atr_multiplier)
    await query.answer()


# --- Обработчики состояний (когда бот ждет ввода от пользователя) ---

@router.message(SettingsState.waiting_for_max_trades)
async def process_max_trades(msg: Message, state: FSMContext):
    try:
        new_max_trades = int(msg.text)
        if not (1 <= new_max_trades <= 10):
            await msg.answer("❌ *Ошибка:* Значение должно быть целым числом от 1 до 10. Попробуйте снова.")
            return
        
        with t_lock:
            # Обновляем значение и в config, и в bot_state для надежности
            config.MAX_CONCURRENT_TRADES = new_max_trades
            bot_state['settings']['max_concurrent_trades'] = new_max_trades
        
        logger.info(f"Максимальное количество сделок изменено на {new_max_trades} пользователем.")
        await msg.answer(f"✅ *Успешно!* Максимальное количество сделок установлено: `{new_max_trades}`.")
        await state.clear() # Выходим из состояния ожидания

    except (ValueError, TypeError):
        await msg.answer("❌ *Ошибка:* Пожалуйста, введите целое число (например, `1`).")

@router.message(SettingsState.waiting_for_atr_multiplier)
async def process_atr_multiplier(msg: Message, state: FSMContext):
    try:
        new_atr = float(msg.text.replace(',', '.')) # Заменяем запятую на точку для удобства
        if not (0.1 <= new_atr <= 10):
            await msg.answer("❌ *Ошибка:* Множитель должен быть числом от 0.1 до 10. Попробуйте снова.")
            return

        with t_lock:
            config.ATR_MULTIPLIER = new_atr
            bot_state['settings']['atr_multiplier'] = new_atr
            # При смене ATR, автоматически ставим этот режим как основной
            config.STOP_LOSS_MODE = 'ATR'
            bot_state['settings']['stop_loss_mode'] = 'ATR'
        
        logger.info(f"Множитель ATR изменен на {new_atr} пользователем.")
        await msg.answer(
            f"✅ *Успешно!* Множитель ATR установлен: `{new_atr}`.\n"
            f"Режим стоп-лосса автоматически переключен на *ATR*."
        )
        await state.clear() # Выходим из состояния ожидания

    except (ValueError, TypeError):
        await msg.answer("❌ *Ошибка:* Пожалуйста, введите число (например, `2.5`).")
        
# --- Функция запуска (без изменений) ---
def start_tg():
    global bot, main_loop
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    async def main_polling():
        global main_loop
        main_loop = asyncio.get_running_loop()
        await send_message_async("🤖 *Бот запущен и готов к работе.*")
        await dp.start_polling(bot)
    try: asyncio.run(main_polling())
    except (KeyboardInterrupt, SystemExit): logger.info("Бот остановлен вручную.")
