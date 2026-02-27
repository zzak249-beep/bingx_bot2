"""
Configuración central — lee variables de entorno.
Railway: Settings → Variables → añade cada variable.
Local:   copia .env.example a .env y rellena.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── API BingX
    API_KEY:    str = os.getenv("BINGX_API_KEY", "")
    API_SECRET: str = os.getenv("BINGX_API_SECRET", "")
    BASE_URL:   str = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com")

    # ── Trading
    SYMBOL:        str   = os.getenv("SYMBOL",        "BTC-USDT")
    TIMEFRAME:     str   = os.getenv("TIMEFRAME",     "5m")
    LEVERAGE:      int   = int(os.getenv("LEVERAGE",  "7"))       # 7x fijo
    TRADE_USDT:    float = float(os.getenv("TRADE_USDT", "8.0")) # 8 USDT fijo
    TAKE_PROFIT_R: float = float(os.getenv("TAKE_PROFIT_R", "2.0"))

    # ── Squeeze Momentum
    SQZ_BB_LEN:  int   = int(os.getenv("SQZ_BB_LEN",   "20"))
    SQZ_BB_MULT: float = float(os.getenv("SQZ_BB_MULT", "2.0"))
    SQZ_KC_LEN:  int   = int(os.getenv("SQZ_KC_LEN",   "20"))
    SQZ_KC_MULT: float = float(os.getenv("SQZ_KC_MULT", "1.5"))
    SQZ_MOM_LEN: int   = int(os.getenv("SQZ_MOM_LEN",  "12"))

    # ── SuperTrend
    ST_ATR_LEN: int   = int(os.getenv("ST_ATR_LEN", "7"))
    ST_FACTOR:  float = float(os.getenv("ST_FACTOR", "2.0"))

    # ── VWAP
    VWAP_SD2: float = float(os.getenv("VWAP_SD2", "2.0"))

    # ── Paper mode
    PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"

    # ── Telegram
    TELEGRAM_TOKEN:   str = os.getenv("TELEGRAM_TOKEN",   "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Timing
    CANDLES_LIMIT:  int = int(os.getenv("CANDLES_LIMIT",  "200"))
    LOOP_SLEEP_SEC: int = int(os.getenv("LOOP_SLEEP_SEC", "10"))

    def validate(self):
        import logging
        log = logging.getLogger("config")
        if not self.PAPER_MODE:
            if not self.API_KEY or not self.API_SECRET:
                raise ValueError("BINGX_API_KEY y BINGX_API_SECRET son obligatorios en modo real.")
            log.warning("⚡ MODO REAL ACTIVADO")
        log.info(f"Colateral por trade: {self.TRADE_USDT} USDT x {self.LEVERAGE}x = {self.TRADE_USDT * self.LEVERAGE:.0f} USDT nocional")
