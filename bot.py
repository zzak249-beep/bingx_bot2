"""
Sniper Bot V26.1 - Institutional Apex
Live Trading: BingX Futures
Signals: EMA Slope Cross + STC + Hull + Volume Institutional
Alerts: Telegram
"""

import asyncio
import logging
import os
from datetime import datetime

from .exchange import BingXClient
from .strategy import SniperStrategy
from .telegram_bot import TelegramNotifier
from .risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ],
)
log = logging.getLogger("SniperBot")


async def main():
    log.info("🚀 Sniper Bot V26.1 Institutional Apex - Iniciando...")

    # Inicializar componentes
    exchange = BingXClient(
        api_key=os.environ["BINGX_API_KEY"],
        api_secret=os.environ["BINGX_API_SECRET"],
    )
    telegram = TelegramNotifier(
        token=os.environ["TELEGRAM_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
    )
    risk = RiskManager(
        max_risk_pct=float(os.getenv("MAX_RISK_PCT", "1.0")),
        rr_ratio=3.0,
    )
    strategy = SniperStrategy(exchange=exchange, risk=risk, telegram=telegram)

    await telegram.send("🟢 *Sniper Bot V26.1 ACTIVO*\nMercado: " + os.getenv("SYMBOL", "BTC-USDT") + "\nTimeframe: " + os.getenv("TIMEFRAME", "15m"))

    symbol   = os.getenv("SYMBOL", "BTC-USDT")
    interval = os.getenv("TIMEFRAME", "15m")

    # Bucle principal
    while True:
        try:
            await strategy.run_cycle(symbol, interval)
        except Exception as e:
            log.error(f"Error en ciclo principal: {e}", exc_info=True)
            await telegram.send(f"⚠️ *Error bot:* `{e}`")
        await asyncio.sleep(60)  # revisa cada minuto


if __name__ == "__main__":
    asyncio.run(main())
