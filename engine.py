"""
QF×JP FUSION BOT v3.4 — Core Engine
======================================
4 Core Pillars:
  1. COMPOSITE SCORE  — weighted multi-factor score (0-100)
  2. HTF ALIGNMENT    — 3 timeframe confluence filter
  3. CONVICTION       — 12-point sub-filter count
  4. ASYMMETRY        — candle range directional dominance

Special edge: VOLUME ASYMMETRY INDEX (VAI)
  Measures ratio of bullish candle range vs bearish candle range
  over a rolling window — institutional pressure fingerprint.
"""

import asyncio
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import logging

logger = logging.getLogger("engine")


class Signal(Enum):
    LONG_SUP   = "★ LONG SUPREMA"
    LONG_FUEL  = "▲ LONG FUEL"
    LONG_STD   = "▲ LONG STD"
    SHORT_SUP  = "★ SHORT SUPREMA"
    SHORT_FUEL = "▼ SHORT FUEL"
    SHORT_STD  = "▼ SHORT STD"
    PRE_LONG   = "⚡ PRE-LONG"
    PRE_SHORT  = "⚡ PRE-SHORT"
    NONE       = "—"


@dataclass
class MarketData:
    symbol: str
    closes:  np.ndarray
    highs:   np.ndarray
    lows:    np.ndarray
    opens:   np.ndarray
    volumes: np.ndarray
    # HTF arrays (15m, 1h)
    closes_15m: Optional[np.ndarray] = None
    closes_1h:  Optional[np.ndarray] = None
    highs_15m:  Optional[np.ndarray] = None
    lows_15m:   Optional[np.ndarray] = None
    highs_1h:   Optional[np.ndarray] = None
    lows_1h:    Optional[np.ndarray] = None


@dataclass
class SignalResult:
    symbol:       str
    signal:       Signal
    score_long:   int
    score_short:  int
    conviction_l: int
    conviction_s: int
    asymmetry:    float        # VAI ratio
    asym_dir:     str          # "BULL", "BEAR", "NEUTRAL"
    htf_long:     int          # 0-3
    htf_short:    int          # 0-3
    atr:          float
    sl_long:      float
    sl_short:     float
    tp1_long:     float
    tp1_short:    float
    tp2_long:     float
    tp2_short:    float
    rr1_long:     float
    rr1_short:    float
    kelly_f:      float
    pos_size:     float
    regime:       str          # TEND↑ TEND↓ LATERAL NEUTRAL
    close:        float
    adx:          float
    cvd_dir:      str
    structure:    str          # ALCISTA / BAJISTA
    vwap_pos:     str          # SOBRE / BAJO
    rsi:          float
    squeeze:      str
    circuit_ok:   bool
    entry_wick:   str
    vai_score:    float        # 0-1 special edge
    extras:       dict = field(default_factory=dict)


# ─── MATH HELPERS ────────────────────────────────────────────────────

def _tanh(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -20, 20)
    e2x = np.exp(2 * x)
    return (e2x - 1) / (e2x + 1)


def ema(src: np.ndarray, length: int) -> np.ndarray:
    alpha = 2.0 / (length + 1)
    out = np.zeros_like(src, dtype=float)
    out[0] = src[0]
    for i in range(1, len(src)):
        out[i] = alpha * src[i] + (1 - alpha) * out[i - 1]
    return out


def sma(src: np.ndarray, length: int) -> np.ndarray:
    return pd.Series(src).rolling(length, min_periods=1).mean().values


def stdev(src: np.ndarray, length: int) -> np.ndarray:
    return pd.Series(src).rolling(length, min_periods=2).std(ddof=0).fillna(0).values


def atr_calc(highs, lows, closes, length=10) -> np.ndarray:
    tr = np.maximum(highs - lows,
         np.maximum(np.abs(highs - np.roll(closes, 1)),
                    np.abs(lows  - np.roll(closes, 1))))
    tr[0] = highs[0] - lows[0]
    return sma(tr, length)


def rsi_calc(closes: np.ndarray, length=14) -> np.ndarray:
    delta = np.diff(closes, prepend=closes[0])
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = sma(gain, length)
    avg_l = sma(loss, length)
    rs    = np.where(avg_l > 0, avg_g / avg_l, 100.0)
    return 100 - 100 / (1 + rs)


