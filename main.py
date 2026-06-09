"""
GUA Bot v2 — Scanner Multi-Par
Escanea 12 pares en paralelo, abre el mejor setup · 10 USDT fijos.
"""

from __future__ import annotations
import asyncio, logging, signal, sys, time
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import health
from exchange import BingXClient
from notifier import Notifier
from position_manager import PositionManager
from strategy import Signal, analyze

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
    handlers= [logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("main")

_client   = BingXClient()
_notifier = Notifier()
_pm       = PositionManager(_client, _notifier)
_running  = True


# ── Scan de un símbolo ─────────────────────────────────────────────────────────

async def scan_symbol(symbol: str) -> Optional[Signal]:
    try:
        candles, candles_trend, candles_macro, funding, oi, ob_imb = await asyncio.gather(
            _client.get_klines(symbol, config.INTERVAL,       config.LOOKBACK),
            _client.get_klines(symbol, config.INTERVAL_TREND, config.LOOKBACK_TREND),
            _client.get_klines(symbol, config.INTERVAL_MACRO, config.LOOKBACK_MACRO),
            _client.get_funding_rate(symbol),
            _client.get_open_interest(symbol),
            _client.get_order_book_imbalance(symbol),
        )

        if not candles:
            return None

        sig = analyze(symbol, candles, candles_trend, candles_macro, funding, oi)

        if sig is None:
            return None

        # Filtro Order Book Imbalance
        if sig.direction == "SHORT" and ob_imb >  config.OB_IMBALANCE_THR:
            log.debug("%s OB_imb=%.2f bloquea SHORT", symbol, ob_imb)
            return None
        if sig.direction == "LONG"  and ob_imb < -config.OB_IMBALANCE_THR:
            log.debug("%s OB_imb=%.2f bloquea LONG", symbol, ob_imb)
            return None

        return sig

    except Exception as e:
        log.warning("Error scan %s: %s", symbol, e)
        return None


# ── Scan principal (cada 3 min) ────────────────────────────────────────────────

async def scan_task() -> None:
    health.register_tick()
    try:
        log.info("── SCAN %d pares [MODE=%s] ──", len(config.SYMBOLS), config.MODE)

        # Monitor posición activa antes de buscar nuevas
        if _pm.has_position:
            sym   = _pm.active_symbol()
            price = await _client.get_price(sym)
            await _pm.monitor(price)
            log.info("Posición abierta en %s @ %.5f — monitoreando", sym, price)
            return

        if _pm.in_cooldown:
            log.info("Cooldown activo — skip")
            return

        # Escanear todos en paralelo
        results = await asyncio.gather(
            *[scan_symbol(s) for s in config.SYMBOLS],
            return_exceptions=True,
        )

        signals: List[Signal] = [
            r for r in results
            if isinstance(r, Signal) and r.score >= config.SCORE_THR
        ]

        if not signals:
            log.info("Sin señales en %d pares escaneados", len(config.SYMBOLS))
            return

        # Elegir la señal con mayor score
        best = max(signals, key=lambda s: s.score)

        log.info("✅ MEJOR: %s %s score=%.0f%% rsi=%.1f adx=%.1f rvol=%.2fx",
                 best.symbol, best.direction, best.score*100,
                 best.rsi, best.adx, best.rvol)

        # Log de todos los candidatos
        for s in sorted(signals, key=lambda x: x.score, reverse=True):
            log.info("  → %s %s %.0f%%", s.symbol, s.direction, s.score*100)

        health.register_signal()
        await _notifier.send_signal(best)

        if config.MODE == "LIVE":
            await _pm.open_position(best)

    except Exception as e:
        log.error("scan_task: %s", e, exc_info=True)
        await _notifier.send_error(f"scan_task: {e}")


# ── Monitor rápido cada 5s ─────────────────────────────────────────────────────

async def monitor_task() -> None:
    if not _pm.has_position:
        return
    try:
        sym   = _pm.active_symbol()
        price = await _client.get_price(sym)
        await _pm.monitor(price)
    except Exception as e:
        log.error("monitor_task: %s", e)


# ── Heartbeat cada 30 min ──────────────────────────────────────────────────────

async def heartbeat_task() -> None:
    try:
        sym   = _pm.active_symbol() or config.SYMBOLS[0]
        price = await _client.get_price(sym)
    except Exception:
        price = 0.0
    await _notifier.send_status(
        f"Escaneando {len(config.SYMBOLS)} pares\n"
        f"{_pm.status(price)}\n"
        f"💵 Trade fijo: {config.TRADE_USDT:.0f} USDT × {config.LEVERAGE}x\n"
        f"⚙️ Modo: *{config.MODE}*"
    )


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    global _running
    log.info("═══════════════════════════════════════")
    log.info("  GUA Bot v2 — Multi-Par Scanner")
    log.info("  Modo: %s | Pares: %d | Trade: %.0f USDT",
             config.MODE, len(config.SYMBOLS), config.TRADE_USDT)
    log.info("  %s", " · ".join(config.SYMBOLS))
    log.info("═══════════════════════════════════════")

    await health.start_health_server()
    await _notifier.send_startup()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(scan_task,      "cron",     minute="*/3", second=5,
                      id="scan",      max_instances=1, misfire_grace_time=30)
    scheduler.add_job(monitor_task,   "interval", seconds=5,
                      id="monitor",   max_instances=1)
    scheduler.add_job(heartbeat_task, "interval", minutes=30,
                      id="heartbeat")
    scheduler.start()

    await asyncio.sleep(3)
    await scan_task()

    loop = asyncio.get_event_loop()
    def _stop(*_):
        global _running; _running = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    while _running:
        await asyncio.sleep(1)

    scheduler.shutdown(wait=False)
    await _client.close()
    await _notifier.close()
    log.info("Bot detenido")


if __name__ == "__main__":
    asyncio.run(main())
