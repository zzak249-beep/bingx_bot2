"""
QF×JP Bot v7.1 — Config TRAILING STOP + ANTI-LIQUIDACIÓN + INDICADORES v3.6
Cambios vs v7.0:
  - Añadidas constantes faltantes para indicators.py v3.6 (Pine Sync):
      CVD_ROLL_WINDOW, EQL_LEN, EQL_TOL, OBP2_DIST, PRE_SCORE
  - Sin estas constantes el bot crasheaba con AttributeError en cada análisis
"""
import os
from dotenv import load_dotenv
load_dotenv()

def _bool(k, d): return os.getenv(k, str(d)).strip().lower() in ("true","1","yes")
def _float(k, d):
    try: return float(os.getenv(k, str(d)))
    except: return d
def _int(k, d):
    try: return int(os.getenv(k, str(d)))
    except: return d
def _list(k, d):
    r = os.getenv(k, d).strip()
    return [x.strip() for x in r.split(",") if x.strip()] if r else []

# ── BingX ─────────────────────────────────────────────────────────────────────
# FIX: .strip() — un espacio/salto de línea invisible al copiar-pegar la
# clave en Railway rompe la firma HMAC en EL 100% de las llamadas (balance,
# set_leverage, entrada...) con error 100001 "signature mismatch", porque
# el secret usado para firmar ya no es exactamente el secret real de BingX.
BINGX_API_KEY    = os.getenv("BINGX_API_KEY", "").strip()
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "").strip()
BINGX_BASE_URL   = "https://open-api.bingx.com"

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ── Modo ──────────────────────────────────────────────────────────────────────
MODE = os.getenv("MODE", "SIGNAL").upper()

# ── Capital y riesgo ──────────────────────────────────────────────────────────
CAPITAL          = _float("CAPITAL", 700.0)
RISK_PCT         = _float("RISK_PCT", 0.5)
LEVERAGE         = _int("LEVERAGE", 10)
MAX_OPEN_TRADES  = _int("MAX_OPEN_TRADES", 3)
MAX_DAILY_TRADES = _int("MAX_DAILY_TRADES", 10)

# ── Umbrales de señal ─────────────────────────────────────────────────────────
MIN_SCORE  = _float("MIN_SCORE",  58.0)
FUEL_SCORE = _float("FUEL_SCORE", 65.0)
SUP_SCORE  = _float("SUP_SCORE",  80.0)
MIN_TIER   = os.getenv("MIN_TIER", "FUEL").upper()

# ── Entrada ───────────────────────────────────────────────────────────────────
# IMPORTANTE: estas 3 son las que más probablemente estén bloqueando TODAS
# las señales. Se pueden cambiar en Railway → Variables sin redeploy:
#   REQUIRE_TL_BREAK=false   → quita el requisito de ruptura exacta de trendline
#   HTF_MIN_ALIGNED=1        → solo exige 1 de 3 timeframes alineado
#   MIN_TIER=STD             → acepta score>=58 en vez de >=65
REQUIRE_TL_BREAK = _bool("REQUIRE_TL_BREAK", True)
HTF_MIN_ALIGNED  = _int("HTF_MIN_ALIGNED", 2)

# ── Scanner ───────────────────────────────────────────────────────────────────
SCAN_INTERVAL   = _int("SCAN_INTERVAL", 60)
TOP_N_SYMBOLS   = _int("TOP_N_SYMBOLS", 0)
BLACKLIST       = set(_list("BLACKLIST", ""))
MIN_VOLUME_USDT = _float("MIN_VOLUME_USDT", 5_000_000.0)

# ── Timeframes ────────────────────────────────────────────────────────────────
TIMEFRAME      = os.getenv("TIMEFRAME",      "3m")
HTF_TIMEFRAME  = os.getenv("HTF_TIMEFRAME",  "15m")
HTF2_TIMEFRAME = os.getenv("HTF2_TIMEFRAME", "1h")
HTF5_TIMEFRAME = os.getenv("HTF5_TIMEFRAME", "4h")

# ── ATR / SL / TP ─────────────────────────────────────────────────────────────
ATR_LEN      = _int("ATR_LEN",       10)
SL_ATR_MULT  = _float("SL_ATR_MULT",  2.0)
TP1_ATR_MULT = _float("TP1_ATR_MULT", 2.0)
TP2_ATR_MULT = _float("TP2_ATR_MULT", 4.0)

# ── ADX ───────────────────────────────────────────────────────────────────────
ADX_LEN     = _int("ADX_LEN", 14)
ADX_TREND   = _float("ADX_TREND",   25.0)
ADX_LATERAL = _float("ADX_LATERAL", 20.0)

# ── Kelly ─────────────────────────────────────────────────────────────────────
KELLY_WIN_RATE = _float("KELLY_WIN_RATE", 0.55)
KELLY_RR       = _float("KELLY_RR",       1.5)
KELLY_FRACTION = _float("KELLY_FRACTION", 0.15)

# ── Circuit Breaker ───────────────────────────────────────────────────────────
CB_ENABLED  = _bool("CB_ENABLED",   True)
CB_ATR_MULT = _float("CB_ATR_MULT", 3.0)
CB_BARS     = _int("CB_BARS",       10)

# ── Gestión de posiciones ─────────────────────────────────────────────────────
POSITION_CHECK_INTERVAL = _int("POSITION_CHECK_INTERVAL", 30)

# ── Trailing Stop Dinámico ────────────────────────────────────────────────────
BREAKEVEN_ATR_MULT = _float("BREAKEVEN_ATR_MULT", 1.0)
TRAIL_DISTANCE_ATR = _float("TRAIL_DISTANCE_ATR", 1.5)

# ── Límite de pérdida diaria ──────────────────────────────────────────────────
DAILY_LOSS_PCT = _float("DAILY_LOSS_PCT", 2.0)

# ── Notional máximo por trade ─────────────────────────────────────────────────
MAX_NOTIONAL_USDT = _float("MAX_NOTIONAL_USDT", 200.0)

# ── Puerto ────────────────────────────────────────────────────────────────────
PORT = _int("PORT", 8080)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Indicadores v3.6 (Pine Sync) — NUEVO en v7.1 ─────────────────────────────
# CRÍTICO: estas 5 constantes son requeridas por indicators.py v3.6.
# Sin ellas el bot lanza AttributeError en cada llamada a analyze() y no
# produce ninguna señal (analyze_error=126 en los logs de Railway).
# ═══════════════════════════════════════════════════════════════════════════════

# CVD rolling window (barras). Pine v3.6 usa 60 (bajado de 100).
CVD_ROLL_WINDOW = _int("CVD_ROLL_WINDOW", 60)

# Equal Highs / Equal Lows detector [EQH/EQL]
EQL_LEN = _int("EQL_LEN",     20)    # lookback en barras
EQL_TOL = _float("EQL_TOL", 0.15)   # tolerancia en múltiplos de ATR

# Order Block Premium approach distance [OBP2]
OBP2_DIST = _float("OBP2_DIST", 1.5)  # distancia al OB en ATR

# Pre-señal anticipatoria [PRE] — score mínimo antes de STD (58)
PRE_SCORE = _float("PRE_SCORE", 45.0)
