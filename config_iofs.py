"""
config_iofs.py — Institutional Order Flow Shield Bot v3.0
==========================================================
PARÁMETROS NUEVOS en v3 (requeridos por analizar_iofs.py v3):
  NET_PRESSURE_MIN — umbral de presión neta para accum/distri (BUG #1 fix)
  SPOOF_VOL_MULT   — threshold spoof relativo a vol_avg (BUG #4 fix)
  ICEBERG_AVG_MULT — threshold iceberg relativo a vol_avg (BUG #2 fix)
  WHALE_RVOL_MIN   — RVOL mínimo para considerar entrada ballena
"""
import os

VERSION = os.getenv("VERSION", "IOFS Bot v3.0 [1m-FIXED]")

# ─── API BingX ───────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
MODO_DEMO        = os.getenv("MODO_DEMO", "false").lower() in ("true", "demo", "1")
MEMORY_DIR       = os.getenv("MEMORY_DIR", "/app/data")
BINGX_MODE       = os.getenv("BINGX_MODE", "hedge")

# ─── Riesgo ──────────────────────────────────────────────────
TRADE_USDT_BASE    = float(os.getenv("TRADE_USDT_BASE",    "10"))
TRADE_USDT_MAX     = float(os.getenv("TRADE_USDT_MAX",     "100"))
LEVERAGE           = int(os.getenv("LEVERAGE",             "10"))
COMPOUND_STEP_USDT = float(os.getenv("COMPOUND_STEP_USDT", "50"))
COMPOUND_ADD_USDT  = float(os.getenv("COMPOUND_ADD_USDT",  "5"))
MAX_PERDIDA_DIA    = float(os.getenv("MAX_PERDIDA_DIA",    "30.0"))
MAX_POSICIONES     = int(os.getenv("MAX_POSICIONES",       "3"))

# ─── Timeframes ──────────────────────────────────────────────
TIMEFRAME     = os.getenv("TIMEFRAME", "1m")
CANDLES_LIMIT = int(os.getenv("CANDLES_LIMIT", "250"))

# ─── Order Flow Engine ───────────────────────────────────────
FLOW_BATCH_LEN         = int(os.getenv("FLOW_BATCH_LEN",          "8"))
VOL_SMA_LEN            = int(os.getenv("VOL_SMA_LEN",             "20"))
# NET_PRESSURE_MIN — NUEVO (fix BUG #1)
# Presión neta mínima para considerar acumulación o distribución.
# Rango: 0.0 (toda presión cuenta) a 1.0 (solo extremos absolutos).
# 0.08 = 8% de diferencia neta entre compras y ventas ajustadas.
# Sube a 0.12-0.15 si quieres señales de mayor calidad (menos frecuentes).
# Baja a 0.05 si quieres más señales.
NET_PRESSURE_MIN       = float(os.getenv("NET_PRESSURE_MIN",       "0.08"))
# FLOW_SENSITIVITY_RATIO — conservado para compatibilidad (ya no se usa en v3)
FLOW_SENSITIVITY_RATIO = float(os.getenv("FLOW_SENSITIVITY_RATIO", "1.2"))

# ─── Supertrend ──────────────────────────────────────────────
ST_FACTOR     = float(os.getenv("ST_FACTOR",     "2.5"))
ST_PERIOD     = int(os.getenv("ST_PERIOD",       "7"))
USE_ST_FILTER = os.getenv("USE_ST_FILTER", "false").lower() == "true"

# ─── Spoof & Iceberg (fix BUG #2 y #4) ───────────────────────
# SPOOF_VOL_MULT — NUEVO: threshold spoof = vol_avg × SPOOF_VOL_MULT
# 2.0 = la caída de volumen debe ser > 2x el vol_avg para contar
SPOOF_VOL_MULT       = float(os.getenv("SPOOF_VOL_MULT",        "2.0"))
# ICEBERG_AVG_MULT — CAMBIADO: ahora es threshold PURO (sin floor absoluto)
# 2.5 = vol_curr debe superar 2.5× el vol_avg promedio
# Baja a 2.0 para más señales de iceberg
ICEBERG_AVG_MULT     = float(os.getenv("ICEBERG_AVG_MULT",      "2.5"))
# WHALE_RVOL_MIN — NUEVO: RVOL mínimo para whale
WHALE_RVOL_MIN       = float(os.getenv("WHALE_RVOL_MIN",        "2.0"))
SPOOF_PULL_PCT       = float(os.getenv("SPOOF_PULL_PCT",        "0.40"))
REQUIRE_PRICE_REVERSAL = os.getenv("REQUIRE_PRICE_REVERSAL", "true").lower() == "true"
SPOOF_PREV_RVOL_MIN  = float(os.getenv("SPOOF_PREV_RVOL_MIN",   "1.2"))
# Parámetros legacy (ya no usados en v3, conservados por si acaso)
MIN_SPOOF_VOL        = float(os.getenv("MIN_SPOOF_VOL",         "0.0"))
MIN_ICEBERG_VOL      = float(os.getenv("MIN_ICEBERG_VOL",       "0.0"))

