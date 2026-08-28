"""
Configuración del bot RSI doble suelo + SuperTrend. Proyecto APARTE
del bot de reversión — mismo patrón de dos cerrojos para LIVE, mismo
estilo de variables de entorno, pero sin ninguno de los filtros de
amplitud/ER/radar 30m del otro bot: esto es una traducción fiel del
script Pine, no una versión reducida del bot principal.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "si", "sí")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ── Modo ──────────────────────────────────────────────────────────────
MODE = os.getenv("MODE", "SIGNAL").strip().upper()
LIVE_CONFIRMED = _bool("LIVE_CONFIRMED", False)

# ── BingX ─────────────────────────────────────────────────────────────
BINGX_API_KEY = os.getenv("BINGX_API_KEY", "").strip()
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET", "").strip()
BINGX_BASE_URL = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com").strip()

# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()

# ── Universo ──────────────────────────────────────────────────────────
TIMEFRAME = os.getenv("TIMEFRAME", "15m").strip()
SCAN_INTERVAL_SEC = _int("SCAN_INTERVAL_SEC", 60)
MAX_SYMBOLS = _int("MAX_SYMBOLS", 0)  # 0 = sin límite, opera el universo completo
SYMBOL_WHITELIST = [s.strip().upper() for s in os.getenv("SYMBOL_WHITELIST", "").split(",") if s.strip()]
EXCLUDE_PREFIXES = [p.strip().upper() for p in os.getenv("EXCLUDE_PREFIXES", "NC").split(",") if p.strip()]

# ── Estrategia (igual que el script Pine original) ─────────────────────
RSI_LENGTH = _int("RSI_LENGTH", 10)
RSI_SIGNAL_LENGTH = _int("RSI_SIGNAL_LENGTH", 10)
RSI_TRIGGER = _float("RSI_TRIGGER", 50.0)
RSI_TARGET_CROSSES = _int("RSI_TARGET_CROSSES", 2)
ST_ATR_PERIOD = _int("ST_ATR_PERIOD", 10)
ST_FACTOR = _float("ST_FACTOR", 2.5)

# ── Riesgo ────────────────────────────────────────────────────────────
RISK_PCT = _float("RISK_PCT", 0.25)
LEVERAGE = _int("LEVERAGE", 3)
# Límite de posiciones simultáneas — el script Pine original NO tiene
# esto (cada símbolo es independiente), así que por defecto no limita.
# Ponlo a mano si quieres acotar el riesgo agregado en LIVE.
MAX_CONCURRENT = _int("MAX_CONCURRENT", 0)  # 0 = sin límite

# Minutos mínimos antes de poder volver a abrir el MISMO símbolo tras
# cerrarlo. Defensa adicional, independiente del arreglo del bug de
# cierre prematuro: aunque ya no cierre al instante por error, un
# mercado muy picado podría generar dos dobles-suelo RSI legítimos
# muy seguidos en el mismo símbolo, y no siempre conviene perseguirlos.
REENTRY_COOLDOWN_MIN = _int("REENTRY_COOLDOWN_MIN", 15)

# Riesgo agregado máximo, sumando lo arriesgado en TODAS las posiciones
# abiertas a la vez (aprox: nº de posiciones × RISK_PCT). MAX_CONCURRENT
# limita CUÁNTAS, esto limita CUÁNTO en conjunto — con RISK_PCT alto y
# muchas posiciones abiertas a la vez, el límite de cantidad solo no
# basta para acotar la exposición total.
MAX_TOTAL_RISK_PCT = _float("MAX_TOTAL_RISK_PCT", 3.0)

# ── Circuit breaker (existía el contador, pero nada lo usaba) ──────────
# Con el volumen de señales de este bot, una mala racha en un mercado
# picado puede encadenar pérdidas rápido. Mismo patrón que el bot de
# reversión: tras N pérdidas seguidas, pausa. Antes se contaba
# consecutive_losses pero ningún sitio lo comprobaba — no frenaba nada.
MAX_CONSECUTIVE_LOSSES = _int("MAX_CONSECUTIVE_LOSSES", 4)
COOLDOWN_MINUTES = _int("COOLDOWN_MINUTES", 60)

# ── Liquidez ──────────────────────────────────────────────────────────
# El script Pine original no filtra por liquidez — cada símbolo es
# independiente y el backtest no paga slippage real. En LIVE, un par
# fino con poco volumen paga slippage peor justo cuando más importa: al
# entrar a mercado, y sobre todo si llega a saltar el stop de urgencia.
MIN_QUOTE_VOLUME_24H = _float("MIN_QUOTE_VOLUME_24H", 2_000_000.0)

# ── Stop de emergencia REAL (solo LIVE) ─────────────────────────────────
# El script original no manda ningún stop al exchange: cierra por
# lógica cuando gira el SuperTrend, sondeado por el propio bot. Eso es
# aceptable en SIGNAL, pero en LIVE significa que si el bot se cae, la
# posición queda en el exchange SIN NINGÚN STOP protegiéndola — no es
# una traducción fiel, es un riesgo que el script Pine nunca tuvo que
# afrontar porque nunca gestionó dinero real él solo. Por eso aquí, y
# SOLO en LIVE, se manda además un stop físico de emergencia, ancho
# (bien por detrás del SuperTrend), que no debería tocarse en
# condiciones normales — es la red bajo la red.
#
# IMPORTANTE: este stop, cuando está activado, es también lo que define
# el tamaño de la posición — ver RISK_PCT más abajo. Sin él, RISK_PCT
# no puede controlar una pérdida máxima real y el bot avisa de ello.
EMERGENCY_SL_ENABLED = _bool("EMERGENCY_SL_ENABLED", True)
EMERGENCY_SL_PCT = _float("EMERGENCY_SL_PCT", 8.0)  # % por debajo de la entrada

# ── Avisos ────────────────────────────────────────────────────────────
DAILY_SUMMARY = _bool("DAILY_SUMMARY", True)
DAILY_SUMMARY_HOUR_UTC = _int("DAILY_SUMMARY_HOUR_UTC", 7)
HEARTBEAT_HOURS = _int("HEARTBEAT_HOURS", 12)

# ── Estado ────────────────────────────────────────────────────────────
# Ruta DISTINTA a la del bot de reversión a propósito — si algún día
# corren en el mismo volumen de Railway, no se pisan el estado.
STATE_PATH = os.getenv("STATE_PATH", "/data/state_rsi.json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()


def is_live() -> bool:
    return MODE == "LIVE" and LIVE_CONFIRMED and bool(BINGX_API_KEY) and bool(BINGX_API_SECRET)


def describe() -> str:
    if is_live():
        return "LIVE — enviando órdenes reales a BingX"
    if MODE == "LIVE":
        return "LIVE pedido pero SIN confirmar (falta LIVE_CONFIRMED o claves) — sigue en SIGNAL"
    return "SIGNAL — solo avisos, no toca el exchange"