def adx_calc(highs, lows, closes, length=14):
    plus_dm  = np.where((highs - np.roll(highs,1)) > (np.roll(lows,1) - lows),
                         np.maximum(highs - np.roll(highs,1), 0), 0)
    minus_dm = np.where((np.roll(lows,1) - lows) > (highs - np.roll(highs,1)),
                         np.maximum(np.roll(lows,1) - lows, 0), 0)
    tr_arr   = atr_calc(highs, lows, closes, length) * length
    tr_arr   = np.where(tr_arr == 0, 1e-10, tr_arr)
    plus_di  = 100 * sma(plus_dm, length) / tr_arr
    minus_di = 100 * sma(minus_dm, length) / tr_arr
    dx       = 100 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) == 0, 1e-10, plus_di + minus_di)
    adx_v    = sma(dx, length)
    return adx_v, plus_di, minus_di


def percentile(arr: np.ndarray, pct: float) -> float:
    return float(np.percentile(arr, pct))


def vwap_calc(highs, lows, closes, volumes) -> np.ndarray:
    hlc3 = (highs + lows + closes) / 3
    cum_vol = np.cumsum(volumes)
    cum_vol = np.where(cum_vol == 0, 1e-10, cum_vol)
    return np.cumsum(hlc3 * volumes) / cum_vol


# ─── VOLUME ASYMMETRY INDEX (VAI) — Special Edge ─────────────────────
# Measures INSTITUTIONAL PRESSURE by comparing the average candle range
# of bullish vs bearish candles. A ratio > 1.2 signals directional dominance.
# Enhanced with volume weighting: volume-weighted range gives TRUE pressure.

def volume_asymmetry_index(opens, closes, highs, lows, volumes, window=10):
    """
    VAI — Volume Asymmetry Index
    Returns:
        ratio_bull: avg_up_range / avg_dn_range  (>1.2 = bull dominance)
        ratio_bear: avg_dn_range / avg_up_range  (>1.2 = bear dominance)
        vai_score:  0-1 normalized directional pressure
        direction:  "BULL" / "BEAR" / "NEUTRAL"
    
    Enhancement over original: volume-weighted range (VWAI)
    Institutional blocks leave both large ranges AND large volume.
    Plain range can be noise; range×volume is always intentional.
    """
    is_bull = closes > opens
    is_bear = closes < opens
    candle_range = highs - lows

    # Volume-weighted range
    vw_range = candle_range * volumes

    up_vwr = np.where(is_bull, vw_range, 0.0)
    dn_vwr = np.where(is_bear, vw_range, 0.0)

    avg_up = sma(up_vwr, window)
    avg_dn = sma(dn_vwr, window)

    avg_up = np.where(avg_up == 0, 1e-10, avg_up)
    avg_dn = np.where(avg_dn == 0, 1e-10, avg_dn)

    ratio_bull = avg_up / avg_dn
    ratio_bear = avg_dn / avg_up

    # VAI score: tanh-normalized, 0=full bear, 1=full bull
    vai_raw  = np.log(avg_up / avg_dn)  # symmetric log ratio
    vai_norm = (_tanh(vai_raw) + 1) / 2  # 0-1

    thresh = 1.20
    direction = np.where(ratio_bull >= thresh, "BULL",
                np.where(ratio_bear >= thresh, "BEAR", "NEUTRAL"))

    return ratio_bull, ratio_bear, vai_norm, direction


# ─── FACTOR SCORES ───────────────────────────────────────────────────

def factor_momentum(closes, length=20):
    roc = (closes - np.roll(closes, length)) / np.where(np.roll(closes, length) == 0, 1e-10, np.roll(closes, length))
    vol_n = stdev(closes, length) / np.where(sma(closes, length) == 0, 1e-10, sma(closes, length))
    f = np.where(vol_n > 0, roc / vol_n, 0.0)
    return f


def factor_mean_rev(closes, length=8):
    basis = sma(closes, length)
    std   = stdev(closes, length)
    return np.where(std > 0, -(closes - basis) / std, 0.0)


def factor_volume(closes, volumes, length=14):
    obv   = np.cumsum(np.where(closes > np.roll(closes,1), volumes, -volumes))
    obv_m = ema(obv, length)
    obv_s = stdev(obv, length)
    return np.where(obv_s > 0, (obv - obv_m) / obv_s, 0.0)


