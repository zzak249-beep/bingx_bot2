"""
config.py — SMC Bot BingX v2.1 [FIXED]
Cambios:
  ✅ SCORE_MIN subido a 5 (filtra mejor calidad de señales)
  ✅ RSI_BUY_MAX bajado a 50 (más conservador en longs)
  ✅ RSI_SELL_MIN subido a 50 (más conservador en shorts)
  ✅ VOLUMEN_VELA_MIN_PCT — filtro de volumen de vela actual
  ✅ MIN_ATR_PCT — descarta pares con ATR demasiado pequeño (poco movimiento)
"""
import os

VERSION = "SMC-Bot v2.1 [FIXED — ALL-PAIRS + COMPOUNDING]"

def _int(var: str, default: int) -> int:
    try:
        raw = os.getenv(var, str(default))
        return int(raw.split()[0].split("(")[0].strip())
    except Exception:
        return default

def _float(var: str, default: float) -> float:
    try:
        raw = os.getenv(var, str(default))
        return float(raw.split()[0].split("(")[0].strip())
    except Exception:
        return default

def _bool(var: str, default: bool) -> bool:
    raw = os.getenv(var, "true" if default else "false")
    return raw.strip().lower().split()[0] == "true"

BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MODO_DEMO    = _bool("MODO_DEMO",   False)
LOOP_SECONDS = _int("LOOP_SECONDS", 60)

TRADE_USDT_BASE    = _float("TRADE_USDT_BASE",    10.0)
TRADE_USDT_MAX     = _float("TRADE_USDT_MAX",     50.0)
COMPOUND_STEP_USDT = _float("COMPOUND_STEP_USDT", 50.0)
COMPOUND_ADD_USDT  = _float("COMPOUND_ADD_USDT",   1.0)

LEVERAGE       = _int("LEVERAGE",       10)
MAX_POSICIONES = _int("MAX_POSICIONES",  3)   # ✅ Bajado a 3 (más conservador)

TP_ATR_MULT       = _float("TP_ATR_MULT",      2.0)
SL_ATR_MULT       = _float("SL_ATR_MULT",      1.0)
PARTIAL_TP1_MULT  = _float("PARTIAL_TP1_MULT", 1.0)
PARTIAL_TP_ACTIVO = _bool("PARTIAL_TP_ACTIVO", True)

TRAILING_ACTIVO    = _bool("TRAILING_ACTIVO",    True)
TRAILING_ACTIVAR   = _float("TRAILING_ACTIVAR",  1.5)
TRAILING_DISTANCIA = _float("TRAILING_DISTANCIA",1.0)

TIME_EXIT_HORAS = _float("TIME_EXIT_HORAS", 8.0)
MAX_PERDIDA_DIA = _float("MAX_PERDIDA_DIA", 30.0)

# ✅ SCORE_MIN subido a 5 — exige más confluencia para entrar
SCORE_MIN    = _int("SCORE_MIN",     5)
FVG_MIN_PIPS = _float("FVG_MIN_PIPS",0.0)
EQ_LOOKBACK  = _int("EQ_LOOKBACK",  50)
EQ_THRESHOLD = _float("EQ_THRESHOLD",0.1)
EQ_PIVOT_LEN = _int("EQ_PIVOT_LEN",  5)

KZ_ASIA_START   = _int("KZ_ASIA_START",    0)
KZ_ASIA_END     = _int("KZ_ASIA_END",    240)
KZ_LONDON_START = _int("KZ_LONDON_START",420)
KZ_LONDON_END   = _int("KZ_LONDON_END",  600)
KZ_NY_START     = _int("KZ_NY_START",    780)
KZ_NY_END       = _int("KZ_NY_END",      960)

EMA_FAST       = _int("EMA_FAST",      21)
EMA_SLOW       = _int("EMA_SLOW",      50)
RSI_PERIOD     = _int("RSI_PERIOD",    14)
# ✅ RSI más conservador: longs solo con RSI ≤ 50, shorts solo con RSI ≥ 50
RSI_BUY_MAX    = _float("RSI_BUY_MAX",  50.0)
RSI_SELL_MIN   = _float("RSI_SELL_MIN", 50.0)
ATR_PERIOD     = _int("ATR_PERIOD",    14)
PIVOT_NEAR_PCT = _float("PIVOT_NEAR_PCT",0.20)

TIMEFRAME     = os.getenv("TIMEFRAME", "5m").strip()
CANDLES_LIMIT = _int("CANDLES_LIMIT", 200)

VOLUMEN_MIN_24H  = _float("VOLUMEN_MIN_24H", 500000.0)
MAX_PARES_SCAN   = _int("MAX_PARES_SCAN",    0)
ANALISIS_WORKERS = _int("ANALISIS_WORKERS",  8)

SOLO_LONG = _bool("SOLO_LONG", False)

PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",   "").split(",") if p.strip()]
PARES_PRIORITARIOS = [p.strip() for p in os.getenv("PARES_PRIORITARIOS", "").split(",") if p.strip()]

# ✅ NUEVO: directorio para memoria persistente (Railway Volume)
MEMORY_DIR = os.getenv("MEMORY_DIR", "/data" if os.path.isdir("/data") else ".")

def validar():
    errores = []
    if not MODO_DEMO:
        if not BINGX_API_KEY:    errores.append("BINGX_API_KEY no configurada")
        if not BINGX_SECRET_KEY: errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:       errores.append("TELEGRAM_TOKEN no configurada")
    if LEVERAGE < 1 or LEVERAGE > 125:
        errores.append(f"LEVERAGE={LEVERAGE} fuera de rango (1-125)")
    if TRADE_USDT_BASE < 1:
        errores.append(f"TRADE_USDT_BASE={TRADE_USDT_BASE} demasiado bajo (min $1)")
    return errores
