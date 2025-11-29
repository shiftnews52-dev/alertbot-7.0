"""
handlers.py - Обработчики команд с оплатой через CryptoBot
"""
import logging
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, DEFAULT_PAIRS
from database import (
    get_user_subscription, update_subscription,
    add_tracked_pair, remove_tracked_pair, get_user_pairs,
    is_user_subscribed
)

logger = logging.getLogger(__name__)

# FSM States
class PromoState(StatesGroup):
    waiting_for_promo = State()

class SupportState(StatesGroup):
    waiting_for_message = State()

# ============================================================
# КОМАНДА /start
# ============================================================

async def cmd_start(message: types.Message):
    """Команда /start - приветствие и главное меню"""
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    logger.info(f"👤 User {user_id} ({username}) started bot")
    
    # Проверяем подписку
    is_subscribed = await is_user_subscribed(user_id)
    
    if is_subscribed:
        text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            f"✅ У вас активная подписка\n\n"
            f"🎯 Используйте команды:\n"
            f"/add — добавить монету для отслеживания\n"
            f"/remove — удалить монету\n"
            f"/list — список ваших монет\n"
            f"/help — справка"
        )
    else:
        text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            f"🤖 Я бот для крипто-сигналов\n\n"
            f"⚠️ У вас нет активной подписки\n"
            f"Используйте кнопки ниже:"
        )
    
    keyboard = get_main_menu(is_subscribed)
    await message.answer(text, reply_markup=keyboard)

