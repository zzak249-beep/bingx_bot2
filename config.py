"""
config.py — SMC Bot BingX v3.1 [CORREGIDO + MEJORADO]
Fixes aplicados vs v3.0:
  ✅ PIVOT_NEAR_PCT subido de 0.20 a 0.80 (era demasiado estrecho → sin señales)
  ✅ SCORE_MIN bajado de 5 a 4 (base FVG+KZ+zona ya vale 4 puntos)
  ✅ MIN_RR 1.5 — ratio riesgo/beneficio mínimo obligatorio
  ✅ Variables de entorno con valores por defecto óptimos
  ✅ Logging de validación más detallado
"""
import os

VERSION = "SMC-Bot v3.2 [FIX-SEÑALES+KZ-OPCIONAL]"

# ── Helpers para leer env vars de forma robusta ──────────────

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
    return raw.strip().lower().split()[0] in ("true", "1", "yes")

# ── Credenciales ──────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── General ───────────────────────────────────────────────────
MODO_DEMO    = _bool("MODO_DEMO",    False)
LOOP_SECONDS = _int("LOOP_SECONDS",  60)

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
PARTIAL_TP_ACTIVO = _bool("PARTIAL_TP_ACTIVO",  True)
MIN_RR            = _float("MIN_RR",            1.5)   # ✅ ratio mínimo R:R

# ── Trailing Stop ─────────────────────────────────────────────
TRAILING_ACTIVO    = _bool("TRAILING_ACTIVO",    True)
TRAILING_ACTIVAR   = _float("TRAILING_ACTIVAR",  1.5)  # ATRs de beneficio para activar
TRAILING_DISTANCIA = _float("TRAILING_DISTANCIA",1.0)  # ATRs de distancia al trail

# ── Protección ────────────────────────────────────────────────
TIME_EXIT_HORAS = _float("TIME_EXIT_HORAS", 8.0)
MAX_PERDIDA_DIA = _float("MAX_PERDIDA_DIA", 25.0)

# ── Score / Señales ───────────────────────────────────────────
# ✅ FIX: era 5, bajado a 4
# La base obligatoria (FVG+KZ+zona) ya vale 4 pts.
# Con SCORE_MIN=5 el bot casi nunca disparaba.
SCORE_MIN    = _int("SCORE_MIN",      4)    # 4 sobre 12 máximo en v3.1
FVG_MIN_PIPS = _float("FVG_MIN_PIPS", 0.0)
EQ_LOOKBACK  = _int("EQ_LOOKBACK",   50)
EQ_THRESHOLD = _float("EQ_THRESHOLD", 0.1)
EQ_PIVOT_LEN = _int("EQ_PIVOT_LEN",   5)

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
RSI_BUY_MAX    = _float("RSI_BUY_MAX",  55.0)   # ✅ Subido de 50 → 55 (más permisivo)
RSI_SELL_MIN   = _float("RSI_SELL_MIN", 45.0)   # ✅ Bajado de 50 → 45 (más permisivo)
ATR_PERIOD     = _int("ATR_PERIOD",    14)

# ✅ FIX v3.2: subido de 0.80 → 1.50 para detectar zonas con precio más alejado.
# 0.80% en BTC@80k = solo ±$640 → raramente activaba.
# 1.50% en BTC@80k = ±$1200 → detecta zonas reales de mercado.
PIVOT_NEAR_PCT = _float("PIVOT_NEAR_PCT", 1.50)

# ── Timeframe ─────────────────────────────────────────────────
TIMEFRAME     = os.getenv("TIMEFRAME", "5m").strip()
CANDLES_LIMIT = _int("CANDLES_LIMIT", 200)

# ── Multi-TimeFrame (MTF) ─────────────────────────────────────
MTF_ACTIVO    = _bool("MTF_ACTIVO",    True)
MTF_TIMEFRAME = os.getenv("MTF_TIMEFRAME", "1h").strip()
MTF_CANDLES   = _int("MTF_CANDLES",   60)

# ── Order Blocks ──────────────────────────────────────────────
OB_ACTIVO   = _bool("OB_ACTIVO",    True)
OB_LOOKBACK = _int("OB_LOOKBACK",  30)

# ── BOS / CHoCH ───────────────────────────────────────────────
BOS_ACTIVO = _bool("BOS_ACTIVO", True)

# ── Rango Asia ────────────────────────────────────────────────
ASIA_RANGE_ACTIVO = _bool("ASIA_RANGE_ACTIVO", True)

# ── Confirmación de vela ──────────────────────────────────────
VELA_CONFIRMACION = _bool("VELA_CONFIRMACION", True)

# ── Correlación entre pares ───────────────────────────────────
CORRELACION_ACTIVO = _bool("CORRELACION_ACTIVO", True)

# ── Scanner ───────────────────────────────────────────────────
VOLUMEN_MIN_24H  = _float("VOLUMEN_MIN_24H", 500_000.0)
MAX_PARES_SCAN   = _int("MAX_PARES_SCAN",    0)
ANALISIS_WORKERS = _int("ANALISIS_WORKERS",  8)

# ── Dirección ─────────────────────────────────────────────────
SOLO_LONG = _bool("SOLO_LONG", False)

# ── Listas de pares ───────────────────────────────────────────
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",   "").split(",") if p.strip()]
PARES_PRIORITARIOS = [p.strip() for p in os.getenv("PARES_PRIORITARIOS", "").split(",") if p.strip()]

# ── Persistencia ──────────────────────────────────────────────
MEMORY_DIR = os.getenv("MEMORY_DIR", "")

# ── Validación de configuración ───────────────────────────────

def validar():
    errores = []
    if not MODO_DEMO:
        if not BINGX_API_KEY:    errores.append("BINGX_API_KEY no configurada")
        if not BINGX_SECRET_KEY: errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:
        errores.append("TELEGRAM_TOKEN no configurada")
    if LEVERAGE < 1 or LEVERAGE > 125:
        errores.append(f"LEVERAGE={LEVERAGE} fuera de rango (1-125)")
    if TRADE_USDT_BASE < 1:
        errores.append(f"TRADE_USDT_BASE={TRADE_USDT_BASE} demasiado bajo (min $1)")
    if SCORE_MIN < 1 or SCORE_MIN > 12:
        errores.append(f"SCORE_MIN={SCORE_MIN} debe estar entre 1 y 12")
    if MIN_RR < 1.0:
        errores.append(f"MIN_RR={MIN_RR} demasiado bajo, mínimo recomendado 1.0")
    if PIVOT_NEAR_PCT < 0.3:
        errores.append(f"PIVOT_NEAR_PCT={PIVOT_NEAR_PCT} demasiado estrecho (mín 0.3, recomendado 1.5)")
    return errores