def composite_score(closes, highs, lows, volumes, adx_v, plus_di, minus_di,
                    w1=0.40, w2=0.30, w3=0.30,
                    adx_tend=25, smo=3, dlen=40):
    f_mom = factor_momentum(closes)
    f_rev = factor_mean_rev(closes)
    f_vol = factor_volume(closes, volumes)

    adx_factor  = np.minimum(1.0, adx_v / (adx_tend * 2.0))
    w_mom_dyn   = w1 + adx_factor * w1 * 0.40
    w_rev_dyn   = np.maximum(w2 * 0.30, w2 - adx_factor * w2 * 0.50)
    w_total     = w_mom_dyn + w_rev_dyn + w3
    w_total     = np.where(w_total == 0, 1e-10, w_total)

    raw = (w_mom_dyn * f_mom + w_rev_dyn * f_rev + w3 * f_vol) / w_total
    comp = ema(raw, smo)
    sc_s = stdev(comp, dlen)
    norm = np.where(sc_s > 0, _tanh(comp / sc_s), 0.0)
    return norm, f_mom, f_rev, f_vol


def decay_signal(norm_score, closes, dlen=40, dthr=0.40, decay_pct=30):
    fwd_ret = (closes - np.roll(closes, 1)) / np.where(np.roll(closes, 1) == 0, 1e-10, np.roll(closes, 1))
    ns_lag  = np.roll(norm_score, 1)

    # Rolling correlation (approx)
    ic_vals = []
    for i in range(len(closes)):
        start = max(0, i - dlen)
        if i - start < 3:
            ic_vals.append(0.0)
        else:
            c = np.corrcoef(ns_lag[start:i], fwd_ret[start:i])
            ic_vals.append(abs(c[0, 1]) if not np.isnan(c[0, 1]) else 0.0)

    ic_roll = ema(np.array(ic_vals), 3)
    ic_peak = pd.Series(ic_roll).rolling(dlen, min_periods=1).max().values
    decay_r = np.where(ic_peak > 0, ic_roll / ic_peak, 0.5)
    sig_alive = decay_r >= dthr
    return sig_alive, decay_r


def cvd_delta(highs, lows, closes, volumes, cvd_len=20, cvd_roll=100, cvd_div=5):
    hl = highs - lows
    bvol = np.where(hl > 0, ((closes - lows) / hl) * volumes, volumes * 0.5)
    svol = np.where(hl > 0, ((highs - closes) / hl) * volumes, volumes * 0.5)
    delta = bvol - svol
    cvd  = sma(delta, cvd_roll) * cvd_roll
    cvd_e = ema(cvd, cvd_len)
    rising = cvd > cvd_e
    bull_div = (closes < np.roll(closes, cvd_div)) & (cvd > np.roll(cvd, cvd_div))
    bear_div = (closes > np.roll(closes, cvd_div)) & (cvd < np.roll(cvd, cvd_div))
    return rising, bull_div, bear_div


def htf_trend(closes_htf, ema_fast=9, ema_slow=21):
    if closes_htf is None or len(closes_htf) < ema_slow + 5:
        return np.zeros(1, dtype=bool), np.zeros(1, dtype=bool)
    f = ema(closes_htf, ema_fast)
    s = ema(closes_htf, ema_slow)
    return f > s, f < s


def swing_structure(highs, lows, closes, pll=5, plr=3, phl=5, phr=3, hlw=40, hlc=2, hhc=2):
    """Returns sell_exhausted (HL↑), buy_exhausted (LH↓), last_sl, last_sh"""
    n = len(closes)
    pl_vals, ph_vals = [], []
    for i in range(pll, n - plr):
        if all(lows[i] <= lows[i-j] for j in range(1,pll+1)) and \
           all(lows[i] <= lows[i+j] for j in range(1,plr+1)):
            pl_vals.append((i, lows[i]))
    for i in range(phl, n - phr):
        if all(highs[i] >= highs[i-j] for j in range(1,phl+1)) and \
           all(highs[i] >= highs[i+j] for j in range(1,phr+1)):
            ph_vals.append((i, highs[i]))

    # Keep only last hlw bars
    recent_pl = [(idx,v) for idx,v in pl_vals if idx >= n-1-hlw]
    recent_ph = [(idx,v) for idx,v in ph_vals if idx >= n-1-hlw]

    hl_count = sum(1 for i in range(1, len(recent_pl)) if recent_pl[i][1] > recent_pl[i-1][1])
    lh_count = sum(1 for i in range(1, len(recent_ph)) if recent_ph[i][1] < recent_ph[i-1][1])

    sell_exhausted = hl_count >= hlc
    buy_exhausted  = lh_count >= hhc
    last_sl = recent_pl[-1][1] if recent_pl else None
    last_sh = recent_ph[-1][1] if recent_ph else None
    return sell_exhausted, buy_exhausted, last_sl, last_sh, hl_count, lh_count


