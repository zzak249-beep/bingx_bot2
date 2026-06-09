"""
GUA Bot v2 — Configuración Multi-Par
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ── BingX ──────────────────────────────────────────────────────────────────────
BINGX_API_KEY  = os.getenv("BINGX_API_KEY", "")
BINGX_SECRET   = os.getenv("BINGX_SECRET", "")
BASE_URL       = "https://open-api.bingx.com"

# ── Multi-par: pares a escanear ────────────────────────────────────────────────
# Seleccionados por: volumen > $10M/día en BingX, estructura SMC clara, volatilidad
_default_symbols = (
    "GUA-USDT,"     # primario del usuario
    "SOL-USDT,"     # mejor SMC en cripto
    "ETH-USDT,"     # institucional, FVGs claros
    "BNB-USDT,"     # estructura limpia
    "DOGE-USDT,"    # sweeps y momentum claros
    "XRP-USDT,"     # buena estructura ICT
    "SUI-USDT,"     # trending, buena volatilidad
    "AVAX-USDT,"    # FVGs frecuentes
    "LINK-USDT,"    # SMC muy limpio
    "WIF-USDT,"     # meme, alta vol, sweeps nítidos
    "PEPE-USDT,"    # ultra volátil, señales rápidas
    "BTC-USDT"      # referencia macro
)
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", _default_symbols).split(",") if s.strip()]

# ── Temporalidades ─────────────────────────────────────────────────────────────
INTERVAL       = os.getenv("INTERVAL",       "3m")
INTERVAL_TREND = os.getenv("INTERVAL_TREND", "15m")
INTERVAL_MACRO = os.getenv("INTERVAL_MACRO", "1h")
LOOKBACK       = 150
LOOKBACK_TREND = 100
LOOKBACK_MACRO = 72

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Modo ── CAMBIA A LIVE EN RAILWAY ──────────────────────────────────────────
MODE = os.getenv("MODE", "SIGNAL")  # SIGNAL | LIVE

# ── Tamaño fijo de trade ───────────────────────────────────────────────────────
# 10 USDT de margen por trade (× leverage = notional)
TRADE_USDT      = float(os.getenv("TRADE_USDT", "10.0"))
LEVERAGE        = int(os.getenv("LEVERAGE",     "5"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "1"))

# ── ATR ────────────────────────────────────────────────────────────────────────
ATR_SL_MULT      = float(os.getenv("ATR_SL_MULT",      "1.5"))
ATR_TP1_MULT     = float(os.getenv("ATR_TP1_MULT",     "2.0"))
ATR_TP2_MULT     = float(os.getenv("ATR_TP2_MULT",     "4.0"))
ATR_TRAIL_MULT   = float(os.getenv("ATR_TRAIL_MULT",   "1.0"))
ATR_HIGHVOL_MULT = float(os.getenv("ATR_HIGHVOL_MULT", "2.0"))

# ── Indicadores ────────────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_OB     = float(os.getenv("RSI_OB",  "63"))
RSI_OS     = float(os.getenv("RSI_OS",  "37"))
EMA_FAST   = 9;  EMA_SLOW = 21;  EMA_TREND = 50;  EMA_MACRO = 200
ADX_PERIOD = 14
ADX_MIN    = float(os.getenv("ADX_MIN", "18"))

# ── TTM Squeeze ────────────────────────────────────────────────────────────────
BB_PERIOD = 20;  BB_MULT = 2.0
KC_PERIOD = 20;  KC_MULT = 1.5
MOM_PERIOD = 12

# ── VWAP ──────────────────────────────────────────────────────────────────────
VWAP_PERIOD   = 60
VWAP_BAND_MULT = 1.5

# ── RVOL ──────────────────────────────────────────────────────────────────────
RVOL_PERIOD = 20
RVOL_MIN    = float(os.getenv("RVOL_MIN", "1.0"))

# ── CVD ────────────────────────────────────────────────────────────────────────
CVD_LB     = 20
CVD_DIV_LB = 10

# ── FVG ────────────────────────────────────────────────────────────────────────
FVG_LOOKBACK = 30
FVG_MIN_SIZE = float(os.getenv("FVG_MIN_SIZE", "0.002"))

# ── Order Blocks ───────────────────────────────────────────────────────────────
OB_LOOKBACK     = 40
OB_IMPULSE_BARS = 3

# ── Liquidity Sweeps ───────────────────────────────────────────────────────────
LIQ_LOOKBACK  = 25
LIQ_TOLERANCE = float(os.getenv("LIQ_TOLERANCE", "0.003"))

# ── ATR Percentil ──────────────────────────────────────────────────────────────
ATR_PERCENTILE_LB = 50

# ── Funding ────────────────────────────────────────────────────────────────────
FUNDING_EXTREME_LONG  = float(os.getenv("FUNDING_EXTREME_LONG",  "0.0003"))
FUNDING_EXTREME_SHORT = float(os.getenv("FUNDING_EXTREME_SHORT", "-0.0003"))

# ── OI ─────────────────────────────────────────────────────────────────────────
OI_HISTORY_LEN = 5

# ── Señal ──────────────────────────────────────────────────────────────────────
SCORE_THR = float(os.getenv("SCORE_THR", "0.55"))

# ── Cooldown ───────────────────────────────────────────────────────────────────
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "15"))

# ── Sesión ─────────────────────────────────────────────────────────────────────
SESSION_FILTER = os.getenv("SESSION_FILTER", "false").lower() == "true"
SESSION_HOURS  = [(0, 24)]

# ── Order Book Imbalance ───────────────────────────────────────────────────────
OB_IMBALANCE_THR = float(os.getenv("OB_IMBALANCE_THR", "0.60"))

# ── Health ─────────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "8080"))
