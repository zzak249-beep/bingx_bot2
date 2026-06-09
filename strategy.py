"""
GUA Bot v2 — Motor de Estrategia Multi-Par
SMC/ICT · TTM Squeeze · CVD Div · VWAP · RVOL · Funding · OI Delta
Estado independiente por símbolo.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

import config
import indicators as ind

log = logging.getLogger("strategy")


@dataclass
class Signal:
    symbol:    str
    direction: str        # "LONG" | "SHORT"
    score:     float
    price:     float
    atr:       float
    atr_pct:   float
    sl:        float
    tp1:       float
    tp2:       float
    rsi:       float
    adx:       float
    funding:   float
    squeeze:   bool
    rvol:      float
    reason:    str
    fvg_hit:   bool = False
    ob_hit:    bool = False
    liq_sweep: bool = False
    bos:       str  = "NONE"
    choch:     str  = "NONE"


@dataclass
class _SymState:
    last_candle_time: int = 0
    oi_history: List[float] = field(default_factory=list)


# Estado independiente por símbolo
_states: Dict[str, _SymState] = {}


def analyze(
    symbol:        str,
    candles:       List[Dict],
    candles_trend: List[Dict],
    candles_macro: List[Dict],
    funding_rate:  float = 0.0,
    open_interest: float = 0.0,
) -> Optional[Signal]:

    if len(candles) < 80:
        return None

    state = _states.setdefault(symbol, _SymState())

    # Anti-duplicado por símbolo
    last_time = candles[-1]["time"]
    if last_time == state.last_candle_time:
        return None
    state.last_candle_time = last_time

    if config.SESSION_FILTER and not _in_session():
        return None

    opens   = [c["open"]   for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]

    # ── Indicadores ────────────────────────────────────────────────────────────
    ema9   = ind.ema(closes, config.EMA_FAST)
    ema21  = ind.ema(closes, config.EMA_SLOW)
    ema50  = ind.ema(closes, config.EMA_TREND)
    ema200 = ind.ema(closes, config.EMA_MACRO)
    rsi14  = ind.rsi(closes, config.RSI_PERIOD)
    atr14  = ind.atr(highs, lows, closes, 14)
    adx14, di_p, di_m = ind.adx(highs, lows, closes, config.ADX_PERIOD)
    cvd20  = ind.cvd(opens, closes, volumes, config.CVD_LB)
    ml, sl_line, hist = ind.macd(closes)

    i = -2
    price   = closes[i]
    e9      = ema9[i];  e21 = ema21[i];  e50 = ema50[i];  e200 = ema200[i]
    rsi_v   = rsi14[i]
    atr_v   = atr14[i]
    adx_v   = adx14[i]

    atr_pct  = ind.atr_percentile(atr14, config.ATR_PERCENTILE_LB)
    high_vol = atr_pct >= 75
    low_vol  = atr_pct <= 25

    sqz_arr, mom_arr = ind.squeeze_momentum(
        highs, lows, closes,
        config.BB_PERIOD, config.BB_MULT,
        config.KC_PERIOD, config.KC_MULT,
        config.MOM_PERIOD,
    )
    in_squeeze   = bool(sqz_arr[i])
    prev_squeeze = bool(sqz_arr[i-1])
    sqz_release  = prev_squeeze and not in_squeeze
    mom_v        = mom_arr[i];  mom_prev = mom_arr[i-1]
    mom_bearish  = sqz_release and mom_v < 0 and mom_v < mom_prev
    mom_bullish  = sqz_release and mom_v > 0 and mom_v > mom_prev

    rvol_arr = ind.rvol(volumes, config.RVOL_PERIOD)
    rvol_v   = float(rvol_arr[i])

    vwap_arr, vwap_up, vwap_dn = ind.vwap_bands(
        highs, lows, closes, volumes,
        config.VWAP_PERIOD, config.VWAP_BAND_MULT,
    )
    vwap_v       = vwap_arr[i]
    above_vwap   = price > vwap_v
    extended_up  = price > vwap_up[i]
    extended_dn  = price < vwap_dn[i]

    cvd_bear_div, cvd_bull_div = ind.cvd_divergence(closes, cvd20, config.CVD_DIV_LB)

    bear_fvg, bull_fvg = ind.detect_fvg(highs, lows, closes, config.FVG_LOOKBACK, config.FVG_MIN_SIZE)
    in_bear_fvg = bear_fvg is not None and bear_fvg["bottom"] <= price <= bear_fvg["top"]
    in_bull_fvg = bull_fvg is not None and bull_fvg["bottom"] <= price <= bull_fvg["top"]

    bear_ob, bull_ob = ind.detect_order_blocks(opens, highs, lows, closes, config.OB_LOOKBACK, config.OB_IMPULSE_BARS)
    in_bear_ob = bear_ob is not None and bear_ob["low"] <= price <= bear_ob["high"]
    in_bull_ob = bull_ob is not None and bull_ob["low"] <= price <= bull_ob["high"]

    swept_highs, swept_lows = ind.detect_liquidity_sweep(highs, lows, closes, opens, config.LIQ_LOOKBACK, config.LIQ_TOLERANCE)

    ms = ind.market_structure(highs, lows, closes)

    # OI delta
    state.oi_history.append(open_interest)
    if len(state.oi_history) > config.OI_HISTORY_LEN:
        state.oi_history.pop(0)
    oi_delta = state.oi_history[-1] - state.oi_history[0] if len(state.oi_history) >= 2 else 0.0

    # ── Bias 15m ───────────────────────────────────────────────────────────────
    trend_bias = "NEUTRAL"
    if len(candles_trend) >= 55:
        tc  = [c["close"] for c in candles_trend]
        te9 = ind.ema(tc, config.EMA_FAST)[-1]
        te21= ind.ema(tc, config.EMA_SLOW)[-1]
        te50= ind.ema(tc, config.EMA_TREND)[-1]
        trend_bias = "DOWN" if te9 < te21 and te21 < te50 else "UP" if te9 > te21 and te21 > te50 else "NEUTRAL"

    # ── Macro 1h ───────────────────────────────────────────────────────────────
    macro_bias = "NEUTRAL"
    if len(candles_macro) >= 55:
        mc   = [c["close"] for c in candles_macro]
        me50 = ind.ema(mc, config.EMA_TREND)[-1]
        me200= ind.ema(mc, config.EMA_MACRO)[-1]
        macro_bias = "DOWN" if mc[-1] < me50 < me200 else "UP" if mc[-1] > me50 > me200 else "NEUTRAL"

    log.debug("%s price=%.5f rsi=%.1f adx=%.1f atrPct=%.0f bias15m=%s macro=%s",
              symbol, price, rsi_v, adx_v, atr_pct, trend_bias, macro_bias)

    if low_vol and adx_v < config.ADX_MIN:
        return None

    short_score, short_parts = _score_short(
        price, e9, e21, e50, e200, rsi_v, adx_v, atr_pct,
        mom_bearish, in_squeeze, rvol_v, above_vwap, extended_up,
        cvd_bear_div, swept_highs, in_bear_fvg, in_bear_ob,
        ms, oi_delta, funding_rate, trend_bias, macro_bias,
    )
    long_score, long_parts = _score_long(
        price, opens, closes, e9, e21, e50, e200, rsi_v, adx_v, atr_pct,
        mom_bullish, in_squeeze, rvol_v, price < vwap_v, extended_dn,
        cvd_bull_div, swept_lows, in_bull_fvg, in_bull_ob,
        ms, oi_delta, funding_rate, trend_bias, macro_bias,
    )

    direction = None; score = 0.0; parts = ""
    if short_score > long_score and short_score >= config.SCORE_THR:
        direction, score, parts = "SHORT", short_score, short_parts
    elif long_score >= config.SCORE_THR:
        direction, score, parts = "LONG", long_score, long_parts

    if direction is None:
        return None

    sl_mult = config.ATR_HIGHVOL_MULT if high_vol else config.ATR_SL_MULT
    if direction == "SHORT":
        sl  = price + atr_v * sl_mult
        tp1 = price - atr_v * config.ATR_TP1_MULT
        tp2 = price - atr_v * config.ATR_TP2_MULT
    else:
        sl  = price - atr_v * sl_mult
        tp1 = price + atr_v * config.ATR_TP1_MULT
        tp2 = price + atr_v * config.ATR_TP2_MULT

    return Signal(
        symbol    = symbol,
        direction = direction,
        score     = round(score, 3),
        price     = round(price, 6),
        atr       = round(atr_v, 6),
        atr_pct   = round(atr_pct, 1),
        sl        = round(sl,  6),
        tp1       = round(tp1, 6),
        tp2       = round(tp2, 6),
        rsi       = round(rsi_v, 1),
        adx       = round(adx_v, 1),
        funding   = round(funding_rate, 6),
        squeeze   = in_squeeze,
        rvol      = round(rvol_v, 2),
        reason    = parts,
        fvg_hit   = in_bear_fvg if direction == "SHORT" else in_bull_fvg,
        ob_hit    = in_bear_ob  if direction == "SHORT" else in_bull_ob,
        liq_sweep = swept_highs if direction == "SHORT" else swept_lows,
        bos       = ms["bos"],
        choch     = ms["choch"],
    )


# ── Scorers ────────────────────────────────────────────────────────────────────

def _score_short(price, e9, e21, e50, e200, rsi, adx, atr_pct,
                 mom_bearish, in_squeeze, rvol, above_vwap, extended_up,
                 cvd_div, swept_highs, in_bear_fvg, in_bear_ob,
                 ms, oi_delta, funding, trend_15m, macro_1h):
    parts = []; score = 0.0
    if not (e9 < e21): return 0.0, ""
    score += 0.18; parts.append("EMA9<EMA21 ✅")
    if e21 < e50:    score += 0.07; parts.append("EMA21<EMA50 ✅")
    if price < e200: score += 0.05; parts.append("Bajo EMA200 ✅")
    if (config.RSI_OS+15) <= rsi <= config.RSI_OB: score += 0.12; parts.append(f"RSI={rsi:.0f} zona cargada ✅")
    elif rsi > config.RSI_OB:                       score += 0.07; parts.append(f"RSI={rsi:.0f} sobrecompra ⚠️")
    if swept_highs:  score += 0.14; parts.append("🎣 LiqSweep highs ✅")
    if in_bear_fvg:  score += 0.10; parts.append("📦 FVG bajista ✅")
    if in_bear_ob:   score += 0.08; parts.append("🧱 OB bajista ✅")
    if ms["bos"]   == "BEAR": score += 0.07; parts.append("⚡ BOS bajista ✅")
    elif ms["choch"]== "BEAR": score += 0.05; parts.append("🔄 CHoCH bajista ✅")
    if mom_bearish:  score += 0.10; parts.append("💥 Squeeze bajista ✅")
    elif in_squeeze: score += 0.03; parts.append("🌀 Squeeze activo ⏳")
    if cvd_div:      score += 0.08; parts.append("📊 CVD div bajista ✅")
    if extended_up:  score += 0.06; parts.append("📈 Sobre banda VWAP ✅")
    elif above_vwap: score += 0.02
    if rvol >= config.RVOL_MIN: score += 0.05; parts.append(f"📣 RVOL={rvol:.1f}x ✅")
    if adx >= config.ADX_MIN:   score += 0.05; parts.append(f"ADX={adx:.1f} ✅")
    else:                        score -= 0.05; parts.append(f"ADX={adx:.1f} bajo ❌")
    if oi_delta > 0:             score += 0.04; parts.append("OI↑ dinero nuevo ✅")
    if funding >= config.FUNDING_EXTREME_LONG:  score += 0.05; parts.append(f"💰 Funding +{funding:.4%} ✅")
    elif funding > 0:                            score += 0.02
    if trend_15m == "DOWN":   score += 0.08; parts.append("📉 Bias 15m bajista ✅")
    elif trend_15m == "UP":   score -= 0.12; parts.append("📈 Bias 15m alcista ❌")
    if macro_1h == "DOWN":    score += 0.06; parts.append("🏔 Macro 1h bajista ✅")
    elif macro_1h == "UP":    score -= 0.08; parts.append("🏔 Macro 1h alcista ❌")
    return min(max(score, 0.0), 1.0), " | ".join(parts)


def _score_long(price, opens, closes, e9, e21, e50, e200, rsi, adx, atr_pct,
                mom_bullish, in_squeeze, rvol, below_vwap, extended_dn,
                cvd_div, swept_lows, in_bull_fvg, in_bull_ob,
                ms, oi_delta, funding, trend_15m, macro_1h):
    parts = []; score = 0.0
    if rsi > config.RSI_OS: return 0.0, ""
    score += 0.20; parts.append(f"RSI={rsi:.0f} sobreventa ✅")
    if swept_lows:   score += 0.16; parts.append("🎣 LiqSweep lows ✅")
    if in_bull_fvg:  score += 0.10; parts.append("📦 FVG alcista ✅")
    if in_bull_ob:   score += 0.08; parts.append("🧱 OB alcista ✅")
    if ms["choch"] == "BULL": score += 0.08; parts.append("🔄 CHoCH alcista ✅")
    elif ms["bos"] == "BULL": score += 0.05; parts.append("⚡ BOS alcista ✅")
    if mom_bullish:  score += 0.10; parts.append("💥 Squeeze alcista ✅")
    if cvd_div:      score += 0.08; parts.append("📊 CVD div alcista ✅")
    if extended_dn:  score += 0.06; parts.append("📉 Bajo banda VWAP ✅")
    if rvol >= config.RVOL_MIN: score += 0.05; parts.append(f"📣 RVOL={rvol:.1f}x ✅")
    if oi_delta < 0: score += 0.04; parts.append("OI↓ short covering ✅")
    if funding <= config.FUNDING_EXTREME_SHORT: score += 0.07; parts.append(f"💰 Funding {funding:.4%} ✅")
    if adx < 25:     score += 0.05; parts.append(f"ADX={adx:.1f} bajo ✅")
    elif adx > 35:   score -= 0.08
    if trend_15m == "UP":   score += 0.07; parts.append("📈 Bias 15m alcista ✅")
    elif trend_15m == "DOWN": score -= 0.12; parts.append("📉 Bias 15m bajista ❌")
    if macro_1h == "DOWN":  score -= 0.10; parts.append("🏔 Macro 1h bajista ❌")
    return min(max(score, 0.0), 1.0), " | ".join(parts)


def _in_session() -> bool:
    hour = datetime.now(timezone.utc).hour
    return any(s <= hour < e for s, e in config.SESSION_HOURS)
