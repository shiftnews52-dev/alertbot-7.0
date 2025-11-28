"""
tasks_v3.py - Фоновые задачи с антиспамом и правильным форматом
"""
import time
import asyncio
import logging
from collections import defaultdict
import httpx
from aiogram import Bot
from aiogram.utils.exceptions import RetryAfter, TelegramAPIError

from config import (
    CHECK_INTERVAL, DEFAULT_PAIRS, TIMEFRAME,
    MAX_SIGNALS_PER_DAY, BATCH_SEND_SIZE, BATCH_SEND_DELAY,
    SIGNAL_COOLDOWN
)
from database import (
    get_all_tracked_pairs, get_pairs_with_users,
    count_signals_today, log_signal, get_all_user_ids
)
from indicators import CANDLES, fetch_price, fetch_candles_binance
from professional_analyzer_v2 import crypto_micky_analyzer

logger = logging.getLogger(__name__)

# 🔥 АНТИСПАМ: Храним время последнего сигнала для каждой пары
LAST_SIGNALS = {}

async def send_message_safe(bot: Bot, user_id: int, text: str, **kwargs):
    """Безопасная отправка с обработкой rate limit"""
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except RetryAfter as e:
        await asyncio.sleep(e.timeout)
        return await send_message_safe(bot, user_id, text, **kwargs)
    except TelegramAPIError:
        return False

async def price_collector(bot: Bot):
    """Сбор рыночных данных для всех ТФ"""
    logger.info("🔄 CryptoMicky Price Collector started (1H, 4H, 1D)")
    
    # Сначала загружаем исторические данные для всех ТФ
    logger.info("📥 Loading historical data for all timeframes...")
    for pair in DEFAULT_PAIRS:
        for tf in ["1h", "4h", "1d"]:
            try:
                candles = await fetch_candles_binance(pair, tf, 100)
                if candles:
                    for candle in candles:
                        CANDLES.add_candle(pair, tf, candle)
                    logger.info(f"✅ Loaded {len(candles)} candles for {pair} {tf}")
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Error loading {pair} {tf}: {e}")
    
    # Загружаем BTC для всех ТФ
    logger.info("📥 Loading BTC data...")
    for tf in ["1h", "4h", "1d"]:
        try:
            candles = await fetch_candles_binance("BTCUSDT", tf, 100)
            if candles:
                for candle in candles:
                    CANDLES.add_candle("BTCUSDT", tf, candle)
                logger.info(f"✅ Loaded {len(candles)} BTC candles {tf}")
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error loading BTCUSDT {tf}: {e}")
    
    logger.info("✅ Historical data loaded for all timeframes!")
    
    # Затем регулярный сбор
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Собираем текущие цены
                pairs = await get_all_tracked_pairs()
                pairs = list(set(pairs + DEFAULT_PAIRS + ["BTCUSDT"]))
                
                ts = time.time()
                for pair in pairs:
                    price_data = await fetch_price(client, pair)
                    if price_data:
                        price, volume = price_data
                        # Добавляем в свечи для 1H (основной ТФ)
                        CANDLES.add_candle(pair, "1h", {
                            't': ts, 'o': price, 'h': price, 
                            'l': price, 'c': price, 'v': volume
                        })
                
                logger.info(f"📊 Prices updated for {len(pairs)} pairs")
                await asyncio.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Price collector error: {e}")
                await asyncio.sleep(60)

