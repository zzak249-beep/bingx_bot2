"""
config_iofs.py — Institutional Order Flow Shield Bot
Todos los parámetros configurables via variables de entorno (Railway).
"""
import os

VERSION = os.getenv("VERSION", "IOFS Bot v1.0")

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
TIMEFRAME     = os.getenv("TIMEFRAME", "1m")       # 1m para IOFS en cripto
CANDLES_LIMIT = int(os.getenv("CANDLES_LIMIT", "250"))

# ─── Order Flow Engine ───────────────────────────────────────
FLOW_BATCH_LEN         = int(os.getenv("FLOW_BATCH_LEN",         "10"))    # Batch length (cfg: 21 TradingView, 10 para 1m cripto)
VOL_SMA_LEN            = int(os.getenv("VOL_SMA_LEN",            "14"))    # SMA del volumen para RVOL
FLOW_SENSITIVITY_RATIO = float(os.getenv("FLOW_SENSITIVITY_RATIO","1.4"))  # 1.8 original, 1.4 para 1m

# ─── Supertrend ──────────────────────────────────────────────
ST_FACTOR = float(os.getenv("ST_FACTOR", "3.0"))
ST_PERIOD = int(os.getenv("ST_PERIOD",   "10"))

# ─── Spoof & Iceberg Detection ────────────────────────────────
MIN_SPOOF_VOL        = float(os.getenv("MIN_SPOOF_VOL",         "500.0"))  # Mínimo diferencial de volumen para spoof
MIN_ICEBERG_VOL      = float(os.getenv("MIN_ICEBERG_VOL",       "1000.0")) # Volumen mínimo iceberg
SPOOF_PULL_PCT       = float(os.getenv("SPOOF_PULL_PCT",        "0.35"))   # 35% del volumen anterior = spoof pull
ICEBERG_AVG_MULT     = float(os.getenv("ICEBERG_AVG_MULT",      "1.6"))    # Multiplicador del avg para iceberg
REQUIRE_PRICE_REVERSAL = os.getenv("REQUIRE_PRICE_REVERSAL", "true").lower() == "true"
SPOOF_PREV_RVOL_MIN  = float(os.getenv("SPOOF_PREV_RVOL_MIN",   "1.3"))   # RVOL mínimo en la barra anterior

# ─── Decision Matrix ─────────────────────────────────────────
WARMUP_BARS    = int(os.getenv("WARMUP_BARS",    "50"))     # Barras de calentamiento inicial
STRONG_BUY_LVL = float(os.getenv("STRONG_BUY_LVL", "0.62"))  # Power Balance > X → STRONG BUY
STRONG_SELL_LVL= float(os.getenv("STRONG_SELL_LVL","0.38"))  # Power Balance < X → STRONG SELL
DECAY_RATE     = int(os.getenv("DECAY_RATE",     "15"))     # Decay lado opuesto por evento
BOOST_RATE     = int(os.getenv("BOOST_RATE",     "25"))     # Boost lado correcto por señal
PASSIVE_DECAY  = float(os.getenv("PASSIVE_DECAY", "1.0"))   # % decay pasivo por ciclo

# ─── Smart Filters ────────────────────────────────────────────
USE_RVOL_FILTER  = os.getenv("USE_RVOL_FILTER",  "true").lower()  == "true"
RVOL_MIN         = float(os.getenv("RVOL_MIN",         "1.3"))
USE_ATR_FILTER   = os.getenv("USE_ATR_FILTER",   "true").lower()  == "true"
ATR_MIN_PCT      = float(os.getenv("ATR_MIN_PCT",       "0.15"))   # 0.15% mínimo ATR/precio para 1m
USE_VWAP_FILTER  = os.getenv("USE_VWAP_FILTER",  "false").lower() == "true"
USE_TREND_FILTER = os.getenv("USE_TREND_FILTER", "false").lower() == "true"  # EMA 50/200 OFF en 1m

# ─── Entrada ─────────────────────────────────────────────────
MIN_CONF_ENTRADA = float(os.getenv("MIN_CONF_ENTRADA", "50.0"))  # Confidence mínima para entrar

# ─── SL / TP ─────────────────────────────────────────────────
SL_ATR_MULT   = float(os.getenv("SL_ATR_MULT",   "1.5"))
TP_DIST_MULT  = float(os.getenv("TP_DIST_MULT",  "3.0"))
TP1_DIST_MULT = float(os.getenv("TP1_DIST_MULT", "1.5"))
MIN_RR        = float(os.getenv("MIN_RR",         "2.0"))

# ─── Gestión ─────────────────────────────────────────────────
TRAILING_ACTIVO    = os.getenv("TRAILING_ACTIVO",  "true").lower() == "true"
TRAILING_ACTIVAR   = float(os.getenv("TRAILING_ACTIVAR",   "1.5"))
TRAILING_DISTANCIA = float(os.getenv("TRAILING_DISTANCIA", "1.0"))
PARTIAL_TP_ACTIVO  = os.getenv("PARTIAL_TP_ACTIVO", "true").lower() == "true"
BE_ACTIVO          = os.getenv("BE_ACTIVO",         "true").lower() == "true"
TIME_EXIT_HORAS    = float(os.getenv("TIME_EXIT_HORAS", "4.0"))   # 4h en 1m (más corto que SMC)
COOLDOWN_VELAS     = int(os.getenv("COOLDOWN_VELAS", "5"))        # Minutos de cooldown por par

# ─── Pares ───────────────────────────────────────────────────
SOLO_LONG          = os.getenv("SOLO_LONG", "false").lower() == "true"
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS","").split(",") if p.strip()]
PARES_PRIORITARIOS = ["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT",
                      "AVAX-USDT","ARB-USDT","OP-USDT","DOGE-USDT","LINK-USDT"]
MAX_PARES_SCAN     = int(os.getenv("MAX_PARES_SCAN",    "30"))
VOLUMEN_MIN_24H    = float(os.getenv("VOLUMEN_MIN_24H", "10000000"))
ANALISIS_WORKERS   = int(os.getenv("ANALISIS_WORKERS",  "4"))
LOOP_SECONDS       = int(os.getenv("LOOP_SECONDS",      "60"))    # 60s en 1m (vs 90s en 5m)

# ─── Telegram ────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Kill zones (minutos UTC) ────────────────────────────────
KZ_LONDON_START = int(os.getenv("KZ_LONDON_START", "480"))   # 08:00 UTC
KZ_LONDON_END   = int(os.getenv("KZ_LONDON_END",   "720"))   # 12:00 UTC
KZ_NY_START     = int(os.getenv("KZ_NY_START",     "780"))   # 13:00 UTC
KZ_NY_END       = int(os.getenv("KZ_NY_END",       "960"))   # 16:00 UTC


def validar() -> list:
    e = []
    if not BINGX_API_KEY:    e.append("BINGX_API_KEY no configurada")
    if not BINGX_SECRET_KEY: e.append("BINGX_SECRET_KEY no configurada")
    if TRADE_USDT_BASE <= 0: e.append("TRADE_USDT_BASE debe ser > 0")
    if STRONG_BUY_LVL <= STRONG_SELL_LVL:
        e.append("STRONG_BUY_LVL debe ser mayor que STRONG_SELL_LVL")
    return e