# ─── Decision Matrix ─────────────────────────────────────────
WARMUP_BARS    = int(os.getenv("WARMUP_BARS",    "30"))
STRONG_BUY_LVL = float(os.getenv("STRONG_BUY_LVL", "0.55"))
STRONG_SELL_LVL= float(os.getenv("STRONG_SELL_LVL","0.45"))
DECAY_RATE     = int(os.getenv("DECAY_RATE",     "10"))
BOOST_RATE     = int(os.getenv("BOOST_RATE",     "20"))
PASSIVE_DECAY  = float(os.getenv("PASSIVE_DECAY", "0.5"))

# ─── Gates obligatorios ──────────────────────────────────────
USE_ATR_FILTER   = os.getenv("USE_ATR_FILTER",   "true").lower()  == "true"
ATR_MIN_PCT      = float(os.getenv("ATR_MIN_PCT",       "0.10"))
USE_RVOL_FILTER  = os.getenv("USE_RVOL_FILTER",  "true").lower()  == "true"
RVOL_MIN         = float(os.getenv("RVOL_MIN",         "1.2"))
USE_VWAP_FILTER  = os.getenv("USE_VWAP_FILTER",  "false").lower() == "true"
USE_TREND_FILTER = os.getenv("USE_TREND_FILTER", "false").lower() == "true"

# ─── Confidence y score ──────────────────────────────────────
MIN_CONF_ENTRADA  = float(os.getenv("MIN_CONF_ENTRADA",  "30.0"))
MIN_SCORE_ENTRADA = int(os.getenv("MIN_SCORE_ENTRADA",   "2"))

# ─── SL / TP ─────────────────────────────────────────────────
SL_ATR_MULT   = float(os.getenv("SL_ATR_MULT",   "1.2"))
TP_DIST_MULT  = float(os.getenv("TP_DIST_MULT",  "2.5"))
TP1_DIST_MULT = float(os.getenv("TP1_DIST_MULT", "1.2"))
MIN_RR        = float(os.getenv("MIN_RR",         "1.8"))

# ─── Gestión ─────────────────────────────────────────────────
TRAILING_ACTIVO    = os.getenv("TRAILING_ACTIVO",  "true").lower() == "true"
TRAILING_ACTIVAR   = float(os.getenv("TRAILING_ACTIVAR",   "1.0"))
TRAILING_DISTANCIA = float(os.getenv("TRAILING_DISTANCIA", "0.8"))
PARTIAL_TP_ACTIVO  = os.getenv("PARTIAL_TP_ACTIVO", "true").lower() == "true"
BE_ACTIVO          = os.getenv("BE_ACTIVO",         "true").lower() == "true"
TIME_EXIT_HORAS    = float(os.getenv("TIME_EXIT_HORAS", "2.0"))
COOLDOWN_VELAS     = int(os.getenv("COOLDOWN_VELAS", "3"))

# ─── Pares ───────────────────────────────────────────────────
SOLO_LONG          = os.getenv("SOLO_LONG", "false").lower() == "true"
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS","").split(",") if p.strip()]
PARES_PRIORITARIOS = ["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT",
                      "AVAX-USDT","ARB-USDT","OP-USDT","DOGE-USDT","LINK-USDT"]
MAX_PARES_SCAN     = int(os.getenv("MAX_PARES_SCAN",    "30"))
VOLUMEN_MIN_24H    = float(os.getenv("VOLUMEN_MIN_24H", "10000000"))
ANALISIS_WORKERS   = int(os.getenv("ANALISIS_WORKERS",  "4"))
LOOP_SECONDS       = int(os.getenv("LOOP_SECONDS",      "60"))

# ─── Telegram ────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Kill zones (minutos UTC) ────────────────────────────────
KZ_LONDON_START = int(os.getenv("KZ_LONDON_START", "480"))
KZ_LONDON_END   = int(os.getenv("KZ_LONDON_END",   "720"))
KZ_NY_START     = int(os.getenv("KZ_NY_START",     "780"))
KZ_NY_END       = int(os.getenv("KZ_NY_END",       "960"))


def validar() -> list:
    e = []
    if not BINGX_API_KEY:    e.append("BINGX_API_KEY no configurada")
    if not BINGX_SECRET_KEY: e.append("BINGX_SECRET_KEY no configurada")
    if TRADE_USDT_BASE <= 0: e.append("TRADE_USDT_BASE debe ser > 0")
    if STRONG_BUY_LVL <= STRONG_SELL_LVL:
        e.append("STRONG_BUY_LVL debe ser mayor que STRONG_SELL_LVL")
    if NET_PRESSURE_MIN < 0 or NET_PRESSURE_MIN > 1:
        e.append("NET_PRESSURE_MIN debe estar entre 0.0 y 1.0")
    return e
