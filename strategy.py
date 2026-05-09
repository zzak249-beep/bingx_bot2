"""
Strategy: Sniper Apex V26.1
Combina:
  - EMA 7/17 cross (V26.1 Apex)
  - EMA 2/4/20 slope divergence (ChartArt V3)
  - Hull MA 50 filtro tendencia
  - STC Momentum
  - Volumen institucional (>1.5x SMA20)
  - Pivot High/Low como niveles de liquidez
Gestión de riesgo: SL en último pivot, TP = SL * 3
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .exchange import BingXClient
from .risk_manager import RiskManager
from .telegram_bot import TelegramNotifier

log = logging.getLogger("SniperStrategy")

LEVERAGE = int(os.getenv("LEVERAGE", "5"))


# ─── Indicator helpers ────────────────────────────────────────────

def ema(values: np.ndarray, period: int) -> np.ndarray:
    k = 2 / (period + 1)
    result = np.zeros_like(values)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def hma(values: np.ndarray, period: int) -> np.ndarray:
    half = ema(values, period // 2)
    full = ema(values, period)
    raw  = 2 * half - full
    return ema(raw, int(np.sqrt(period)))


def sma(values: np.ndarray, period: int) -> np.ndarray:
    return np.convolve(values, np.ones(period) / period, mode="same")


def stoch_series(src: np.ndarray, period: int) -> np.ndarray:
    result = np.zeros_like(src)
    for i in range(period - 1, len(src)):
        window = src[i - period + 1 : i + 1]
        lo, hi = window.min(), window.max()
        result[i] = (src[i] - lo) / (hi - lo + 1e-10)
    return result


def stc(close: np.ndarray, stc_len=10, fast=23, slow=50) -> np.ndarray:
    macd  = ema(close, fast) - ema(close, slow)
    s1    = stoch_series(macd, stc_len)
    s2    = stoch_series(s1, stc_len)
    return s2


def pivot_high(highs: np.ndarray, n: int) -> np.ndarray:
    result = np.full_like(highs, np.nan)
    for i in range(n, len(highs) - n):
        window = highs[i - n : i + n + 1]
        if highs[i] == window.max():
            result[i] = highs[i]
    return result


def pivot_low(lows: np.ndarray, n: int) -> np.ndarray:
    result = np.full_like(lows, np.nan)
    for i in range(n, len(lows) - n):
        window = lows[i - n : i + n + 1]
        if lows[i] == window.min():
            result[i] = lows[i]
    return result


# ─── Signal logic ─────────────────────────────────────────────────

@dataclass
class Signal:
    direction: str   # "LONG" | "SHORT" | "NONE"
    entry:     float
    sl:        float
    tp:        float
    atr:       float
    winrate_note: str = ""


class SniperStrategy:
    def __init__(self, exchange: BingXClient, risk: RiskManager, telegram: TelegramNotifier):
        self.exchange = exchange
        self.risk     = risk
        self.telegram = telegram
        self._last_signal = "NONE"

    def _compute_signals(self, candles: list) -> Signal:
        closes  = np.array([c["close"]  for c in candles], dtype=float)
        highs   = np.array([c["high"]   for c in candles], dtype=float)
        lows    = np.array([c["low"]    for c in candles], dtype=float)
        volumes = np.array([c["volume"] for c in candles], dtype=float)

        # EMA suite (V26.1)
        e7  = ema(closes, 7)
        e17 = ema(closes, 17)
        hull50 = hma(closes, 50)

        # EMA suite (ChartArt slopes)
        e2  = ema(closes, 2)
        e4  = ema(closes, 4)
        e20 = ema(closes, 20)

        # Institutional volume
        vol_ma    = sma(volumes, 20)
        inst_vol  = volumes[-1] > vol_ma[-1] * 1.5

        # STC
        stc_vals = stc(closes)

        # Pivots
        ph = pivot_high(highs, 5)
        pl = pivot_low(lows, 5)

        # Last known pivot levels
        peak   = float(np.nanmax(ph[-50:]))  if not np.all(np.isnan(ph[-50:])) else highs[-1]
        valley = float(np.nanmin(pl[-50:])) if not np.all(np.isnan(pl[-50:])) else lows[-1]

        # ATR approx
        tr    = np.maximum(highs - lows, np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1)))
        atr14 = float(np.mean(tr[-14:]))

        i = -1  # last bar

        # ── Apex LONG (V26.1) ──────────────────────────
        apex_long = (
            e7[i - 1] < e17[i - 1] and e7[i] > e17[i]  # EMA7 cruza arriba EMA17
            and closes[i] > peak                          # rompe resistencia pivot
            and inst_vol                                  # volumen institucional
            and closes[i] > hull50[i]                    # precio sobre Hull
            and stc_vals[i] > stc_vals[i - 1]            # STC ascendente
            and (e7[i] - e7[i - 1]) > 0                  # slope positivo
        )

        # ── ChartArt LONG confirm ──────────────────────
        ca_long = (
            closes[i] < e20[i] and closes[i - 1] >= e20[i - 1]  # precio cruza bajo EMA20 (re-entry)
        ) or (
            (closes[i] - closes[i - 1]) < 0
            and (e2[i] - e2[i - 1]) < 0
            and closes[i - 1] >= e2[i - 1] and closes[i] < e2[i]
            and (e4[i] - e4[i - 1]) > 0
        )

        # ── Apex SHORT (V26.1) ─────────────────────────
        apex_short = (
            e7[i - 1] > e17[i - 1] and e7[i] < e17[i]
            and closes[i] < valley
            and inst_vol
            and closes[i] < hull50[i]
            and stc_vals[i] < stc_vals[i - 1]
            and (e7[i] - e7[i - 1]) < 0
        )

        # ── ChartArt SHORT confirm ─────────────────────
        ca_short = (
            closes[i] > e20[i] and closes[i - 1] <= e20[i - 1]
        ) or (
            (closes[i] - closes[i - 1]) > 0
            and (e2[i] - e2[i - 1]) > 0
            and closes[i - 1] <= e2[i - 1] and closes[i] > e2[i]
            and (e4[i] - e4[i - 1]) < 0
        )

        entry = closes[i]

        if apex_long and ca_long:
            sl   = valley
            risk = abs(entry - sl)
            tp   = entry + risk * 3.0
            return Signal("LONG", entry, sl, tp, atr14)

        if apex_short and ca_short:
            sl   = peak
            risk = abs(sl - entry)
            tp   = entry - risk * 3.0
            return Signal("SHORT", entry, sl, tp, atr14)

        # Fallback: solo Apex sin doble confirmación (señal débil)
        if apex_long:
            sl = valley
            tp = entry + abs(entry - sl) * 3.0
            return Signal("LONG", entry, sl, tp, atr14, winrate_note="⚠️ Sin confirm CA")

        if apex_short:
            sl = peak
            tp = entry - abs(sl - entry) * 3.0
            return Signal("SHORT", entry, sl, tp, atr14, winrate_note="⚠️ Sin confirm CA")

        return Signal("NONE", entry, 0, 0, atr14)

    async def run_cycle(self, symbol: str, interval: str):
        candles  = await self.exchange.get_klines(symbol, interval, limit=200)
        signal   = self._compute_signals(candles)
        position = await self.exchange.get_position(symbol)

        has_position = position and abs(float(position.get("positionAmt", 0))) > 0

        # ── Cerrar posición contraria ───────────────────
        if has_position and signal.direction != "NONE":
            pos_side = "LONG" if float(position["positionAmt"]) > 0 else "SHORT"
            if pos_side != signal.direction:
                log.info(f"Cerrando {pos_side} para abrir {signal.direction}")
                await self.exchange.close_position(symbol, position)
                await self.telegram.send(
                    f"🔄 *Cierre posición* {pos_side}\n`{symbol}` @ {signal.entry:.4f}"
                )
                has_position = False

        # ── Abrir nueva posición ────────────────────────
        if not has_position and signal.direction != "NONE":
            if signal.direction == self._last_signal:
                log.info("Señal repetida, ignorando")
                return

            balance = await self.exchange.get_balance()
            qty     = self.risk.calc_qty(balance, signal.entry, signal.sl)

            if qty <= 0:
                await self.telegram.send("⚠️ Balance insuficiente para operar")
                return

            await self.exchange.set_leverage(symbol, LEVERAGE)

            side  = "BUY" if signal.direction == "LONG" else "SELL"
            pside = signal.direction

            await self.exchange.place_order(
                symbol        = symbol,
                side          = side,
                position_side = pside,
                qty           = qty,
                stop_loss     = round(signal.sl, 4),
                take_profit   = round(signal.tp, 4),
            )

            emoji = "🟢" if signal.direction == "LONG" else "🔴"
            msg = (
                f"{emoji} *{signal.direction} ABIERTO*\n"
                f"Par: `{symbol}`\n"
                f"Entry: `{signal.entry:.4f}`\n"
                f"SL: `{signal.sl:.4f}`\n"
                f"TP: `{signal.tp:.4f}` (3R)\n"
                f"Qty: `{qty}`\n"
                f"ATR: `{signal.atr:.4f}`\n"
                f"{signal.winrate_note}"
            )
            await self.telegram.send(msg)
            log.info(f"Orden enviada: {signal}")
            self._last_signal = signal.direction
        else:
            if signal.direction == "NONE":
                self._last_signal = "NONE"
