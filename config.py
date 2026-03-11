"""
config.py — SMC Bot BingX
Lee todas las variables de entorno (Railway Variables)
"""
import os

VERSION = "SMC-Bot v1.0 [FVG+EQH/EQL+Killzones]"

# ── API KEYS ──────────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY",    "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")

# ── TELEGRAM ──────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── MODO ──────────────────────────────────────────────────────
MODO_DEMO   = os.getenv("MODO_DEMO",   "false").lower() == "true"
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))   # segundos entre ciclos

# ── GESTIÓN DE RIESGO ─────────────────────────────────────────
LEVERAGE        = int(os.getenv("LEVERAGE",        "10"))
MAX_POSICIONES  = int(os.getenv("MAX_POSICIONES",  "3"))
RIESGO_PCT      = float(os.getenv("RIESGO_PCT",    "2.0"))  # % del balance por trade

# TP / SL basados en ATR
TP_ATR_MULT     = float(os.getenv("TP_ATR_MULT",   "2.0"))
SL_ATR_MULT     = float(os.getenv("SL_ATR_MULT",   "1.0"))
PARTIAL_TP1_MULT= float(os.getenv("PARTIAL_TP1_MULT","1.0"))  # TP1 a 1×ATR (50%)
PARTIAL_TP_ACTIVO = os.getenv("PARTIAL_TP_ACTIVO","true").lower() == "true"

# Trailing stop
TRAILING_ACTIVO   = os.getenv("TRAILING_ACTIVO",   "true").lower() == "true"
TRAILING_ACTIVAR  = float(os.getenv("TRAILING_ACTIVAR",  "1.5"))  # activa tras X×ATR en ganancia
TRAILING_DISTANCIA= float(os.getenv("TRAILING_DISTANCIA","1.0"))  # distancia X×ATR

# Time exit
TIME_EXIT_HORAS = float(os.getenv("TIME_EXIT_HORAS", "8"))

# Pérdida máxima diaria (USDT) — 0 = desactivado
MAX_PERDIDA_DIA = float(os.getenv("MAX_PERDIDA_DIA", "0"))

# ── SEÑALES SMC ───────────────────────────────────────────────
# Score mínimo para entrar (1-5 confirmaciones)
SCORE_MIN        = int(os.getenv("SCORE_MIN", "3"))

# FVG
FVG_MIN_PIPS     = float(os.getenv("FVG_MIN_PIPS", "0.0"))

# Equal Highs/Lows
EQ_LOOKBACK      = int(os.getenv("EQ_LOOKBACK",   "50"))
EQ_THRESHOLD     = float(os.getenv("EQ_THRESHOLD", "0.1"))  # tolerancia %
EQ_PIVOT_LEN     = int(os.getenv("EQ_PIVOT_LEN",  "5"))

# Killzones UTC
KZ_ASIA_START    = int(os.getenv("KZ_ASIA_START",   "0"))    # 00:00
KZ_ASIA_END      = int(os.getenv("KZ_ASIA_END",     "240"))  # 04:00
KZ_LONDON_START  = int(os.getenv("KZ_LONDON_START", "420"))  # 07:00
KZ_LONDON_END    = int(os.getenv("KZ_LONDON_END",   "600"))  # 10:00
KZ_NY_START      = int(os.getenv("KZ_NY_START",     "780"))  # 13:00
KZ_NY_END        = int(os.getenv("KZ_NY_END",       "960"))  # 16:00

# Filtros adicionales
EMA_FAST         = int(os.getenv("EMA_FAST",     "21"))
EMA_SLOW         = int(os.getenv("EMA_SLOW",     "50"))
RSI_PERIOD       = int(os.getenv("RSI_PERIOD",   "14"))
RSI_BUY_MAX      = float(os.getenv("RSI_BUY_MAX",  "55"))   # RSI < X para LONG
RSI_SELL_MIN     = float(os.getenv("RSI_SELL_MIN", "45"))   # RSI > X para SHORT
ATR_PERIOD       = int(os.getenv("ATR_PERIOD",   "14"))
PIVOT_NEAR_PCT   = float(os.getenv("PIVOT_NEAR_PCT","0.20"))  # % cercanía al pivot

# Solo LONG (para evitar hedging accidental)
SOLO_LONG        = os.getenv("SOLO_LONG", "false").lower() == "true"

# Pares bloqueados / prioritarios (configurados en memoria o aquí)
PARES_BLOQUEADOS    = [p.strip() for p in os.getenv("PARES_BLOQUEADOS",    "").split(",") if p.strip()]
PARES_PRIORITARIOS  = [p.strip() for p in os.getenv("PARES_PRIORITARIOS",  "").split(",") if p.strip()]

# Timeframe de las velas para análisis
TIMEFRAME        = os.getenv("TIMEFRAME", "5m")   # 1m, 3m, 5m, 15m, 1h
CANDLES_LIMIT    = int(os.getenv("CANDLES_LIMIT", "200"))

# ── VALIDACIÓN ────────────────────────────────────────────────
def validar():
    errores = []
    if not MODO_DEMO:
        if not BINGX_API_KEY:
            errores.append("BINGX_API_KEY no configurada")
        if not BINGX_SECRET_KEY:
            errores.append("BINGX_SECRET_KEY no configurada")
    if not TELEGRAM_TOKEN:
        errores.append("TELEGRAM_TOKEN no configurada (notificaciones desactivadas)")
    if LEVERAGE < 1 or LEVERAGE > 125:
        errores.append(f"LEVERAGE={LEVERAGE} fuera de rango (1-125)")
    return errores
