import os

# ══════════════════════════════════════════════════════
# config.py — PARÁMETROS DEL BOT v12.3
# ══════════════════════════════════════════════════════

# ── Indicadores ────────────────────────────────────────
BB_PERIOD      = 20
BB_SIGMA       = 2.0
RSI_PERIOD     = 14
RSI_LONG       = 32
RSI_SHORT      = 68
PARTIAL_TP_ATR = 2.5
SMA_PERIOD     = 50

# ── Gestión de riesgo básica ───────────────────────────
LEVERAGE       = int(os.getenv("LEVERAGE",   2))
RISK_PCT       = float(os.getenv("RISK_PCT", 0.02))
INITIAL_BAL    = float(os.getenv("INITIAL_BAL", 100.0))
MIN_RR         = 1.2
SL_BUFFER      = 0.001
SCORE_MIN      = 45
COOLDOWN_BARS  = 3

# ── Gestión de riesgo avanzada ─────────────────────────
MAX_DAILY_LOSS_PCT   = 0.05   # pausa si pierde >5% del balance en el día
MAX_DRAWDOWN_PCT     = 0.12   # pausa si drawdown desde máximo >12%
MAX_CONCURRENT_POS   = 4      # máximo posiciones abiertas simultáneas
ATR_SIZING           = True   # sizing dinámico basado en volatilidad ATR
ATR_SIZING_BASE      = 0.02   # riesgo base para sizing (2%)
CIRCUIT_BREAKER_LOSS = 3      # tras N pérdidas seguidas → reducir size 50%

# ── Trailing SL dinámico ───────────────────────────────
TRAIL_ATR_MULT_INIT  = 2.0    # ATR multiplicador trailing antes partial TP
TRAIL_ATR_MULT_AFTER = 1.5    # ATR multiplicador trailing después partial TP
TRAIL_FROM_START     = True   # activar trailing desde apertura (no solo post-TP)

# ── Re-entry ───────────────────────────────────────────
REENTRY_ENABLED   = True   # re-entrar en el mismo par tras SL si señal sigue
REENTRY_COOLDOWN  = 2      # horas de espera antes de re-entrar
REENTRY_SCORE_MIN = 60     # score mínimo más alto para re-entry

# ── Filtro de volumen ──────────────────────────────────
VOLUME_FILTER     = True   # activar filtro
VOLUME_MA_PERIOD  = 20     # periodo media de volumen
VOLUME_MIN_RATIO  = 0.8    # volumen actual >= 80% de la media para operar

# ── Multi-timeframe ────────────────────────────────────
MTF_ENABLED       = True   # confirmar señal 1h con tendencia 4h
MTF_INTERVAL      = "4h"   # timeframe de confirmación
MTF_BLOCK_COUNTER = True   # bloquear LONG si 4h bajista y viceversa

# ── Tendencia 1h ──────────────────────────────────────
TREND_LOOKBACK = 10
TREND_THRESH   = 0.05

# ── TOP 15 PARES backtested WR>=50% PF>=1.2 ───────────
SYMBOLS = [
    "RSR-USDT",            # WR:100% PF:999 $+0.83
    "NCSKGME2USD-USDT",    # WR:100% PF:999 $+0.31
    "LINK-USDT",           # WR: 67% PF:16  $+0.36
    "DEEP-USDT",           # WR: 67% PF:8.6 $+0.33
    "BLESS-USDT",          # WR: 67% PF:8.5 $+0.29
    "ZEC-USDT",            # WR: 67% PF:7.3 $+0.37
    "VANRY-USDT",          # WR: 67% PF:4.7 $+0.25
    "PROVE-USDT",          # WR: 50% PF:4.1 $+0.19
    "AKE-USDT",            # WR: 50% PF:3.8 $+0.43
    "BOME-USDT",           # WR: 50% PF:3.6 $+0.20
    "BMT-USDT",            # WR: 60% PF:3.6 $+0.17
    "ZEN-USDT",            # WR: 50% PF:2.7 $+0.25
    "SUSHI-USDT",          # WR: 67% PF:2.6 $+0.11
    "SQD-USDT",            # WR: 50% PF:2.3 $+0.11
    "CRO-USDT",            # WR: 67% PF:2.2 $+0.07
]

# ── Versión ────────────────────────────────────────────
VERSION = "v12.3"

# ── Credenciales ──────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Modo de operación ─────────────────────────────────
TRADE_MODE    = os.getenv("TRADE_MODE", "paper")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 3600))

# ── Dashboard web ─────────────────────────────────────
DASHBOARD_PORT    = int(os.getenv("PORT", 8080))
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
