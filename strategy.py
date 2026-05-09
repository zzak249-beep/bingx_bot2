"""
Strategy: Sniper Apex V26.1 — Multi-Coin Ready
Añade watchlist dinámica actualizada por el escáner.
"""

import logging
import os
from dataclasses import dataclass

import numpy as np

from .exchange import BingXClient
from .risk_manager import RiskManager
from .telegram_bot import TelegramNotifier

log = logging.getLogger("SniperStrategy")
LEVERAGE = int(os.getenv("LEVERAGE", "5"))

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
    return ema(2 * half - full, int(np.sqrt(period)))

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
    macd = ema(close, fast) - ema(close, slow)
    return stoch_series(stoch_series(macd, stc_len), stc_len)

def pivot_high(highs: np.ndarray, n: int) -> np.ndarray:
    result = np.full_like(highs, np.nan)
    for i in range(n, len(highs) - n):
        if highs[i] == highs[i - n : i + n + 1].max():
            result[i] = highs[i]
    return result

def pivot_low(lows: np.ndarray, n: int) -> np.ndarray:
    result = np.full_like(lows, np.nan)
    for i in range(n, len(lows) - n):
        if lows[i] == lows[i - n : i + n + 1].min():
            result[i] = lows[i]
    return result

@dataclass
class Signal:
    direction: str
    entry: float
    sl: float
    tp: float
    atr: float
    score: int = 0
    winrate_note: str = ""

class SniperStrategy:
    def __init__(self, exchange: BingXClient, risk: RiskManager, telegram: TelegramNotifier):
        self.exchange = exchange
        self.risk = risk
        self.telegram = telegram
        self._last_signal = {}
        self.watchlist = []

    def update_watchlist(self, coins: list):
        self.watchlist = coins
        log.info(f"Watchlist: {[c.symbol for c in coins]}")

    def _compute_signals(self, candles: list) -> Signal:
        closes  = np.array([c["close"]  for c in candles], dtype=float)
        highs   = np.array([c["high"]   for c in candles], dtype=float)
        lows    = np.array([c["low"]    for c in candles], dtype=float)
        volumes = np.array([c["volume"] for c in candles], dtype=float)

        e7, e17 = ema(closes, 7), ema(closes, 17)
        e2, e4, e20 = ema(closes, 2), ema(closes, 4), ema(closes, 20)
        hull50 = hma(closes, 50)
        stc_vals = stc(closes)
        vol_ma = sma(volumes, 20)
        inst_vol = volumes[-1] > vol_ma[-1] * 1.5

        ph, pl = pivot_high(highs, 5), pivot_low(lows, 5)
        valid_ph, valid_pl = ph[~np.isnan(ph)], pl[~np.isnan(pl)]
        peak   = float(valid_ph[-1]) if len(valid_ph) > 0 else highs[-1]
        valley = float(valid_pl[-1]) if len(valid_pl) > 0 else lows[-1]

        tr = np.maximum(highs - lows,
             np.abs(highs - np.roll(closes, 1)),
             np.abs(lows  - np.roll(closes, 1)))
        atr14 = float(np.mean(tr[-14:]))
        i = -1
        entry = closes[i]

        apex_long = (
            e7[i-1] < e17[i-1] and e7[i] > e17[i]
            and closes[i] > peak and inst_vol
            and closes[i] > hull50[i]
            and stc_vals[i] > stc_vals[i-1]
            and (e7[i] - e7[i-1]) > 0
        )
        apex_short = (
            e7[i-1] > e17[i-1] and e7[i] < e17[i]
            and closes[i] < valley and inst_vol
            and closes[i] < hull50[i]
            and stc_vals[i] < stc_vals[i-1]
            and (e7[i] - e7[i-1]) < 0
        )
        ca_long = (closes[i] < e20[i] and closes[i-1] >= e20[i-1]) or (
            (closes[i]-closes[i-1])<0 and (e2[i]-e2[i-1])<0
            and closes[i-1]>=e2[i-1] and closes[i]<e2[i] and (e4[i]-e4[i-1])>0)
        ca_short = (closes[i] > e20[i] and closes[i-1] <= e20[i-1]) or (
            (closes[i]-closes[i-1])>0 and (e2[i]-e2[i-1])>0
            and closes[i-1]<=e2[i-1] and closes[i]>e2[i] and (e4[i]-e4[i-1])<0)

        if apex_long and ca_long:
            sl = valley
            return Signal("LONG", entry, sl, entry + abs(entry-sl)*3, atr14, score=100)
        if apex_short and ca_short:
            sl = peak
            return Signal("SHORT", entry, sl, entry - abs(sl-entry)*3, atr14, score=100)
        if apex_long:
            sl = valley
            return Signal("LONG", entry, sl, entry + abs(entry-sl)*3, atr14, score=70, winrate_note="⚠️ Sin confirm CA")
        if apex_short:
            sl = peak
            return Signal("SHORT", entry, sl, entry - abs(sl-entry)*3, atr14, score=70, winrate_note="⚠️ Sin confirm CA")
        return Signal("NONE", entry, 0, 0, atr14)

    async def run_cycle(self, symbol: str, interval: str):
        candles  = await self.exchange.get_klines(symbol, interval, limit=200)
        signal   = self._compute_signals(candles)
        position = await self.exchange.get_position(symbol)
        has_position = position and abs(float(position.get("positionAmt", 0))) > 0

        if has_position and signal.direction != "NONE":
            pos_side = "LONG" if float(position["positionAmt"]) > 0 else "SHORT"
            if pos_side != signal.direction:
                await self.exchange.close_position(symbol, position)
                await self.telegram.send(f"🔄 *Cierre* {pos_side} `{symbol}` @ `{signal.entry:.4f}`")
                has_position = False

        if not has_position and signal.direction != "NONE":
            if self._last_signal.get(symbol) == signal.direction:
                return
            balance = await self.exchange.get_balance()
            qty = self.risk.calc_qty(balance, signal.entry, signal.sl)
            if qty <= 0:
                return
            await self.exchange.set_leverage(symbol, LEVERAGE)
            side = "BUY" if signal.direction == "LONG" else "SELL"
            await self.exchange.place_order(
                symbol=symbol, side=side, position_side=signal.direction,
                qty=qty, stop_loss=round(signal.sl, 4), take_profit=round(signal.tp, 4),
            )
            emoji = "🟢" if signal.direction == "LONG" else "🔴"
            await self.telegram.send(
                f"{emoji} *{signal.direction}* `{symbol}`\n"
                f"Entry: `{signal.entry:.4f}`\n"
                f"SL: `{signal.sl:.4f}`  TP: `{signal.tp:.4f}` (3R)\n"
                f"Qty: `{qty}`  Score: `{signal.score}/100`\n{signal.winrate_note}"
            )
            self._last_signal[symbol] = signal.direction
        elif signal.direction == "NONE":
            self._last_signal[symbol] = "NONE"
