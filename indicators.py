"""
indicators.py - Индикаторы и торговая стратегия (УЛУЧШЕННАЯ ВЕРСИЯ)
"""
import time
import logging
from typing import Optional, Dict, List, Tuple
from collections import defaultdict, deque
import httpx

from config import (
    CANDLE_TF, MAX_CANDLES, PRICE_CACHE_TTL,
    EMA_FAST, EMA_SLOW, EMA_TREND, EMA_LONG_TREND,
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD,
    MIN_SIGNAL_SCORE, MIN_VOLUME_RATIO, MIN_VOLATILITY, MAX_SPREAD_PERCENT
)

logger = logging.getLogger(__name__)

# ==================== PRICE CACHE ====================
class PriceCache:
    """Кэш цен для снижения нагрузки на API"""
    def __init__(self, ttl: int = PRICE_CACHE_TTL):
        self.cache: Dict[str, Tuple[float, float, float]] = {}
        self.ttl = ttl
    
    def get(self, pair: str) -> Optional[Tuple[float, float]]:
        if pair in self.cache:
            price, volume, cached_at = self.cache[pair]
            if time.time() - cached_at < self.ttl:
                return price, volume
        return None
    
    def set(self, pair: str, price: float, volume: float):
        self.cache[pair] = (price, volume, time.time())
    
    def clear_old(self):
        now = time.time()
        self.cache = {
            k: v for k, v in self.cache.items()
            if now - v[2] < self.ttl
        }

PRICE_CACHE = PriceCache()

# ==================== CANDLE STORAGE ====================
class CandleStorage:
    """Хранилище свечей"""
    def __init__(self, timeframe=CANDLE_TF, maxlen=MAX_CANDLES):
        self.tf = timeframe
        self.maxlen = maxlen
        self.candles: Dict[str, deque] = defaultdict(lambda: deque(maxlen=maxlen))
        self.current: Dict[str, dict] = {}
    
    def get_bucket(self, ts: float) -> int:
        return int(ts // self.tf) * self.tf
    
    def add_price(self, pair: str, price: float, volume: float, ts: float):
        pair = pair.upper()
        bucket = self.get_bucket(ts)
        
        if pair not in self.current or self.current[pair]["ts"] != bucket:
            if pair in self.current:
                self.candles[pair].append(self.current[pair])
            self.current[pair] = {
                "ts": bucket, "o": price, "h": price, "l": price, "c": price, "v": volume
            }
        else:
            c = self.current[pair]
            c["h"] = max(c["h"], price)
            c["l"] = min(c["l"], price)
            c["c"] = price
            c["v"] += volume
    
    def get_candles(self, pair: str) -> List[dict]:
        pair = pair.upper()
        result = list(self.candles[pair])
        if pair in self.current:
            result.append(self.current[pair])
        return result

CANDLES = CandleStorage()

# ==================== API FUNCTIONS ====================
async def fetch_price(client: httpx.AsyncClient, pair: str) -> Optional[Tuple[float, float]]:
    """Получить цену с Binance"""
    cached = PRICE_CACHE.get(pair)
    if cached:
        return cached
    
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={pair.upper()}"
        resp = await client.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["lastPrice"])
        volume = float(data["volume"])
        
        PRICE_CACHE.set(pair, price, volume)
        return price, volume
    except Exception as e:
        logger.error(f"Error fetching {pair}: {e}")
        return None

