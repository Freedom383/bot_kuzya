# telegram_bot.py
import logging
import asyncio
import threading
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
import config # Импортируем весь модуль config

# --- Глобальные переменные для связи между модулями ---
bot = None
main_loop = None # Будем хранить здесь главный event loop
bot_state = None
t_lock = None
run_scanner_func = None
scanner_thread = None

router = Router()
logger = logging.getLogger("bot_logger")

def get_main_loop():
    """Возвращает текущий event loop."""
    return main_loop

def register_main_objects(state_obj, lock_obj, scanner_func):
    """Получает общие объекты из main.py"""
    global bot_state, t_lock, run_scanner_func
    bot_state = state_obj
    t_lock = lock_obj
    run_scanner_func = scanner_func

async def send_message_async(text: str):
    """Асинхронная отправка сообщений"""
    if not bot: return
    try:
        # Используем parse_mode Markdown для красивого форматирования
        await bot.send_message(config.TELEGRAM_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[TG] Ошибка отправки: {e}")

def send_message(text: str):
    """Безопасная отправка сообщений из любого потока"""
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(send_message_async(text), main_loop)

# --- Обработчики команд ---

@router.message(Command('status'))
async def status_handler(msg: types.Message):
    with t_lock:
        is_running = bot_state.get('running', False)
        active_trades = bot_state['active_trades'].copy()

    status_text = "🟢 *Работает*" if is_running else "🔴 *Остановлен*"
    msg_text = f"📊 *Статус бота:* {status_text}\n\n"
    
    if not active_trades:
        # Теперь config.MAX_CONCURRENT_TRADES будет найден
        msg_text += f"Свободных слотов: *{config.MAX_CONCURRENT_TRADES}*. Нет активных сделок."
    else:
        # И здесь тоже
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
    # Создаем и запускаем поток сканера
    scanner_thread = threading.Thread(target=run_scanner_func, daemon=True)
    scanner_thread.start()
    await msg.answer("✅ *Сканер запущен!*")


def start_tg():
    """Главная функция запуска бота"""
    global bot, main_loop
    
    # Теперь обращаемся к переменным через config.
    if config.USE_PROXY:
        logger.info(f"Использую прокси: {config.HTTP_PROXY}")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN, proxy=config.HTTP_PROXY)
    else:
        logger.info("Работаю без прокси.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    dp = Dispatcher()
    dp.include_router(router)

    async def main_polling():
        global main_loop
        main_loop = asyncio.get_running_loop() # Сохраняем главный цикл
        await send_message_async("🤖 *Бот запущен и готов к работе.*")
        await dp.start_polling(bot)

    try:
        asyncio.run(main_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
