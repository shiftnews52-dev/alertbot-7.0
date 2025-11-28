"""
tasks_v2.py - Фоновые задачи с CryptoMicky Analyzer
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
    MAX_SIGNALS_PER_DAY, BATCH_SEND_SIZE, BATCH_SEND_DELAY
)
from database import (
    get_all_tracked_pairs, get_pairs_with_users,
    count_signals_today, log_signal, get_all_user_ids
)
from indicators import CANDLES, fetch_price, fetch_candles_binance
from professional_analyzer_v2 import crypto_micky_analyzer

logger = logging.getLogger(__name__)
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
            
            for pair in active_pairs:
                analyzed += 1
                
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
                    text = _format_cryptomicky_signal(signal)
                    
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
                    LAST_SIGNALS[pair] = time.time()
            
            # Статистика цикла
            logger.info(f"📊 Cycle: {analyzed} pairs analyzed, {signals_found} signals found")
            
            if signals_found == 0:
                logger.info("💤 No high-confidence signals this cycle (60%+ required)")
                
        except Exception as e:
            logger.error(f"Signal analyzer error: {e}")
        
        await asyncio.sleep(60)

def _format_cryptomicky_signal(signal: dict) -> str:
    """
    Форматирование сообщения по ТЗ CryptoMicky п.11
    
    Формат:
    🔻 ETH — SHORT
    
    Логика: Цена тестирует зону сопротивления 3450–3470$, 
    объёмы снижаются, RSI разворачивается вниз, BTC не 
    подтверждает рост.
    
    Сценарий:
    Вход: 3450–3470$
    Цели: 3300 → 3180 → 3050$
    Стоп: 3520$
    Объём: до 10–12% депо
    Confidence: 82%
    
    ⚠️ Не финансовый совет.
    """
    side_emoji = "🟢" if signal['side'] == 'LONG' else "🔴"
    
    # Заголовок
    text = f"{side_emoji} <b>{signal['pair']} — {signal['side']}</b>\n\n"
    
    # Логика
    text += f"<b>Логика:</b> {signal['logic']}\n\n"
    
    # Сценарий
    entry_min, entry_max = signal['entry_zone']
    text += f"<b>Сценарий:</b>\n"
    text += f"Вход: {entry_min:.2f}–{entry_max:.2f}$\n"
    text += f"Цели: {signal['take_profit_1']:.2f} → {signal['take_profit_2']:.2f} → {signal['take_profit_3']:.2f}$\n"
    text += f"Стоп: {signal['stop_loss']:.2f}$\n"
    text += f"Объём: {signal['position_size']}\n"
    text += f"Confidence: {signal['confidence']}% 🎯\n\n"
    
    # Время и дисклеймер
    text += "⏰ " + time.strftime('%H:%M:%S') + "\n"
    text += "⚠️ <i>Не финансовый совет</i>"
    
    return text