async def signal_analyzer(bot: Bot):
    """Анализ и отправка сигналов по ТЗ CryptoMicky"""
    logger.info("🎯 CryptoMicky Signal Analyzer started (60%+ Confidence)")
    
    # Ждём загрузки данных
    await asyncio.sleep(20)
    
    # 🔥 ДИАГНОСТИКА: проверяем загрузку данных
    logger.info("🔍 Checking data availability...")
    for pair in DEFAULT_PAIRS:
        candles_1h = CANDLES.get_candles(pair, "1h")
        candles_4h = CANDLES.get_candles(pair, "4h")
        candles_1d = CANDLES.get_candles(pair, "1d")
        logger.info(f"📊 {pair} - 1H: {len(candles_1h)}, 4H: {len(candles_4h)}, 1D: {len(candles_1d)}")
    
    # Проверяем BTC
    btc_1h = CANDLES.get_candles("BTCUSDT", "1h")
    logger.info(f"📊 BTCUSDT - 1H: {len(btc_1h)}")
    
    while True:
        try:
            rows = await get_pairs_with_users()
            active_pairs = list(set([row["pair"] for row in rows]))
            
            logger.info(f"🔍 Analyzing {len(active_pairs)} user pairs: {active_pairs}")
            
            if not active_pairs:
                logger.warning("⚠️ No users with active pairs. Users need to add coins via /start")
                await asyncio.sleep(60)
                continue
            
            # Анализируем каждую пару
            analyzed = 0
            signals_found = 0
            current_time = time.time()
            
            for pair in active_pairs:
                analyzed += 1
                
                # 🔥 АНТИСПАМ: Проверяем cooldown (по умолчанию 6 часов)
                if pair in LAST_SIGNALS:
                    time_since_last = current_time - LAST_SIGNALS[pair]
                    if time_since_last < SIGNAL_COOLDOWN:
                        cooldown_left = int((SIGNAL_COOLDOWN - time_since_last) / 60)
                        logger.debug(f"⏳ {pair}: Cooldown active ({cooldown_left}m left)")
                        continue
                
                # Получаем свечи
                candles_1h = CANDLES.get_candles(pair, "1h")
                candles_4h = CANDLES.get_candles(pair, "4h") 
                candles_1d = CANDLES.get_candles(pair, "1d")
                btc_candles_1h = CANDLES.get_candles("BTCUSDT", "1h")
                
                if len(candles_1h) < 100 or len(candles_4h) < 50 or len(candles_1d) < 30:
                    logger.debug(f"⚠️ {pair}: Not enough candles for analysis")
                    continue
                
                # 🔥 CryptoMicky анализ
                signal = crypto_micky_analyzer.analyze_pair(
                    pair, candles_1h, candles_4h, candles_1d, btc_candles_1h
                )
                
                if signal:
                    signals_found += 1
                    logger.info(f"🎯 FOUND SIGNAL: {pair} {signal['side']} ({signal['confidence']}%)")
                    
                    # Отправка пользователям
                    users = [row["user_id"] for row in rows if row["pair"] == pair]
                    text = _format_micky_alert_signal(signal)
                    
                    sent_count = 0
                    for user_id in users:
                        if await send_message_safe(bot, user_id, text):
                            await log_signal(
                                user_id, pair, signal['side'], 
                                signal['current_price'], signal['confidence']
                            )
                            sent_count += 1
                        await asyncio.sleep(0.05)
                    
                    logger.info(f"📤 Sent to {sent_count}/{len(users)} users")
                    
                    # 🔥 АНТИСПАМ: Обновляем время последнего сигнала
                    LAST_SIGNALS[pair] = current_time
            
            # Статистика цикла
            logger.info(f"📊 Cycle: {analyzed} pairs analyzed, {signals_found} signals found")
            
            if signals_found == 0:
                logger.info("💤 No high-confidence signals this cycle (60%+ required)")
                
        except Exception as e:
            logger.error(f"Signal analyzer error: {e}")
        
        await asyncio.sleep(60)

