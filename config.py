"""
config.py — Liquidez Lateral [Bellsz] Bot v1.0
================================================
Bot basado en la estrategia Liquidez Lateral:
  - Purgas de BSL/SSL en H1, H4 y Diario
  - Confirmación EMA 9/21
  - Confirmación RSI con momentum
  - Score de confluencia 1-10
  - Break-Even + Trailing + Partial TP
  - Filtro de sesiones (Asia/Londres/NY)
  - MetaClaw IA validación (opcional)
"""
import os

VERSION = os.getenv("VERSION", "Bellsz Bot v1.0 [Liquidez Lateral]")

# ══════════════════════════════════════════════════════════════
# API KEYS (variables de entorno en Railway)
# ══════════════════════════════════════════════════════════════
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
API_KEY          = BINGX_API_KEY
API_SECRET       = BINGX_SECRET_KEY

# ══════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════
EXCHANGE  = "bingx"
LEVERAGE  = int(os.getenv("LEVERAGE", "10"))
MODO_DEMO = os.getenv("BINGX_MODE", os.getenv("MODO_DEMO", "false")).lower() in ("true", "demo")

# ══════════════════════════════════════════════════════════════
# MEMORIA
# ══════════════════════════════════════════════════════════════
MEMORY_DIR = os.getenv("MEMORY_DIR", "/app/data")

# ══════════════════════════════════════════════════════════════
# TAMAÑO DE POSICIÓN Y COMPOUNDING
# ══════════════════════════════════════════════════════════════
TRADE_USDT_BASE    = float(os.getenv("TRADE_USDT_BASE",    "10"))
TRADE_USDT_MAX     = float(os.getenv("TRADE_USDT_MAX",     "100"))
COMPOUND_STEP_USDT = float(os.getenv("COMPOUND_STEP_USDT", "50"))
COMPOUND_ADD_USDT  = float(os.getenv("COMPOUND_ADD_USDT",  "5"))

# ══════════════════════════════════════════════════════════════
# TIMEFRAMES
# ══════════════════════════════════════════════════════════════
TIMEFRAME     = os.getenv("TIMEFRAME", "5m")
CANDLES_LIMIT = int(os.getenv("CANDLES_LIMIT", "200"))

# HTF para niveles de liquidez
HTF_H1_TF    = "1h"
HTF_H4_TF    = "4h"
HTF_D_TF     = "1d"
HTF_CANDLES  = int(os.getenv("HTF_CANDLES", "60"))

# MTF tendencia
MTF_ACTIVO    = os.getenv("MTF_ACTIVO",    "true").lower() == "true"
MTF_TIMEFRAME = os.getenv("MTF_TIMEFRAME", "1h")
MTF_CANDLES   = int(os.getenv("MTF_CANDLES", "100"))
MTF_4H_ACTIVO = os.getenv("MTF_4H_ACTIVO", "true").lower() == "true"

# ══════════════════════════════════════════════════════════════
# INDICADORES BASE
# ══════════════════════════════════════════════════════════════
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))

# EMA para confirmación de tendencia (Capa 2 — Bellsz)
EMA_FAST       = int(os.getenv("EMA_FAST",       "9"))    # EMA rápida
EMA_SLOW       = int(os.getenv("EMA_SLOW",       "21"))   # EMA lenta
EMA_LOCAL_FAST = int(os.getenv("EMA_LOCAL_FAST", "9"))
EMA_LOCAL_SLOW = int(os.getenv("EMA_LOCAL_SLOW", "21"))

# RSI límites (Capa 3 — Bellsz)
RSI_BUY_MAX  = float(os.getenv("RSI_BUY_MAX",  "70"))    # no sobrecomprado
RSI_SELL_MIN = float(os.getenv("RSI_SELL_MIN", "30"))    # no sobrevendido

VWAP_ACTIVO = os.getenv("VWAP_ACTIVO", "true").lower() == "true"
VWAP_PCT    = float(os.getenv("VWAP_PCT", "0.3"))

