"""
Multi-Symbol Scanner
Scans all USDT perpetual pairs concurrently
Filters by volume, applies full QF engine, ranks by score
"""

import asyncio
import logging
import numpy as np
from typing import Optional
from src.engine import QFEngine, MarketData, SignalResult, Signal

logger = logging.getLogger("scanner")


async def fetch_symbol_data(exchange, symbol: str, cfg: dict) -> Optional[MarketData]:
    """Fetch 3m + 15m + 1h klines for a symbol"""
    try:
        limit = cfg.get("kline_limit", 250)
        # Concurrent fetch
        k3m_task  = exchange.get_klines(symbol, "3m",  limit)
        k15m_task = exchange.get_klines(symbol, "15m", 100)
        k1h_task  = exchange.get_klines(symbol, "1h",  100)

        k3m, k15m, k1h = await asyncio.gather(k3m_task, k15m_task, k1h_task)

        if len(k3m) < 60:
            return None

        def parse(klines):
            arr = np.array([[float(k["open"]), float(k["high"]),
                             float(k["low"]),  float(k["close"]),
                             float(k["volume"])] for k in klines])
            return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]

        o3, h3, l3, c3, v3   = parse(k3m)
        o15, h15, l15, c15, v15 = parse(k15m) if k15m else (None,)*5
        o1h, h1h, l1h, c1h, v1h = parse(k1h)  if k1h  else (None,)*5

        # Volume filter: skip low-volume symbols
        avg_vol_usdt = float(np.mean(c3[-20:] * v3[-20:]))
        min_vol = cfg.get("min_volume_usdt", 500_000)
        if avg_vol_usdt < min_vol:
            return None

        return MarketData(
            symbol=symbol,
            closes=c3, highs=h3, lows=l3, opens=o3, volumes=v3,
            closes_15m=c15, closes_1h=c1h,
            highs_15m=h15, lows_15m=l15,
            highs_1h=h1h, lows_1h=l1h,
        )
    except Exception as e:
        logger.debug(f"Fetch error {symbol}: {e}")
        return None


class Scanner:
    def __init__(self, exchange, engine: QFEngine, config: dict):
        self.exchange = exchange
        self.engine   = engine
        self.cfg      = config
        self._symbols: list = []
        self._symbol_refresh = 0

    async def refresh_symbols(self):
        """Refresh symbol list every N scans"""
        symbols = await self.exchange.get_all_symbols()
        # Blacklist filter
        blacklist = set(self.cfg.get("blacklist", []))
        self._symbols = [s for s in symbols if s not in blacklist]
        logger.info(f"Symbols loaded: {len(self._symbols)}")

    async def scan_all(self) -> list[SignalResult]:
        """
        Scan all symbols, return list of SignalResults sorted by score.
        Uses semaphore to limit concurrent requests.
        """
        self._symbol_refresh += 1
        if self._symbol_refresh % 20 == 1 or not self._symbols:
            await self.refresh_symbols()

        sem = asyncio.Semaphore(self.cfg.get("max_concurrent", 15))
        results = []

        async def process(symbol: str):
            async with sem:
                md = await fetch_symbol_data(self.exchange, symbol, self.cfg)
                if md is None:
                    return
                try:
                    result = self.engine.analyze(md)
                    results.append(result)
                except Exception as e:
                    logger.debug(f"Engine error {symbol}: {e}")

        await asyncio.gather(*[process(s) for s in self._symbols])

        # Sort: active signals first, then by max score
        def sort_key(r: SignalResult):
            has_signal = r.signal not in (Signal.NONE,)
            score = max(r.score_long, r.score_short)
            return (has_signal, score)

        results.sort(key=sort_key, reverse=True)
        logger.info(f"Scan complete: {len(results)} results, "
                    f"{sum(1 for r in results if r.signal not in (Signal.NONE, Signal.PRE_LONG, Signal.PRE_SHORT))} signals")
        return results

    def get_actionable(self, results: list[SignalResult]) -> list[SignalResult]:
        """Filter only signals worth trading (excludes NONE and pre-alerts)"""
        min_score = self.cfg.get("min_score_trade", 55)
        min_rr    = self.cfg.get("min_rr", 1.3)
        return [
            r for r in results
            if r.signal not in (Signal.NONE,)
            and max(r.score_long, r.score_short) >= min_score
            and (r.rr1_long >= min_rr or r.rr1_short >= min_rr)
        ]
