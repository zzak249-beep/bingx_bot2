"""
GUA Bot v2 — Gestor de Posiciones
Trade fijo de TRADE_USDT · Partial TP → BE → Trailing · Multi-par.
"""

from __future__ import annotations
import logging, time
from dataclasses import dataclass, field
from typing import Optional

import config
from exchange import BingXClient
from notifier import Notifier
from strategy import Signal

log = logging.getLogger("pm")


def _calc_qty(price: float) -> float:
    """
    10 USDT de margen × leverage = notional.
    qty = notional / precio, redondeado según magnitud del precio.
    Ej: GUA 0.72 → 10×5/0.72 = 69.4 → round a 1 decimal = 69.4
    """
    notional = config.TRADE_USDT * config.LEVERAGE
    qty = notional / price
    if   price >= 10_000: return round(qty, 6)   # BTC
    elif price >= 1_000:  return round(qty, 5)   # ETH
    elif price >= 100:    return round(qty, 4)   # BNB, SOL
    elif price >= 10:     return round(qty, 3)   # AVAX, LINK
    elif price >= 1:      return round(qty, 2)   # XRP, SUI
    elif price >= 0.1:    return round(qty, 1)   # GUA, DOGE
    else:                 return round(qty, 0)   # PEPE, BONK


@dataclass
class ActivePosition:
    symbol:     str
    direction:  str
    entry:      float
    sl:         float
    tp1:        float
    tp2:        float
    atr:        float
    atr_pct:    float
    qty_total:  float
    qty_left:   float
    tp1_hit:    bool  = False
    trail_sl:   float = 0.0
    opened_at:  float = field(default_factory=time.time)
    peak_price: float = 0.0


