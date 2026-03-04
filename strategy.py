import numpy as np
import pandas as pd
from indicators import (add_indicators, get_trend, divergence,
                        calc_score_long, calc_score_short,
                        volume_ok, momentum_bars)
from data_feed import get_df
from config import (BB_PERIOD, SMA_PERIOD, RSI_LONG, RSI_SHORT,
                    SCORE_MIN, MIN_RR, SL_BUFFER, PARTIAL_TP_ATR,
                    MTF_ENABLED, MTF_INTERVAL, MTF_BLOCK_COUNTER,
                    REENTRY_ENABLED, REENTRY_COOLDOWN, REENTRY_SCORE_MIN)

# ══════════════════════════════════════════════════════
# strategy.py — Señales BB+RSI Elite v12.3
# Mejoras: multi-timeframe 4h, filtro volumen, re-entry,
#          scoring con momentum, trailing desde apertura
# ══════════════════════════════════════════════════════

MIN_BARS = max(BB_PERIOD, SMA_PERIOD) + 30


def _get_4h_bias(symbol: str) -> str:
    """
    Retorna tendencia en 4h: "up", "down", "flat".
    Se usa para confirmar/bloquear señales 1h.
    """
    if not MTF_ENABLED:
        return "flat"
    try:
        df4 = get_df(symbol, interval=MTF_INTERVAL, limit=100)
        if df4.empty or len(df4) < 30:
            return "flat"
        df4 = add_indicators(df4)
        trend = get_trend(df4["basis"], len(df4) - 1)
        return trend
    except Exception:
        return "flat"


def get_signal(df: pd.DataFrame, symbol: str = "",
               reentry_info: dict = None) -> dict | None:
    """
    Analiza la vela más reciente y retorna señal o None.

    reentry_info: {"side": "long"|"short", "last_sl_time": datetime_iso}
      → si se pasa, aplica reglas de re-entry más estrictas
    """
    if len(df) < MIN_BARS:
        return None

    df = add_indicators(df)
    i    = len(df) - 1
    cur  = df.iloc[i]

    price = float(cur["close"])
    r     = float(cur["rsi"])   if not np.isnan(cur["rsi"])   else 50.0
    a     = float(cur["atr"])   if not np.isnan(cur["atr"])   else 0.0
    mb    = float(cur["macd"]) > 0 if not np.isnan(cur["macd"]) else True
    stv   = float(cur["stoch"]) if not np.isnan(cur["stoch"]) else 50.0
    sma   = float(cur["sma50"]) if not np.isnan(cur["sma50"]) else price
    if a <= 0:
        return None

    blo   = float(cur["lower"])
    bhi   = float(cur["upper"])
    trend_1h = get_trend(df["basis"], i)

    # ── Filtro volumen ─────────────────────────────────
    if not volume_ok(df, i):
        return None

    # ── Multi-timeframe bias ───────────────────────────
    bias_4h = _get_4h_bias(symbol) if symbol else "flat"

    # ── Divergencia ────────────────────────────────────
    dv = divergence(
        df["close"].iloc[max(0, i-8):i+1],
        df["rsi"].iloc[max(0, i-8):i+1],
    )

    # ── Score mínimo para re-entry ─────────────────────
    score_threshold = SCORE_MIN
    is_reentry = False
    if reentry_info and REENTRY_ENABLED:
        score_threshold = REENTRY_SCORE_MIN
        is_reentry = True

    # ── LONG ──────────────────────────────────────────
    if trend_1h != "down" and price >= sma * 0.97:
        # Bloquear LONG si 4h bajista
        if MTF_BLOCK_COUNTER and bias_4h == "down":
            pass  # señal bloqueada por MTF
        else:
            # Contar velas bajistas para penalización
            bear_bars = momentum_bars(df["close"], i, lookback=5)
            touch = (price <= blo * 1.002) or \
                    (dv == "bull" and r < RSI_LONG and price <= blo * 1.01)
            if touch and r < RSI_LONG:
                sc = calc_score_long(r, dv, mb, stv, bear_bars)
                if sc >= score_threshold:
                    sl  = float(cur["low"]) * (1 - SL_BUFFER)
                    tp  = bhi
                    tp_p = price + PARTIAL_TP_ATR * a
                    if sl > 0 and tp > price and (price - sl) > 0:
                        rr = (tp - price) / (price - sl)
                        if rr >= MIN_RR:
                            return dict(
                                side="long", price=price, sl=sl, tp=tp,
                                tp_p=tp_p, score=sc, rsi=round(r, 1),
                                trend=trend_1h, atr=a,
                                bias_4h=bias_4h, reentry=is_reentry
                            )

    # ── SHORT ─────────────────────────────────────────
    if trend_1h == "flat" and price <= sma * 1.03:
        # Bloquear SHORT si 4h alcista
        if MTF_BLOCK_COUNTER and bias_4h == "up":
            pass
        else:
            bull_bars = momentum_bars(df["close"], i, lookback=5)
            touch = (price >= bhi * 0.998) or \
                    (dv == "bear" and r > RSI_SHORT and price >= bhi * 0.99)
            if touch and r > RSI_SHORT:
                sc = calc_score_short(r, dv, mb, stv, bull_bars)
                if sc >= score_threshold:
                    sl  = float(cur["high"]) * (1 + SL_BUFFER)
                    tp  = blo
                    tp_p = price - PARTIAL_TP_ATR * a
                    if sl > price and tp < price and (sl - price) > 0:
                        rr = (price - tp) / (sl - price)
                        if rr >= MIN_RR:
                            return dict(
                                side="short", price=price, sl=sl, tp=tp,
                                tp_p=tp_p, score=sc, rsi=round(r, 1),
                                trend=trend_1h, atr=a,
                                bias_4h=bias_4h, reentry=is_reentry
                            )
    return None
