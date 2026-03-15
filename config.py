"""
config.py — Bellsz Bot v2.0 [Liquidez Lateral]
"""
import os

VERSION = os.getenv("VERSION", "Bellsz Bot v2.0")

BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
API_KEY          = BINGX_API_KEY
API_SECRET       = BINGX_SECRET_KEY
EXCHANGE         = "bingx"
LEVERAGE         = int(os.getenv("LEVERAGE", "10"))
MODO_DEMO        = os.getenv("MODO_DEMO", "false").lower() in ("true", "demo", "1")
MEMORY_DIR       = os.getenv("MEMORY_DIR", "/app/data")

TRADE_USDT_BASE    = float(os.getenv("TRADE_USDT_BASE",    "10"))
TRADE_USDT_MAX     = float(os.getenv("TRADE_USDT_MAX",     "100"))
COMPOUND_STEP_USDT = float(os.getenv("COMPOUND_STEP_USDT", "50"))
COMPOUND_ADD_USDT  = float(os.getenv("COMPOUND_ADD_USDT",  "5"))

TIMEFRAME     = os.getenv("TIMEFRAME", "5m")
CANDLES_LIMIT = int(os.getenv("CANDLES_LIMIT", "200"))
HTF_H1_TF     = "1h"
HTF_H4_TF     = "4h"
HTF_D_TF      = "1d"
HTF_CANDLES   = int(os.getenv("HTF_CANDLES", "60"))
MTF_ACTIVO    = os.getenv("MTF_ACTIVO",    "true").lower() == "true"
MTF_TIMEFRAME = os.getenv("MTF_TIMEFRAME", "1h")
MTF_4H_ACTIVO = os.getenv("MTF_4H_ACTIVO", "true").lower() == "true"

ATR_PERIOD   = int(os.getenv("ATR_PERIOD", "14"))
RSI_PERIOD   = int(os.getenv("RSI_PERIOD", "14"))
EMA_FAST     = int(os.getenv("EMA_FAST",   "9"))
EMA_SLOW     = int(os.getenv("EMA_SLOW",   "21"))
RSI_BUY_MAX  = float(os.getenv("RSI_BUY_MAX",  "70"))
RSI_SELL_MIN = float(os.getenv("RSI_SELL_MIN", "30"))
VWAP_ACTIVO  = os.getenv("VWAP_ACTIVO", "true").lower() == "true"
VWAP_PCT     = float(os.getenv("VWAP_PCT", "0.3"))

# LIQ_MARGEN replica margen_pip del Pine Script (se divide /100 internamente)
LIQ_LOOKBACK = int(os.getenv("LIQ_LOOKBACK",  "50"))
LIQ_MARGEN   = float(os.getenv("LIQ_MARGEN",  "0.1"))

SL_ATR_MULT      = float(os.getenv("SL_ATR_MULT",   "1.5"))
TP_DIST_MULT     = float(os.getenv("TP_DIST_MULT",  "3.0"))
TP1_DIST_MULT    = float(os.getenv("TP1_DIST_MULT", "1.5"))
MIN_RR           = float(os.getenv("MIN_RR",        "2.0"))

TRAILING_ACTIVO    = os.getenv("TRAILING_ACTIVO",  "true").lower() == "true"
TRAILING_ACTIVAR   = float(os.getenv("TRAILING_ACTIVAR",   "1.5"))
TRAILING_DISTANCIA = float(os.getenv("TRAILING_DISTANCIA", "1.0"))
PARTIAL_TP_ACTIVO  = os.getenv("PARTIAL_TP_ACTIVO", "true").lower() == "true"
BE_ACTIVO          = os.getenv("BE_ACTIVO",         "true").lower() == "true"
BE_TRIGGER_ATR     = float(os.getenv("BE_TRIGGER_ATR", "1.0"))
TIME_EXIT_HORAS    = float(os.getenv("TIME_EXIT_HORAS", "8.0"))

SCORE_MIN      = int(os.getenv("SCORE_MIN",      "4"))
MAX_POSICIONES = int(os.getenv("MAX_POSICIONES", "3"))
COOLDOWN_VELAS  = int(os.getenv("COOLDOWN_VELAS",   "5"))
MAX_PERDIDA_DIA = float(os.getenv("MAX_PERDIDA_DIA", "30.0"))

OB_ACTIVO               = os.getenv("OB_ACTIVO",    "true").lower() == "true"
OB_LOOKBACK             = int(os.getenv("OB_LOOKBACK", "20"))
BOS_ACTIVO              = os.getenv("BOS_ACTIVO",   "true").lower() == "true"
FVG_ACTIVO              = os.getenv("FVG_ACTIVO",   "true").lower() == "true"
SWEEP_ACTIVO            = os.getenv("SWEEP_ACTIVO", "true").lower() == "true"
SWEEP_LOOKBACK          = int(os.getenv("SWEEP_LOOKBACK", "20"))
DISPLACEMENT_ACTIVO     = os.getenv("DISPLACEMENT_ACTIVO",     "true").lower() == "true"
PREMIUM_DISCOUNT_ACTIVO = os.getenv("PREMIUM_DISCOUNT_ACTIVO", "true").lower() == "true"
PREMIUM_DISCOUNT_LB     = int(os.getenv("PREMIUM_DISCOUNT_LB", "50"))
CORRELACION_ACTIVO      = os.getenv("CORRELACION_ACTIVO", "true").lower() == "true"
ASIA_RANGE_ACTIVO       = os.getenv("ASIA_RANGE_ACTIVO",  "true").lower() == "true"
VELA_CONFIRMACION       = os.getenv("VELA_CONFIRMACION",  "true").lower() == "true"
PINBAR_RATIO            = float(os.getenv("PINBAR_RATIO", "0.50"))

KZ_ASIA_START   = int(os.getenv("KZ_ASIA_START",   "0"))
KZ_ASIA_END     = int(os.getenv("KZ_ASIA_END",     "240"))
KZ_LONDON_START = int(os.getenv("KZ_LONDON_START", "480"))
KZ_LONDON_END   = int(os.getenv("KZ_LONDON_END",   "720"))
KZ_NY_START     = int(os.getenv("KZ_NY_START",     "780"))
KZ_NY_END       = int(os.getenv("KZ_NY_END",       "960"))

SOLO_LONG          = os.getenv("SOLO_LONG", "false").lower() == "true"
PARES_BLOQUEADOS   = [p.strip() for p in os.getenv("PARES_BLOQUEADOS","").split(",") if p.strip()]
PARES_PRIORITARIOS = ["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT","AVAX-USDT","ARB-USDT","OP-USDT"]

VOLUMEN_MIN_24H  = float(os.getenv("VOLUMEN_MIN_24H", "2000000"))
MAX_PARES_SCAN   = int(os.getenv("MAX_PARES_SCAN",    "50"))
ANALISIS_WORKERS = int(os.getenv("ANALISIS_WORKERS",  "6"))
LOOP_SECONDS     = int(os.getenv("LOOP_SECONDS",      "60"))

METACLAW_ACTIVO      = os.getenv("METACLAW_ACTIVO", "false").lower() == "true"
METACLAW_VETO_MINIMO = int(os.getenv("METACLAW_VETO_MINIMO", "7"))

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def validar() -> list:
    e = []
    if not BINGX_API_KEY:    e.append("BINGX_API_KEY no configurada")
    if not BINGX_SECRET_KEY: e.append("BINGX_SECRET_KEY no configurada")
    if TRADE_USDT_BASE <= 0: e.append("TRADE_USDT_BASE debe ser > 0")
    return e
