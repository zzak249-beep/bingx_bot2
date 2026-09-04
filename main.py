"""
main.py — Sweep Reversal Map Bot — BingX

Mismo esqueleto que el bot wavelet (mismo bingx_client, misma forma de
reconciliar posiciones desde BingX, mismo patrón de batches), cambiando
solo el motor de señal (sweep_engine.replay_signal en vez de
wavelet_engine.compute_signal) y el cálculo de SL/TP (depende del
nivel barrido, no de un ATR simétrico).
"""

import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pandas as pd

from bingx_client import BingXClient, BingXAPIError, ERR_POSITION_NOT_EXIST
from config import Config
import risk_manager
import sweep_engine
from state_manager import StateManager, timeframe_to_ms
from telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sweep_bot.main")


def _make_health_handler(bot: "Bot"):
    """Handler con acceso al Bot vía closure -- http.server no tiene
    inyección de dependencias, así que se genera la clase en caliente."""

    class _Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/health"):
                self._json(200, {
                    "status": "ok",
                    "bingx_env": "demo/VST" if Config.DEMO_MODE else "PRODUCCIÓN REAL",
                    "live_trading": Config.LIVE_TRADING,
                    "symbols": Config.SYMBOLS,
                })
                return
            if path == "/positions":
                try:
                    live = [
                        p for p in bot.client.get_positions()
                        if float(p.get("positionAmt", p.get("positionSize", 0)) or 0) != 0
                    ]
                    self._json(200, {"count": len(live), "positions": live})
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            if path.startswith("/emergency-stop/"):
                secret = path.rsplit("/", 1)[-1]
                if not Config.WEBHOOK_SECRET or secret != Config.WEBHOOK_SECRET:
                    self._json(401, {"error": "unauthorized"})
                    return
                result = bot.emergency_stop()
                self._json(200, result)
                return
            self._json(404, {"error": "not found"})

        def log_message(self, *args):
            pass

    return _Handler


def start_health_server(port: int, bot: "Bot") -> None:
    def _serve():
        try:
            HTTPServer(("0.0.0.0", port), _make_health_handler(bot)).serve_forever()
        except OSError as exc:
            logger.warning("No se pudo levantar el servidor de salud en :%d (%s)", port, exc)

    threading.Thread(target=_serve, daemon=True).start()
    logger.info("Servidor de salud escuchando en :%d (/, /positions, /emergency-stop/<secret>)", port)


