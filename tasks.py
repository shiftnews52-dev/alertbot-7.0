async def signal_analyzer(bot: Bot):
    """Анализ и отправка сигналов по ТЗ (80%+ Confidence только)"""
    logger.info("🎯 Professional Signal Analyzer started (80%+ Confidence only)")
    
    # Ждём загрузки данных
    await asyncio.sleep(20)
    
    # 🔥 ДИАГНОСТИКА: проверяем загрузку данных
    logger.info("🔍 Checking data availability...")
    for pair in DEFAULT_PAIRS:
        candles_1h = CANDLES.get_candles(pair, "1h")
        candles_4h = CANDLES.get_candles(pair, "4h")
        candles_1d = CANDLES.get_candles(pair, "1d")
        logger.info(f"📊 {pair} - 1H: {len(candles_1h)}, 4H: {len(candles_4h)}, 1D: {len(candles_1d)}")
    
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
                
                if len(candles_1h) < 50 or len(candles_4h) < 50 or len(candles_1d) < 30:
                    continue
                
                # Профессиональный анализ (80%+ Confidence)
                signal = professional_analyzer.analyze_pair(pair, candles_1h, candles_4h, candles_1d)
                if signal:
                    signals_found += 1
                    logger.info(f"🎯 FOUND SIGNAL: {pair} {signal['side']} ({signal['confidence']}%)")
                    
                    # Отправка пользователям
                    users = [row["user_id"] for row in rows if row["pair"] == pair]
                    text = _format_signal_message(signal)
                    
                    sent_count = 0
                    for user_id in users:
                        if await send_message_safe(bot, user_id, text):
                            await log_signal(user_id, pair, signal['side'], signal['current_price'], signal['confidence'])
                            sent_count += 1
                        await asyncio.sleep(0.05)
                    
                    logger.info(f"📤 Sent to {sent_count}/{len(users)} users")
                    LAST_SIGNALS[pair] = time.time()
            
            # Статистика цикла
            logger.info(f"📊 Cycle: {analyzed} pairs analyzed, {signals_found} signals found")
            
            if signals_found == 0:
                logger.info("💤 No high-confidence signals this cycle (80%+ required)")
                
        except Exception as e:
            logger.error(f"Signal analyzer error: {e}")
        
        await asyncio.sleep(60)