def get_main_menu(is_subscribed: bool) -> InlineKeyboardMarkup:
    """Главное меню"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    if not is_subscribed:
        keyboard.add(
            InlineKeyboardButton("💎 Оплатить подписку", callback_data="subscribe")
        )
    
    keyboard.add(
        InlineKeyboardButton("💬 Связь с нами", callback_data="support"),
        InlineKeyboardButton("🎁 Ввести промокод", callback_data="promo")
    )
    
    if is_subscribed:
        keyboard.add(
            InlineKeyboardButton("📊 Мои монеты", callback_data="my_coins")
        )
    
    return keyboard

# ============================================================
# ОПЛАТА ЧЕРЕЗ CRYPTOBOT
# ============================================================

async def callback_subscribe(callback: types.CallbackQuery):
    """Обработчик кнопки оплаты"""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("💳 1 месяц - 20 USDT", callback_data="pay_1month"),
        InlineKeyboardButton("💳 3 месяца - 50 USDT", callback_data="pay_3months"),
        InlineKeyboardButton("💳 6 месяцев - 90 USDT", callback_data="pay_6months"),
        InlineKeyboardButton("💳 1 год - 149 USDT", callback_data="pay_1year"),
        InlineKeyboardButton("« Назад", callback_data="back_to_menu")
    )
    
    text = (
        "💎 <b>Выберите тариф:</b>\n\n"
        "1️⃣ 1 месяц — 20 USDT\n"
        "2️⃣ 3 месяца — 50 USDT (скидка 17%)\n"
        "3️⃣ 6 месяцев — 90 USDT (скидка 25%)\n"
        "4️⃣ 1 год — 149 USDT (скидка 38%)\n\n"
        "💰 Оплата через @CryptoBot\n"
        "✅ Моментальная активация"
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)

async def callback_payment(callback: types.CallbackQuery):
    """Обработчик выбора тарифа"""
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Определяем тариф
    tariff_map = {
        "pay_1month": ("1 месяц", 20, 30),
        "pay_3months": ("3 месяца", 50, 90),
        "pay_6months": ("6 месяцев", 90, 180),
        "pay_1year": ("1 год", 149, 365)
    }
    
    if callback.data not in tariff_map:
        return
    
    tariff_name, amount, days = tariff_map[callback.data]
    
    # Создаём инвойс для CryptoBot
    text = (
        f"💳 <b>Оплата: {tariff_name}</b>\n\n"
        f"💰 Сумма: {amount} USDT\n\n"
        f"📝 <b>Инструкция:</b>\n"
        f"1. Нажмите кнопку ниже\n"
        f"2. Откроется @CryptoBot\n"
        f"3. Выберите способ оплаты\n"
        f"4. После оплаты подписка активируется автоматически\n\n"
        f"⚡️ Активация моментальная!"
    )
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    # Ссылка на CryptoBot с инвойсом
    cryptobot_link = f"https://t.me/CryptoBot?start=pay_{user_id}_{callback.data}"
    
    keyboard.add(
        InlineKeyboardButton("💳 Оплатить через CryptoBot", url=cryptobot_link),
        InlineKeyboardButton("« Назад", callback_data="subscribe")
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    
    logger.info(f"💳 User {user_id} initiated payment: {tariff_name} - {amount} USDT")

# ============================================================
# ПРОМОКОД
# ============================================================

async def callback_promo(callback: types.CallbackQuery):
    """Обработчик кнопки промокода"""
    await callback.answer()
    
    text = (
        "🎁 <b>Ввод промокода</b>\n\n"
        "Отправьте промокод в следующем сообщении\n\n"
        "Для отмены напишите /cancel"
    )
    
    await callback.message.edit_text(text)
    await PromoState.waiting_for_promo.set()

async def process_promo(message: types.Message, state: FSMContext):
    """Обработка промокода"""
    promo_code = message.text.strip().upper()
    user_id = message.from_user.id
    
    # Проверка промокода
    valid_promos = {
        "START2024": 30,
        "CRYPTO50": 7,
        "WELCOME": 14
    }
    
    if promo_code in valid_promos:
        days = valid_promos[promo_code]
        
        # Активируем подписку
        await update_subscription(user_id, days)
        
        text = (
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"🎁 Код: {promo_code}\n"
            f"⏰ Добавлено: {days} дней\n\n"
            f"Используйте /add чтобы добавить монеты"
        )
        
        logger.info(f"🎁 User {user_id} activated promo: {promo_code} ({days} days)")
    else:
        text = (
            f"❌ <b>Промокод недействителен</b>\n\n"
            f"Код: {promo_code}\n\n"
            f"Попробуйте другой промокод или купите подписку"
        )
        
        logger.warning(f"❌ User {user_id} tried invalid promo: {promo_code}")
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("« Главное меню", callback_data="back_to_menu")
    )
    
    await message.answer(text, reply_markup=keyboard)
    await state.finish()

# ============================================================
# ПОДДЕРЖКА
# ============================================================

async def callback_support(callback: types.CallbackQuery):
    """Обработчик кнопки поддержки"""
    await callback.answer()
    
    text = (
        "💬 <b>Связь с поддержкой</b>\n\n"
        "Напишите ваше сообщение, и мы ответим в ближайшее время\n\n"
        "Для отмены напишите /cancel"
    )
    
    await callback.message.edit_text(text)
    await SupportState.waiting_for_message.set()

async def process_support(message: types.Message, state: FSMContext):
    """Обработка сообщения в поддержку"""
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    support_msg = message.text
    
    # Отправляем админу
    admin_text = (
        f"💬 <b>Новое сообщение в поддержку</b>\n\n"
        f"👤 User: {user_id} (@{username})\n"
        f"📝 Сообщение:\n{support_msg}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.error(f"Failed to send support message to admin {admin_id}: {e}")
    
    text = (
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы ответим вам в ближайшее время"
    )
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("« Главное меню", callback_data="back_to_menu")
    )
    
    await message.answer(text, reply_markup=keyboard)
    await state.finish()
    
    logger.info(f"💬 Support message from {user_id}: {support_msg[:50]}...")

# ============================================================
# НАВИГАЦИЯ
# ============================================================

async def callback_back_to_menu(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback.answer()
    
    user_id = callback.from_user.id
    is_subscribed = await is_user_subscribed(user_id)
    
    if is_subscribed:
        text = (
            f"👋 <b>Главное меню</b>\n\n"
            f"✅ У вас активная подписка\n\n"
            f"🎯 Используйте команды:\n"
            f"/add — добавить монету\n"
            f"/remove — удалить монету\n"
            f"/list — список монет"
        )
    else:
        text = (
            f"👋 <b>Главное меню</b>\n\n"
            f"⚠️ У вас нет активной подписки\n"
            f"Используйте кнопки ниже:"
        )
    
    keyboard = get_main_menu(is_subscribed)
    await callback.message.edit_text(text, reply_markup=keyboard)

async def callback_my_coins(callback: types.CallbackQuery):
    """Показать список монет пользователя"""
    await callback.answer()
    
    user_id = callback.from_user.id
    pairs = await get_user_pairs(user_id)
    
    if pairs:
        text = "📊 <b>Ваши отслеживаемые монеты:</b>\n\n"
        for pair in pairs:
            text += f"• {pair}\n"
        text += f"\n📍 Всего: {len(pairs)} монет"
    else:
        text = (
            "📊 <b>У вас нет отслеживаемых монет</b>\n\n"
            "Используйте /add чтобы добавить"
        )
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("« Назад", callback_data="back_to_menu")
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)

# ============================================================
# ОТМЕНА
# ============================================================

async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer("Нечего отменять")
        return
    
    await state.finish()
    await message.answer(
        "✅ Действие отменено\n\nИспользуйте /start для главного меню"
    )

# ============================================================
# КОМАНДЫ УПРАВЛЕНИЯ МОНЕТАМИ
# ============================================================

async def cmd_add(message: types.Message):
    """Добавить монету"""
    user_id = message.from_user.id
    
    if not await is_user_subscribed(user_id):
        await message.answer(
            "⚠️ У вас нет активной подписки\n\n"
            "Используйте /start для оплаты"
        )
        return
    
    args = message.get_args()
    if not args:
        pairs_list = ", ".join(DEFAULT_PAIRS[:10])
        await message.answer(
            f"Используйте: /add СИМВОЛ\n\n"
            f"Примеры:\n"
            f"/add BTCUSDT\n"
            f"/add ETHUSDT\n\n"
            f"Доступные пары:\n{pairs_list}..."
        )
        return
    
    pair = args.upper()
    if not pair.endswith("USDT"):
        pair = f"{pair}USDT"
    
    success = await add_tracked_pair(user_id, pair)
    if success:
        await message.answer(f"✅ Добавлено: {pair}")
        logger.info(f"➕ User {user_id} added pair: {pair}")
    else:
        await message.answer(f"⚠️ {pair} уже в вашем списке")

async def cmd_remove(message: types.Message):
    """Удалить монету"""
    user_id = message.from_user.id
    
    args = message.get_args()
    if not args:
        await message.answer("Используйте: /remove СИМВОЛ\n\nПример: /remove BTCUSDT")
        return
    
    pair = args.upper()
    if not pair.endswith("USDT"):
        pair = f"{pair}USDT"
    
    success = await remove_tracked_pair(user_id, pair)
    if success:
        await message.answer(f"✅ Удалено: {pair}")
        logger.info(f"➖ User {user_id} removed pair: {pair}")
    else:
        await message.answer(f"⚠️ {pair} не найдено в вашем списке")

async def cmd_list(message: types.Message):
    """Список монет"""
    user_id = message.from_user.id
    pairs = await get_user_pairs(user_id)
    
    if pairs:
        text = "📊 <b>Ваши монеты:</b>\n\n"
        for pair in pairs:
            text += f"• {pair}\n"
        text += f"\n📍 Всего: {len(pairs)}"
    else:
        text = "📊 У вас нет отслеживаемых монет\n\nИспользуйте /add"
    
    await message.answer(text)

async def cmd_help(message: types.Message):
    """Справка"""
    text = (
        "📚 <b>Справка</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start — главное меню\n"
        "/add СИМВОЛ — добавить монету\n"
        "/remove СИМВОЛ — удалить монету\n"
        "/list — список ваших монет\n"
        "/cancel — отменить действие\n\n"
        "<b>Оплата:</b>\n"
        "💳 Через @CryptoBot (USDT)\n"
        "🎁 Промокоды для бесплатного доступа\n\n"
        "<b>Поддержка:</b>\n"
        "💬 Кнопка \"Связь с нами\" в меню"
    )
    await message.answer(text)

# ============================================================
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# ============================================================

def setup_handlers(dp):
    """Регистрация всех обработчиков"""
    # Команды
    dp.register_message_handler(cmd_start, commands=['start'])
    dp.register_message_handler(cmd_cancel, commands=['cancel'], state='*')
    dp.register_message_handler(cmd_add, commands=['add'])
    dp.register_message_handler(cmd_remove, commands=['remove'])
    dp.register_message_handler(cmd_list, commands=['list'])
    dp.register_message_handler(cmd_help, commands=['help'])
    
    # Коллбэки
    dp.register_callback_query_handler(callback_subscribe, lambda c: c.data == "subscribe")
    dp.register_callback_query_handler(callback_payment, lambda c: c.data.startswith("pay_"))
    dp.register_callback_query_handler(callback_promo, lambda c: c.data == "promo")
    dp.register_callback_query_handler(callback_support, lambda c: c.data == "support")
    dp.register_callback_query_handler(callback_back_to_menu, lambda c: c.data == "back_to_menu")
    dp.register_callback_query_handler(callback_my_coins, lambda c: c.data == "my_coins")
    
    # FSM обработчики
    dp.register_message_handler(process_promo, state=PromoState.waiting_for_promo)
    dp.register_message_handler(process_support, state=SupportState.waiting_for_message)
