#!/usr/bin/env python3
"""
indicators.py v4.0 — Indicadores técnicos completos
BB, RSI, SMA, MACD, Stochastic, ATR, Divergencias, Score
"""

import numpy as np
import pandas as pd
from config import (BB_PERIOD, BB_STD, SMA_PERIOD, RSI_PERIOD,
                    ATR_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
                    STOCH_K, STOCH_D, TREND_LOOKBACK, TREND_THRESH)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high, low, close, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _stoch(high, low, close, k=14, d=3) -> pd.Series:
    lo  = low.rolling(k).min()
    hi  = high.rolling(k).max()
    raw = (close - lo) / (hi - lo + 1e-10) * 100
    return raw.rolling(d).mean()


def _bollinger(close, period=20, std=2.0):
    basis = close.rolling(period).mean()
    s     = close.rolling(period).std()
    return basis, basis + std * s, basis - std * s


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade todos los indicadores al DataFrame."""
    c, h, l = df["close"], df["high"], df["low"]

    basis, upper, lower = _bollinger(c, BB_PERIOD, BB_STD)
    df["basis"] = basis
    df["upper"] = upper
    df["lower"] = lower

    df["sma50"] = c.rolling(SMA_PERIOD).mean()
    df["rsi"]   = _rsi(c, RSI_PERIOD)
    df["atr"]   = _atr(h, l, c, ATR_PERIOD)

    ema_fast = _ema(c, MACD_FAST)
    ema_slow = _ema(c, MACD_SLOW)
    macd_line  = ema_fast - ema_slow
    signal_line = _ema(macd_line, MACD_SIGNAL)
    df["macd"]        = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"]   = macd_line - signal_line

    df["stoch"] = _stoch(h, l, c, STOCH_K, STOCH_D)

    df["volume_ma"] = df["volume"].rolling(20).mean() if "volume" in df.columns else 1

    return df


def get_trend(basis: pd.Series, idx: int, lookback: int = None) -> str:
    """Detecta tendencia: 'up', 'down', 'flat'."""
    lb = lookback or TREND_LOOKBACK
    if idx < lb:
        return "flat"
    try:
        recent = float(basis.iloc[idx])
        past   = float(basis.iloc[idx - lb])
        if past == 0:
            return "flat"
        change = (recent - past) / past
        if change > TREND_THRESH:
            return "up"
        if change < -TREND_THRESH:
            return "down"
        return "flat"
    except Exception:
        return "flat"


def divergence(close: pd.Series, rsi: pd.Series) -> str:
    """
    Detecta divergencia entre precio y RSI.
    Returns: 'bull', 'bear', o 'none'
    """
    try:
        if len(close) < 6:
            return "none"
        c = close.dropna().values
        r = rsi.dropna().values
        n = min(len(c), len(r))
        if n < 6:
            return "none"
        c, r = c[-n:], r[-n:]
        # Últimos 2 valles (LONG) o picos (SHORT)
        c_low1, c_low2 = min(c[-6:-3]), min(c[-3:])
        r_low1, r_low2 = min(r[-6:-3]), min(r[-3:])
        if c_low2 < c_low1 and r_low2 > r_low1:
            return "bull"
        c_hi1, c_hi2 = max(c[-6:-3]), max(c[-3:])
        r_hi1, r_hi2 = max(r[-6:-3]), max(r[-3:])
        if c_hi2 > c_hi1 and r_hi2 < r_hi1:
            return "bear"
    except Exception:
        pass
    return "none"


def volume_ok(df: pd.DataFrame, idx: int, mult: float = 1.2) -> bool:
    """True si volumen actual > 1.2x media 20 velas."""
    try:
        if "volume" not in df.columns or "volume_ma" not in df.columns:
            return True
        vol    = float(df["volume"].iloc[idx])
        vol_ma = float(df["volume_ma"].iloc[idx])
        if vol_ma <= 0 or np.isnan(vol_ma):
            return True
        return vol >= vol_ma * mult
    except Exception:
        return True


def momentum_bars(close: pd.Series, idx: int, lookback: int = 5) -> int:
    """
    Cuenta velas bajistas en las últimas N velas.
    Returns: número de velas bajistas (cierre < apertura).
    Nota: necesita la serie completa con columna 'open'.
    """
    # Versión simplificada: cuenta velas donde close < close anterior
    try:
        n = min(lookback, idx)
        if n < 1:
            return 0
        closes = close.iloc[idx - n: idx + 1].values
        bear_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])
        return bear_count
    except Exception:
        return 0


def calc_score_long(rsi: float, dv: str, macd_pos: bool,
                    stoch: float, bear_bars: int) -> int:
    """
    Score para señal LONG. Máximo ~100.
    Mayor score = señal más fuerte.
    """
    score = 0

    # RSI oversold
    if rsi < 25:   score += 35
    elif rsi < 30: score += 28
    elif rsi < 35: score += 20
    elif rsi < 40: score += 12

    # Divergencia
    if dv == "bull": score += 20
    elif dv == "none": score += 0

    # MACD positivo
    if macd_pos: score += 15

    # Stochastic oversold
    if stoch < 20:   score += 15
    elif stoch < 30: score += 8

    # Momentum: muchas velas bajistas = rebote inminente
    if bear_bars >= 4: score += 15
    elif bear_bars >= 3: score += 8

    return score


def calc_score_short(rsi: float, dv: str, macd_pos: bool,
                     stoch: float, bull_bars: int) -> int:
    """
    Score para señal SHORT. Máximo ~100.
    """
    score = 0

    # RSI overbought
    if rsi > 75:   score += 35
    elif rsi > 70: score += 28
    elif rsi > 65: score += 20
    elif rsi > 60: score += 12

    # Divergencia
    if dv == "bear": score += 20
    elif dv == "none": score += 0

    # MACD negativo
    if not macd_pos: score += 15

    # Stochastic overbought
    if stoch > 80:   score += 15
    elif stoch > 70: score += 8

    # Momentum: muchas velas alcistas = caída inminente
    if bull_bars >= 4: score += 15
    elif bull_bars >= 3: score += 8

    return score
