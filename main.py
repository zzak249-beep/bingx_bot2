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
        self.volumes: dict[str, float] = {}
        self.last_volume_refresh = 0.0

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

    async def reconcile_startup(self) -> None:
        """
        Se llama UNA vez, antes de entrar en el bucle. Si Railway
        reinicia el bot (redeploy, caída) mientras hay posiciones LIVE
        abiertas, el estado guardado en disco podría no coincidir con
        lo que de verdad hay en el exchange — sin esto, nadie se entera
        y el bot puede seguir gestionando (o creer que gestiona) una
        posición que ya no existe, o ignorar una que sí existe.
        """
        if not self.live:
            return
        try:
            posiciones = await self.api.open_positions()
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo reconciliar contra el exchange al arrancar: %s", exc)
            return

        vivas = {str(p.get("symbol", "")) for p in posiciones if float(p.get("positionAmt", 0) or 0) != 0}
        guardadas = {s for s, p in self.state.data.get("open", {}).items() if p.get("mode") == "LIVE"}

        perdidas = guardadas - vivas  # el bot la creía abierta; el exchange dice que no
        huerfanas = vivas - guardadas  # el exchange tiene una posición que el bot no conoce

        if perdidas:
            for sym in perdidas:
                log.warning(
                    "%s: el bot la creía abierta pero no está en el exchange — se retira sin "
                    "registrar resultado (no hay forma fiable de saber a qué precio cerró de "
                    "verdad mientras el bot estaba caído)",
                    sym,
                )
                self.state.data["open"].pop(sym, None)
            self.state.save()
            await self.tg.send(
                f"⚠️ <b>Reconciliación al arrancar</b>\n"
                f"{len(perdidas)} posición(es) que el bot creía abiertas ya no están en BingX: "
                f"{', '.join(sorted(perdidas))}. Se retiraron del estado SIN registrar ganancia "
                f"ni pérdida — no hay dato fiable del precio real de cierre."
            )

        if huerfanas:
            await self.tg.send(
                f"⚠️ <b>Reconciliación al arrancar</b>\n"
                f"BingX tiene {len(huerfanas)} posición(es) que este bot no gestiona: "
                f"{', '.join(sorted(huerfanas))}. Revísalas a mano — el bot no las va a tocar."
            )

    async def refresh_volumes(self) -> None:
        """Volumen 24h por símbolo, refrescado cada 15 min — no hace
        falta más fresco que eso para un filtro de liquidez mínima."""
        if time.time() - self.last_volume_refresh < 15 * 60 and self.volumes:
            return
        try:
            self.volumes = await self.api.tickers_24h()
            self.last_volume_refresh = time.time()
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo refrescar volúmenes 24h: %s", exc)

    def en_cooldown(self) -> bool:
        return time.time() < self.state.data.get("cooldown_until", 0)

    def riesgo_total_abierto(self) -> float:
        """Suma aproximada de lo arriesgado en todas las posiciones
        abiertas ahora mismo — cada una a RISK_PCT (aprox, no reajusta
        por cambios de equity entre una apertura y otra, pero basta
        para el propósito de acotar la exposición agregada)."""
        return len(self.state.data.get("open", {})) * config.RISK_PCT

    def stats_text(self) -> str:
        d = self.state.data
        cerradas = d.get("closed_trades", 0)
        wins = d.get("wins", 0)
        wr = (wins / cerradas * 100.0) if cerradas else 0.0
        abiertas = len(d.get("open", {}))
        texto = (
            f"Cerradas: {cerradas} · aciertos {wins} ({wr:.0f}%)\n"
            f"Abiertas: {abiertas} · racha: {d.get('consecutive_losses', 0)}"
        )
        if self.en_cooldown():
            minutos = int((d.get("cooldown_until", 0) - time.time()) / 60)
            texto += f"\n⏸️ Circuit breaker activo · quedan ~{max(minutos, 0)} min"
        return texto

    async def start(self) -> None:
        await self.refresh_symbols()
        await self.reconcile_startup()
        await self.tg.send(
            "🤖 <b>Bot RSI doble suelo iniciado</b>\n"
            f"{config.describe()}\n"
            f"RSI({config.RSI_LENGTH}) cruzando SMA({config.RSI_SIGNAL_LENGTH}) bajo {config.RSI_TRIGGER:.0f}\n"
            f"Señal en el cruce nº{config.RSI_TARGET_CROSSES} · "
            f"salida SuperTrend({config.ST_ATR_PERIOD}, {config.ST_FACTOR})\n"
            f"Timeframe {config.TIMEFRAME} · riesgo {config.RISK_PCT}% por operación "
            f"(máx. agregado {config.MAX_TOTAL_RISK_PCT}%)\n"
            f"Circuit breaker: {config.MAX_CONSECUTIVE_LOSSES} pérdidas seguidas · "
            f"pausa {config.COOLDOWN_MINUTES} min\n"
            f"Liquidez mínima: {config.MIN_QUOTE_VOLUME_24H/1e6:.1f}M USDT/24h"
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
        if self.en_cooldown():
            log.info("Circuit breaker activo — sin escanear hasta que pase el enfriamiento")
            return

        await self.refresh_volumes()

        abiertas_activas = len(self.state.data.get("open", {}))
        for sym in self.symbols:
            if config.MAX_CONCURRENT > 0 and abiertas_activas >= config.MAX_CONCURRENT:
                break
            if self.riesgo_total_abierto() + config.RISK_PCT > config.MAX_TOTAL_RISK_PCT:
                log.info("Riesgo agregado al límite (%.2f%%) — sin abrir más por ahora", config.MAX_TOTAL_RISK_PCT)
                break
            if sym in self.state.data.get("open", {}):
                continue
            ultimo_cierre = self.state.data.get("last_close", {}).get(sym, 0)
            if time.time() - ultimo_cierre < config.REENTRY_COOLDOWN_MIN * 60:
                continue
            if self.volumes and self.volumes.get(sym, 0.0) < config.MIN_QUOTE_VOLUME_24H:
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

        if config.EMERGENCY_SL_ENABLED:
            # Tamaño por RIESGO real: cuánto se pierde si salta el stop
            # de emergencia es lo que debe igualar RISK_PCT del equity,
            # no el margen comprometido. ANTES el tamaño salía de
            # equity×RISK_PCT×LEVERAGE, que mide margen, no pérdida
            # posible — con el stop al 8% y leverage 3x, la pérdida real
            # si saltaba el stop rondaba el 0.06% del equity, muy por
            # debajo de lo que RISK_PCT prometía por su nombre.
            riesgo_cash = equity * config.RISK_PCT / 100.0
            riesgo_por_unidad = precio * config.EMERGENCY_SL_PCT / 100.0
            qty = riesgo_cash / riesgo_por_unidad if riesgo_por_unidad > 0 else 0.0
        else:
            # Sin stop de emergencia no hay una distancia de pérdida
            # definida contra la que dimensionar — se cae al criterio
            # antiguo (fracción de margen) y se avisa de que el riesgo
            # real queda SIN acotar.
            log.warning(
                "%s: EMERGENCY_SL_ENABLED=false — el tamaño se calcula por margen, "
                "no por riesgo; una pérdida grande no está acotada por RISK_PCT",
                sig.symbol,
            )
            qty = (equity * config.RISK_PCT / 100.0 * config.LEVERAGE) / precio if precio > 0 else 0.0

        qty = self.api.round_qty(sig.symbol, qty)
        if qty <= 0 or qty < self.api.min_qty(sig.symbol):
            await self.tg.send(f"⚠️ {sig.symbol}: tamaño calculado por debajo del mínimo, señal descartada")
            return

        margen_necesario = qty * precio / config.LEVERAGE if config.LEVERAGE > 0 else qty * precio
        if margen_necesario > equity * 0.9:
            await self.tg.send(
                f"⚠️ {sig.symbol}: el tamaño calculado por riesgo pide más margen del disponible "
                f"({margen_necesario:.2f} USDT sobre {equity:.2f} de equity) — señal descartada"
            )
            return

        try:
            await self.api.set_leverage(sig.symbol, "LONG", config.LEVERAGE)
            await self.api.set_leverage(sig.symbol, "SHORT", config.LEVERAGE)
            if config.EMERGENCY_SL_ENABLED:
                sl_emergencia = precio * (1 - config.EMERGENCY_SL_PCT / 100.0)
                sl_r = self.api.round_price(sig.symbol, sl_emergencia)
                # market_order() de bingx.py exige sl Y tp en la misma
                # orden. Se manda un TP lejano solo para poder mandar el
                # SL real — ×3 y no ×1000: un multiplicador absurdo
                # puede caer fuera de los límites de precio válidos del
                # contrato en BingX y hacer que la orden entera se
                # rechace. ×3 sigue siendo, en la práctica, "nunca se
                # toca" para la vida de esta operación (sale mucho antes
                # por giro de SuperTrend), y es un precio con muchas más
                # garantías de ser válido.
                tp_lejano = self.api.round_price(sig.symbol, precio * 3)
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
            if not entry_rsi.flipped_bearish(velas, config.ST_ATR_PERIOD, config.ST_FACTOR):
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
            if d["consecutive_losses"] >= config.MAX_CONSECUTIVE_LOSSES:
                d["cooldown_until"] = time.time() + config.COOLDOWN_MINUTES * 60
                d["consecutive_losses"] = 0
                # register_close es síncrono (lo llama check_exits, que
                # sí es async) — asyncio.create_task en vez de await,
                # mismo patrón que ya usa el bot de reversión para esto.
                asyncio.create_task(
                    self.tg.send(
                        f"⏸️ <b>Circuit breaker</b>\n"
                        f"{config.MAX_CONSECUTIVE_LOSSES} pérdidas seguidas · "
                        f"pausa de {config.COOLDOWN_MINUTES} min.\n"
                        f"No es un fallo: es el bot dejando de insistir."
                    )
                )
        d.get("open", {}).pop(symbol, None)
        d.setdefault("last_close", {})[symbol] = time.time()
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