def _format_micky_alert_signal(signal: dict) -> str:
    """
    Форматирование сообщения КАК НА СКРИНШОТЕ
    
    Пример из скриншота:
    
    Переслано от 🔥 Micky_Alert
    🟢 DOTUSDT — LONG
    
    Логика:
    • ✅ Уровень поддержки
    • 📈 Бычий тренд
    • 📊 MACD положительный
    • 💰 Объёмы подтверждают
    
    🎯 Вход: 2.74 - 2.79
    🎯 Цели:
    TP1: 2.89 (+2.00%)
    TP2: 2.95 (+4.00%)
    TP3: 3.00 (+6.00%)
    🛡 Стоп: 2.73 (-3.80%)
    
    💰 Объём позиции: 5-8% депо
    📊 Confidence Score: 70%
    
    ⏰ 09:26:46
    ⚠️ Не финансовый совет
    """
    
    # Эмодзи для направления
    side_emoji = "🟢" if signal['side'] == 'LONG' else "🔴"
    
    # Заголовок
    text = f"Переслано от 🔥 Micky_Alert\n"
    text += f"{side_emoji} <b>{signal['pair']} — {signal['side']}</b>\n\n"
    
    # Логика с эмодзи (из conditions_desc)
    text += f"<b>Логика:</b>\n"
    
    # Преобразуем описания условий в красивый формат с эмодзи
    conditions = signal.get('conditions_desc', [])
    if conditions:
        # Добавляем эмодзи к каждому условию
        for condition in conditions[:4]:  # Берём первые 4
            if 'поддержки' in condition.lower() or 'support' in condition.lower():
                text += f"• ✅ Уровень поддержки\n"
            elif 'сопротивления' in condition.lower() or 'resistance' in condition.lower():
                text += f"• ✅ Уровень сопротивления\n"
            elif 'rsi' in condition.lower():
                if signal['side'] == 'LONG':
                    text += f"• 📈 RSI бычий\n"
                else:
                    text += f"• 📉 RSI медвежий\n"
            elif 'объём' in condition.lower() or 'volume' in condition.lower():
                text += f"• 💰 Объёмы подтверждают\n"
            elif 'btc' in condition.lower():
                text += f"• 🔥 BTC поддерживает\n"
            elif 'тренд' in condition.lower() or 'trend' in condition.lower():
                if signal['side'] == 'LONG':
                    text += f"• 📈 Бычий тренд\n"
                else:
                    text += f"• 📉 Медвежий тренд\n"
            elif 'работал' in condition.lower() or 'раз' in condition.lower():
                text += f"• ✅ Проверенный уровень\n"
    else:
        # Фоллбэк: базовые условия
        text += f"• ✅ Уровень {'поддержки' if signal['side'] == 'LONG' else 'сопротивления'}\n"
        text += f"• 📈 {'Бычий' if signal['side'] == 'LONG' else 'Медвежий'} тренд\n"
        text += f"• 💰 Объёмы подтверждают\n"
    
    text += "\n"
    
    # Зона входа
    entry_min, entry_max = signal['entry_zone']
    text += f"🎯 <b>Вход:</b> {entry_min:.2f} - {entry_max:.2f}\n"
    
    # Цели
    text += f"🎯 <b>Цели:</b>\n"
    
    # Расчёт процентов для TP
    entry_price = (entry_min + entry_max) / 2
    tp1_pct = ((signal['take_profit_1'] - entry_price) / entry_price) * 100
    tp2_pct = ((signal['take_profit_2'] - entry_price) / entry_price) * 100
    tp3_pct = ((signal['take_profit_3'] - entry_price) / entry_price) * 100
    
    # Для SHORT проценты будут отрицательными, меняем знак
    if signal['side'] == 'SHORT':
        tp1_pct = -tp1_pct
        tp2_pct = -tp2_pct
        tp3_pct = -tp3_pct
    
    text += f"TP1: {signal['take_profit_1']:.2f} ({tp1_pct:+.2f}%)\n"
    text += f"TP2: {signal['take_profit_2']:.2f} ({tp2_pct:+.2f}%)\n"
    text += f"TP3: {signal['take_profit_3']:.2f} ({tp3_pct:+.2f}%)\n"
    
    # Стоп-лосс
    sl_pct = ((signal['stop_loss'] - entry_price) / entry_price) * 100
    if signal['side'] == 'SHORT':
        sl_pct = -sl_pct
    
    text += f"🛡 <b>Стоп:</b> {signal['stop_loss']:.2f} ({sl_pct:+.2f}%)\n\n"
    
    # Объём позиции
    text += f"💰 <b>Объём позиции:</b> {signal['position_size']}\n"
    
    # Confidence Score
    text += f"📊 <b>Confidence Score:</b> {signal['confidence']}%\n\n"
    
    # Время
    text += f"⏰ {time.strftime('%H:%M:%S')}\n"
    text += f"⚠️ <i>Не финансовый совет</i>"
    
    return text
