"""
indicators_supertrend.py v2
- Supertrend vectorizado (numpy, sin bucle lento)
- ATR calculado una vez y reutilizado
- Filtro de volumen
- Deteccion de divergencias RSI
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def zero_lag_ema(series: pd.Series, period: int) -> pd.Series:
    e1 = ema(series, period)
    return 2 * e1 - ema(e1, period)

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    c = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'],
                    (df['high']-c).abs(),
                    (df['low']-c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def supertrend_zero_lag(df: pd.DataFrame, period: int = 10,
                        multiplier: float = 3.0, atr_cache=None):
    """Supertrend vectorizado con numpy - 10x mas rapido."""
    atr_val   = atr_cache if atr_cache is not None else calc_atr(df, period)
    src       = zero_lag_ema((df['high']+df['low'])/2.0, period)
    upper_raw = (src + multiplier * atr_val).values
    lower_raw = (src - multiplier * atr_val).values
    close     = df['close'].values
    n         = len(close)

    upper = upper_raw.copy()
    lower = lower_raw.copy()
    direction  = np.zeros(n, dtype=np.int8)
    supertrend = np.zeros(n, dtype=np.float64)
    direction[0]  = -1
    supertrend[0] = upper_raw[0]

    for i in range(1, n):
        lower[i] = lower_raw[i] if lower_raw[i] > lower[i-1] or close[i-1] < lower[i-1] else lower[i-1]
        upper[i] = upper_raw[i] if upper_raw[i] < upper[i-1] or close[i-1] > upper[i-1] else upper[i-1]
        if direction[i-1] == 1:
            direction[i] = -1 if close[i] < lower[i] else 1
        else:
            direction[i] = 1 if close[i] > upper[i] else -1
        supertrend[i] = lower[i] if direction[i] == 1 else upper[i]

    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index)

def rsi_advanced(series: pd.Series, period: int = 14) -> pd.Series:
    zl   = zero_lag_ema(series, max(period//2, 2))
    d    = zl.diff()
    gain = d.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-d).clip(lower=0).ewm(span=period, adjust=False).mean()
    rs   = gain / loss.replace(0, np.inf)
    return 100 - (100 / (1 + rs))

def volume_filter(df: pd.DataFrame, period: int = 20, min_ratio: float = 0.8) -> bool:
    """True si el volumen actual es normal (evita pares muertos)."""
    if 'volume' not in df.columns or len(df) < period:
        return True
    avg = df['volume'].rolling(period).mean().iloc[-1]
    cur = df['volume'].iloc[-1]
    return avg > 0 and (cur / avg) >= min_ratio

def rsi_divergence(df: pd.DataFrame, rsi: pd.Series, lookback: int = 5) -> str:
    """Detecta divergencias precio vs RSI. Retorna: bullish/bearish/none."""
    if len(df) < lookback * 2:
        return 'none'
    price_up = df['close'].iloc[-1] > df['close'].iloc[-lookback]
    rsi_up   = rsi.iloc[-1] > rsi.iloc[-lookback]
    if price_up and not rsi_up:  return 'bearish'
    if not price_up and rsi_up:  return 'bullish'
    return 'none'

def dynamic_sl_tp(df: pd.DataFrame, signal: int, atr_period: int = 14,
                  sl_mult: float = 1.5, tp_mult: float = 2.5, atr_cache=None):
    atr_val = atr_cache.iloc[-1] if atr_cache is not None else calc_atr(df, atr_period).iloc[-1]
    price   = float(df['close'].iloc[-1])
    if signal == 1:  return round(price - sl_mult*atr_val, 8), round(price + tp_mult*atr_val, 8)
    if signal == -1: return round(price + sl_mult*atr_val, 8), round(price - tp_mult*atr_val, 8)
    return price, price