async def check_liquidity(client: httpx.AsyncClient, pair: str) -> Optional[float]:
    """Проверить ликвидность пары (спред bid/ask)"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={pair.upper()}"
        resp = await client.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        
        bid = float(data["bidPrice"])
        ask = float(data["askPrice"])
        
        if bid == 0:
            return None
        
        spread_percent = ((ask - bid) / bid) * 100
        return spread_percent
    except Exception as e:
        logger.error(f"Error checking liquidity for {pair}: {e}")
        return None

# ==================== INDICATORS ====================
def ema(values: List[float], period: int) -> Optional[float]:
    """Exponential Moving Average"""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def sma(values: List[float], period: int) -> Optional[float]:
    """Simple Moving Average"""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def rsi(closes: List[float], period: int = RSI_PERIOD) -> Optional[float]:
    """Relative Strength Index"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def macd(closes: List[float]) -> Optional[Tuple[float, float, float]]:
    """MACD индикатор - (macd_line, signal_line, histogram)"""
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return None
    
    ema_fast = ema(closes, MACD_FAST)
    ema_slow = ema(closes, MACD_SLOW)
    
    if ema_fast is None or ema_slow is None:
        return None
    
    macd_line = ema_fast - ema_slow
    
    macd_history = []
    for i in range(len(closes) - MACD_SLOW - MACD_SIGNAL, len(closes)):
        if i < MACD_FAST:
            continue
        ef = ema(closes[:i+1], MACD_FAST)
        es = ema(closes[:i+1], MACD_SLOW)
        if ef and es:
            macd_history.append(ef - es)
    
    if len(macd_history) < MACD_SIGNAL:
        return None
    
    signal_line = ema(macd_history, MACD_SIGNAL)
    if signal_line is None:
        return None
    
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def bollinger_bands(closes: List[float]) -> Optional[Tuple[float, float, float]]:
    """Bollinger Bands - (upper, middle, lower)"""
    if len(closes) < BB_PERIOD:
        return None
    
    middle = sma(closes, BB_PERIOD)
    if middle is None:
        return None
    
    recent = closes[-BB_PERIOD:]
    variance = sum((x - middle) ** 2 for x in recent) / BB_PERIOD
    std = variance ** 0.5
    
    upper = middle + (std * BB_STD)
    lower = middle - (std * BB_STD)
    
    return upper, middle, lower

def volume_strength(candles: List[dict], period=20) -> Optional[float]:
    """Сила объёма относительно средней"""
    if len(candles) < period + 1:
        return None
    
    volumes = [c.get("v", 0) for c in candles[-period-1:]]
    avg_volume = sum(volumes[:-1]) / period
    current_volume = volumes[-1]
    
    if avg_volume == 0:
        return 1.0
    
    return current_volume / avg_volume

def atr(candles: List[dict], period=14) -> Optional[float]:
    """Average True Range"""
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(-period, 0):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        true_ranges.append(tr)
    return sum(true_ranges) / period

def calculate_volatility(closes: List[float], period=20) -> Optional[float]:
    """Рассчитать волатильность (стандартное отклонение доходности)"""
    if len(closes) < period + 1:
        return None
    
    returns = []
    for i in range(-period, 0):
        if closes[i-1] != 0:
            ret = (closes[i] - closes[i-1]) / closes[i-1]
            returns.append(ret)
    
    if not returns:
        return None
    
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    volatility = variance ** 0.5
    
    return volatility

def check_divergence(closes: List[float], rsi_values: List[float]) -> Optional[str]:
    """Проверка дивергенции между ценой и RSI"""
    if len(closes) < 20 or len(rsi_values) < 20:
        return None
    
    price_recent = closes[-20:]
    rsi_recent = rsi_values[-20:]
    
    # Бычья дивергенция
    if price_recent[-1] < price_recent[0] and rsi_recent[-1] > rsi_recent[0]:
        price_change = (price_recent[-1] - price_recent[0]) / price_recent[0]
        rsi_change = rsi_recent[-1] - rsi_recent[0]
        if price_change < -0.02 and rsi_change > 5:
            return "bullish"
    
    # Медвежья дивергенция
    if price_recent[-1] > price_recent[0] and rsi_recent[-1] < rsi_recent[0]:
        price_change = (price_recent[-1] - price_recent[0]) / price_recent[0]
        rsi_change = rsi_recent[-1] - rsi_recent[0]
        if price_change > 0.02 and rsi_change < -5:
            return "bearish"
    
    return None

