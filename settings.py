"""
Configuration — loads from environment variables (Railway-compatible)
All sensitive keys via env vars, all tuning params here with defaults.
"""

import os
from typing import Any


def env(key: str, default: Any = None, cast=str) -> Any:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return cast(val)
    except Exception:
        return default


def load_config() -> dict:
    return {
        # ── CREDENTIALS (set in Railway/env) ──────────────────────────
        "bingx_api_key":    env("BINGX_API_KEY",    ""),
        "bingx_api_secret": env("BINGX_API_SECRET", ""),
        "telegram_token":   env("TELEGRAM_TOKEN",   ""),
        "telegram_chat_id": env("TELEGRAM_CHAT_ID", ""),

        # ── EXCHANGE ──────────────────────────────────────────────────
        "testnet":    env("TESTNET",  False, lambda x: x.lower() == "true"),
        "leverage":   env("LEVERAGE", 5,  int),
        "auto_trade": env("AUTO_TRADE", False, lambda x: x.lower() == "true"),

        # ── SCANNER ───────────────────────────────────────────────────
        "scan_interval_sec":  env("SCAN_INTERVAL", 30,  int),
        "kline_limit":        250,
        "max_concurrent":     env("MAX_CONCURRENT", 15, int),
        "min_volume_usdt":    env("MIN_VOLUME", 500_000, float),
        "summary_every_scans": 20,
        "blacklist":          ["BTC-USDT", "ETH-USDT"],  # optional: skip majors

        # ── ENGINE — 4 Core Pillars ───────────────────────────────────
        # 1. COMPOSITE SCORE thresholds
        "thr_std":  env("THR_STD",  55, int),
        "thr_fuel": env("THR_FUEL", 68, int),
        "thr_sup":  env("THR_SUP",  80, int),

        # 2. HTF ALIGNMENT
        "htf_min":  env("HTF_MIN", 2, int),   # Min TFs aligned

        # 3. CONVICTION
        "min_score_trade": 55,

        # 4. ASYMMETRY (VAI)
        "asym_window": 10,
        "asym_thr":    1.20,   # 20% larger candle range = institutional

        # ── ENGINE PARAMS ─────────────────────────────────────────────
        "atr_len":      10,
        "adx_len":      14,
        "adx_tend":     25,
        "adx_lat":      20,
        "smo":          3,
        "dlen":         40,
        "w1":           0.40,
        "w2":           0.30,
        "w3":           0.30,
        "rsi_len":      14,
        "oi_len":       20,
        "spl":          5,
        "bpt":          0.18,
        "vol_filter":   True,
        "vol_thr":      0.70,
        "cb_on":        True,
        "cb_mult":      3.0,
        "ent_on":       True,
        "ent_wick":     0.6,
        "sld_on":       True,
        "sld_mult":     1.0,
        "sld_min":      0.5,
        "ptp_on":       True,
        "ptp_mult":     0.5,

        # ── RISK MANAGEMENT ───────────────────────────────────────────
        "capital":            env("CAPITAL", 1000.0, float),
        "risk_pct":           env("RISK_PCT", 1.0,   float),
        "max_pos_pct":        env("MAX_POS_PCT", 0.05, float),  # 5% per trade
        "max_open_positions": env("MAX_POSITIONS", 5, int),
        "max_daily_loss_pct": env("MAX_DAILY_LOSS", 3.0, float),
        "max_daily_trades":   env("MAX_DAILY_TRADES", 20, int),
        "min_pos_size":       0.001,
        "min_rr":             1.3,
        "tp1_mult":           1.5,
        "tp2_mult":           3.0,

        # ── KELLY ─────────────────────────────────────────────────────
        "kel_win":   env("KEL_WIN",  0.55, float),
        "kel_rr":    env("KEL_RR",   1.8,  float),
        "kel_frac":  env("KEL_FRAC", 0.25, float),

        # ── AUTO TRADE QUALITY GATE ───────────────────────────────────
        # Only auto-trade signals at or above this level: STD / FUEL / SUP
        "min_signal_autotrade": env("MIN_SIGNAL", "FUEL"),
    }
