"""
Bot RSI doble suelo + SuperTrend — proyecto standalone, traducción
fiel del script Pine "ProBorsa: RSI & SuperTrend Özel Dip Stratejisi".

Solo largo. Sin TP. Sin los filtros de amplitud/ER/radar 30m del bot
de reversión — esto es OTRO bot, no una variante del principal.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

import config
import entry_rsi
from bingx import BingX, BingXError
from notify import State, Telegram

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def fmt_signal(sig: entry_rsi.EntrySignal, live: bool) -> str:
    cabecera = "🟢 EJECUTADO" if live else "🔔 SEÑAL"
    return (
        f"{cabecera} · LARGO {sig.symbol}  (doble suelo RSI)\n"
        f"Entrada {sig.entry:.8g}\n"
        f"SL (SuperTrend) {sig.st_stop:.8g}  ·  riesgo {sig.riesgo_pct:.2f}%\n"
        f"Sin TP: sale cuando gire el SuperTrend\n"
        f"RSI {sig.rsi_actual:.1f} · cruce nº{config.RSI_TARGET_CROSSES} bajo {config.RSI_TRIGGER:.0f} "
        f"· ATR {sig.atr_pct:.2f}%"
    )


def fmt_close(symbol: str, entry: float, exit_price: float, pct: float) -> str:
    icono = "✅" if pct > 0 else "🛑"
    return (
        f"{icono} {symbol} cerrada · giro de SuperTrend\n"
        f"Entrada {entry:.8g} → Salida {exit_price:.8g}  ·  {pct:+.2f}%"
    )


class Bot:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient()
        self.api = BingX(self.client)
        self.tg = Telegram(self.client)
        self.state = State(config.STATE_PATH)
        self.symbols: list[str] = []
        self.live = config.is_live()
        self.last_daily = 0.0
        self.last_heartbeat = time.time()

    async def refresh_symbols(self) -> None:
        try:
            todos = await self.api.symbols()
        except Exception as exc:  # noqa: BLE001
            log.error("No se pudo listar símbolos: %s", exc)
            self.symbols = []
            return
        if config.SYMBOL_WHITELIST:
            self.symbols = [s for s in todos if s in config.SYMBOL_WHITELIST]
        else:
            self.symbols = todos
        if config.MAX_SYMBOLS > 0:
            self.symbols = self.symbols[: config.MAX_SYMBOLS]
        log.info("Universo: %d símbolos", len(self.symbols))

    def stats_text(self) -> str:
        d = self.state.data
        cerradas = d.get("closed_trades", 0)
        wins = d.get("wins", 0)
        wr = (wins / cerradas * 100.0) if cerradas else 0.0
        abiertas = len(d.get("open", {}))
        return (
            f"Cerradas: {cerradas} · aciertos {wins} ({wr:.0f}%)\n"
            f"Abiertas: {abiertas} · racha: {d.get('consecutive_losses', 0)}"
        )

    async def start(self) -> None:
        await self.refresh_symbols()
        await self.tg.send(
            "🤖 <b>Bot RSI doble suelo iniciado</b>\n"
            f"{config.describe()}\n"
            f"RSI({config.RSI_LENGTH}) cruzando SMA({config.RSI_SIGNAL_LENGTH}) bajo {config.RSI_TRIGGER:.0f}\n"
            f"Señal en el cruce nº{config.RSI_TARGET_CROSSES} · "
            f"salida SuperTrend({config.ST_ATR_PERIOD}, {config.ST_FACTOR})\n"
            f"Timeframe {config.TIMEFRAME} · riesgo {config.RISK_PCT}%"
        )
        while True:
            try:
                await self.check_exits()
                await self.scan_once()
                await self.maybe_daily_summary()
                await self.maybe_heartbeat()
            except Exception as exc:  # noqa: BLE001
                log.exception("Error en el ciclo principal: %s", exc)
            await asyncio.sleep(config.SCAN_INTERVAL_SEC)

    # ── entradas ─────────────────────────────────────────────────────
    async def scan_once(self) -> None:
        abiertas_activas = len(self.state.data.get("open", {}))
        for sym in self.symbols:
            if config.MAX_CONCURRENT > 0 and abiertas_activas >= config.MAX_CONCURRENT:
                break
            if sym in self.state.data.get("open", {}):
                continue
            try:
                velas = await self.api.klines(sym, config.TIMEFRAME, limit=200)
            except Exception as exc:  # noqa: BLE001
                log.debug("%s: sin velas (%s)", sym, exc)
                continue

            sig = entry_rsi.evaluate(
                sym, velas,
                rsi_length=config.RSI_LENGTH,
                sig_length=config.RSI_SIGNAL_LENGTH,
                trigger=config.RSI_TRIGGER,
                target_count=config.RSI_TARGET_CROSSES,
                st_period=config.ST_ATR_PERIOD,
                st_factor=config.ST_FACTOR,
            )
            if sig is None:
                continue

            await self.handle_signal(sig)
            abiertas_activas += 1
            await asyncio.sleep(0.2)

    async def handle_signal(self, sig: entry_rsi.EntrySignal) -> None:
        log.info(
            "SEÑAL LARGO %s entrada=%.8g st=%.8g riesgo=%.2f%% rsi=%.1f",
            sig.symbol, sig.entry, sig.st_stop, sig.riesgo_pct, sig.rsi_actual,
        )

        if not self.live:
            await self.tg.send(fmt_signal(sig, live=False))
            self.state.data.setdefault("open", {})[sig.symbol] = {
                "mode": "SIGNAL",
                "entry": sig.entry,
                "qty": 0,
                "opened_at": time.time(),
            }
            self.state.save()
            return

        # LIVE — entrada a mercado. El script Pine original no manda
        # ningún stop al exchange; aquí SÍ se manda uno de emergencia
        # (ver config.py) porque operar sin ningún stop resting en el
        # exchange es un riesgo que el script nunca tuvo que asumir.
        equity = await self.api.balance_usdt()
        precio = sig.entry
        # RISK_PCT como fracción de margen expuesto, apalancado por
        # LEVERAGE — más conservador y explícito que replicar el 100%
        # del equity que usa el backtest de Pine por defecto.
        qty = (equity * config.RISK_PCT / 100.0 * config.LEVERAGE) / precio if precio > 0 else 0.0
        qty = self.api.round_qty(sig.symbol, qty)
        if qty <= 0 or qty < self.api.min_qty(sig.symbol):
            await self.tg.send(f"⚠️ {sig.symbol}: tamaño calculado por debajo del mínimo, señal descartada")
            return

        try:
            await self.api.set_leverage(sig.symbol, "LONG", config.LEVERAGE)
            await self.api.set_leverage(sig.symbol, "SHORT", config.LEVERAGE)
            sl_emergencia = precio * (1 - config.EMERGENCY_SL_PCT / 100.0)
            if config.EMERGENCY_SL_ENABLED:
                sl_r = self.api.round_price(sig.symbol, sl_emergencia)
                # market_order() de bingx.py exige sl Y tp en la misma
                # orden — se manda un tp muy lejano (no debería
                # tocarse nunca) solo para poder mandar el sl real.
                tp_lejano = self.api.round_price(sig.symbol, precio * 1000)
                await self.api.market_order(sig.symbol, "BUY", qty, sl_r, tp_lejano)
            else:
                await self.api.market_order(sig.symbol, "BUY", qty, 0, 0)
        except BingXError as exc:
            await self.tg.send(f"❌ BingX rechazó la orden en {sig.symbol}: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await self.tg.send(f"❌ Error al ejecutar {sig.symbol}: {exc}")
            return

        self.state.data.setdefault("open", {})[sig.symbol] = {
            "mode": "LIVE",
            "entry": sig.entry,
            "qty": qty,
            "opened_at": time.time(),
        }
        self.state.save()
        await self.tg.send(fmt_signal(sig, live=True))

    # ── salidas ──────────────────────────────────────────────────────
    async def check_exits(self) -> None:
        abiertas = self.state.data.get("open", {})
        for symbol, pos in list(abiertas.items()):
            try:
                velas = await self.api.klines(symbol, config.TIMEFRAME, limit=200)
            except Exception as exc:  # noqa: BLE001
                log.debug("%s: no se pudo comprobar salida (%s)", symbol, exc)
                continue
            if not entry_rsi.is_bearish_now(velas, config.ST_ATR_PERIOD, config.ST_FACTOR):
                continue

            exit_price = velas[-2]["close"] if len(velas) >= 2 else velas[-1]["close"]
            entry = float(pos["entry"])
            pct = (exit_price - entry) / entry * 100.0 if entry > 0 else 0.0

            if pos.get("mode") == "LIVE" and self.live:
                try:
                    qty = float(pos.get("qty", 0))
                    if qty > 0:
                        await self.api.close_position(symbol, "BUY", qty)
                except Exception as exc:  # noqa: BLE001
                    await self.tg.send(f"⚠️ No se pudo cerrar {symbol}: {exc}")
                    continue

            self.register_close(symbol, pct)
            await self.tg.send(fmt_close(symbol, entry, exit_price, pct))

    def register_close(self, symbol: str, pct: float) -> None:
        won = pct > 0
        d = self.state.data
        d["closed_trades"] = d.get("closed_trades", 0) + 1
        if won:
            d["wins"] = d.get("wins", 0) + 1
            d["consecutive_losses"] = 0
        else:
            d["losses"] = d.get("losses", 0) + 1
            d["consecutive_losses"] = d.get("consecutive_losses", 0) + 1
        d.get("open", {}).pop(symbol, None)
        historial = d.setdefault("trades", [])
        historial.append({"symbol": symbol, "pct": round(pct, 3), "closed_at": time.time()})
        if len(historial) > 1000:
            del historial[: len(historial) - 1000]
        self.state.save()

    # ── avisos periódicos ────────────────────────────────────────────
    async def maybe_daily_summary(self) -> None:
        if not config.DAILY_SUMMARY:
            return
        ahora = datetime.now(timezone.utc)
        hoy = ahora.strftime("%Y-%m-%d")
        if ahora.hour != config.DAILY_SUMMARY_HOUR_UTC:
            return
        if self.state.data.get("last_summary_date") == hoy:
            return
        self.state.data["last_summary_date"] = hoy
        self.state.save()
        await self.tg.send(
            f"📊 <b>Resumen diario RSI</b> · {hoy}\n"
            f"{config.describe()}\n\n"
            f"{self.stats_text()}\n"
            f"Universo: {len(self.symbols)} símbolos"
        )

    async def maybe_heartbeat(self) -> None:
        if config.HEARTBEAT_HOURS <= 0:
            return
        if time.time() - self.last_heartbeat < config.HEARTBEAT_HOURS * 3600:
            return
        self.last_heartbeat = time.time()
        await self.tg.send(f"💓 Vivo · {self.stats_text()}")


async def main() -> None:
    bot = Bot()
    try:
        await bot.start()
    finally:
        await bot.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
