"""
Python port of the "Sweep Reversal Map [Herman]" Pine Script SIGNAL logic
(swing sweep -> reclaim -> structure break -> displacement confirmation).

IMPORTANT — read before trusting this module:

Only the BEARISH half of the original Pine script was ever shared in this
conversation. The BULLISH half here is a RECONSTRUCTED MIRROR, inferred
from the parallel `bullish*` state variables the original script already
declares (bullishActive, bullishReclaimed, bullishLevel, bullishExtreme,
bullishConfirmationLevel, ...) but whose actual detection/confirmation
code was never shown. The mirror below swaps every high/low, >/< , and
max/min in the bearish logic — which is the standard, and near-certainly
correct, symmetric design — but it has NOT been checked against the
author's real bullish code, because that code hasn't been provided. If
you get the real block later, `_scan()` below is generic over direction,
so patching in the true bullish rules should be a small diff.

This ports only the SIGNAL logic (pivot -> sweep -> reclaim -> structure
break -> displacement), not the original's box/line/label drawing, which
is TradingView-chart visualization with no equivalent in a headless bot.

Like wavelet.py, this is causal: nothing at bar i depends on bar > i. A
pivot is only "revealed" `swing_length` bars after it happened (matching
Pine's ta.pivothigh/pivotlow — lagging, but never repainting once
revealed). See tests/test_sweep_reversal.py for a no-lookahead check
using the same truncate-and-recompute method as the wavelet tests.
"""
import logging

import numpy as np
import pandas as pd

from .wavelet import atr as atr_fn

log = logging.getLogger(__name__)


def _pivot_high(high: pd.Series, left: int, right: int) -> pd.Series:
    """Causal port of Pine's ta.pivothigh(high, left, right): the pivot
    value for candidate bar i is only written at index i+right (once
    `right` bars have closed after it), matching Pine's own reveal delay."""
    n = len(high)
    out = pd.Series(np.nan, index=high.index)
    values = high.to_numpy()
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        if values[i] == window.max():
            out.iloc[i + right] = values[i]
    return out


def _pivot_low(low: pd.Series, left: int, right: int) -> pd.Series:
    n = len(low)
    out = pd.Series(np.nan, index=low.index)
    values = low.to_numpy()
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        if values[i] == window.min():
            out.iloc[i + right] = values[i]
    return out


def _scan(
    df: pd.DataFrame,
    pivot_series: pd.Series,
    structure_level: pd.Series,
    extreme_col: str,
    direction: str,
    atr: pd.Series,
    min_penetration: float,
    max_confirmation_bars: int,
    min_displacement: float,
) -> pd.Series:
    """Bar-by-bar state machine, generic over direction so the (ported)
    bearish rules and the (mirrored) bullish rules share one
    implementation instead of two hand-duplicated copies."""
    assert direction in ("bearish", "bullish")
    n = len(df)
    confirmed = np.zeros(n, dtype=bool)

    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    extreme_price = df[extreme_col].to_numpy()
    struct_level = structure_level.to_numpy()
    pivot = pivot_series.to_numpy()
    atr_vals = atr.to_numpy()

    latest_swing = np.nan
    swing_available = False

    active = False
    reclaimed = False
    start_bar = -1
    level = np.nan
    conf_level = np.nan

    for i in range(n):
        # Pivot tracking updates every bar, unconditionally — matches the
        # original script, where this sits outside the confirmed-bar block.
        if not np.isnan(pivot[i]):
            latest_swing = pivot[i]
            swing_available = True

        a = atr_vals[i]
        body = abs(close[i] - open_[i])
        displacement_pass = (not np.isnan(a)) and body >= a * min_displacement
        min_pen = 0.0 if np.isnan(a) else a * min_penetration

        if (
            not active
            and swing_available
            and not np.isnan(latest_swing)
            and not np.isnan(struct_level[i])
        ):
            if direction == "bearish":
                swept = extreme_price[i] >= latest_swing + min_pen
            else:
                swept = extreme_price[i] <= latest_swing - min_pen

            if swept:
                active = True
                level = latest_swing
                conf_level = struct_level[i]
                start_bar = i
                reclaimed = (close[i] < level) if direction == "bearish" else (close[i] > level)
                swing_available = False  # this level is "used" until a fresh pivot appears

        if active:
            if direction == "bearish":
                reclaimed = reclaimed or (close[i] < level)
                confirm = reclaimed and (close[i] < conf_level) and displacement_pass
            else:
                reclaimed = reclaimed or (close[i] > level)
                confirm = reclaimed and (close[i] > conf_level) and displacement_pass

            expired = (i - start_bar) > max_confirmation_bars

            if confirm:
                confirmed[i] = True
                active = False
            elif expired:
                active = False

    return pd.Series(confirmed, index=df.index)


class SweepReversalSignals:
    def __init__(
        self,
        swing_length: int = 5,
        atr_length: int = 14,
        min_penetration: float = 0.0,
        structure_length: int = 3,
        max_confirmation_bars: int = 12,
        min_displacement: float = 0.2,
    ):
        self.swing_length = swing_length
        self.atr_length = atr_length
        self.min_penetration = min_penetration
        self.structure_length = structure_length
        self.max_confirmation_bars = max_confirmation_bars
        self.min_displacement = min_displacement
        self.min_bars_required = 2 * swing_length + structure_length + max_confirmation_bars

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.min_bars_required + 5:
            raise ValueError(
                f"Need at least {self.min_bars_required + 5} candles for the sweep-reversal "
                f"scan, got {len(df)}."
            )

        atr_series = atr_fn(df, length=self.atr_length)
        pivot_high = _pivot_high(df["high"], self.swing_length, self.swing_length)
        pivot_low = _pivot_low(df["low"], self.swing_length, self.swing_length)
        prior_structure_low = df["low"].rolling(self.structure_length).min().shift(1)
        prior_structure_high = df["high"].rolling(self.structure_length).max().shift(1)

        bearish = _scan(
            df,
            pivot_series=pivot_high,
            structure_level=prior_structure_low,
            extreme_col="high",
            direction="bearish",
            atr=atr_series,
            min_penetration=self.min_penetration,
            max_confirmation_bars=self.max_confirmation_bars,
            min_displacement=self.min_displacement,
        )
        bullish = _scan(
            df,
            pivot_series=pivot_low,
            structure_level=prior_structure_high,
            extreme_col="low",
            direction="bullish",
            atr=atr_series,
            min_penetration=self.min_penetration,
            max_confirmation_bars=self.max_confirmation_bars,
            min_displacement=self.min_displacement,
        )

        out = pd.DataFrame(index=df.index)
        out["bearish_confirmed"] = bearish
        out["bullish_confirmed"] = bullish
        return out