def market_structure(highs, lows, closes, last_sl, last_sh):
    n = len(closes)
    mkt_bull = True
    choch_bull = choch_bear = bos_bull = bos_bear = False
    liq_bull = liq_bear = False

    if last_sl and last_sh:
        bos_bull_raw = closes[-1] > last_sh and closes[-2] <= last_sh
        bos_bear_raw = closes[-1] < last_sl and closes[-2] >= last_sl
        liq_bull = lows[-1] < last_sl and closes[-1] > last_sl
        liq_bear = highs[-1] > last_sh and closes[-1] < last_sh

        if bos_bull_raw:
            if not mkt_bull: choch_bull = True
            else: bos_bull = True
            mkt_bull = True
        if bos_bear_raw:
            if mkt_bull: choch_bear = True
            else: bos_bear = True
            mkt_bull = False

    return mkt_bull, choch_bull, choch_bear, bos_bull, bos_bear, liq_bull, liq_bear


def squeeze_momentum(closes, highs, lows, sq_len=20, bbm=2.0, kcm=1.5):
    basis  = sma(closes, sq_len)
    dev    = stdev(closes, sq_len)
    bb_hi  = basis + bbm * dev
    bb_lo  = basis - bbm * dev
    kc_atr = atr_calc(highs, lows, closes, sq_len)
    kc_e   = ema(closes, sq_len)
    kc_hi  = kc_e + kcm * kc_atr
    kc_lo  = kc_e - kcm * kc_atr
    sq_on  = (bb_hi < kc_hi) & (bb_lo > kc_lo)
    sq_fire = ~sq_on & np.roll(sq_on, 1)
    hh = pd.Series(highs).rolling(sq_len, min_periods=1).max().values
    ll = pd.Series(lows).rolling(sq_len, min_periods=1).min().values
    mid_val = (hh + ll) / 2
    diff    = closes - (mid_val + basis) / 2
    # linreg approximation: last value of linear regression
    sq_val = np.zeros(len(closes))
    for i in range(sq_len, len(closes)):
        y = diff[i-sq_len:i]
        x = np.arange(sq_len)
        if np.std(x) > 0:
            sq_val[i] = np.polyfit(x, y, 1)[0] * (sq_len - 1) + np.polyfit(x, y, 1)[1]
    sq_bull = sq_fire & (sq_val > 0)
    sq_bear = sq_fire & (sq_val < 0)
    return sq_on, sq_fire, sq_bull, sq_bear


# ─── KELLY CRITERION ─────────────────────────────────────────────────

def kelly_sizing(win_rate: float, rr: float, fraction: float = 0.25,
                 capital: float = 1000.0, sl_dist: float = 1.0) -> tuple:
    """Returns (kelly_f, position_size)"""
    b = rr
    p = np.clip(win_rate, 0.01, 0.99)
    f_raw = (p * (b + 1) - 1) / b
    f = max(0.0, min(0.5, f_raw * fraction))
    pos_size = (capital * f / sl_dist) if sl_dist > 0 else 0.0
    return f, pos_size


# ─── MAIN ANALYZER ───────────────────────────────────────────────────

