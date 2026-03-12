"""
config.py — SMC Bot BingX v4.0 [REAL MONEY | 24/7 | AUTO-LEARN]
"""
import os

VERSION = "SMC-Bot v4.0 [PRECISION+APRENDE+COMPOUNDING]"

def _int(var, default):
    try:
        return int(os.getenv(var, str(default)).split()[0].split("(")[0].strip())
    except Exception:
        return default

def _float(var, default):
    try:
        return float(os.getenv(var, str(default)).split()[0].split("(")[0].strip())
    except Exception:
        return default

def _bool(var, default):
    raw = os.getenv(var, "true" if default else "false")
    return raw.strip().lower().split()[0] in ("true", "1", "yes")

# ── Credenciales ──────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── General ───────────────────────────────────────────────────
MODO_DEMO    = _bool("MODO_DEMO",    False)   # FALSE = dinero real
LOOP_SECONDS = _int("LOOP_SECONDS",  60)      # ciclo cada 60s (24/7)

# ── Capital y Compounding ─────────────────────────────────────
TRADE_USDT_BASE    = _float("TRADE_USDT_BASE",    10.0)  # $10 base siempre
TRADE_USDT_MAX     = _float("TRADE_USDT_MAX",     50.0)  # máximo $50
COMPOUND_STEP_USDT = _float("COMPOUND_STEP_USDT", 30.0)  # cada $30 ganados
COMPOUND_ADD_USDT  = _float("COMPOUND_ADD_USDT",   1.0)  # añade $1 al trade

# ── Posiciones ────────────────────────────────────────────────
LEVERAGE       = _int("LEVERAGE",       10)   # 10x fijo
MAX_POSICIONES = _int("MAX_POSICIONES",  3)   # máx 3 abiertas simultáneas

# ── TP / SL ───────────────────────────────────────────────────
TP_ATR_MULT       = _float("TP_ATR_MULT",      2.5)   # ATR x2.5 para TP
SL_ATR_MULT       = _float("SL_ATR_MULT",      1.0)   # ATR x1.0 para SL
PARTIAL_TP1_MULT  = _float("PARTIAL_TP1_MULT", 1.2)   # ATR x1.2 TP parcial
PARTIAL_TP_ACTIVO = _bool("PARTIAL_TP_ACTIVO",  True)
MIN_RR            = _float("MIN_RR",            2.0)   # R:R mínimo 2:1

# ── Trailing Stop ─────────────────────────────────────────────
TRAILING_ACTIVO    = _bool("TRAILING_ACTIVO",    True)
TRAILING_ACTIVAR   = _float("TRAILING_ACTIVAR",  1.2)  # activa al llegar a 1.2 ATR
TRAILING_DISTANCIA = _float("TRAILING_DISTANCIA", 0.8)  # sigue a 0.8 ATR

# ── Protección ────────────────────────────────────────────────
TIME_EXIT_HORAS = _float("TIME_EXIT_HORAS", 6.0)   # cierra a las 6h sin TP/SL
MAX_PERDIDA_DIA = _float("MAX_PERDIDA_DIA", 20.0)  # pausa si pierde $20/día

# ── Score / Señales ── v4.0 usa score /14 ────────────────────
SCORE_MIN    = _int("SCORE_MIN",       5)     # mínimo 5/14
FVG_MIN_PIPS = _float("FVG_MIN_PIPS",  0.0)
EQ_LOOKBACK  = _int("EQ_LOOKBACK",    50)
EQ_THRESHOLD = _float("EQ_THRESHOLD",  0.1)
EQ_PIVOT_LEN = _int("EQ_PIVOT_LEN",    5)

# ── Killzones (minutos UTC) ───────────────────────────────────
KZ_ASIA_START   = _int("KZ_ASIA_START",    0)
KZ_ASIA_END     = _int("KZ_ASIA_END",    240)
KZ_LONDON_START = _int("KZ_LONDON_START",420)
KZ_LONDON_END   = _int("KZ_LONDON_END",  600)
KZ_NY_START     = _int("KZ_NY_START",    780)
KZ_NY_END       = _int("KZ_NY_END",      960)
KZ_REQUERIDA    = _bool("KZ_REQUERIDA",  False)  # False = opera fuera de KZ también

