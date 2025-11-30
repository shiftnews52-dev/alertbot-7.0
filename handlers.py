"""
handlers.py - Обработчики команд и кнопок (полная версия)
"""
import time
import asyncio
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import RetryAfter, TelegramAPIError
from aiogram import Bot

from config import ADMIN_IDS, SUPPORT_URL, t, BOT_NAME
from config import IMG_START, IMG_ALERTS, IMG_GUIDE, IMG_PAYWALL, IMG_REF
from database import *
from indicators import fetch_price
import httpx

# Состояния пользователей для диалогов
USER_STATES = {}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def send_message_safe_local(bot, user_id: int, text: str, **kwargs):
    """Локальная версия для handlers"""
    from aiogram.utils.exceptions import RetryAfter, TelegramAPIError
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except RetryAfter as e:
        await asyncio.sleep(e.timeout)
        return await send_message_safe_local(bot, user_id, text, **kwargs)
    except TelegramAPIError:
        return False

async def send_photo_or_text(message_or_call, photo_url: str, text: str, reply_markup=None, is_callback=False):
    """Отправить фото если есть URL, иначе текст"""
    try:
        if photo_url:
            if is_callback:
                try:
                    await message_or_call.message.delete()
                except:
                    pass
                await message_or_call.message.answer_photo(
                    photo=photo_url,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                await message_or_call.answer_photo(
                    photo=photo_url,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
        else:
            if is_callback:
                try:
                    await message_or_call.message.edit_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                except:
                    await message_or_call.message.answer(
                        text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
            else:
                await message_or_call.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
    except Exception as e:
        # fallback на текст
        if is_callback:
            await message_or_call.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await message_or_call.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

# ==================== КЛАВИАТУРЫ ====================

def main_menu_kb(is_admin_user: bool, is_paid_user: bool, lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=2)
    if is_paid_user:
        kb.add(
            InlineKeyboardButton(t(lang, "btn_alerts"), callback_data="menu_alerts"),
            InlineKeyboardButton(t(lang, "btn_ref"), callback_data="menu_ref")
        )
    kb.add(
        InlineKeyboardButton(t(lang, "btn_guide"), callback_data="menu_guide"),
        InlineKeyboardButton(t(lang, "btn_support"), url=SUPPORT_URL)
    )
    if not is_paid_user:
        kb.add(InlineKeyboardButton(t(lang, "btn_unlock"), callback_data="menu_pay"))
    if is_admin_user:
        kb.add(InlineKeyboardButton(t(lang, "btn_admin"), callback_data="menu_admin"))
    return kb

def alerts_menu_kb(lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📈 BTCUSDT", callback_data="toggle_BTCUSDT"),
        InlineKeyboardButton("📈 ETHUSDT", callback_data="toggle_ETHUSDT"),
    )
    kb.add(
        InlineKeyboardButton("📈 TONUSDT", callback_data="toggle_TONUSDT"),
        InlineKeyboardButton("📈 SOLUSDT", callback_data="toggle_SOLUSDT"),
    )
    kb.add(
        InlineKeyboardButton("📈 BNBUSDT", callback_data="toggle_BNBUSDT"),
    )
    kb.add(
        InlineKeyboardButton("➕ Добавить монету", callback_data="add_custom"),
        InlineKeyboardButton("📊 Мои монеты", callback_data="my_pairs")
    )
    kb.add(InlineKeyboardButton("📖 Как это работает", callback_data="alerts_info"))
    kb.add(InlineKeyboardButton(t(lang, "btn_back"), callback_data="back_main"))
    return kb

def ref_kb(lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔗 " + ("Моя ссылка" if lang == "ru" else "My link"), callback_data="ref_link"),
        InlineKeyboardButton("💰 " + ("Баланс" if lang == "ru" else "Balance"), callback_data="ref_balance")
    )
    kb.add(
        InlineKeyboardButton("💎 " + ("Вывод (крипта)" if lang == "ru" else "Withdraw (crypto)"), callback_data="ref_withdraw"),
        InlineKeyboardButton("📜 " + ("Условия" if lang == "ru" else "Terms"), callback_data="ref_terms")
    )
    kb.add(InlineKeyboardButton(t(lang, "btn_back"), callback_data="back_main"))
    return kb

def guide_kb(lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(t(lang, "btn_back"), callback_data="back_main"))
    return kb

def pay_kb(lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("💳 Оплата (CryptoBot)", callback_data="pay_cryptobot"),
        InlineKeyboardButton("🎁 Ввести промокод", callback_data="pay_code")
    )
    kb.add(InlineKeyboardButton(t(lang, "btn_back"), callback_data="back_main"))
    return kb

def admin_kb(lang: str = "ru"):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 " + ("Статистика" if lang == "ru" else "Statistics"), callback_data="adm_stats"),
        InlineKeyboardButton("📢 " + ("Рассылка" if lang == "ru" else "Broadcast"), callback_data="adm_broadcast")
    )
    kb.add(
        InlineKeyboardButton("✅ " + ("Выдать доступ" if lang == "ru" else "Grant access"), callback_data="adm_grant"),
        InlineKeyboardButton("💰 " + ("Начислить" if lang == "ru" else "Add balance"), callback_data="adm_give")
    )
    kb.add(InlineKeyboardButton(t(lang, "btn_back"), callback_data="back_main"))
    return kb

# ==================== SETUP HANDLERS ====================

def setup_handlers(dp):
    """Регистрация всех хендлеров"""

    # ==================== MAIN COMMANDS ====================

    async def show_language_selection(message: types.Message):
        """Показать выбор языка для новых пользователей"""
        text = "👋 <b>Welcome! / Привет!</b>\n\n"
        text += "🌐 Please select your language\n"
        text += "🌐 Пожалуйста, выбери свой язык"

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🇷🇺 Русский", callback_data="first_lang_ru"),
            InlineKeyboardButton("🇬🇧 English", callback_data="first_lang_en")
        )

        await message.answer(text, reply_markup=kb)

    @dp.message_handler(commands=["start"])
    async def cmd_start(message: types.Message):
        uid = message.from_user.id
        args = message.get_args()
        invited_by = int(args) if args and args.isdigit() and int(args) != uid else None

        # Проверяем, новый ли пользователь
        conn = await db_pool.acquire()
        try:
            cursor = await conn.execute("SELECT id, language FROM users WHERE id=?", (uid,))
            existing_user = await cursor.fetchone()

            if not existing_user:
                # Новый пользователь - создаём запись
                await conn.execute(
                    "INSERT INTO users(id, invited_by, created_ts) VALUES(?,?,?)",
                    (uid, invited_by, int(time.time()))
                )
                await conn.commit()
                # Показываем выбор языка
                await show_language_selection(message)
                return
            else:
                lang = existing_user["language"] or "ru"
        finally:
            await db_pool.release(conn)

        paid = await is_paid(uid)
        text = t(lang, "start_text")
        await send_photo_or_text(message, IMG_START, text, main_menu_kb(is_admin(uid), paid, lang))

    @dp.callback_query_handler(lambda c: c.data.startswith("first_lang_"))
    async def first_lang_selected(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = call.data.split("_")[2]  # ru или en

        # Сохраняем язык
        await set_user_lang(uid, lang)

        # Показываем главное меню с выбранным языком
        text = t(lang, "start_text")
        paid = await is_paid(uid)

        try:
            await call.message.delete()
        except:
            pass

        await send_photo_or_text(call, IMG_START, text, main_menu_kb(is_admin(uid), paid, lang), is_callback=True)

    @dp.callback_query_handler(lambda c: c.data == "back_main")
    async def back_main(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        paid = await is_paid(uid)
        text = t(lang, "start_text")
        await send_photo_or_text(call, IMG_START, text, main_menu_kb(is_admin(uid), paid, lang), is_callback=True)

    # ==================== ALERTS MENU ====================
    @dp.callback_query_handler(lambda c: c.data == "menu_alerts")
    async def menu_alerts(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        paid = await is_paid(uid)
        if not paid and not is_admin(uid):
            await call.answer(t(lang, "paywall_short"), show_alert=True)
            return

        user_pairs = await get_user_pairs(uid)
        text = t(lang, "alerts_title") + "\n\n"
        if user_pairs:
            text += t(lang, "your_pairs").format(pairs=", ".join(user_pairs))
        else:
            text += t(lang, "no_pairs")

        await send_photo_or_text(call, IMG_ALERTS, text, alerts_menu_kb(lang), is_callback=True)

    @dp.callback_query_handler(lambda c: c.data.startswith("toggle_"))
    async def toggle_pair(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        pair = call.data.split("_", 1)[1]

        user_pairs = await get_user_pairs(uid)
        if pair in user_pairs:
            await remove_user_pair(uid, pair)
            text = t(lang, "coin_removed").format(pair=pair)
        else:
            if len(user_pairs) >= 10:
                await call.answer(t(lang, "max_coins"), show_alert=True)
                return
            await add_user_pair(uid, pair)
            text = t(lang, "coin_added").format(pair=pair)

        await call.answer(text, show_alert=True)

        # Обновляем меню
        user_pairs = await get_user_pairs(uid)
        text = t(lang, "alerts_title") + "\n\n"
        if user_pairs:
            text += t(lang, "your_pairs").format(pairs=", ".join(user_pairs))
        else:
            text += t(lang, "no_pairs")

        await send_photo_or_text(call, IMG_ALERTS, text, alerts_menu_kb(lang), is_callback=True)

    @dp.callback_query_handler(lambda c: c.data == "my_pairs")
    async def my_pairs(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        user_pairs = await get_user_pairs(uid)

        if not user_pairs:
            await call.answer(t(lang, "no_pairs"), show_alert=True)
            return

        text = t(lang, "your_pairs").format(pairs=", ".join(user_pairs))
        await call.answer(text, show_alert=True)

    @dp.callback_query_handler(lambda c: c.data == "add_custom")
    async def add_custom(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)

        USER_STATES[uid] = {"mode": "waiting_custom_pair"}
        await call.message.answer(t(lang, "send_coin_symbol"))

    @dp.message_handler(lambda m: USER_STATES.get(m.from_user.id, {}).get("mode") == "waiting_custom_pair")
    async def handle_custom_pair(message: types.Message):
        uid = message.from_user.id
        lang = await get_user_lang(uid)
        pair = message.text.strip().upper()

        if not pair.endswith("USDT") or len(pair) < 6:
            await message.answer(t(lang, "invalid_format"))
            return

        async with httpx.AsyncClient() as client:
            price_data = await fetch_price(client, pair)
            if not price_data:
                await message.answer(t(lang, "pair_not_found").format(pair=pair))
                return

        user_pairs = await get_user_pairs(uid)
        if pair in user_pairs:
            await message.answer(t(lang, "coin_removed").format(pair=pair))
        else:
            if len(user_pairs) >= 10:
                await message.answer(t(lang, "max_coins"))
                return
            await add_user_pair(uid, pair)
            await message.answer(t(lang, "coin_added").format(pair=pair))

        USER_STATES.pop(uid, None)

    @dp.callback_query_handler(lambda c: c.data == "alerts_info")
    async def alerts_info(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        text = t(lang, "alerts_info")
        await call.message.answer(text, parse_mode="HTML")

    # ==================== PAY / PROMO ====================

    @dp.callback_query_handler(lambda c: c.data == "menu_pay")
    async def menu_pay(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        text = t(lang, "paywall_full")
        await send_photo_or_text(call, IMG_PAYWALL, text, pay_kb(lang), is_callback=True)

    @dp.callback_query_handler(lambda c: c.data == "pay_code")
    async def pay_code(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        USER_STATES[call.from_user.id] = {"mode": "waiting_promo"}
        text = t(lang, "send_promo")

        try:
            await call.message.edit_text(text, reply_markup=pay_kb(lang))
        except:
            await call.message.answer(text, reply_markup=pay_kb(lang))

    @dp.message_handler(lambda m: USER_STATES.get(m.from_user.id, {}).get("mode") == "waiting_promo")
    async def handle_promo(message: types.Message):
        lang = await get_user_lang(message.from_user.id)
        await grant_access(message.from_user.id)
        USER_STATES.pop(message.from_user.id, None)
        await message.answer(t(lang, "access_granted"))

    # ==================== REFERRAL ====================

    @dp.callback_query_handler(lambda c: c.data == "menu_ref")
    async def menu_ref(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        text = t(lang, "ref_title")
        await send_photo_or_text(call, IMG_REF, text, ref_kb(lang), is_callback=True)

    @dp.callback_query_handler(lambda c: c.data == "ref_link")
    async def ref_link(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        bot_username = BOT_NAME
        ref_link = f"https://t.me/{bot_username}?start={uid}"
        await call.answer(ref_link, show_alert=True)

    @dp.callback_query_handler(lambda c: c.data == "ref_balance")
    async def ref_balance(call: types.CallbackQuery):
        uid = call.from_user.id
        lang = await get_user_lang(uid)
        balance = await get_user_balance(uid)
        await call.answer(t(lang, "ref_balance_text").format(balance=balance), show_alert=True)

    @dp.callback_query_handler(lambda c: c.data == "ref_terms")
    async def ref_terms(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        await call.message.answer(t(lang, "ref_terms_text"), parse_mode="HTML")

    @dp.callback_query_handler(lambda c: c.data == "ref_withdraw")
    async def ref_withdraw(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        await call.message.answer(t(lang, "ref_withdraw_text"), parse_mode="HTML")

    # ==================== GUIDE ====================

    @dp.callback_query_handler(lambda c: c.data == "menu_guide")
    async def menu_guide(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        text = t(lang, "guide_full")
        await send_photo_or_text(call, IMG_GUIDE, text, guide_kb(lang), is_callback=True)

    # ==================== SUPPORT ====================

    @dp.callback_query_handler(lambda c: c.data == "menu_support")
    async def menu_support(call: types.CallbackQuery):
        lang = await get_user_lang(call.from_user.id)
        await call.message.answer(t(lang, "support_text").format(link=SUPPORT_URL), parse_mode="HTML")

    # ==================== ADMIN ====================

    @dp.callback_query_handler(lambda c: c.data == "menu_admin")
    async def menu_admin(call: types.CallbackQuery):
        if not is_admin(call.from_user.id):
            await call.answer("Access denied", show_alert=True)
            return
        lang = await get_user_lang(call.from_user.id)
        await call.message.answer("👑 Admin panel", reply_markup=admin_kb(lang))

    @dp.callback_query_handler(lambda c: c.data == "adm_stats")
    async def adm_stats(call: types.CallbackQuery):
        if not is_admin(call.from_user.id):
            await call.answer("Access denied", show_alert=True)
            return

        total_users = await get_users_count()
        paid_users = await get_paid_users_count()
        active_users = await get_active_users_count()

        text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: <b>{total_users}</b>\n"
            f"💎 Оплатили доступ: <b>{paid_users}</b>\n"
            f"📈 Активные (с монетами): <b>{active_users}</b>\n"
        )

        await call.message.answer(text, parse_mode="HTML")

    @dp.callback_query_handler(lambda c: c.data == "adm_grant")
    async def adm_grant(call: types.CallbackQuery):
        if not is_admin(call.from_user.id):
            await call.answer("Access denied", show_alert=True)
            return
        await call.message.answer("Отправь ID пользователя, которому выдать доступ")
        USER_STATES[call.from_user.id] = {"mode": "adm_grant"}

    @dp.callback_query_handler(lambda c: c.data == "adm_give")
    async def adm_give(call: types.CallbackQuery):
        if not is_admin(call.from_user.id):
            await call.answer("Access denied", show_alert=True)
            return
        await call.message.answer("Отправь ID и сумму в формате: <code>123456789 10</code>")
        USER_STATES[call.from_user.id] = {"mode": "adm_give"}

    @dp.message_handler(lambda m: USER_STATES.get(m.from_user.id, {}).get("mode") == "adm_grant")
    async def adm_handle_grant(message: types.Message):
        try:
            uid = int(message.text.strip())
            await grant_access(uid)
            await message.answer("✅ Доступ выдан")
        except:
            await message.answer("❌ Неверный формат")
        USER_STATES.pop(message.from_user.id, None)

    @dp.message_handler(lambda m: USER_STATES.get(m.from_user.id, {}).get("mode") == "adm_give")
    async def adm_handle_give(message: types.Message):
        try:
            parts = message.text.strip().split()
            uid = int(parts[0])
            amount = float(parts[1])
            await add_balance(uid, amount)
            await message.answer("✅ Баланс начислен")
        except:
            await message.answer("❌ Неверный формат")
        USER_STATES.pop(message.from_user.id, None)
