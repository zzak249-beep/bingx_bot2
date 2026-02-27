"""
BingX Trading Bot — Punto de entrada
Squeeze Momentum + SuperTrend + VWAP | 8 USDT x 7x | Telegram alerts
"""
import asyncio
import logging
import signal
import sys

from core.bot import TradingBot
from config   import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


async def main():
    config = Config()
    config.validate()

    logger.info("=" * 55)
    logger.info("BingX Scalping Bot")
    logger.info(f"Par:       {config.SYMBOL}")
    logger.info(f"Timeframe: {config.TIMEFRAME}")
    logger.info(f"Por trade: {config.TRADE_USDT} USDT x {config.LEVERAGE}x")
    logger.info(f"RR ratio:  1:{config.TAKE_PROFIT_R}")
    logger.info(f"Paper:     {config.PAPER_MODE}")
    logger.info("=" * 55)

    bot  = TradingBot(config)
    loop = asyncio.get_event_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop("SIGTERM")))

    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.stop("KeyboardInterrupt")
    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
        await bot.stop(str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