class PositionManager:

    def __init__(self, client: BingXClient, notifier: Notifier) -> None:
        self._c   = client
        self._n   = notifier
        self._pos: Optional[ActivePosition] = None
        self._cooldown_until: float = 0.0

    @property
    def has_position(self) -> bool:
        return self._pos is not None

    @property
    def in_cooldown(self) -> bool:
        return time.time() < self._cooldown_until

    def active_symbol(self) -> Optional[str]:
        return self._pos.symbol if self._pos else None

    # ── Apertura ───────────────────────────────────────────────────────────────

    async def open_position(self, signal: Signal) -> None:
        if self.has_position or self.in_cooldown:
            return

        qty = _calc_qty(signal.price)
        if qty <= 0:
            log.error("Qty inválida: %.6f para precio %.5f", qty, signal.price)
            return

        # Verificar balance mínimo
        try:
            balance = await self._c.get_balance()
            if balance < config.TRADE_USDT:
                log.error("Balance %.2f USDT < TRADE_USDT %.2f — no se puede abrir",
                          balance, config.TRADE_USDT)
                await self._n.send_error(
                    f"❌ Balance insuficiente: {balance:.2f} USDT (necesita ≥{config.TRADE_USDT:.0f})"
                )
                return
        except Exception as e:
            log.error("Error obteniendo balance: %s", e)
            return

        side = "BUY" if signal.direction == "LONG" else "SELL"

        if config.MODE == "LIVE":
            try:
                await self._c.set_leverage(signal.symbol, config.LEVERAGE)
                result = await self._c.place_market_order(signal.symbol, side, qty)
                log.info("✅ Orden %s %s qty=%.4f → %s", signal.direction, signal.symbol, qty, result)
            except Exception as e:
                log.error("Error abriendo orden: %s", e)
                await self._n.send_error(f"❌ Error orden {signal.symbol}: {e}")
                return
        else:
            log.info("[SIGNAL] %s %s qty=%.4f (sin ejecutar)", signal.direction, signal.symbol, qty)

        init_trail = (
            signal.price - signal.atr * config.ATR_TRAIL_MULT if signal.direction == "LONG"
            else signal.price + signal.atr * config.ATR_TRAIL_MULT
        )
        self._pos = ActivePosition(
            symbol     = signal.symbol,
            direction  = signal.direction,
            entry      = signal.price,
            sl         = signal.sl,
            tp1        = signal.tp1,
            tp2        = signal.tp2,
            atr        = signal.atr,
            atr_pct    = signal.atr_pct,
            qty_total  = qty,
            qty_left   = qty,
            trail_sl   = init_trail,
            peak_price = signal.price,
        )
        await self._n.send_entry(signal, qty, balance)

    # ── Monitor ────────────────────────────────────────────────────────────────

    async def monitor(self, price: float) -> None:
        if not self._pos:
            return
        p = self._pos
        if p.direction == "LONG"  and price > p.peak_price: p.peak_price = price
        if p.direction == "SHORT" and price < p.peak_price: p.peak_price = price

        if not p.tp1_hit:
            tp1_hit = (p.direction == "LONG"  and price >= p.tp1) or \
                      (p.direction == "SHORT" and price <= p.tp1)
            if tp1_hit:
                await self._partial_close(p, price, "TP1")
                p.tp1_hit = True
                p.sl = p.entry
                return

        if p.tp1_hit:
            if p.direction == "LONG":
                nt = price - p.atr * config.ATR_TRAIL_MULT
                if nt > p.trail_sl: p.trail_sl = nt
            else:
                nt = price + p.atr * config.ATR_TRAIL_MULT
                if nt < p.trail_sl: p.trail_sl = nt

        tp2_hit = (p.direction == "LONG"  and price >= p.tp2) or \
                  (p.direction == "SHORT" and price <= p.tp2)
        if tp2_hit:
            await self._full_close(p, price, "TP2"); return

        sl_ref  = p.trail_sl if p.tp1_hit else p.sl
        sl_hit  = (p.direction == "LONG"  and price <= sl_ref) or \
                  (p.direction == "SHORT" and price >= sl_ref)
        if sl_hit:
            await self._full_close(p, price, "Trailing SL" if p.tp1_hit else "SL")

    # ── Cierres ────────────────────────────────────────────────────────────────

    async def _partial_close(self, p: ActivePosition, price: float, label: str) -> None:
        qty  = round(p.qty_total * 0.5, 6)
        side = "SELL" if p.direction == "LONG" else "BUY"
        pnl  = self._pnl(p, price, qty)
        if config.MODE == "LIVE":
            try:
                await self._c.place_market_order(p.symbol, side, qty, reduce_only=True)
            except Exception as e:
                log.error("Partial close error: %s", e); return
        p.qty_left -= qty
        await self._n.send_tp(label, p.symbol, price, pnl, partial=True)
        log.info("%s parcial %s @%.5f PnL=%.4f", label, p.symbol, price, pnl)

    async def _full_close(self, p: ActivePosition, price: float, label: str) -> None:
        side = "SELL" if p.direction == "LONG" else "BUY"
        pnl  = self._pnl(p, price, p.qty_left)
        if config.MODE == "LIVE":
            try:
                await self._c.place_market_order(p.symbol, side, p.qty_left, reduce_only=True)
            except Exception as e:
                log.error("Full close error: %s", e); return
        is_sl = label in ("SL", "Trailing SL")
        await self._n.send_close(label, p.symbol, price, pnl, is_sl=is_sl)
        log.info("%s %s @%.5f PnL=%.4f", label, p.symbol, price, pnl)
        self._pos = None
        self._cooldown_until = time.time() + config.COOLDOWN_MIN * 60

    def _pnl(self, p: ActivePosition, price: float, qty: float) -> float:
        return ((price - p.entry) * qty * config.LEVERAGE if p.direction == "LONG"
                else (p.entry - price) * qty * config.LEVERAGE)

    async def force_close(self, price: float, reason: str = "manual") -> None:
        if self._pos:
            await self._full_close(self._pos, price, f"Forzado ({reason})")

    def status(self, price: float) -> str:
        if not self._pos:
            return "Sin posición activa"
        p   = self._pos
        pnl = self._pnl(p, price, p.qty_left)
        tr  = f"\n🔄 Trail SL: {p.trail_sl:.5f}" if p.tp1_hit else ""
        return (
            f"{'📈' if p.direction=='LONG' else '📉'} {p.direction} {p.symbol}\n"
            f"Entry: {p.entry:.5f} | Precio: {price:.5f}\n"
            f"SL: {p.sl:.5f}{tr}\n"
            f"TP1: {p.tp1:.5f} {'✅' if p.tp1_hit else '⏳'} | TP2: {p.tp2:.5f}\n"
            f"Qty: {p.qty_left:.4f} | PnL: {pnl:+.4f} USDT\n"
            f"💵 Trade size: {config.TRADE_USDT:.0f} USDT × {config.LEVERAGE}x"
        )
