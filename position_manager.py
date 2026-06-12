"""
QF×JP Bot v6.5 — Position Manager

FIXES v6.5:
  [BUG #1 CRÍTICO] reconcile_on_startup: be_moved=True en posiciones reconciliadas.
      Causa de 109420 spam: el atr estimado (0.5% entry) disparaba BE inmediatamente
      tras redeploy, intentando cancelar órdenes de posiciones cuyo estado real
      desconocemos. Ahora las posiciones reconciliadas no tocan el SL existente.

  [BUG #2 CRÍTICO] _move_to_breakeven: cualquier fallo de BingX ahora setea
      be_moved=True para evitar el bucle de reintento cada 30 s.
      Si el código es 109420 ("position not exist"), elimina el trade del tracker.

  [BUG #3 IMPORTANTE] _move_to_breakeven: tras BE exitoso, recoloca TP1 y TP2.
      Antes se cancelaban todas las órdenes y el TP nunca se volvía a poner.

  [BUG #4] _calc_pnl: eliminado el ×LEVERAGE. Para futuros lineales USDT
      PnL = (close - entry) × qty  — el leverage ya va implícito en el tamaño.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import config as C
from bingx_client import BingXClient
from risk_manager import RiskManager
import telegram_client as tg

log = logging.getLogger("position_mgr")


# ── Dataclass de trade ────────────────────────────────────────────────────────

@dataclass
class OpenTrade:
    symbol:    str
    direction: str       # LONG | SHORT
    entry:     float
    sl:        float
    tp1:       float
    tp2:       float
    qty:       float
    atr:       float
    order_id:  str
    be_moved:  bool = False
    tp1_hit:   bool = False


# ── Manager ───────────────────────────────────────────────────────────────────

class PositionManager:
    def __init__(self, client: BingXClient, risk: RiskManager):
        self.client = client
        self.risk   = risk
        self._trades: dict[str, OpenTrade] = {}
        self._lock = asyncio.Lock()

    # ── Startup reconciliation ────────────────────────────────────────────────

    async def reconcile_on_startup(self):
        """
        Consulta BingX al arrancar y registra posiciones ya abiertas.
        FIX: be_moved=True en todas las posiciones reconciliadas para que el
        monitor NO intente mover el SL, ya que desconocemos su estado real.
        """
        try:
            real_positions = await self.client.get_open_positions()
        except Exception as e:
            log.warning("reconcile_on_startup: no se pudo obtener posiciones: %s", e)
            return

        if not real_positions:
            log.info("reconcile_on_startup: sin posiciones abiertas en BingX")
            return

        count = 0
        for pos in real_positions:
            sym = pos.get("symbol", "")
            if not sym:
                continue

            amt = float(pos.get("positionAmt", 0) or 0)
            if amt == 0:
                continue

            direction = "LONG" if amt > 0 else "SHORT"
            entry     = float(pos.get("avgPrice", pos.get("entryPrice", 0)) or 0)
            qty       = abs(amt)

            sl  = entry * 0.99  if direction == "LONG"  else entry * 1.01
            tp1 = entry * 1.015 if direction == "LONG"  else entry * 0.985
            tp2 = entry * 1.03  if direction == "LONG"  else entry * 0.97

            trade = OpenTrade(
                symbol=sym,
                direction=direction,
                entry=entry,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                qty=qty,
                atr=entry * 0.005,
                order_id="reconciled",
                be_moved=True,   # ← FIX #1: NO intentar mover SL en posiciones reconciliadas
            )

            async with self._lock:
                self._trades[sym] = trade

            count += 1
            log.info(
                "[%s] Reconciliado: %s qty=%.4f entry=%.6f (be_moved=True — SL intacto)",
                sym, direction, qty, entry,
            )

        if count:
            log.info("reconcile_on_startup: %d posición(es) reconciliada(s)", count)
            await tg.notify_error(
                "reconcile_startup",
                f"{count} posición(es) reconciliada(s) desde BingX tras redeploy",
            )

    # ── Registro / eliminación ────────────────────────────────────────────────

    async def register_trade(self, trade: OpenTrade):
        async with self._lock:
            self._trades[trade.symbol] = trade
        await self.risk.on_trade_opened()
        log.info(
            "[%s] Trade registrado %s entry=%.6f",
            trade.symbol, trade.direction, trade.entry,
        )

    async def remove_trade(self, symbol: str, pnl: float = 0.0):
        async with self._lock:
            self._trades.pop(symbol, None)
        await self.risk.on_trade_closed(pnl)

    # ── Monitor loop ──────────────────────────────────────────────────────────

    async def monitor_loop(self):
        log.info("Position monitor iniciado (intervalo=%ds)", C.POSITION_CHECK_INTERVAL)
        while True:
            try:
                await self._check_all_positions()
            except Exception as e:
                log.error("monitor_loop error: %s", e)
                await tg.notify_error("position_monitor", str(e))
            await asyncio.sleep(C.POSITION_CHECK_INTERVAL)

    async def _check_all_positions(self):
        try:
            real_positions = await self.client.get_open_positions()
        except Exception as e:
            log.warning("get_open_positions failed: %s", e)
            return

        real_map: dict[str, dict] = {
            pos["symbol"]: pos
            for pos in real_positions
            if pos.get("symbol")
        }

        await self.risk.update_open_count(len(real_map))

        async with self._lock:
            tracked = dict(self._trades)

        for symbol, trade in tracked.items():

            # ── Posición cerrada externamente (SL/TP de BingX) ───────────────
            if symbol not in real_map:
                try:
                    ticker      = await self.client.get_ticker(symbol)
                    close_price = float(ticker.get("lastPrice", trade.entry))
                except Exception:
                    close_price = trade.entry

                pnl = self._calc_pnl(trade, close_price)
                log.info("[%s] Posición cerrada externamente. PnL≈%.4f USDT", symbol, pnl)
                await tg.notify_trade_closed(
                    symbol, trade.direction, trade.entry, close_price,
                    trade.qty, "sl_tp_auto", pnl,
                )
                await self.remove_trade(symbol, pnl)
                continue

            # ── Posición abierta — obtener precio actual ──────────────────────
            pos = real_map[symbol]
            try:
                mark_price = float(pos.get("markPrice", 0) or 0)
                if mark_price <= 0:
                    ticker     = await self.client.get_ticker(symbol)
                    mark_price = float(ticker.get("lastPrice", trade.entry))
            except Exception:
                continue

            if mark_price <= 0:
                continue

            # ── Breakeven ─────────────────────────────────────────────────────
            if not trade.be_moved:
                be_trigger = (
                    trade.entry + trade.atr * C.BREAKEVEN_ATR_MULT
                    if trade.direction == "LONG"
                    else trade.entry - trade.atr * C.BREAKEVEN_ATR_MULT
                )
                be_reached = (
                    (trade.direction == "LONG"  and mark_price >= be_trigger) or
                    (trade.direction == "SHORT" and mark_price <= be_trigger)
                )
                if be_reached:
                    await self._move_to_breakeven(trade, mark_price)

            # ── TP1 tracking ──────────────────────────────────────────────────
            if not trade.tp1_hit:
                tp1_hit = (
                    (trade.direction == "LONG"  and mark_price >= trade.tp1) or
                    (trade.direction == "SHORT" and mark_price <= trade.tp1)
                )
                if tp1_hit:
                    trade.tp1_hit = True
                    log.info("[%s] TP1 alcanzado @ %.6f", symbol, mark_price)

    # ── Breakeven ─────────────────────────────────────────────────────────────

    async def _move_to_breakeven(self, trade: OpenTrade, current_price: float):
        """
        Mueve SL a breakeven y recoloca TP1/TP2.

        FIX #2: Cualquier fallo de BingX marca be_moved=True para no reintentar.
                109420 "position not exist" → además elimina el trade del tracker.
        FIX #3: Tras BE exitoso recoloca TP1 y TP2 (antes se perdían al cancelar).
        """
        try:
            positions    = await self.client.get_open_positions()
            symbols_open = {p.get("symbol", "") for p in positions}
            if trade.symbol not in symbols_open:
                log.info("[%s] BE skip — posición ya cerrada en BingX", trade.symbol)
                await self.remove_trade(trade.symbol, 0.0)
                return

            await self.client.cancel_all_orders(trade.symbol)
            await asyncio.sleep(0.3)

            side_close = "SELL" if trade.direction == "LONG" else "BUY"
            resp = await self.client.place_stop_market_order(
                trade.symbol,
                side_close,
                trade.qty,
                trade.entry,
                trade.direction,
                close_position=True,
                order_type="STOP_MARKET",
            )

            if resp.get("code", -1) == 0:
                # ── BE exitoso: recolocar TP1 y TP2 ──────────────────────────
                trade.be_moved = True
                log.info("[%s] SL movido a breakeven @ %.6f", trade.symbol, trade.entry)
                await self._replace_tps(trade, side_close)
            else:
                bx_code = resp.get("code", -1)
                log.warning("[%s] Fallo al mover SL a BE (code=%s): %s",
                            trade.symbol, bx_code, resp)

                # FIX #2: marcar be_moved para no reintentar en los próximos ciclos
                trade.be_moved = True

                # 109420 = "position not exist" → posición ya cerrada, limpiar tracker
                if bx_code == 109420:
                    log.info("[%s] Posición inexistente según BingX, eliminando del tracker",
                             trade.symbol)
                    await self.remove_trade(trade.symbol, 0.0)

        except Exception as e:
            log.error("[%s] _move_to_breakeven error: %s", trade.symbol, e)
            # Evitar bucle de errores
            trade.be_moved = True

    async def _replace_tps(self, trade: OpenTrade, side_close: str):
        """Recoloca TP1 y TP2 tras mover SL a breakeven."""
        try:
            qty_half = self.client._round_qty(trade.symbol, trade.qty / 2)
            tp1_task = self.client.place_stop_market_order(
                trade.symbol, side_close, qty_half, trade.tp1, trade.direction,
                close_position=False, order_type="TAKE_PROFIT_MARKET",
            )
            tp2_task = self.client.place_stop_market_order(
                trade.symbol, side_close, qty_half, trade.tp2, trade.direction,
                close_position=False, order_type="TAKE_PROFIT_MARKET",
            )
            tp1_r, tp2_r = await asyncio.gather(tp1_task, tp2_task,
                                                 return_exceptions=True)
            for name, r in [("TP1", tp1_r), ("TP2", tp2_r)]:
                if isinstance(r, dict) and r.get("code") == 0:
                    log.info("[%s] %s recolocado tras BE", trade.symbol, name)
                else:
                    log.warning("[%s] Fallo al recolocar %s tras BE: %s",
                                trade.symbol, name, r)
        except Exception as e:
            log.error("[%s] _replace_tps error: %s", trade.symbol, e)

    # ── Cierre de emergencia ──────────────────────────────────────────────────

    async def close_position_emergency(self, symbol: str, reason: str = "emergency"):
        async with self._lock:
            trade = self._trades.get(symbol)

        if not trade:
            log.warning("[%s] close_emergency: trade no registrado localmente", symbol)
            return

        try:
            await self.client.cancel_all_orders(symbol)
            await asyncio.sleep(0.2)
            await self.client.close_position_market(symbol, trade.qty, trade.direction)

            ticker      = await self.client.get_ticker(symbol)
            close_price = float(ticker.get("lastPrice", trade.entry))
            pnl         = self._calc_pnl(trade, close_price)

            log.info("[%s] Cierre emergencia. PnL=%.4f USDT", symbol, pnl)
            await tg.notify_trade_closed(
                symbol, trade.direction, trade.entry, close_price,
                trade.qty, reason, pnl,
            )
            await self.remove_trade(symbol, pnl)
        except Exception as e:
            log.error("[%s] close_emergency error: %s", symbol, e)
            await tg.notify_error(f"close_emergency({symbol})", str(e))

    # ── PnL ───────────────────────────────────────────────────────────────────

    def _calc_pnl(self, trade: OpenTrade, close_price: float) -> float:
        """
        PnL real en USDT para futuros lineales (USDT-margined).
        FIX #4: Eliminado ×LEVERAGE — en contratos lineales el leverage determina
        el margen requerido, no el PnL. PnL = (Δprecio) × qty_base.
        """
        if trade.direction == "LONG":
            raw = (close_price - trade.entry) * trade.qty
        else:
            raw = (trade.entry - close_price) * trade.qty
        return round(raw, 4)

    # ── Consultas de estado ───────────────────────────────────────────────────

    def get_tracked(self) -> dict[str, OpenTrade]:
        return dict(self._trades)

    def is_trading(self, symbol: str) -> bool:
        return symbol in self._trades
