import numpy as np
import pandas as pd
import pytest

from bot.sweep_reversal import SweepReversalSignals, _pivot_high, _pivot_low


def _idx(n):
    return pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")


def test_pivot_high_basic():
    # index 2 (value 5) is the max of the 5-wide window [1,2,3,4,5,6] -> [3,3,5,4,3]... 
    highs = pd.Series([3.0, 3.0, 5.0, 4.0, 3.0, 3.0, 3.0], index=_idx(7))
    piv = _pivot_high(highs, left=2, right=2)
    # revealed 2 bars after the pivot bar (index 2) -> index 4
    assert piv.iloc[4] == 5.0
    assert piv.dropna().tolist() == [5.0]


def test_pivot_low_basic():
    lows = pd.Series([3.0, 3.0, 1.0, 2.0, 3.0, 3.0, 3.0], index=_idx(7))
    piv = _pivot_low(lows, left=2, right=2)
    assert piv.iloc[4] == 1.0
    assert piv.dropna().tolist() == [1.0]


def test_min_bars_validation():
    df = pd.DataFrame(
        {"open": [1.0] * 10, "high": [1.0] * 10, "low": [1.0] * 10, "close": [1.0] * 10},
        index=_idx(10),
    )
    scanner = SweepReversalSignals(swing_length=5, structure_length=3, max_confirmation_bars=12)
    with pytest.raises(ValueError):
        scanner.compute(df)


def _make_ohlc(close, high=None, low=None, open_=None):
    close = np.asarray(close, dtype=float)
    high = np.asarray(high, dtype=float) if high is not None else close
    low = np.asarray(low, dtype=float) if low is not None else close
    open_ = np.asarray(open_, dtype=float) if open_ is not None else np.roll(close, 1)
    open_[0] = close[0]
    n = len(close)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=_idx(n))


def test_no_signals_in_monotonic_uptrend():
    """A strictly increasing series can never sweep below an old low or
    revisit an old high from above in a way that reverses — there's
    nothing to sweep-and-reverse. Both directions should stay silent."""
    n = 60
    close = 100 + np.arange(n) * 0.5
    df = _make_ohlc(close, high=close + 0.1, low=close - 0.1)

    scanner = SweepReversalSignals(swing_length=3, structure_length=3, max_confirmation_bars=8)
    out = scanner.compute(df)
    assert out["bearish_confirmed"].sum() == 0
    assert out["bullish_confirmed"].sum() == 0


def test_bearish_confirmed_on_engineered_sweep_and_reversal():
    """Engineered pattern: rise to a swing high, pull back, poke slightly
    above the old high (the sweep), then reverse hard through recent
    structure with a big red candle (the confirmation)."""
    close = [
        100, 101, 102, 104, 103, 102, 101, 102, 103,   # 0-8: build up to a swing high (~104 @ idx3)
        103, 104, 106,                                  # 9-11: pull back then poke above the swing high
        105, 103, 100, 97,                              # 12-15: reclaim + break structure, big red candle
        97, 97, 97, 97, 97, 97, 97, 97, 97, 97,         # 16-25: drift, let it resolve
    ]
    high = list(close)
    low = list(close)
    high[11] = 107.0  # the sweep wick itself, above the ~104 swing high
    low[15] = 94.0    # a large-range red candle for the displacement filter

    df = _make_ohlc(close, high=high, low=low)
    scanner = SweepReversalSignals(
        swing_length=2, atr_length=5, min_penetration=0.0,
        structure_length=2, max_confirmation_bars=6, min_displacement=0.1,
    )
    out = scanner.compute(df)
    assert out["bearish_confirmed"].sum() >= 1, out[["bearish_confirmed"]]


def test_causal_no_lookahead():
    """Same property test as wavelet.py's: truncating history must not
    change any already-revealed value. A repainting sweep signal would
    be actively dangerous to trade on live."""
    rng = np.random.default_rng(11)
    n = 150
    returns = rng.normal(0, 0.003, n)
    close = 100 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0015, n)))
    df = _make_ohlc(close, high=high, low=low)

    scanner = SweepReversalSignals(swing_length=4, structure_length=3, max_confirmation_bars=10)
    full = scanner.compute(df)
    cutoff = 110
    partial = scanner.compute(df.iloc[:cutoff])

    pd.testing.assert_frame_equal(full.iloc[:cutoff], partial, check_exact=True)
