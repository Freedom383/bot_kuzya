# telegram_handlers.py
import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from trading_bot import TradingBot # Импортируем наш главный класс
import config

logger = logging.getLogger("bot_logger")
router = Router()

# Мидлварь для проверки, что пишет только админ
@router.message.middleware()
async def admin_check_middleware(handler, event, data):
    if event.from_user.id != int(config.TELEGRAM_CHAT_ID):
        logger.warning(f"Попытка доступа от неизвестного пользователя: {event.from_user.id}")
        return
    return await handler(event, data)


@router.message(CommandStart())
async def cmd_start(message: Message, trading_bot: TradingBot):
    """Обработчик команды /start"""
    success = trading_bot.start()
    if success:
        await message.answer("✅ *Сканер запущен!* Начинаю поиск сигналов.", parse_mode="Markdown")
    else:
        await message.answer("✅ Бот уже был запущен.")

@router.message(Command("stop"))
async def cmd_stop(message: Message, trading_bot: TradingBot):
    """Обработчик команды /stop"""
    success = trading_bot.stop()
    if success:
        await message.answer("⛔️ *Сканер остановлен.*", parse_mode="Markdown")
    else:
        await message.answer("⛔️ Бот уже был остановлен.")

@router.message(Command("status"))
async def cmd_status(message: Message, trading_bot: TradingBot):
    """Обработчик команды /status"""
    async with trading_bot.lock:
        active_trades = trading_bot.active_trades
        is_running = trading_bot.is_running
        status_text = "🟢 *Работает*" if is_running else "🔴 *Остановлен*"
        
        msg = f"📊 *Статус бота:* {status_text}\n\n"
        if not active_trades:
            msg += f"Свободных слотов: *{config.MAX_CONCURRENT_TRADES}*. Нет активных сделок."
        else:
            msg += f"Занято слотов: *{len(active_trades)} / {config.MAX_CONCURRENT_TRADES}*\n\n"
            for symbol, data in active_trades.items():
                msg += f"🪙 *Токен:* `{symbol}`\n"
                msg += f"   *Цена входа:* `{data['entry_price']}`\n"
                msg += f"   *Время входа:* `{data['entry_time']}`\n\n"
    
    await message.answer(msg, parse_mode="Markdown")