# ==================== TP/SL CALCULATION ====================
def calculate_tp_sl(entry: float, side: str, atr_val: float) -> Dict:
    """
    Расчёт TP/SL с тремя уровнями (УЛУЧШЕННАЯ ВЕРСИЯ)
    
    Изменено для часового таймфрейма:
    - TP1: 2:1 R/R (было 1.5:1) - больше пространства для движения
    - TP2: 4:1 R/R (было 3:1) - более реалистичные цели
    - TP3: 6:1 R/R (было 5:1) - агрессивные, но достижимые
    """
    sl_distance = atr_val * 2.0
    tp1_distance = sl_distance * 2.0  # R/R 2:1 (было 1.5)
    tp2_distance = sl_distance * 4.0  # R/R 4:1 (было 3.0)
    tp3_distance = sl_distance * 6.0  # R/R 6:1 (было 5.0)
    
    if side == "LONG":
        sl = entry - sl_distance
        tp1 = entry + tp1_distance
        tp2 = entry + tp2_distance
        tp3 = entry + tp3_distance
    else:
        sl = entry + sl_distance
        tp1 = entry - tp1_distance
        tp2 = entry - tp2_distance
        tp3 = entry - tp3_distance
    
    return {
        "stop_loss": sl,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "sl_percent": abs((sl - entry) / entry * 100),
        "tp1_percent": abs((tp1 - entry) / entry * 100),
        "tp2_percent": abs((tp2 - entry) / entry * 100),
        "tp3_percent": abs((tp3 - entry) / entry * 100)
    }

# ==================== STRATEGY ====================
def quick_screen(pair: str) -> bool:
    """Быстрый скрининг - отсев слабых кандидатов"""
    candles = CANDLES.get_candles(pair)
    if len(candles) < 60:
        return False
    
    closes = [c["c"] for c in candles]
    
    # Проверка волатильности
    volatility = calculate_volatility(closes, 20)
    if volatility is None or volatility < MIN_VOLATILITY:
        return False
    
    # Проверка объёма
    vol_str = volume_strength(candles, 20)
    if vol_str is None or vol_str < MIN_VOLUME_RATIO:
        return False
    
    # Проверка расхождения EMA
    ema9 = ema(closes, EMA_FAST)
    ema21 = ema(closes, EMA_SLOW)
    
    if ema9 is None or ema21 is None:
        return False
    
    return abs(ema9 - ema21) / ema21 > 0.002

