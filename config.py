"""
config.py — Carga de configuración desde variables de entorno.

Los parámetros de detección replican 1:1 los `input.*()` del script
Pine "Sweep Reversal Map [Herman]". SWEEP_SL_ATR_BUFFER y
SWEEP_RR_RATIO son diseño propio (el original es un indicator() sin
gestión de trade) — ver sweep_engine.compute_sweep_sl_tp.
"""

import logging
import os

logger = logging.getLogger("sweep_bot.config")


def _clean(raw: str) -> str:
    value = raw.split("#", 1)[0].strip()
    return value.strip("'").strip('"')


def _get_str(key: str, default: str) -> str:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return _clean(raw)


def _get_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return _clean(raw).lower() in ("1", "true", "yes", "on", "si", "sí")


def _get_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(_clean(raw)))
    except ValueError:
        logger.warning("No se pudo parsear %s=%r como int, uso default=%s", key, raw, default)
        return default


def _get_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(_clean(raw))
    except ValueError:
        logger.warning("No se pudo parsear %s=%r como float, uso default=%s", key, raw, default)
        return default


class Config:
    # ── Credenciales BingX ──────────────────────────────────────────
    BINGX_API_KEY = _get_str("BINGX_API_KEY", "")
    BINGX_API_SECRET = _get_str("BINGX_API_SECRET", "")
    BINGX_BASE_URL = _get_str("BINGX_BASE_URL", "https://open-api.bingx.com")
    BINGX_RECV_WINDOW_MS = _get_int("BINGX_RECV_WINDOW_MS", 5000)
    DEMO_MODE = _get_bool("DEMO_MODE", False)

    # ── Telegram ─────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = _get_str("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = _get_str("TELEGRAM_CHAT_ID", "")

    LIVE_TRADING = _get_bool("LIVE_TRADING", True)

    # ── Universo de símbolos ─────────────────────────────────────────
    SYMBOLS = _get_str("SYMBOLS", "ALL")
    # Volumen mínimo en USDT de 24h para vigilar un símbolo en modo ALL, y
    # patrones de nombre a excluir siempre (memecoins con volumen
    # especulativo alto pero no aptos para trading automático de
    # estructura/reversión) -- mismos defaults que el bot wavelet.
    MIN_24H_VOLUME_USDT = _get_float("MIN_24H_VOLUME_USDT", 20_000_000)
    MEME_BLOCKLIST_PATTERNS = [
        s.strip().upper() for s in _get_str(
            "MEME_BLOCKLIST_PATTERNS",
            "BROCCOLI,BANANA,PEPE,DOGE,SHIB,FLOKI,WIF,BONK,MEME,INU,ELON,MOON,SAFE,BABY,CUM,PUMP,GASOLINE"
        ).split(",") if s.strip()
    ]
    SCAN_ALL_MAX_SYMBOLS = _get_int("SCAN_ALL_MAX_SYMBOLS", 150)
    # Umbral de funding rate absoluto por encima del cual se evita abrir
    # una entrada que pagaría funding en contra (0.005 = 0.5% por periodo,
    # bastante permisivo -- solo bloquea funding realmente extremo).
    FUNDING_RATE_MAX_ABS = _get_float("FUNDING_RATE_MAX_ABS", 0.005)
    # El script original no ata esta estrategia a ningún timeframe fijo
    # (a diferencia del wavelet, que es explícitamente "5m"). 15m es un
    # punto de partida razonable para un patrón de estructura/reversión
    # -- suficientemente lento para que swing/estructura signifiquen
    # algo, cámbialo si prefieres otra cosa.
    TIMEFRAME = _get_str("TIMEFRAME", "15m")

    POLL_INTERVAL_SECONDS = _get_int("POLL_INTERVAL_SECONDS", 60)
    SYMBOL_BATCH_SIZE = _get_int("SYMBOL_BATCH_SIZE", 5)
    SYMBOL_BATCH_DELAY_SECONDS = _get_float("SYMBOL_BATCH_DELAY_SECONDS", 1.0)

    # ── Parámetros de detección (idénticos a los inputs del Pine) ───
    SWING_LENGTH = _get_int("SWING_LENGTH", 5)
    SWEEP_ATR_LENGTH = _get_int("SWEEP_ATR_LENGTH", 14)
    MIN_PENETRATION_ATR = _get_float("MIN_PENETRATION_ATR", 0.0)
    STRUCTURE_LENGTH = _get_int("STRUCTURE_LENGTH", 3)
    MAX_CONFIRMATION_BARS = _get_int("MAX_CONFIRMATION_BARS", 12)
    MIN_DISPLACEMENT_ATR = _get_float("MIN_DISPLACEMENT_ATR", 0.2)

    # ── Riesgo ────────────────────────────────────────────────────────
    QTY_PCT = _get_float("QTY_PCT", 10.0)
    LEVERAGE = _get_int("LEVERAGE", 10)
    # Diseño propio (no está en el Pine, ver sweep_engine.compute_sweep_sl_tp)
    SWEEP_SL_ATR_BUFFER = _get_float("SWEEP_SL_ATR_BUFFER", 0.3)
    SWEEP_RR_RATIO = _get_float("SWEEP_RR_RATIO", 2.0)

    # ── Salvaguardas propias del bot ─────────────────────────────────
    MAX_CONCURRENT_POSITIONS = _get_int("MAX_CONCURRENT_POSITIONS", 5)
    SKIP_IF_SYMBOL_HAS_POSITION = _get_bool("SKIP_IF_SYMBOL_HAS_POSITION", True)
    MIN_BALANCE_USDT = _get_float("MIN_BALANCE_USDT", 0.0)
    # Tope duro independiente de MAX_CONCURRENT_POSITIONS, verificado en
    # vivo contra BingX (no contra el snapshot de posiciones del ciclo,
    # que puede quedar desactualizado si varios símbolos entran a la vez
    # en el mismo batch concurrente -- ver Bot._handle_entry).
    HARD_MAX_TOTAL_POSITIONS = _get_int("HARD_MAX_TOTAL_POSITIONS", 5)

    # Secreto para el endpoint /emergency-stop del servidor de salud
    WEBHOOK_SECRET = _get_str("WEBHOOK_SECRET", "")

    HEALTH_PORT = _get_int("PORT", _get_int("HEALTH_PORT", 8080))
    LOG_LEVEL = _get_str("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls):
        missing = []
        if not cls.BINGX_API_KEY:
            missing.append("BINGX_API_KEY")
        if not cls.BINGX_API_SECRET:
            missing.append("BINGX_API_SECRET")
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cls.TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise RuntimeError("Faltan variables de entorno obligatorias: " + ", ".join(missing))

    @classmethod
    def summary(cls) -> str:
        modo = "DEMO (VST)" if cls.DEMO_MODE else "REAL"
        trading = "ACTIVO (envía órdenes reales)" if cls.LIVE_TRADING else "DESACTIVADO (solo señales)"
        return (
            f"Sweep Reversal Map — BingX\n"
            f"Modo cuenta: {modo} | Trading: {trading}\n"
            f"Símbolos: {cls.SYMBOLS} | Timeframe: {cls.TIMEFRAME}\n"
            f"qty_pct={cls.QTY_PCT}% | leverage={cls.LEVERAGE}x | "
            f"max_posiciones_simultaneas={cls.MAX_CONCURRENT_POSITIONS}\n"
            f"swing={cls.SWING_LENGTH} | structure={cls.STRUCTURE_LENGTH} | "
            f"max_confirmation_bars={cls.MAX_CONFIRMATION_BARS} | "
            f"min_displacement={cls.MIN_DISPLACEMENT_ATR}x ATR\n"
            f"SL: nivel barrido ± {cls.SWEEP_SL_ATR_BUFFER}x ATR | TP: RR {cls.SWEEP_RR_RATIO}x"
        )
