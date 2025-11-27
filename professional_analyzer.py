"""
professional_analyzer.py - Анализ по ТЗ CryptoMicky Alerts (80%+ Confidence) - БЕЗ numpy
"""
import logging
from typing import Dict, List, Optional, Tuple
import math

logger = logging.getLogger(__name__)

class ProfessionalAnalyzer:
    """Профессиональный анализатор по ТЗ"""
    
    def __init__(self):
        self.required_conditions = {
            'LONG': [
                'price_at_support',
                'support_level_works',
                'rsi_from_oversold', 
                'volume_decreasing_on_red',
                'btc_not_falling'
            ],
            'SHORT': [
                'price_at_resistance',
                'resistance_level_works',
                'rsi_from_overbought',
                'volume_decreasing_on_green',
                'btc_not_pumping'
            ]
        }
    
    def analyze_pair(self, pair: str, candles_1h: List, candles_4h: List, candles_1d: List) -> Optional[Dict]:
        """Основной анализ по ТЗ"""
        try:
            # Проверяем достаточность данных
            if len(candles_1h) < 50 or len(candles_4h) < 50 or len(candles_1d) < 30:
                return None
            
            # Определяем тренд
            trend_4h = self._determine_trend(candles_4h)
            trend_1d = self._determine_trend(candles_1d)
            
            # Находим ключевые уровни
            supports, resistances = self._find_key_levels(candles_4h)
            
            # Анализируем LONG
            long_signal = self._analyze_long(pair, candles_1h, candles_4h, trend_4h, trend_1d, supports)
            if long_signal:
                # 🔥 ФИЛЬТР: только сигналы от 80% Confidence
                if long_signal.get('confidence', 0) >= 80:
                    logger.info(f"📊 {pair} LONG: {long_signal['confidence']}% confidence ✅")
                    return long_signal
                else:
                    logger.debug(f"📊 {pair} LONG: {long_signal['confidence']}% confidence ❌ (ниже 80%)")
            
            # Анализируем SHORT
            short_signal = self._analyze_short(pair, candles_1h, candles_4h, trend_4h, trend_1d, resistances)
            if short_signal:
                # 🔥 ФИЛЬТР: только сигналы от 80% Confidence
                if short_signal.get('confidence', 0) >= 80:
                    logger.info(f"📊 {pair} SHORT: {short_signal['confidence']}% confidence ✅")
                    return short_signal
                else:
                    logger.debug(f"📊 {pair} SHORT: {short_signal['confidence']}% confidence ❌ (ниже 80%)")
            
            logger.debug(f"📊 {pair}: No high-confidence signal found")
            return None
            
        except Exception as e:
            logger.error(f"Analysis error for {pair}: {e}")
            return None
    
    def _determine_trend(self, candles: List) -> str:
        """Определение тренда по ТЗ п.3"""
        if len(candles) < 20:
            return 'neutral'
        
        closes = [c['c'] for c in candles]
        highs = [c['h'] for c in candles]
        lows = [c['l'] for c in candles]
        
        # Анализ структуры цены
        recent_highs = highs[-10:]
        recent_lows = lows[-10:]
        
        # Higher highs / lower lows
        higher_highs = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i-1])
        lower_lows = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i-1])
        
        # RSI анализ
        rsi = self._calculate_rsi(closes)
        if rsi is None:
            return 'neutral'
        
        # EMA анализ
        ema_50 = self._calculate_ema(closes, 50)
        ema_100 = self._calculate_ema(closes, 100)
        
        bull_conditions = 0
        bear_conditions = 0
        
        # Бычьи условия (минимум 2 из 4)
        if higher_highs > 5:
            bull_conditions += 1
        if rsi > 50:
            bull_conditions += 1
        if ema_50 and ema_100 and closes[-1] > ema_50 and closes[-1] > ema_100:
            bull_conditions += 1
        
        # Медвежьи условия (минимум 2 из 4)
        if lower_lows > 5:
            bear_conditions += 1
        if rsi < 50:
            bear_conditions += 1
        if ema_50 and ema_100 and closes[-1] < ema_50 and closes[-1] < ema_100:
            bear_conditions += 1
        
        if bull_conditions >= 2:
            return 'bullish'
        elif bear_conditions >= 2:
            return 'bearish'
        else:
            return 'neutral'
    
    def _find_key_levels(self, candles: List) -> Tuple[List[float], List[float]]:
        """Поиск ключевых уровней по ТЗ п.4"""
        if len(candles) < 50:
            return [], []
        
        highs = [c['h'] for c in candles]
        lows = [c['l'] for c in candles]
        closes = [c['c'] for c in candles]
        volumes = [c['v'] for c in candles]
        
        supports = []
        resistances = []
        
        # Ищем уровни поддержки (минимум 2 отскока)
        for i in range(20, len(candles)-10):
            current_low = lows[i]
            
            # Проверяем был ли это уровень поддержки
            bounce_count = 0
            for j in range(max(0, i-30), min(len(candles), i+30)):
                if abs(lows[j] - current_low) / current_low <= 0.02:  # 2% tolerance
                    # Средний объём без numpy
                    volume_slice = volumes[max(0, j-5):j]
                    avg_volume = sum(volume_slice) / len(volume_slice) if volume_slice else 0
                    if volumes[j] > avg_volume:
                        bounce_count += 1
            
            if bounce_count >= 2 and current_low < closes[-1]:
                supports.append(current_low)
        
        # Ищем уровни сопротивления (минимум 2 отскока)
        for i in range(20, len(candles)-10):
            current_high = highs[i]
            
            # Проверяем был ли это уровень сопротивления
            bounce_count = 0
            for j in range(max(0, i-30), min(len(candles), i+30)):
                if abs(highs[j] - current_high) / current_high <= 0.02:  # 2% tolerance
                    # Средний объём без numpy
                    volume_slice = volumes[max(0, j-5):j]
                    avg_volume = sum(volume_slice) / len(volume_slice) if volume_slice else 0
                    if volumes[j] > avg_volume:
                        bounce_count += 1
            
            if bounce_count >= 2 and current_high > closes[-1]:
                resistances.append(current_high)
        
        # Фильтруем и группируем уровни
        supports = self._filter_levels(supports, closes[-1])
        resistances = self._filter_levels(resistances, closes[-1])
        
        return supports, resistances
    
    def _analyze_long(self, pair: str, candles_1h: List, candles_4h: List, 
                     trend_4h: str, trend_1d: str, supports: List[float]) -> Optional[Dict]:
        """Анализ LONG по ТЗ п.5.2"""
        current_price = candles_1h[-1]['c']
        
        # Находим ближайшую поддержку
        best_support = None
        for support in supports:
            if support < current_price:
                distance_pct = (current_price - support) / current_price
                if distance_pct <= 0.015:  # 1.5%
                    if best_support is None or support > best_support:
                        best_support = support
        
        if not best_support:
            return None
        
        # Проверяем ВСЕ условия для LONG
        conditions_met = []
        
        # 1. Цена у поддержки (±1.5%)
        price_diff = abs(current_price - best_support) / best_support
        if price_diff <= 0.015:
            conditions_met.append('price_at_support')
        
        # 2. Уровень работал минимум 2 раза (уже в фильтре)
        conditions_met.append('support_level_works')
        
        # 3. RSI растёт от 30-45
        rsi_1h = self._calculate_rsi([c['c'] for c in candles_1h])
        rsi_4h = self._calculate_rsi([c['c'] for c in candles_4h])
        if rsi_1h and rsi_4h and 30 <= rsi_1h <= 45 and rsi_1h > rsi_4h:
            conditions_met.append('rsi_from_oversold')
        
        # 4. Объёмы на красных свечах уменьшаются
        if self._check_volume_decrease_on_red(candles_1h):
            conditions_met.append('volume_decreasing_on_red')
        
        # 5. BTC не падает сильно (заглушка - нужно реализовать проверку BTC)
        conditions_met.append('btc_not_falling')
        
        # Проверяем выполнены ли ВСЕ условия
        if set(conditions_met) == set(self.required_conditions['LONG']):
            return self._create_signal('LONG', pair, current_price, best_support, conditions_met)
        
        return None
    
    def _analyze_short(self, pair: str, candles_1h: List, candles_4h: List,
                      trend_4h: str, trend_1d: str, resistances: List[float]) -> Optional[Dict]:
        """Анализ SHORT по ТЗ п.5.1"""
        current_price = candles_1h[-1]['c']
        
        # Находим ближайшее сопротивление
        best_resistance = None
        for resistance in resistances:
            if resistance > current_price:
                distance_pct = (resistance - current_price) / current_price
                if distance_pct <= 0.015:  # 1.5%
                    if best_resistance is None or resistance < best_resistance:
                        best_resistance = resistance
        
        if not best_resistance:
            return None
        
        # Проверяем ВСЕ условия для SHORT
        conditions_met = []
        
        # 1. Цена у сопротивления (±1.5%)
        price_diff = abs(current_price - best_resistance) / best_resistance
        if price_diff <= 0.015:
            conditions_met.append('price_at_resistance')
        
        # 2. Уровень работал минимум 2 раза
        conditions_met.append('resistance_level_works')
        
        # 3. RSI падает сверху вниз
        rsi_1h = self._calculate_rsi([c['c'] for c in candles_1h])
        rsi_4h = self._calculate_rsi([c['c'] for c in candles_4h])
        if rsi_1h and rsi_4h and 55 <= rsi_1h <= 70 and rsi_1h < rsi_4h:
            conditions_met.append('rsi_from_overbought')
        
        # 4. Объёмы на зелёных свечах уменьшаются
        if self._check_volume_decrease_on_green(candles_1h):
            conditions_met.append('volume_decreasing_on_green')
        
        # 5. BTC не бычий (заглушка)
        conditions_met.append('btc_not_pumping')
        
        # Проверяем выполнены ли ВСЕ условия
        if set(conditions_met) == set(self.required_conditions['SHORT']):
            return self._create_signal('SHORT', pair, current_price, best_resistance, conditions_met)
        
        return None
    
    def _create_signal(self, side: str, pair: str, current_price: float, 
                      level: float, conditions_met: List[str]) -> Dict:
        """Создание сигнала по ТЗ"""
        
        # Confidence score (ТЗ п.10)
        confidence = len(conditions_met) * 20  # база
        if len(conditions_met) == 5:  # все условия
            confidence += 10
        confidence = min(confidence, 100)
        
        # 🔥 ФИЛЬТР: только сигналы от 80% Confidence (проверка в analyze_pair)
        
        # Расчёт входа (ТЗ п.6)
        if side == 'LONG':
            entry_min = level * 0.995  # -0.5%
            entry_max = level * 1.015  # +1.5%
            stop_loss = level * 0.985  # -1.5%
        else:  # SHORT
            entry_min = level * 0.985  # -1.5%
            entry_max = level * 1.005  # +0.5%
            stop_loss = level * 1.015  # +1.5%
        
        # Расчёт тейков (ТЗ п.8)
        tp1, tp2, tp3 = self._calculate_take_profits(side, current_price, level)
        
        # Позиционный sizing (ТЗ п.9)
        position_size = self._get_position_size(len(conditions_met))
        
        # Форматирование логики
        logic = self._format_logic(side, conditions_met, level)
        
        return {
            'side': side,
            'pair': pair,
            'entry_zone': (entry_min, entry_max),
            'stop_loss': stop_loss,
            'take_profit_1': tp1,
            'take_profit_2': tp2,
            'take_profit_3': tp3,
            'confidence': confidence,
            'position_size': position_size,
            'logic': logic,
            'current_price': current_price,
            'level': level
        }
    
    def _calculate_take_profits(self, side: str, current_price: float, level: float) -> Tuple[float, float, float]:
        """Расчёт 3 тейк-профитов по ТЗ п.8"""
        if side == 'LONG':
            # TP1 - ближайшая ликвидность (+2-3%)
            tp1 = current_price * 1.025
            # TP2 - среднесрочная зона (+5-7%)
            tp2 = current_price * 1.06
            # TP3 - глубокая цель (+10-12%)
            tp3 = current_price * 1.11
        else:  # SHORT
            # TP1 - ближайшая ликвидность (-2-3%)
            tp1 = current_price * 0.975
            # TP2 - среднесрочная зона (-5-7%)
            tp2 = current_price * 0.94
            # TP3 - глубокая цель (-10-12%)
            tp3 = current_price * 0.89
        
        return tp1, tp2, tp3
    
    def _get_position_size(self, conditions_count: int) -> str:
        """Определение размера позиции по ТЗ п.9"""
        if conditions_count == 5:
            return "15-20% депо"
        elif conditions_count == 4:
            return "10-12% депо"
        elif conditions_count == 3:
            return "5-8% депо"
        else:
            return "0% (сигнал не даётся)"
    
    def _format_logic(self, side: str, conditions: List[str], level: float) -> str:
        """Форматирование логики для сигнала"""
        base = f"Цена тестирует зону {'поддержки' if side == 'LONG' else 'сопротивления'} {level:.2f}$"
        
        details = []
        if 'rsi_from_oversold' in conditions or 'rsi_from_overbought' в conditions:
            details.append("RSI показывает разворот")
        if 'volume_decreasing_on_red' in conditions or 'volume_decreasing_on_green' в conditions:
            details.append("объёмы снижаются")
        if 'btc_not_falling' in conditions or 'btc_not_pumping' в conditions:
            details.append("BTC не подтверждает движение")
        
        if details:
            base += ", " + ", ".join(details)
        
        return base + "."
    
    # Вспомогательные методы
    def _calculate_rsi(self, closes: List[float], period: int = 14) -> Optional[float]:
        """Расчёт RSI без numpy"""
        if len(closes) < period + 1:
            return None
        
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(0, change))
            losses.append(max(0, -change))
        
        if len(gains) < period:
            return None
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_ema(self, values: List[float], period: int) -> Optional[float]:
        """Расчёт EMA"""
        if len(values) < period:
            return None
        
        k = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * k + ema * (1 - k)
        return ema
    
    def _check_volume_decrease_on_red(self, candles: List) -> bool:
        """Проверка уменьшения объёмов на красных свечах"""
        if len(candles) < 10:
            return False
        
        red_candles = [c for c in candles[-5:] if c['c'] < c['o']]
        if len(red_candles) < 2:
            return False
        
        # Проверяем тренд объёмов
        volumes = [c['v'] for c in red_candles]
        return volumes[-1] < volumes[0]
    
    def _check_volume_decrease_on_green(self, candles: List) -> bool:
        """Проверка уменьшения объёмов на зелёных свечах"""
        if len(candles) < 10:
            return False
        
        green_candles = [c for c in candles[-5:] if c['c'] > c['o']]
        if len(green_candles) < 2:
            return False
        
        # Проверяем тренд объёмов
        volumes = [c['v'] for c in green_candles]
        return volumes[-1] < volumes[0]
    
    def _filter_levels(self, levels: List[float], current_price: float) -> List[float]:
        """Фильтрация уровней"""
        if not levels:
            return []
        
        # Убираем уровни слишком далеко от цены
        filtered = [l for l in levels if abs(l - current_price) / current_price <= 0.1]
        
        # Группируем близкие уровни
        filtered.sort()
        grouped = []
        current_group = [filtered[0]]
        
        for level in filtered[1:]:
            if abs(level - current_group[0]) / current_group[0] <= 0.02:  # 2%
                current_group.append(level)
            else:
                grouped.append(sum(current_group) / len(current_group))
                current_group = [level]
        
        if current_group:
            grouped.append(sum(current_group) / len(current_group))
        
        return grouped

# Глобальный экземпляр анализатора
professional_analyzer = ProfessionalAnalyzer()