class Bot:
    def __init__(self):
        self.client = BingXClient(
            Config.BINGX_API_KEY, Config.BINGX_API_SECRET, Config.BINGX_BASE_URL,
            recv_window_ms=Config.BINGX_RECV_WINDOW_MS, demo_mode=Config.DEMO_MODE,
        )
        self.tg = TelegramNotifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
        self.state = StateManager()
        self.timeframe_ms = timeframe_to_ms(Config.TIMEFRAME)
        self._contracts: dict[str, dict] = {}
        self._contracts_fetched_at = 0.0
        # Serializa el tramo "comprobar límite de posiciones + abrir
        # entrada": varios símbolos del mismo batch corren en threads
        # paralelos, y sin este lock todos podrían leer "hay hueco" a la
        # vez contra el mismo snapshot desactualizado y abrir más
        # posiciones de las permitidas simultáneamente.
        self._entry_lock = threading.Lock()
        self._emergency_halted = False

    def refresh_contracts(self, force: bool = False) -> None:
        if not force and (time.time() - self._contracts_fetched_at) < 3600:
            return
        raw = self.client.get_contracts()
        contracts = {}
        for c in raw:
            symbol = c.get("symbol", "")
            if not symbol.endswith("-USDT") or int(c.get("status", 0)) != 1:
                continue
            contracts[symbol] = {
                "quantityPrecision": int(c.get("quantityPrecision", 4)),
                "pricePrecision": int(c.get("pricePrecision", 4)),
                "tradeMinQuantity": float(c.get("tradeMinQuantity", 0) or 0),
                "tradeMinUSDT": float(c.get("tradeMinUSDT", 0) or 0),
            }
        self._contracts = contracts
        self._contracts_fetched_at = time.time()
        logger.info("Contratos USDT-M activos: %d", len(contracts))

    def symbol_universe(self) -> list[str]:
        if Config.SYMBOLS.strip().upper() != "ALL":
            return [s.strip() for s in Config.SYMBOLS.split(",") if s.strip()]

        symbols = list(self._contracts.keys())

        if Config.MEME_BLOCKLIST_PATTERNS:
            before = len(symbols)
            symbols = [
                s for s in symbols
                if not any(p in s.upper() for p in Config.MEME_BLOCKLIST_PATTERNS)
            ]
            if before != len(symbols):
                logger.info("Filtro de nombre: %d símbolos excluidos por MEME_BLOCKLIST_PATTERNS", before - len(symbols))

        volumes = self.client.get_24h_quote_volumes()
        if volumes:
            liquid = [s for s in symbols if volumes.get(s, 0) >= Config.MIN_24H_VOLUME_USDT]
            if liquid:
                liquid.sort(key=lambda s: volumes.get(s, 0), reverse=True)
                symbols = liquid
            else:
                logger.warning("Ningún símbolo supera MIN_24H_VOLUME_USDT=%s, se usa la lista sin filtrar por liquidez",
                                Config.MIN_24H_VOLUME_USDT)
        else:
            logger.warning("No se pudo leer volumen de 24h, se omite el filtro de liquidez este ciclo")

        return symbols[:Config.SCAN_ALL_MAX_SYMBOLS]

    def contract_meta(self, symbol: str) -> dict:
        return self._contracts.get(symbol, {
            "quantityPrecision": 4, "pricePrecision": 4,
            "tradeMinQuantity": 0.0, "tradeMinUSDT": 0.0,
        })

    def reconcile_positions(self) -> dict:
        try:
            positions = self.client.get_positions()
        except Exception as exc:
            logger.error("No se pudieron leer posiciones: %s", exc)
            return self.state.known_positions

        current = {}
        for p in positions:
            amt = float(p.get("positionAmt", p.get("positionSize", 0)) or 0)
            if amt == 0:
                continue
            current[(p.get("symbol"), p.get("positionSide", "BOTH"))] = p

        for key, old in self.state.known_positions.items():
            if key not in current:
                symbol, side = key
                exit_price = old.get("markPrice") or old.get("avgPrice") or 0
                self.tg.exit_notice(symbol, side, float(exit_price or 0))
                logger.info("Posición cerrada detectada: %s %s", symbol, side)

        self.state.known_positions = current
        return current

    def get_equity(self) -> float:
        try:
            bal = self.client.get_balance()
            for key in ("equity", "balance", "availableMargin"):
                if key in bal:
                    return float(bal[key])
            if isinstance(bal, list) and bal:
                return float(bal[0].get("equity", bal[0].get("balance", 0)))
        except Exception as exc:
            logger.error("No se pudo leer el balance: %s", exc)
        return 0.0

    def process_symbol(self, symbol: str, open_positions: dict, equity: float) -> None:
        try:
            if Config.SKIP_IF_SYMBOL_HAS_POSITION:
                if any(sym == symbol for sym, _side in open_positions.keys()):
                    return

            # historial generoso: el replay necesita cubrir cualquier
            # sweep que pudiera seguir activo desde varias barras atrás
            candles = self.client.get_klines(
                symbol, Config.TIMEFRAME,
                limit=max(300, Config.MAX_CONFIRMATION_BARS + Config.STRUCTURE_LENGTH + Config.SWING_LENGTH * 4 + 100),
            )
            if len(candles) < 40:
                return

            now_ms = int(time.time() * 1000)
            if candles[-1]["time"] + self.timeframe_ms > now_ms:
                candles = candles[:-1]
            if not candles:
                return

            df = pd.DataFrame(candles)
            signal = sweep_engine.replay_signal(df, Config)
            if signal is None:
                return

            candle_time = signal["time"]
            if not self.state.can_signal(symbol, candle_time, 1, self.timeframe_ms):
                # cooldown mínimo de 1 barra: nunca proceses la misma
                # vela cerrada dos veces si el sondeo se solapa
                return

            # bearish y bullish son máquinas de estado independientes
            # (igual que en el Pine original): en teoría podrían
            # confirmar ambas en la misma barra. Sin lado claro, no se
            # entra en ninguna -- mejor que elegir una arbitrariamente.
            if signal["long_cond"] and signal["short_cond"]:
                logger.info("%s: long_cond y short_cond confirmados a la vez, señal ambigua, se descarta", symbol)
                return
            side = "LONG" if signal["long_cond"] else ("SHORT" if signal["short_cond"] else None)
            if side is None:
                return

            self.state.mark_signal(symbol, candle_time)
            self._handle_entry(symbol, side, signal, equity, open_positions)

        except BingXAPIError as exc:
            if exc.code == ERR_POSITION_NOT_EXIST:
                return
            logger.warning("Error de API en %s: %s", symbol, exc)
        except Exception as exc:
            logger.exception("Error inesperado procesando %s: %s", symbol, exc)

    def _handle_entry(self, symbol: str, side: str, signal: dict, equity: float, open_positions: dict) -> None:
        meta = self.contract_meta(symbol)
        is_long = side == "LONG"
        entry_price = signal["close"]
        sl_price, tp_price = sweep_engine.compute_sweep_sl_tp(
            entry_price, is_long, signal["swept_level"], signal.get("atr"), Config,
        )

        if Config.MIN_BALANCE_USDT and equity < Config.MIN_BALANCE_USDT:
            self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                            reason="balance por debajo del mínimo configurado")
            return

        sizing = risk_manager.compute_position_size(
            equity, Config.QTY_PCT, entry_price,
            meta["quantityPrecision"], meta["tradeMinQuantity"], meta["tradeMinUSDT"],
        )
        if not sizing.ok:
            self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False, reason=sizing.reason)
            return

        required_margin = sizing.notional / max(Config.LEVERAGE, 1)
        if required_margin > equity * 0.95:
            self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                            reason=f"margen insuficiente (necesita ~{required_margin:.2f} USDT, equity {equity:.2f} USDT)")
            return

        funding_rate = self.client.get_funding_rate(symbol)
        if funding_rate is not None:
            unfavorable = (is_long and funding_rate > Config.FUNDING_RATE_MAX_ABS) or \
                          (not is_long and funding_rate < -Config.FUNDING_RATE_MAX_ABS)
            if unfavorable:
                self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                                reason=f"funding rate desfavorable ({funding_rate:.4%})")
                return

        if not Config.LIVE_TRADING:
            self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                            reason="LIVE_TRADING desactivado")
            return

        # Sección crítica serializada: el batch corre process_symbol() en
        # threads paralelos, así que sin este lock varios símbolos podrían
        # leer "hay hueco" a la vez contra el mismo open_positions
        # (snapshot tomado una vez al principio del ciclo) y abrir más
        # posiciones de las permitidas simultáneamente. Dentro del lock se
        # relee el límite EN VIVO contra BingX, no el snapshot del ciclo.
        with self._entry_lock:
            if self._emergency_halted:
                self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                                reason="parada de emergencia activa")
                return
            if len(open_positions) >= Config.MAX_CONCURRENT_POSITIONS:
                self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                                reason="máximo de posiciones simultáneas alcanzado")
                return

            try:
                live_positions = self.client.get_positions()
                live_count = sum(
                    1 for p in live_positions
                    if float(p.get("positionAmt", p.get("positionSize", 0)) or 0) != 0
                )
            except Exception as exc:
                self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                                reason=f"no se pudo verificar posiciones reales en BingX: {exc}")
                return
            if live_count >= Config.HARD_MAX_TOTAL_POSITIONS:
                self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=False,
                                reason=f"tope duro alcanzado ({live_count} posiciones reales en BingX)")
                return

            try:
                if not self.state.leverage_already_set(symbol):
                    self.client.set_leverage(symbol, side, Config.LEVERAGE)
                    self.state.mark_leverage_set(symbol)

                entry_side = "BUY" if is_long else "SELL"
                exit_side = "SELL" if is_long else "BUY"

                self.client.place_market_order(symbol, entry_side, side, sizing.quantity)
            except Exception as exc:
                logger.exception("Fallo al ejecutar la entrada en %s: %s", symbol, exc)
                self.tg.error(f"entrada {symbol} {side}", str(exc))
                return

            # A partir de aquí la posición YA está abierta en BingX. Si el
            # SL o el TP fallan, NO se debe dejar la posición desprotegida
            # -- se cierra de inmediato en vez de confiar en que el
            # siguiente ciclo lo arregle.
            sl_ok = tp_ok = False
            try:
                self.client.place_stop_market(symbol, exit_side, side, sl_price, close_position=True)
                sl_ok = True
                self.client.place_take_profit_market(symbol, exit_side, side, tp_price, close_position=True)
                tp_ok = True
            except Exception as exc:
                logger.exception("Fallo colocando SL/TP en %s tras abrir la entrada", symbol)
                self.tg.error(f"SL/TP {symbol} {side}", str(exc))

            if not (sl_ok and tp_ok):
                logger.error("%s abierta SIN SL/TP completo (sl_ok=%s tp_ok=%s) -- cerrando de emergencia",
                             symbol, sl_ok, tp_ok)
                try:
                    self.client.cancel_all_open_orders(symbol)
                    self.client.close_position_market(symbol, exit_side, side)
                    self.tg.error(
                        f"{symbol} {side}",
                        "Se abrió pero el SL/TP no se completó -- posición cerrada de inmediato por seguridad.",
                    )
                except Exception as exc:
                    self.tg.error(
                        f"{symbol} {side}",
                        f"🚨🚨 Se abrió SIN SL/TP y el cierre de emergencia TAMBIÉN falló: {exc}. "
                        f"REVISA BINGX A MANO AHORA.",
                    )
                return

            self.tg.signal(symbol, side, entry_price, sl_price, tp_price, executed=True)
            logger.info("Entrada ejecutada: %s %s qty=%s @ %.6g (SL=%.6g TP=%.6g, barrido=%.6g)",
                        symbol, side, sizing.quantity, entry_price, sl_price, tp_price, signal["swept_level"])

    def emergency_stop(self) -> dict:
        """Pausa el trading YA y cierra TODAS las posiciones reales
        abiertas en BingX (consultadas directamente al exchange)."""
        self._emergency_halted = True
        try:
            live = [
                p for p in self.client.get_positions()
                if float(p.get("positionAmt", p.get("positionSize", 0)) or 0) != 0
            ]
        except Exception as exc:
            self.tg.error("parada de emergencia", f"no se pudo leer posiciones: {exc}")
            return {"status": "error", "error": str(exc)}

        closed, failed = [], []
        for p in live:
            symbol = p.get("symbol")
            position_side = p.get("positionSide", "LONG")
            exit_side = "SELL" if position_side == "LONG" else "BUY"
            try:
                self.client.cancel_all_open_orders(symbol)
                self.client.close_position_market(symbol, exit_side, position_side)
                closed.append(symbol)
            except Exception as exc:
                logger.exception("Fallo cerrando %s en parada de emergencia", symbol)
                failed.append([symbol, str(exc)])

        msg = f"🛑 <b>PARADA DE EMERGENCIA</b> — trading pausado.\nCerradas: {closed or 'ninguna'}"
        if failed:
            msg += f"\n⚠️ Fallaron: {failed} — CIÉRRALAS A MANO EN BINGX AHORA."
        self.tg.send(msg)
        return {"status": "stopped", "closed": closed, "failed": failed}

    def run(self) -> None:
        Config.validate()
        start_health_server(Config.HEALTH_PORT, self)
        logger.info("Iniciando bot.\n%s", Config.summary())
        self.tg.info("Bot iniciado.\n" + Config.summary())
        if not Config.DEMO_MODE and Config.LIVE_TRADING:
            self.tg.send(
                "🔴 <b>Bot arrancado en PRODUCCIÓN con LIVE_TRADING=true</b> — "
                "las órdenes que ejecute serán con dinero real."
            )

        self.refresh_contracts(force=True)

        while True:
            cycle_start = time.time()
            try:
                self.refresh_contracts()
                open_positions = self.reconcile_positions()
                equity = self.get_equity()

                if self._emergency_halted:
                    time.sleep(max(1.0, Config.POLL_INTERVAL_SECONDS))
                    continue

                symbols = self.symbol_universe()

                for i in range(0, len(symbols), Config.SYMBOL_BATCH_SIZE):
                    batch = symbols[i:i + Config.SYMBOL_BATCH_SIZE]
                    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                        list(pool.map(lambda s: self.process_symbol(s, open_positions, equity), batch))
                    time.sleep(Config.SYMBOL_BATCH_DELAY_SECONDS)

            except Exception as exc:
                logger.exception("Error en el ciclo principal: %s", exc)
                self.tg.error("ciclo principal", str(exc))

            elapsed = time.time() - cycle_start
            time.sleep(max(1.0, Config.POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    Bot().run()