# ══════════════════════════════════════════════════════════════
# NIVELES DE LIQUIDEZ HTF (núcleo Bellsz)
# ══════════════════════════════════════════════════════════════
LIQ_LOOKBACK  = int(os.getenv("LIQ_LOOKBACK",  "50"))    # velas para buscar BSL/SSL
LIQ_MARGEN    = float(os.getenv("LIQ_MARGEN",  "0.001")) # margen de zona (%)
LIQ_MOSTRAR_H1 = os.getenv("LIQ_MOSTRAR_H1", "true").lower() == "true"
LIQ_MOSTRAR_H4 = os.getenv("LIQ_MOSTRAR_H4", "true").lower() == "true"
LIQ_MOSTRAR_D  = os.getenv("LIQ_MOSTRAR_D",  "true").lower() == "true"

# ══════════════════════════════════════════════════════════════
# SL / TP — Sistema Bellsz (basado en dist_SL, probado en bt_v4)
# ══════════════════════════════════════════════════════════════
SL_ATR_MULT      = float(os.getenv("SL_ATR_MULT",      "1.5"))
TP_DIST_MULT     = float(os.getenv("TP_DIST_MULT",     "3.0"))  # TP = dist_SL x 3
TP1_DIST_MULT    = float(os.getenv("TP1_DIST_MULT",    "1.5"))  # TP1 = dist_SL x 1.5
PARTIAL_TP1_MULT = float(os.getenv("PARTIAL_TP1_MULT", "1.5"))
MIN_RR           = float(os.getenv("MIN_RR",           "2.0"))  # R:R mínimo 1:2

# ══════════════════════════════════════════════════════════════
# TRAILING STOP Y BREAK-EVEN
# ══════════════════════════════════════════════════════════════
TRAILING_ACTIVO    = os.getenv("TRAILING_ACTIVO",    "true").lower() == "true"
TRAILING_ACTIVAR   = float(os.getenv("TRAILING_ACTIVAR",   "1.5"))
TRAILING_DISTANCIA = float(os.getenv("TRAILING_DISTANCIA", "1.0"))

PARTIAL_TP_ACTIVO  = os.getenv("PARTIAL_TP_ACTIVO", "true").lower() == "true"
BE_ACTIVO          = os.getenv("BE_ACTIVO",         "true").lower() == "true"
BE_TRIGGER_ATR     = float(os.getenv("BE_TRIGGER_ATR", "1.0"))

# ══════════════════════════════════════════════════════════════
# TIME EXIT
# ══════════════════════════════════════════════════════════════
TIME_EXIT_HORAS = float(os.getenv("TIME_EXIT_HORAS", "8.0"))

# ══════════════════════════════════════════════════════════════
# SCORE Y POSICIONES
# ══════════════════════════════════════════════════════════════
# Score máximo Bellsz = 10:
#   Capa 1 — Liquidez (hasta 6): Purga H1=1, H4=2, D=3
#   Capa 2 — EMA (hasta 2): cruce=2, tendencia=1
#   Capa 3 — RSI (hasta 2): ok=1, momentum=1
SCORE_MIN      = int(os.getenv("SCORE_MIN",      "5"))   # mín 5/10
MAX_POSICIONES = int(os.getenv("MAX_POSICIONES", "3"))

# ══════════════════════════════════════════════════════════════
# COOLDOWN Y CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════
COOLDOWN_VELAS  = int(os.getenv("COOLDOWN_VELAS",  "5"))
MAX_PERDIDA_DIA = float(os.getenv("MAX_PERDIDA_DIA", "30.0"))