# ── Indicadores ───────────────────────────────────────────────
EMA_FAST       = _int("EMA_FAST",      21)
EMA_SLOW       = _int("EMA_SLOW",      50)
EMA_LOCAL_FAST = _int("EMA_LOCAL_FAST",  9)   # EMA rápida local (nuevo v4)
EMA_LOCAL_SLOW = _int("EMA_LOCAL_SLOW", 21)   # EMA lenta local (nuevo v4)
RSI_PERIOD     = _int("RSI_PERIOD",    14)
RSI_BUY_MAX    = _float("RSI_BUY_MAX",  68.0)  # no comprar si RSI > 68
RSI_SELL_MIN   = _float("RSI_SELL_MIN", 32.0)  # no vender si RSI < 32
ATR_PERIOD     = _int("ATR_PERIOD",    14)
ATR_FAST       = _int("ATR_FAST",       7)     # ATR rápido para SL en 5m

PIVOT_NEAR_PCT = _float("PIVOT_NEAR_PCT", 1.50)  # zona ±1.5%

# ── Filtros de precisión v4.0 ─────────────────────────────────
PINBAR_RATIO     = _float("PINBAR_RATIO",    0.55)  # mecha >= 55% del rango
ENGULF_ACTIVO    = _bool("ENGULF_ACTIVO",    True)
VWAP_ACTIVO      = _bool("VWAP_ACTIVO",      True)
VWAP_PCT         = _float("VWAP_PCT",        0.20)  # proximidad VWAP ±0.20%
COOLDOWN_VELAS   = _int("COOLDOWN_VELAS",    5)     # mínimo 5 velas entre señales mismo par
MOMENTUM_ACTIVO  = _bool("MOMENTUM_ACTIVO",  True)

# ── Timeframes ────────────────────────────────────────────────
TIMEFRAME     = os.getenv("TIMEFRAME",     "5m").strip()
CANDLES_LIMIT = _int("CANDLES_LIMIT",     200)
MTF_ACTIVO    = _bool("MTF_ACTIVO",        True)
MTF_TIMEFRAME = os.getenv("MTF_TIMEFRAME", "1h").strip()
MTF_CANDLES   = _int("MTF_CANDLES",        60)

# ── Módulos activos ───────────────────────────────────────────
OB_ACTIVO          = _bool("OB_ACTIVO",          True)
OB_LOOKBACK        = _int("OB_LOOKBACK",          30)
BOS_ACTIVO         = _bool("BOS_ACTIVO",          True)
ASIA_RANGE_ACTIVO  = _bool("ASIA_RANGE_ACTIVO",   True)
VELA_CONFIRMACION  = _bool("VELA_CONFIRMACION",   True)
CORRELACION_ACTIVO = _bool("CORRELACION_ACTIVO",  True)
MACD_ACTIVO        = _bool("MACD_ACTIVO",         True)
SWEEP_ACTIVO       = _bool("SWEEP_ACTIVO",        True)  # detección sweeps (nuevo v4)
SWEEP_LOOKBACK     = _int("SWEEP_LOOKBACK",       20)

# ── Scanner ───────────────────────────────────────────────────
VOLUMEN_MIN_24H  = _float("VOLUMEN_MIN_24H", 500_000.0)
MAX_PARES_SCAN   = _int("MAX_PARES_SCAN",    0)
ANALISIS_WORKERS = _int("ANALISIS_WORKERS",  6)

# ── Dirección ─────────────────────────────────────────────────
SOLO_LONG = _bool("SOLO_LONG", False)  # opera long y short

# ── Listas ────────────────────────────────────────────────────
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",   "RESOLV-USDT").split(",") if p.strip()]
PARES_PRIORITARIOS = [p.strip() for p in os.getenv("PARES_PRIORITARIOS", "").split(",") if p.strip()]

# ── Persistencia ──────────────────────────────────────────────
MEMORY_DIR = os.getenv("MEMORY_DIR", "")


def validar():
    errores = []
    if not MODO_DEMO:
        if not BINGX_API_KEY:    errores.append("BINGX_API_KEY no configurada")
        if not BINGX_SECRET_KEY: errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:
        errores.append("TELEGRAM_TOKEN no configurada")
    if LEVERAGE < 1 or LEVERAGE > 125:
        errores.append(f"LEVERAGE={LEVERAGE} fuera de rango")
    if TRADE_USDT_BASE < 1:
        errores.append(f"TRADE_USDT_BASE={TRADE_USDT_BASE} muy bajo")
    if SCORE_MIN < 1 or SCORE_MIN > 14:
        errores.append(f"SCORE_MIN={SCORE_MIN} debe ser 1-14")
    if MIN_RR < 1.0:
        errores.append(f"MIN_RR={MIN_RR} peligroso (mín 1.0)")
    return errores
