import numpy as np
import pandas as pd
import pytest

from bot.config import Config
from bot.strategy import PortfolioStrategy
from bot.telegram_notify import TelegramNotifier


def _make_firing_series():
    """A synthetic OHLCV series verified (see conversation / dev notes) to
    fire a fresh long entry signal (is_trending & cross_up & h8>0) on its
    very last closed bar, at lookback_energy=15, k_dominance=1.3. One
    extra duplicate final row is appended so strategy.py's `iloc[:-1]`
    (which drops the still-forming candle) lands exactly back on it."""
    rng = np.random.default_rng(7)
    n = 47
    t = np.arange(400)[:n]
    trend = np.sin(t / 40) * 0.02
    noise = rng.normal(0, 0.004, n)
    returns = trend / 40 + noise
    close = 100 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0015, n)))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 500.0}, index=idx
    )
    return pd.concat([df, df.iloc[[-1]]])  # + one forming candle to be dropped


class FakeMultiSymbolExchange:
    has_keys = True

    def __init__(self, symbols):
        self.series = _make_firing_series()
        self.entered = []  # (symbol, side)

    def fetch_ohlcv_df(self, symbol, timeframe, limit=300):
        return self.series

    def fetch_equity_usdt(self):
        return 1000.0

    def fetch_all_open_positions(self):
        return []  # nothing open at the start of any cycle in this test

    def enter_position(self, symbol, side, notional_usdt, price, sl, tp):
        self.entered.append((symbol, side))


def make_config(max_concurrent):
    return Config(
        bingx_api_key="fake", bingx_api_secret="fake", market_type="swap",
        symbol_universe="S1/USDT:USDT,S2/USDT:USDT,S3/USDT:USDT,S4/USDT:USDT,S5/USDT:USDT",
        symbol_exclude="", min_24h_volume_usdt=0.0, max_concurrent_positions=max_concurrent,
        timeframe="5m", leverage=10, dry_run=False,
        lookback_energy=15, k_dominance=1.3, cooldown_bars=4,
        use_vol_filter=False, vol_len=20, vol_mult=1.2,
        qty_pct=10.0, use_atr_sl=True, atr_length=14, atr_mult_sl=1.5, atr_mult_tp=2.5,
        sl_percent=0.01, tp_percent=0.02, use_trail=False, trail_trigger_atr=1.0, trail_offset_atr=1.0,
        max_daily_loss_pct=5.0,
        use_sweep_exit_filter=False, sweep_swing_length=5, sweep_atr_length=14,
        sweep_min_penetration=0.0, sweep_structure_length=3, sweep_max_confirmation_bars=12,
        sweep_min_displacement=0.2, sweep_exit_action="alert_only",
        telegram_bot_token="", telegram_chat_id="",
        poll_seconds=1, log_level="INFO",
    )


@pytest.mark.parametrize("cap", [1, 2, 5])
def test_concurrent_position_cap_holds_within_one_scan(cap):
    """The whole point of MAX_CONCURRENT_POSITIONS: if every symbol in the
    universe fires an entry signal in the SAME cycle, no more than `cap`
    of them may actually place an order — checked live, across the batch,
    not against a stale start-of-cycle count."""
    symbols = ["S1/USDT:USDT", "S2/USDT:USDT", "S3/USDT:USDT", "S4/USDT:USDT", "S5/USDT:USDT"]
    exchange = FakeMultiSymbolExchange(symbols)
    config = make_config(max_concurrent=cap)
    notifier = TelegramNotifier("", "", enabled=False)

    strategy = PortfolioStrategy(config, exchange, notifier)
    assert strategy.symbols == symbols

    strategy.run_once()

    assert len(exchange.entered) == min(cap, len(symbols))
    assert all(side == "long" for _, side in exchange.entered)
    # no duplicate entries on the same symbol
    assert len(set(s for s, _ in exchange.entered)) == len(exchange.entered)


def test_universe_resolves_explicit_list():
    exchange = FakeMultiSymbolExchange([])
    config = make_config(max_concurrent=3)
    notifier = TelegramNotifier("", "", enabled=False)
    strategy = PortfolioStrategy(config, exchange, notifier)
    assert strategy.symbols == [
        "S1/USDT:USDT", "S2/USDT:USDT", "S3/USDT:USDT", "S4/USDT:USDT", "S5/USDT:USDT",
    ]
    assert set(strategy.state.keys()) == set(strategy.symbols)
