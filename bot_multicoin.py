"""
Sniper Bot V26.1 — Modo Multi-Coin con Escáner
Cada 15 min escanea el mercado completo.
Las mejores coins pasan al motor de trading.
"""

import asyncio
import logging
import os

from .exchange import BingXClient
from .strategy import SniperStrategy
from .scanner  import MarketScanner, SCORE_THRESHOLD
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

os.makedirs("logs", exist_ok=True)


async def main():
    log.info("🚀 Sniper Bot V26.1 Multi-Coin Scanner — Iniciando...")

    exchange = BingXClient(
        api_key    = os.environ["BINGX_API_KEY"],
        api_secret = os.environ["BINGX_API_SECRET"],
    )
    telegram = TelegramNotifier(
        token   = os.environ["TELEGRAM_TOKEN"],
        chat_id = os.environ["TELEGRAM_CHAT_ID"],
    )
    risk = RiskManager(
        max_risk_pct = float(os.getenv("MAX_RISK_PCT", "1.0")),
        rr_ratio     = 3.0,
    )
    scanner  = MarketScanner(exchange=exchange, telegram=telegram)
    strategy = SniperStrategy(exchange=exchange, risk=risk, telegram=telegram)

    timeframe = os.getenv("TIMEFRAME", "15m")

    await telegram.send(
        "🟢 *Sniper Bot V26.1 ACTIVO*\n"
        f"Modo: *Multi-Coin Scanner*\n"
        f"Timeframe: `{timeframe}`\n"
        f"Score mínimo: `{SCORE_THRESHOLD}/100`\n"
        f"Top N coins: `{os.getenv('SCAN_TOP_N','10')}`"
    )

    # Lanzar escáner y motor de trading en paralelo
    await asyncio.gather(
        scanner_loop(scanner, strategy, timeframe),
        trading_watchdog(strategy, scanner),
    )


async def scanner_loop(scanner: MarketScanner, strategy: SniperStrategy, timeframe: str):
    """Bucle de escaneo: cada X minutos rankea el mercado."""
    while True:
        try:
            coins = await scanner.scan(timeframe)
            await scanner.notify_scan_results(coins)

            # Pasar coins operables al motor de trading
            operables = [c for c in coins if c.score >= SCORE_THRESHOLD and c.direction != "NEUTRAL"]
            strategy.update_watchlist(operables)

        except Exception as e:
            log.error(f"Scanner error: {e}", exc_info=True)

        await asyncio.sleep(int(os.getenv("SCAN_INTERVAL_MIN", "15")) * 60)


async def trading_watchdog(strategy: SniperStrategy, scanner: MarketScanner):
    """Bucle de trading: cada minuto revisa coins en watchlist."""
    while True:
        try:
            for coin in strategy.watchlist:
                await strategy.run_cycle(coin.symbol, os.getenv("TIMEFRAME", "15m"))
                await asyncio.sleep(2)  # pequeña pausa entre coins
        except Exception as e:
            log.error(f"Trading error: {e}", exc_info=True)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
