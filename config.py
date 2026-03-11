"""
config.py — SMC Bot BingX v2.0
$10 fijos por operación + reinversión de ganancias
"""
import os

VERSION = "SMC-Bot v2.0 [ALL-PAIRS + COMPOUNDING]"

# ── API KEYS ──────────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")

# ── TELEGRAM ──────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── MODO ──────────────────────────────────────────────────────
MODO_DEMO    = os.getenv("MODO_DEMO",    "false").lower() == "true"
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))

# ── INVERSIÓN FIJA + COMPOUNDING ──────────────────────────────
# Cantidad FIJA por trade en USDT
TRADE_USDT_BASE = float(os.getenv("TRADE_USDT_BASE", "10.0"))   # $10 fijos
TRADE_USDT_MAX  = float(os.getenv("TRADE_USDT_MAX",  "50.0"))   # máximo $50 (con compounding)
# Cada $50 de ganancia acumulada → +$1 al trade size
COMPOUND_STEP_USDT = float(os.getenv("COMPOUND_STEP_USDT", "50.0"))
COMPOUND_ADD_USDT  = float(os.getenv("COMPOUND_ADD_USDT",  "1.0"))

# ── APALANCAMIENTO Y POSICIONES ───────────────────────────────
LEVERAGE       = int(os.getenv("LEVERAGE",       "10"))
MAX_POSICIONES = int(os.getenv("MAX_POSICIONES", "5"))   # más pares = más posiciones

# ── TP / SL (multiplicadores ATR) ────────────────────────────
TP_ATR_MULT      = float(os.getenv("TP_ATR_MULT",      "2.0"))
SL_ATR_MULT      = float(os.getenv("SL_ATR_MULT",      "1.0"))
PARTIAL_TP1_MULT = float(os.getenv("PARTIAL_TP1_MULT",  "1.0"))
PARTIAL_TP_ACTIVO = os.getenv("PARTIAL_TP_ACTIVO", "true").lower() == "true"

# ── TRAILING STOP ─────────────────────────────────────────────
TRAILING_ACTIVO    = os.getenv("TRAILING_ACTIVO",    "true").lower() == "true"
TRAILING_ACTIVAR   = float(os.getenv("TRAILING_ACTIVAR",   "1.5"))
TRAILING_DISTANCIA = float(os.getenv("TRAILING_DISTANCIA", "1.0"))

# ── TIME EXIT ─────────────────────────────────────────────────
TIME_EXIT_HORAS = float(os.getenv("TIME_EXIT_HORAS", "8"))

# ── PÉRDIDA MÁXIMA DIARIA ─────────────────────────────────────
MAX_PERDIDA_DIA = float(os.getenv("MAX_PERDIDA_DIA", "30.0"))  # $30/día máx

# ── SEÑALES SMC ───────────────────────────────────────────────
SCORE_MIN        = int(os.getenv("SCORE_MIN", "4"))
FVG_MIN_PIPS     = float(os.getenv("FVG_MIN_PIPS", "0.0"))
EQ_LOOKBACK      = int(os.getenv("EQ_LOOKBACK",   "50"))
EQ_THRESHOLD     = float(os.getenv("EQ_THRESHOLD", "0.1"))
EQ_PIVOT_LEN     = int(os.getenv("EQ_PIVOT_LEN",  "5"))

# ── KILLZONES UTC ─────────────────────────────────────────────
KZ_ASIA_START   = int(os.getenv("KZ_ASIA_START",   "0"))
KZ_ASIA_END     = int(os.getenv("KZ_ASIA_END",     "240"))
KZ_LONDON_START = int(os.getenv("KZ_LONDON_START", "420"))
KZ_LONDON_END   = int(os.getenv("KZ_LONDON_END",   "600"))
KZ_NY_START     = int(os.getenv("KZ_NY_START",     "780"))
KZ_NY_END       = int(os.getenv("KZ_NY_END",       "960"))

# ── FILTROS TÉCNICOS ─────────────────────────────────────────
EMA_FAST       = int(os.getenv("EMA_FAST",     "21"))
EMA_SLOW       = int(os.getenv("EMA_SLOW",     "50"))
RSI_PERIOD     = int(os.getenv("RSI_PERIOD",   "14"))
RSI_BUY_MAX    = float(os.getenv("RSI_BUY_MAX",  "55"))
RSI_SELL_MIN   = float(os.getenv("RSI_SELL_MIN", "45"))
ATR_PERIOD     = int(os.getenv("ATR_PERIOD",   "14"))
PIVOT_NEAR_PCT = float(os.getenv("PIVOT_NEAR_PCT", "0.20"))

# ── TIMEFRAME ─────────────────────────────────────────────────
TIMEFRAME      = os.getenv("TIMEFRAME",      "5m")
CANDLES_LIMIT  = int(os.getenv("CANDLES_LIMIT", "200"))

# ── ESCÁNER DE PARES ─────────────────────────────────────────
# Volumen mínimo 24h para incluir un par (USDT)
VOLUMEN_MIN_24H = float(os.getenv("VOLUMEN_MIN_24H", "500000"))
# Máximo de pares a escanear por ciclo (0 = todos)
MAX_PARES_SCAN  = int(os.getenv("MAX_PARES_SCAN", "0"))

# ── SOLO LONG ────────────────────────────────────────────────
SOLO_LONG = os.getenv("SOLO_LONG", "false").lower() == "true"

# ── PARES BLOQUEADOS / PRIORITARIOS ──────────────────────────
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",   "").split(",") if p.strip()]
PARES_PRIORITARIOS = [p.strip() for p in os.getenv("PARES_PRIORITARIOS", "").split(",") if p.strip()]

# ── WORKERS PARA ANÁLISIS PARALELO ───────────────────────────
ANALISIS_WORKERS = int(os.getenv("ANALISIS_WORKERS", "8"))

def validar():
    errores = []
    if not MODO_DEMO:
        if not BINGX_API_KEY:    errores.append("BINGX_API_KEY no configurada")
        if not BINGX_SECRET_KEY: errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:       errores.append("TELEGRAM_TOKEN no configurada")
    if LEVERAGE < 1 or LEVERAGE > 125:
        errores.append(f"LEVERAGE={LEVERAGE} fuera de rango (1-125)")
    if TRADE_USDT_BASE < 1:
        errores.append(f"TRADE_USDT_BASE={TRADE_USDT_BASE} demasiado bajo (mín $1)")
    return errores