def analyze_signal(pair: str) -> Optional[Dict]:
    """Глубокий анализ сигнала с улучшенными фильтрами"""
    if not quick_screen(pair):
        return None
    
    candles = CANDLES.get_candles(pair)
    if len(candles) < 250:
        return None
    
    closes = [c["c"] for c in candles]
    current_price = closes[-1]
    
    # Все индикаторы
    ema9 = ema(closes, EMA_FAST)
    ema21 = ema(closes, EMA_SLOW)
    ema50 = ema(closes, EMA_TREND)
    ema200 = ema(closes, EMA_LONG_TREND) if len(closes) >= 200 else None
    
    # RSI история для дивергенций
    rsi_history = []
    for i in range(len(closes) - 50, len(closes)):
        if i >= RSI_PERIOD:
            rsi_val = rsi(closes[:i+1], RSI_PERIOD)
            if rsi_val:
                rsi_history.append(rsi_val)
    
    rsi_current = rsi(closes, RSI_PERIOD)
    macd_data = macd(closes)
    bb_data = bollinger_bands(closes)
    vol_strength = volume_strength(candles, 20)
    atr_val = atr(candles, 14)
    volatility = calculate_volatility(closes, 20)
    
    if None in [ema9, ema21, ema50, rsi_current, macd_data, bb_data, vol_strength, atr_val, volatility]:
        return None
    
    # Дополнительный фильтр: проверка минимальной волатильности
    if volatility < MIN_VOLATILITY:
        return None
    
    macd_line, signal_line, histogram = macd_data
    bb_upper, bb_middle, bb_lower = bb_data
    divergence = check_divergence(closes[-50:], rsi_history) if len(rsi_history) >= 20 else None
    
    score = 0
    reasons = []
    side = None
    
    # ========== LONG СИГНАЛ ==========
    if ema9 > ema21 and ema21 > ema50:
        score += 20
        reasons.append("✅ Восходящий тренд (EMA 9>21>50)")
        
        if ema200 and current_price > ema200:
            score += 10
            reasons.append("✅ Цена выше EMA200")
        
        if RSI_OVERSOLD < rsi_current < 65:
            if 45 <= rsi_current <= 55:
                score += 20
                reasons.append(f"🎯 RSI идеален ({rsi_current:.1f})")
            else:
                score += 15
                reasons.append(f"✅ RSI приемлем ({rsi_current:.1f})")
        
        if macd_line > signal_line:
            score += 15
            reasons.append("✅ MACD бычий")
            if histogram > 0 and abs(histogram) > abs(macd_line) * 0.1:
                score += 5
                reasons.append("📈 MACD импульс растёт")
        
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower)
        if bb_position < 0.3:
            score += 15
            reasons.append("🎯 Сильный отскок от нижней BB")
        elif bb_position < 0.5:
            score += 10
            reasons.append("✅ Отскок от нижней BB")
        
        if vol_strength > 2.0:
            score += 10
            reasons.append(f"🔥 Очень высокий объём ({vol_strength:.1f}x)")
        elif vol_strength > 1.5:
            score += 7
            reasons.append(f"📊 Высокий объём ({vol_strength:.1f}x)")
        
        if volatility > MIN_VOLATILITY * 1.5:
            score += 5
            reasons.append(f"💹 Хорошая волатильность ({volatility*100:.2f}%)")
        
        momentum = (ema9 - ema21) / ema21
        if momentum > 0.01:
            score += 10
            reasons.append("⚡ Очень сильный импульс")
        elif momentum > 0.005:
            score += 7
            reasons.append("✅ Сильный импульс")
        
        if divergence == "bullish":
            score += 15
            reasons.append("🚀 Бычья дивергенция!")
        
        if score >= MIN_SIGNAL_SCORE:
            side = "LONG"
    
    # ========== SHORT СИГНАЛ ==========
    elif ema9 < ema21 and ema21 < ema50:
        score += 20
        reasons.append("✅ Нисходящий тренд (EMA 9<21<50)")
        
        if ema200 and current_price < ema200:
            score += 10
            reasons.append("✅ Цена ниже EMA200")
        
        if 35 < rsi_current < RSI_OVERBOUGHT:
            if 45 <= rsi_current <= 55:
                score += 20
                reasons.append(f"🎯 RSI идеален ({rsi_current:.1f})")
            else:
                score += 15
                reasons.append(f"✅ RSI приемлем ({rsi_current:.1f})")
        
        if macd_line < signal_line:
            score += 15
            reasons.append("✅ MACD медвежий")
            if histogram < 0 and abs(histogram) > abs(macd_line) * 0.1:
                score += 5
                reasons.append("📉 MACD импульс падает")
        
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower)
        if bb_position > 0.7:
            score += 15
            reasons.append("🎯 Сильный откат от верхней BB")
        elif bb_position > 0.5:
            score += 10
            reasons.append("✅ Откат от верхней BB")
        
        if vol_strength > 2.0:
            score += 10
            reasons.append(f"🔥 Очень высокий объём ({vol_strength:.1f}x)")
        elif vol_strength > 1.5:
            score += 7
            reasons.append(f"📊 Высокий объём ({vol_strength:.1f}x)")
        
        if volatility > MIN_VOLATILITY * 1.5:
            score += 5
            reasons.append(f"💹 Хорошая волатильность ({volatility*100:.2f}%)")
        
        momentum = (ema21 - ema9) / ema21
        if momentum > 0.01:
            score += 10
            reasons.append("⚡ Очень сильный импульс")
        elif momentum > 0.005:
            score += 7
            reasons.append("✅ Сильный импульс")
        
        if divergence == "bearish":
            score += 15
            reasons.append("🚀 Медвежья дивергенция!")
        
        if score >= MIN_SIGNAL_SCORE:
            side = "SHORT"
    
    if side and score >= MIN_SIGNAL_SCORE:
        tp_sl = calculate_tp_sl(current_price, side, atr_val)
        return {
            "side": side,
            "price": current_price,
            "score": score,
            "reasons": reasons,
            "volatility": volatility,
            "volume_ratio": vol_strength,
            **tp_sl
        }
    
    return None