# ══════════════════════════════════════════════════════════════
# FILTROS ADICIONALES
# ══════════════════════════════════════════════════════════════
OB_ACTIVO           = os.getenv("OB_ACTIVO",  "true").lower() == "true"
OB_LOOKBACK         = int(os.getenv("OB_LOOKBACK", "20"))
BOS_ACTIVO          = os.getenv("BOS_ACTIVO", "true").lower() == "true"
FVG_ACTIVO          = os.getenv("FVG_ACTIVO", "true").lower() == "true"
SWEEP_ACTIVO        = os.getenv("SWEEP_ACTIVO", "true").lower() == "true"
SWEEP_LOOKBACK      = int(os.getenv("SWEEP_LOOKBACK", "20"))
DISPLACEMENT_ACTIVO = os.getenv("DISPLACEMENT_ACTIVO", "true").lower() == "true"
PREMIUM_DISCOUNT_ACTIVO = os.getenv("PREMIUM_DISCOUNT_ACTIVO", "true").lower() == "true"
PREMIUM_DISCOUNT_LB     = int(os.getenv("PREMIUM_DISCOUNT_LB", "50"))
CORRELACION_ACTIVO  = os.getenv("CORRELACION_ACTIVO", "true").lower() == "true"
RANGE_ACTIVO        = os.getenv("RANGE_ACTIVO", "false").lower() == "true"
ASIA_RANGE_ACTIVO   = os.getenv("ASIA_RANGE_ACTIVO", "true").lower() == "true"
VELA_CONFIRMACION   = os.getenv("VELA_CONFIRMACION", "true").lower() == "true"
PINBAR_RATIO        = float(os.getenv("PINBAR_RATIO", "0.50"))

# ══════════════════════════════════════════════════════════════
# EQUAL HIGHS / LOWS
# ══════════════════════════════════════════════════════════════
EQ_LOOKBACK  = int(os.getenv("EQ_LOOKBACK",  "50"))
EQ_PIVOT_LEN = int(os.getenv("EQ_PIVOT_LEN", "5"))
EQ_THRESHOLD = float(os.getenv("EQ_THRESHOLD", "0.1"))
PIVOT_NEAR_PCT = float(os.getenv("PIVOT_NEAR_PCT", "0.3"))

# ══════════════════════════════════════════════════════════════
# KILL ZONES (minutos desde 00:00 UTC)
# ══════════════════════════════════════════════════════════════
KZ_ASIA_START   = int(os.getenv("KZ_ASIA_START",   "0"))
KZ_ASIA_END     = int(os.getenv("KZ_ASIA_END",     "240"))
KZ_LONDON_START = int(os.getenv("KZ_LONDON_START", "480"))
KZ_LONDON_END   = int(os.getenv("KZ_LONDON_END",   "720"))
KZ_NY_START     = int(os.getenv("KZ_NY_START",     "780"))
KZ_NY_END       = int(os.getenv("KZ_NY_END",       "960"))

# ══════════════════════════════════════════════════════════════
# PARES
# ══════════════════════════════════════════════════════════════
SOLO_LONG          = os.getenv("SOLO_LONG", "false").lower() == "true"
PARES_BLOQUEADOS:   list = [p.strip() for p in os.getenv("PARES_BLOQUEADOS", "").split(",") if p.strip()]
PARES_PRIORITARIOS: list = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
    "NEAR-USDT", "AVAX-USDT", "ARB-USDT", "OP-USDT",
]

# ══════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════
VOLUMEN_MIN_24H  = float(os.getenv("VOLUMEN_MIN_24H", "5000000"))
MAX_PARES_SCAN   = int(os.getenv("MAX_PARES_SCAN",    "60"))
ANALISIS_WORKERS = int(os.getenv("ANALISIS_WORKERS",  "4"))

# ══════════════════════════════════════════════════════════════
# LOOP
# ══════════════════════════════════════════════════════════════
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))

# ══════════════════════════════════════════════════════════════
# METACLAW (IA validación — requiere ANTHROPIC_API_KEY)
# ══════════════════════════════════════════════════════════════
METACLAW_ACTIVO      = os.getenv("METACLAW_ACTIVO", "false").lower() == "true"
METACLAW_VETO_MINIMO = int(os.getenv("METACLAW_VETO_MINIMO", "7"))

# ══════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ══════════════════════════════════════════════════════════════
# VALIDACIÓN
# ══════════════════════════════════════════════════════════════
def validar() -> list:
    errores = []
    if not BINGX_API_KEY:    errores.append("BINGX_API_KEY no configurada")
    if not BINGX_SECRET_KEY: errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:   errores.append("TELEGRAM_TOKEN no configurado — sin notificaciones")
    if TRADE_USDT_BASE <= 0: errores.append("TRADE_USDT_BASE debe ser > 0")
    if LEVERAGE <= 0:        errores.append("LEVERAGE debe ser > 0")
    return errores
