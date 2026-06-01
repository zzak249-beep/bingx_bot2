"""
QF×JP Fusion Bot v3.4 — Main Orchestrator
==========================================
Runs the scan loop, processes signals, executes trades, sends Telegram alerts.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from src.engine  import QFEngine, Signal
from src.exchange import BingXClient
from src.telegram import TelegramBot
from src.scanner  import Scanner
from src.risk     import RiskManager
from config.settings import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ]
)
logger = logging.getLogger("bot")


class QFBot:
    def __init__(self, cfg: dict):
        self.cfg      = cfg
        self.engine   = QFEngine(cfg)
        self.exchange = BingXClient(
            api_key    = cfg["bingx_api_key"],
            api_secret = cfg["bingx_api_secret"],
            testnet    = cfg.get("testnet", False),
        )
        self.telegram = TelegramBot(
            token   = cfg["telegram_token"],
            chat_id = cfg["telegram_chat_id"],
        )
        self.scanner  = Scanner(self.exchange, self.engine, cfg)
        self.risk     = RiskManager(cfg)

        self.scan_count       = 0
        self.last_summary_bar = -1
        self._running         = False

    # ── MAIN LOOP ────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        logger.info("🚀 QF×JP Bot v3.4 starting…")
        await self.telegram.send_alert("🚀 <b>QF×JP Bot v3.4 iniciado</b>\nScanner activo — todas las monedas USDT")

        # Refresh balance
        balance = await self.exchange.get_account_balance()
        if balance > 0:
            self.risk.equity = balance
            logger.info(f"Balance: {balance:.2f} USDT")

        scan_interval = self.cfg.get("scan_interval_sec", 30)

        while self._running:
            try:
                t_start = time.monotonic()
                await self._cycle()
                elapsed = time.monotonic() - t_start
                wait = max(0, scan_interval - elapsed)
                logger.debug(f"Scan {self.scan_count} done in {elapsed:.1f}s, waiting {wait:.1f}s")
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                await asyncio.sleep(10)

        await self._shutdown()

    async def _cycle(self):
        self.scan_count += 1

        # ── 1. SCAN ──
        results = await self.scanner.scan_all()

        # ── 2. PROCESS SIGNALS ──
        actionable = self.scanner.get_actionable(results)
        for result in actionable:
            await self._process_signal(result)

        # ── 3. MONITOR OPEN POSITIONS ──
        await self._monitor_positions()

        # ── 4. SUMMARY (every N scans) ──
        summary_every = self.cfg.get("summary_every_scans", 20)
        if self.scan_count % summary_every == 1 and results:
            await self.telegram.send_scan_summary(results)

        # ── 5. DAILY RESET ──
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute < 1:
            self.risk.reset_daily()

    async def _process_signal(self, result):
        """Evaluate signal and optionally execute trade"""
        sig  = result.signal
        sym  = result.symbol
        dir_ = ("LONG"  if sig in (Signal.LONG_SUP,  Signal.LONG_FUEL,  Signal.LONG_STD)
                else "SHORT" if sig in (Signal.SHORT_SUP, Signal.SHORT_FUEL, Signal.SHORT_STD)
                else None)

        # ── Always send Telegram ──
        if sig not in (Signal.NONE,):
            await self.telegram.send_signal(result)

        if dir_ is None:
            return

        # ── Auto-trade if enabled ──
        if not self.cfg.get("auto_trade", False):
            return

        # Skip if already in position or blocked
        if not self.risk.can_trade(sym, dir_):
            return

        # Minimum signal quality for auto-trade
        min_sig_level = self.cfg.get("min_signal_autotrade", "FUEL")
        sig_level_map = {"SUP": 3, "FUEL": 2, "STD": 1}
        sig_level = 3 if "SUP" in sig.value else (2 if "FUEL" in sig.value else 1)
        min_level = sig_level_map.get(min_sig_level, 2)
        if sig_level < min_level:
            return

        # Compute position size
        size = self.risk.compute_size(result, dir_)
        if size <= 0:
            return

        # Set leverage
        leverage = self.cfg.get("leverage", 5)
        await self.exchange.set_leverage(sym, leverage, dir_)

        # Execute
        side     = "BUY" if dir_ == "LONG" else "SELL"
        sl_price = result.sl_long  if dir_ == "LONG"  else result.sl_short
        tp_price = result.tp1_long if dir_ == "LONG"  else result.tp1_short

        order = await self.exchange.place_order(
            symbol=sym,
            side=side,
            quantity=size,
            position_side=dir_,
            stop_loss=sl_price,
            take_profit=tp_price,
        )

        if order.get("code") == 0:
            self.risk.register_open(result, dir_, size)
            logger.info(f"✅ Order placed: {sym} {dir_} size={size}")
            await self.telegram.send_alert(
                f"✅ <b>ORDEN EJECUTADA</b>\n"
                f"<b>{sym}</b> {dir_} × {size}\n"
                f"Entry: {result.close:.6g}  SL: {sl_price:.6g}  TP: {tp_price:.6g}"
            )
        else:
            logger.error(f"Order failed: {sym} {order}")

    async def _monitor_positions(self):
        """Check partial TP, manage open positions"""
        if not self.risk.positions:
            return

        for symbol, pos in list(self.risk.positions.items()):
            try:
                ticker = await self.exchange.get_ticker(symbol)
                price  = float(ticker.get("lastPrice", 0))
                if price <= 0:
                    continue

                # Partial TP
                if self.cfg.get("auto_trade") and self.cfg.get("ptp_on", True):
                    partial = self.risk.check_partial_tp(symbol, price)
                    if partial:
                        close_side = "SELL" if pos.side == "LONG" else "BUY"
                        await self.exchange.place_order(
                            symbol=symbol,
                            side=close_side,
                            quantity=partial,
                            position_side=pos.side,
                        )
                        await self.telegram.send_alert(
                            f"🎯 <b>PARTIAL TP</b> {symbol}\n"
                            f"Cerrado 25% @ {price:.6g} → SL → Breakeven"
                        )

                # Check if SL hit (fallback)
                sl_hit = (pos.side == "LONG"  and price <= pos.sl) or \
                         (pos.side == "SHORT" and price >= pos.sl)
                if sl_hit:
                    self.risk.register_close(symbol, price)
                    await self.telegram.send_alert(f"🛑 SL hit: {symbol} @ {price:.6g}")

            except Exception as e:
                logger.debug(f"Monitor error {symbol}: {e}")

    async def _shutdown(self):
        logger.info("Shutting down…")
        await self.telegram.send_alert("⚠️ Bot detenido")
        await self.exchange.close()
        await self.telegram.close()

    async def status(self) -> str:
        balance = await self.exchange.get_account_balance()
        return (
            f"🤖 <b>QF×JP Bot v3.4 STATUS</b>\n"
            f"Scans: {self.scan_count}\n"
            f"Balance: {balance:.2f} USDT\n\n"
            f"{self.risk.summary()}"
        )


# ── ENTRY POINT ──────────────────────────────────────────────────────

async def main():
    import os
    os.makedirs("logs", exist_ok=True)
    cfg = load_config()
    bot = QFBot(cfg)

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        await bot._shutdown()


if __name__ == "__main__":
    asyncio.run(main())