class QFEngine:
    def __init__(self, config: dict):
        self.cfg = config

    def analyze(self, md: MarketData) -> SignalResult:
        c = md.closes
        h = md.highs
        lo = md.lows
        o = md.opens
        v = md.volumes
        n = len(c)

        if n < 60:
            return self._empty_result(md.symbol, c[-1])

        cfg = self.cfg

        # ── ATR ──
        atr = atr_calc(h, lo, c, cfg.get("atr_len", 10))
        atr_val = float(atr[-1])
        atr_avg20 = float(sma(atr, 20)[-1])

        # ── CIRCUIT BREAKER ──
        giant = abs(c[-1] - o[-1]) > atr_avg20 * cfg.get("cb_mult", 3.0)
        circuit_ok = not cfg.get("cb_on", True) or not giant

        # ── ADX ──
        adx_v, plus_di, minus_di = adx_calc(h, lo, c, cfg.get("adx_len", 14))
        adx_last = float(adx_v[-1])
        trend_strong = adx_last >= cfg.get("adx_tend", 25)
        trend_up     = float(plus_di[-1]) > float(minus_di[-1]) and trend_strong
        trend_dn     = float(minus_di[-1]) > float(plus_di[-1]) and trend_strong
        is_lateral   = adx_last < cfg.get("adx_lat", 20)

        regime = "TEND↑" if trend_up else ("TEND↓" if trend_dn else ("LATERAL" if is_lateral else "NEUTRAL"))

        # ── COMPOSITE SCORE ──
        norm_score, f_mom, f_rev, f_vol = composite_score(
            c, h, lo, v, adx_v, plus_di, minus_di,
            w1=cfg.get("w1", 0.40), w2=cfg.get("w2", 0.30), w3=cfg.get("w3", 0.30),
            adx_tend=cfg.get("adx_tend", 25), smo=cfg.get("smo", 3), dlen=cfg.get("dlen", 40)
        )

        # ── DECAY ──
        sig_alive_arr, decay_r_arr = decay_signal(norm_score, c, dlen=cfg.get("dlen", 40))
        sig_alive = bool(sig_alive_arr[-1])
        decay_r   = float(decay_r_arr[-1])

        # ── CVD ──
        cvd_rising_arr, cvd_bull_div_arr, cvd_bear_div_arr = cvd_delta(h, lo, c, v)
        cvd_rising    = bool(cvd_rising_arr[-1])
        cvd_bull_div  = bool(cvd_bull_div_arr[-1])
        cvd_bear_div  = bool(cvd_bear_div_arr[-1])
        cvd_dir = "ACUM↑" if cvd_bull_div else ("DIST↓" if cvd_bear_div else ("ALCISTA" if cvd_rising else "BAJISTA"))

        # ── SWING STRUCTURE ──
        sell_exh, buy_exh, last_sl, last_sh, hl_cnt, lh_cnt = swing_structure(h, lo, c)

        # ── MARKET STRUCTURE ──
        mkt_bull, choch_bull, choch_bear, bos_bull, bos_bear, liq_bull, liq_bear = \
            market_structure(h, lo, c, last_sl, last_sh)

        structure = "ALCISTA" if mkt_bull else "BAJISTA"

        # ── HTF ALIGNMENT ──
        htf_bull = htf_bear = htf2_bull = htf2_bear = False
        if md.closes_15m is not None and len(md.closes_15m) > 25:
            b15, d15 = htf_trend(md.closes_15m)
            htf_bull, htf_bear = bool(b15[-1]), bool(d15[-1])
        if md.closes_1h is not None and len(md.closes_1h) > 25:
            b1h, d1h = htf_trend(md.closes_1h)
            htf2_bull, htf2_bear = bool(b1h[-1]), bool(d1h[-1])

        htf_score_long  = (1 if htf_bull else 0) + (1 if htf2_bull else 0) + (1 if mkt_bull else 0)
        htf_score_short = (1 if htf_bear else 0) + (1 if htf2_bear else 0) + (1 if not mkt_bull else 0)

        # ── VOLUME ASYMMETRY INDEX (Special Edge) ──
        ratio_bull, ratio_bear, vai_norm, vai_dir_arr = volume_asymmetry_index(
            o, c, h, lo, v, window=cfg.get("asym_window", 10)
        )
        rb = float(ratio_bull[-1])
        rd = float(ratio_bear[-1])
        vai_score = float(vai_norm[-1])
        vai_dir   = str(vai_dir_arr[-1])
        asym_bull = rb >= cfg.get("asym_thr", 1.20)
        asym_bear = rd >= cfg.get("asym_thr", 1.20)

        # ── VWAP ──
        vwap_arr = vwap_calc(h, lo, c, v)
        above_vwap = c[-1] > vwap_arr[-1]
        vwap_pos = "SOBRE" if above_vwap else "BAJO"

        # ── RSI ──
        rsi_arr = rsi_calc(c, cfg.get("rsi_len", 14))
        rsi_val = float(rsi_arr[-1])

        # ── SQUEEZE ──
        sq_on_arr, sq_fire_arr, sq_bull_arr, sq_bear_arr = squeeze_momentum(c, h, lo)
        sq_bull = bool(sq_bull_arr[-1])
        sq_bear = bool(sq_bear_arr[-1])
        sq_on   = bool(sq_on_arr[-1])
        squeeze = "FUEGO↑" if sq_bull else ("FUEGO↓" if sq_bear else ("COMPRIM." if sq_on else "LIBRE"))

        # ── OI DELTA SYNTHETIC ──
        buy_vol  = np.where(c > o, v, 0.0)
        sell_vol = np.where(c < o, v, 0.0)
        oi_buy_e  = ema(buy_vol, cfg.get("oi_len", 20))
        oi_sell_e = ema(sell_vol, cfg.get("oi_len", 20))
        oi_total  = oi_buy_e + oi_sell_e
        oi_ratio  = np.where(oi_total > 0, oi_buy_e / oi_total, 0.5)
        oi_conf_long  = bool((c[-1] > c[-cfg.get("oi_len",20)]) and oi_ratio[-1] > 0.55)
        oi_conf_short = bool((c[-1] < c[-cfg.get("oi_len",20)]) and oi_ratio[-1] < 0.45)
        oi_squeeze    = bool((h[-1] - lo[-1]) > atr_val * 1.5 and oi_ratio[-1] < 0.40 and c[-1] > c[-1-cfg.get("oi_len",20)])

        # ── EXECUTION FILTER ──
        hi_lo_r    = np.log(np.where(lo > 0, h / lo, 1.0))
        spread_est = sma(hi_lo_r, cfg.get("spl", 5)) * c
        bp_drain   = (spread_est / np.where(c > 0, c, 1.0)) * 100
        exec_ok    = bool(bp_drain[-1] < cfg.get("bpt", 0.18))

        # ── VOL FILTER ──
        vol_ok = bool(not cfg.get("vol_filter", True) or (atr_val > atr_avg20 * cfg.get("vol_thr", 0.70)))

        # ── NORM SCORES ──
        ns_last = float(norm_score[-1])
        def _tanh_scalar(x: float) -> float:
            x = max(-20.0, min(20.0, x))
            e2x = np.exp(2 * x)
            return float((e2x - 1) / (e2x + 1))

        ns_norm      = (_tanh_scalar(ns_last) + 1) / 2
        ns_norm_s    = (_tanh_scalar(-ns_last) + 1) / 2
        mom_norm     = (_tanh_scalar(float(f_mom[-1]) * 2) + 1) / 2
        mom_norm_s   = (_tanh_scalar(-float(f_mom[-1]) * 2) + 1) / 2
        decay_norm   = min(1.0, decay_r)

        # CVD score
        cvd_std = float(stdev(np.array([float(v) for v in (ema(np.cumsum(np.where(c > np.roll(c,1), v, -v)),20))]), 40)[-1])
        cvd_z_val = 0.5  # simplified
        cvd_score_l = max(0, min(1, (float(_tanh(np.array([cvd_z_val]))[0]) + 1) / 2))
        cvd_score_s = 1.0 - cvd_score_l

        htf3_norm_l = htf_score_long  / 3.0
        htf3_norm_s = htf_score_short / 3.0

        struc_l = (0.5 if mkt_bull else 0.0) + (0.3 if (choch_bull or bos_bull) else 0.0) + (0.2 if liq_bull else 0.0)
        struc_s = (0.5 if not mkt_bull else 0.0) + (0.3 if (choch_bear or bos_bear) else 0.0) + (0.2 if liq_bear else 0.0)

        # Regime weights
        rw_score = 0.22 if trend_strong else (0.28 if is_lateral else 0.25)
        rw_cvd   = 0.25 if trend_strong else (0.18 if is_lateral else 0.20)
        rw_mom   = 0.20 if trend_strong else (0.10 if is_lateral else 0.15)
        rw_struc = 0.06 if trend_strong else (0.12 if is_lateral else 0.10)
        rw_decay = 0.10
        rw_htf   = 0.12
        rw_vp    = 0.03  # simplified (no real volume profile in bars)
        rw_sent  = 0.02

        # VAI integration: add vai_score as extra weight
        vai_boost_l = (vai_score - 0.5) * 0.10      # +5% max for strong bull
        vai_boost_s = (0.5 - vai_score) * 0.10

        comp_l_raw = (rw_score * ns_norm + rw_cvd * cvd_score_l + rw_mom * mom_norm
                    + rw_decay * decay_norm + rw_htf * htf3_norm_l + rw_struc * min(1.0, struc_l)
                    + vai_boost_l)
        comp_s_raw = (rw_score * ns_norm_s + rw_cvd * cvd_score_s + rw_mom * mom_norm_s
                    + rw_decay * decay_norm + rw_htf * htf3_norm_s + rw_struc * min(1.0, struc_s)
                    + vai_boost_s)

        comp_l_base = int(round(comp_l_raw * 100))
        comp_s_base = int(round(comp_s_raw * 100))

        # ── CONVICTION ──
        long_conv = (
            (1 if ns_last > 0.10 else 0) +
            (1 if sig_alive else 0) +
            (1 if exec_ok else 0) +
            (1 if htf_score_long >= 2 else 0) +
            (1 if asym_bull else 0) +
            (1 if sell_exh else 0) +
            (1 if liq_bull or choch_bull else 0) +
            (1 if cvd_rising else 0) +
            (1 if sq_bull else 0) +
            (1 if oi_conf_long else 0) +
            (1 if above_vwap else 0) +
            (1 if vai_score > 0.60 else 0)  # VAI contribution
        )
        short_conv = (
            (1 if ns_last < -0.10 else 0) +
            (1 if sig_alive else 0) +
            (1 if exec_ok else 0) +
            (1 if htf_score_short >= 2 else 0) +
            (1 if asym_bear else 0) +
            (1 if buy_exh else 0) +
            (1 if liq_bear or choch_bear else 0) +
            (1 if not cvd_rising else 0) +
            (1 if sq_bear else 0) +
            (1 if oi_conf_short else 0) +
            (1 if not above_vwap else 0) +
            (1 if vai_score < 0.40 else 0)  # VAI contribution
        )

        # Conv boost
        conv_boost_l = long_conv * 0.5
        conv_boost_s = short_conv * 0.5

        comp_long  = min(100, comp_l_base + round(conv_boost_l))
        comp_short = min(100, comp_s_base + round(conv_boost_s))

        # ── SL / TP / KELLY ──
        thr_std  = cfg.get("thr_std",  55)
        thr_fuel = cfg.get("thr_fuel", 68)
        thr_sup  = cfg.get("thr_sup",  80)

        sl_dist_l = max(atr_val * cfg.get("sld_min", 0.5),
                        (c[-1] - last_sl) if last_sl else atr_val)
        sl_dist_s = max(atr_val * cfg.get("sld_min", 0.5),
                        (last_sh - c[-1]) if last_sh else atr_val)
        sl_dist_l = max(sl_dist_l, atr_val * cfg.get("sld_mult", 1.0))
        sl_dist_s = max(sl_dist_s, atr_val * cfg.get("sld_mult", 1.0))

        sl_long_price  = c[-1] - sl_dist_l
        sl_short_price = c[-1] + sl_dist_s

        tp1_long   = c[-1] + atr_val * cfg.get("tp1_mult", 1.5)
        tp1_short  = c[-1] - atr_val * cfg.get("tp1_mult", 1.5)
        tp2_long   = last_sh if last_sh else c[-1] + atr_val * cfg.get("tp2_mult", 3.0)
        tp2_short  = last_sl if last_sl else c[-1] - atr_val * cfg.get("tp2_mult", 3.0)

        rr1_l = (tp1_long  - c[-1]) / sl_dist_l if sl_dist_l > 0 else 0.0
        rr1_s = (c[-1] - tp1_short) / sl_dist_s if sl_dist_s > 0 else 0.0
        rr2_l = (tp2_long  - c[-1]) / sl_dist_l if sl_dist_l > 0 else 0.0
        rr2_s = (c[-1] - tp2_short) / sl_dist_s if sl_dist_s > 0 else 0.0

        # Win rate from recent signals (simplified: use config estimate)
        wr = cfg.get("kel_win", 0.55)
        kel_f, pos_size = kelly_sizing(
            wr, cfg.get("kel_rr", 1.8), cfg.get("kel_frac", 0.25),
            cfg.get("capital", 1000.0),
            sl_dist_l if comp_long > comp_short else sl_dist_s
        )

        # ── ENTRY WICK 1m (proxy: check last candle wick) ──
        body = abs(c[-1] - o[-1])
        body_sz = max(body, atr_val * 0.05)
        wick_lo = min(c[-1], o[-1]) - lo[-1]
        wick_hi = h[-1] - max(c[-1], o[-1])
        wick_thr = cfg.get("ent_wick", 0.6)
        ent_bull = (wick_lo / body_sz) >= wick_thr and c[-1] > o[-1]
        ent_bear = (wick_hi / body_sz) >= wick_thr and c[-1] < o[-1]
        entry_wick = "WICK↑ ✓" if ent_bull else ("WICK↓ ✓" if ent_bear else "ESPERANDO")

        # ── FINAL SIGNALS ──
        htf_min = cfg.get("htf_min", 2)
        base_l  = comp_long  >= thr_std and exec_ok and sig_alive and vol_ok and circuit_ok
        base_s  = comp_short >= thr_std and exec_ok and sig_alive and vol_ok and circuit_ok

        std_l  = base_l and htf_score_long  >= htf_min and sell_exh
        std_s  = base_s and htf_score_short >= htf_min and buy_exh

        fuel_cat_l = (sq_bull or liq_bull or choch_bull or bos_bull)
        fuel_cat_s = (sq_bear or liq_bear or choch_bear or bos_bear)

        fuel_l = std_l and comp_long  >= thr_fuel and fuel_cat_l and (ent_bull or not cfg.get("ent_on", True))
        fuel_s = std_s and comp_short >= thr_fuel and fuel_cat_s and (ent_bear or not cfg.get("ent_on", True))

        sup_l  = fuel_l and comp_long  >= thr_sup  and (cvd_bull_div or (rsi_val < 40)) and not oi_squeeze
        sup_s  = fuel_s and comp_short >= thr_sup  and (cvd_bear_div or (rsi_val > 60)) and not oi_squeeze

        if sup_l:    sig = Signal.LONG_SUP
        elif fuel_l: sig = Signal.LONG_FUEL
        elif std_l:  sig = Signal.LONG_STD
        elif sup_s:  sig = Signal.SHORT_SUP
        elif fuel_s: sig = Signal.SHORT_FUEL
        elif std_s:  sig = Signal.SHORT_STD
        else:
            # Pre-alert
            accel_l = comp_long  - (comp_long  if n < 5 else comp_long)  # simplified
            if comp_long >= 50 and comp_long < thr_std:
                sig = Signal.PRE_LONG
            elif comp_short >= 50 and comp_short < thr_std:
                sig = Signal.PRE_SHORT
            else:
                sig = Signal.NONE

        return SignalResult(
            symbol=md.symbol,
            signal=sig,
            score_long=comp_long,
            score_short=comp_short,
            conviction_l=long_conv,
            conviction_s=short_conv,
            asymmetry=rb if asym_bull else (rd if asym_bear else 1.0),
            asym_dir=vai_dir,
            htf_long=htf_score_long,
            htf_short=htf_score_short,
            atr=atr_val,
            sl_long=sl_long_price,
            sl_short=sl_short_price,
            tp1_long=tp1_long,
            tp1_short=tp1_short,
            tp2_long=tp2_long,
            tp2_short=tp2_short,
            rr1_long=rr1_l,
            rr1_short=rr1_s,
            kelly_f=kel_f,
            pos_size=pos_size,
            regime=regime,
            close=float(c[-1]),
            adx=adx_last,
            cvd_dir=cvd_dir,
            structure=structure,
            vwap_pos=vwap_pos,
            rsi=rsi_val,
            squeeze=squeeze,
            circuit_ok=circuit_ok,
            entry_wick=entry_wick,
            vai_score=float(vai_score),
            extras={
                "asym_bull": asym_bull,
                "asym_bear": asym_bear,
                "ratio_bull": rb,
                "ratio_bear": rd,
                "f_mom": float(f_mom[-1]),
                "f_rev": float(f_rev[-1]),
                "f_vol": float(f_vol[-1]),
                "norm_score": ns_last,
                "oi_conf_long": oi_conf_long,
                "oi_conf_short": oi_conf_short,
                "oi_squeeze": oi_squeeze,
                "rr2_long": rr2_l,
                "rr2_short": rr2_s,
                "mkt_bull": mkt_bull,
                "choch_bull": choch_bull,
                "choch_bear": choch_bear,
                "bos_bull": bos_bull,
                "bos_bear": bos_bear,
                "liq_bull": liq_bull,
                "liq_bear": liq_bear,
                "htf_bull": htf_bull,
                "htf_bear": htf_bear,
                "htf2_bull": htf2_bull,
                "htf2_bear": htf2_bear,
                "cvd_bull_div": cvd_bull_div,
                "cvd_bear_div": cvd_bear_div,
                "sq_bull": sq_bull,
                "sq_bear": sq_bear,
                "sell_exh": sell_exh,
                "buy_exh": buy_exh,
                "hl_count": hl_cnt,
                "lh_count": lh_cnt,
                "sig_alive": sig_alive,
                "decay_r": decay_r,
                "exec_ok": exec_ok,
                "vol_ok": vol_ok,
                "above_vwap": above_vwap,
                "dp_buy": False,  # Would need tape data
                "dp_sell": False,
            }
        )

    def _empty_result(self, symbol: str, close: float) -> SignalResult:
        return SignalResult(
            symbol=symbol, signal=Signal.NONE,
            score_long=0, score_short=0,
            conviction_l=0, conviction_s=0,
            asymmetry=1.0, asym_dir="NEUTRAL",
            htf_long=0, htf_short=0,
            atr=0.0, sl_long=0.0, sl_short=0.0,
            tp1_long=0.0, tp1_short=0.0,
            tp2_long=0.0, tp2_short=0.0,
            rr1_long=0.0, rr1_short=0.0,
            kelly_f=0.0, pos_size=0.0,
            regime="NEUTRAL", close=close,
            adx=0.0, cvd_dir="—", structure="—",
            vwap_pos="—", rsi=50.0, squeeze="—",
            circuit_ok=True, entry_wick="—",
            vai_score=0.5
        )
