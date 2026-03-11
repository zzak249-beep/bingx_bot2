"""
config.py — SMC Bot BingX v3.0 [MÁXIMO RENDIMIENTO]
Nuevas variables:
  ✅ SCORE_MIN subido a 5 (sobre 12 máximo)
  ✅ MTF_TIMEFRAME — timeframe confirmación tendencia
  ✅ OB_LOOKBACK — cuántas velas buscar Order Blocks
  ✅ ASIA_RANGE_ACTIVO — activar rango Asia
  ✅ CORRELACION_ACTIVO — filtro correlación entre pares
  ✅ VELA_CONFIRMACION — exigir vela confirmadora
  ✅ MIN_RR — ratio riesgo/beneficio mínimo
"""
import os

VERSION = "SMC-Bot v3.0 [MTF+OB+BOS+ASIA+CORRELACION]"

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

# ── Credenciales ──────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── General ───────────────────────────────────────────────────
MODO_DEMO    = _bool("MODO_DEMO",   False)
LOOP_SECONDS = _int("LOOP_SECONDS", 60)

# ── Capital ───────────────────────────────────────────────────
TRADE_USDT_BASE    = _float("TRADE_USDT_BASE",    10.0)
TRADE_USDT_MAX     = _float("TRADE_USDT_MAX",     50.0)
COMPOUND_STEP_USDT = _float("COMPOUND_STEP_USDT", 50.0)
COMPOUND_ADD_USDT  = _float("COMPOUND_ADD_USDT",   1.0)

# ── Posiciones ────────────────────────────────────────────────
LEVERAGE       = _int("LEVERAGE",       10)
MAX_POSICIONES = _int("MAX_POSICIONES",  3)

# ── TP / SL ───────────────────────────────────────────────────
TP_ATR_MULT       = _float("TP_ATR_MULT",      2.0)
SL_ATR_MULT       = _float("SL_ATR_MULT",      1.0)
PARTIAL_TP1_MULT  = _float("PARTIAL_TP1_MULT", 1.0)
PARTIAL_TP_ACTIVO = _bool("PARTIAL_TP_ACTIVO", True)
MIN_RR            = _float("MIN_RR",           1.5)   # ✅ NUEVO ratio mínimo R:R

# ── Trailing Stop ─────────────────────────────────────────────
TRAILING_ACTIVO    = _bool("TRAILING_ACTIVO",    True)
TRAILING_ACTIVAR   = _float("TRAILING_ACTIVAR",  1.5)
TRAILING_DISTANCIA = _float("TRAILING_DISTANCIA",1.0)

# ── Protección ────────────────────────────────────────────────
TIME_EXIT_HORAS = _float("TIME_EXIT_HORAS", 8.0)
MAX_PERDIDA_DIA = _float("MAX_PERDIDA_DIA", 25.0)

# ── Score / Señales ───────────────────────────────────────────
SCORE_MIN    = _int("SCORE_MIN",     4)    # ✅ FIX: era 5, bajado a 4 (base ya exige FVG+KZ+zona)
FVG_MIN_PIPS = _float("FVG_MIN_PIPS",0.0)
EQ_LOOKBACK  = _int("EQ_LOOKBACK",  50)
EQ_THRESHOLD = _float("EQ_THRESHOLD",0.1)
EQ_PIVOT_LEN = _int("EQ_PIVOT_LEN",  5)

# ── Killzones (minutos desde medianoche UTC) ──────────────────
KZ_ASIA_START   = _int("KZ_ASIA_START",    0)
KZ_ASIA_END     = _int("KZ_ASIA_END",    240)
KZ_LONDON_START = _int("KZ_LONDON_START",420)
KZ_LONDON_END   = _int("KZ_LONDON_END",  600)
KZ_NY_START     = _int("KZ_NY_START",    780)
KZ_NY_END       = _int("KZ_NY_END",      960)

# ── Indicadores ───────────────────────────────────────────────
EMA_FAST       = _int("EMA_FAST",      21)
EMA_SLOW       = _int("EMA_SLOW",      50)
RSI_PERIOD     = _int("RSI_PERIOD",    14)
RSI_BUY_MAX    = _float("RSI_BUY_MAX",  50.0)
RSI_SELL_MIN   = _float("RSI_SELL_MIN", 50.0)
ATR_PERIOD     = _int("ATR_PERIOD",    14)
PIVOT_NEAR_PCT = _float("PIVOT_NEAR_PCT",0.80)  # ✅ FIX: era 0.20 (demasiado estrecho)

# ── Timeframe ─────────────────────────────────────────────────
TIMEFRAME     = os.getenv("TIMEFRAME", "5m").strip()
CANDLES_LIMIT = _int("CANDLES_LIMIT", 200)

# ── ✅ NUEVO: Multi-TimeFrame (MTF) ───────────────────────────
MTF_ACTIVO     = _bool("MTF_ACTIVO",    True)   # confirmar con 1h
MTF_TIMEFRAME  = os.getenv("MTF_TIMEFRAME", "1h").strip()
MTF_CANDLES    = _int("MTF_CANDLES",   60)

# ── ✅ NUEVO: Order Blocks ────────────────────────────────────
OB_ACTIVO      = _bool("OB_ACTIVO",    True)
OB_LOOKBACK    = _int("OB_LOOKBACK",  30)   # velas hacia atrás

# ── ✅ NUEVO: BOS / CHoCH ─────────────────────────────────────
BOS_ACTIVO     = _bool("BOS_ACTIVO",   True)

# ── ✅ NUEVO: Rango Asia ──────────────────────────────────────
ASIA_RANGE_ACTIVO = _bool("ASIA_RANGE_ACTIVO", True)

# ── ✅ NUEVO: Confirmación de vela ────────────────────────────
VELA_CONFIRMACION = _bool("VELA_CONFIRMACION", True)

# ── ✅ NUEVO: Correlación entre pares ─────────────────────────
CORRELACION_ACTIVO = _bool("CORRELACION_ACTIVO", True)

# ── Scanner ───────────────────────────────────────────────────
VOLUMEN_MIN_24H  = _float("VOLUMEN_MIN_24H", 500000.0)
MAX_PARES_SCAN   = _int("MAX_PARES_SCAN",    0)
ANALISIS_WORKERS = _int("ANALISIS_WORKERS",  8)

# ── Dirección ─────────────────────────────────────────────────
SOLO_LONG = _bool("SOLO_LONG", False)

# ── Listas ────────────────────────────────────────────────────
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",   "").split(",") if p.strip()]
PARES_PRIORITARIOS = [p.strip() for p in os.getenv("PARES_PRIORITARIOS", "").split(",") if p.strip()]

# ── Persistencia ──────────────────────────────────────────────
MEMORY_DIR = os.getenv("MEMORY_DIR", "")

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
