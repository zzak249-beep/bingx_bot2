#!/usr/bin/env python3
"""
learner.py v3.0 — Aprendizaje automático mejorado
Analiza trades históricos y ajusta parámetros dinámicamente.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
import statistics

STATE_DIR   = Path("bot_state")
TRADES_FILE = "paper_trades.json"
LEARNER_FILE = STATE_DIR / "learner_state.json"


def _load_trades():
    try:
        with open(TRADES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _load_learner_state():
    try:
        with open(LEARNER_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_update": None,
            "pair_stats": {},
            "top_pairs": [],
            "bottom_pairs": [],
            "market_regime": "neutral",
        }

def _save_learner_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    with open(LEARNER_FILE, "w") as f:
        json.dump(state, f, indent=2)


class PairAnalyzer:
    """Analiza performance por par."""

    def __init__(self, trades):
        self.trades = trades
        self.pair_stats = self._calculate_stats()

    def _calculate_stats(self) -> dict:
        pairs = defaultdict(lambda: {
            "total": 0, "wins": 0, "losses": 0,
            "pnl_total": 0.0, "pnl_list": [],
            "wr": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "ratio": 0.0, "sharpe": 0.0, "last_trade": None,
        })

        for trade in self.trades:
            symbol = trade.get("symbol", "UNKNOWN")
            pnl    = trade.get("pnl", 0)
            is_win = pnl > 0

            pairs[symbol]["total"] += 1
            pairs[symbol]["pnl_total"] += pnl
            pairs[symbol]["pnl_list"].append(pnl)
            pairs[symbol]["last_trade"] = trade.get("close_time", "")

            if is_win:
                pairs[symbol]["wins"] += 1
            else:
                pairs[symbol]["losses"] += 1

        for symbol, stats in pairs.items():
            if stats["total"] == 0:
                continue

            stats["wr"] = stats["wins"] / stats["total"] * 100

            wins   = [p for p in stats["pnl_list"] if p > 0]
            losses = [p for p in stats["pnl_list"] if p < 0]

            stats["avg_win"]  = statistics.mean(wins)   if wins   else 0
            stats["avg_loss"] = statistics.mean(losses) if losses else 0

            if stats["avg_loss"] != 0:
                stats["ratio"] = abs(stats["avg_win"] / stats["avg_loss"])

            if len(stats["pnl_list"]) > 1:
                try:
                    std_dev = statistics.stdev(stats["pnl_list"])
                    if std_dev > 0:
                        stats["sharpe"] = (statistics.mean(stats["pnl_list"]) / std_dev) * (252 ** 0.5)
                except Exception:
                    pass

        return dict(pairs)

    def get_top_pairs(self, n=10) -> list:
        """Top N pares por WR + Sharpe combinado."""
        sorted_pairs = sorted(
            [(k, v) for k, v in self.pair_stats.items() if v["total"] >= 3],
            key=lambda x: (x[1]["wr"] * 0.6 + x[1]["sharpe"] * 0.4),
            reverse=True
        )
        return [p[0] for p in sorted_pairs[:n]]

    def get_bottom_pairs(self, n=5) -> list:
        """Bottom N pares perdedores (mínimo 5 trades para calificar)."""
        sorted_pairs = sorted(
            [(k, v) for k, v in self.pair_stats.items() if v["total"] >= 5],
            key=lambda x: (x[1]["wr"] * 0.6 + x[1]["sharpe"] * 0.4),
        )
        return [p[0] for p in sorted_pairs[:n]]

    def get_stats_by_pair(self, symbol) -> dict:
        return self.pair_stats.get(symbol, {})


class ParameterAdjuster:
    """Ajusta parámetros según historial del par."""

    def __init__(self, analyzer: PairAnalyzer):
        self.analyzer = analyzer

    def get_score_min_for_pair(self, symbol: str) -> int:
        stats = self.analyzer.get_stats_by_pair(symbol)
        if not stats:
            return 45

        wr    = stats.get("wr", 0)
        ratio = stats.get("ratio", 0)
        score_min = 45

        if wr < 35:    score_min += 15
        elif wr < 40:  score_min += 10
        elif wr > 55:  score_min -= 10
        elif wr > 60:  score_min -= 15

        if ratio < 1.2:   score_min += 10
        elif ratio > 2.5: score_min -= 5

        return max(30, min(80, score_min))

    def get_size_multiplier_for_pair(self, symbol: str) -> float:
        stats = self.analyzer.get_stats_by_pair(symbol)
        if not stats:
            return 1.0

        wr    = stats.get("wr", 0)
        ratio = stats.get("ratio", 0)
        mult  = 1.0

        if wr > 60:    mult *= 1.5
        elif wr > 55:  mult *= 1.3
        elif wr > 50:  mult *= 1.1
        elif wr < 35:  mult *= 0.6
        elif wr < 40:  mult *= 0.8

        if ratio > 2.5:  mult *= 1.3
        elif ratio > 2.0: mult *= 1.1
        elif ratio < 1.2: mult *= 0.7

        return max(0.3, min(2.0, round(mult, 2)))

    def should_skip_pair(self, symbol: str) -> bool:
        stats = self.analyzer.get_stats_by_pair(symbol)
        if not stats or stats.get("total", 0) < 5:
            return False
        return stats.get("wr", 100) < 30 or stats.get("ratio", 999) < 0.9


class MarketRegimeDetector:
    """Detecta el régimen de mercado basado en trades recientes."""

    def __init__(self, analyzer: PairAnalyzer):
        self.analyzer = analyzer

    def detect_regime(self, lookback_hours=24) -> str:
        trades = self.analyzer.trades
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        recent = []
        for t in trades:
            try:
                ct = t.get("close_time", "")
                if ct:
                    dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    if dt.replace(tzinfo=timezone.utc) > cutoff:
                        recent.append(t)
            except Exception:
                pass

        if len(recent) < 5:
            return "neutral"

        recent_wr = sum(1 for t in recent if t.get("pnl", 0) > 0) / len(recent) * 100
        longs  = [t for t in recent if t.get("side") == "long"]
        shorts = [t for t in recent if t.get("side") == "short"]

        long_wr  = sum(1 for t in longs  if t.get("pnl", 0) > 0) / len(longs)  * 100 if longs  else 50
        short_wr = sum(1 for t in shorts if t.get("pnl", 0) > 0) / len(shorts) * 100 if shorts else 50

        if long_wr > 60 and short_wr < 40:   return "bullish"
        if short_wr > 60 and long_wr < 40:   return "bearish"
        if 40 < long_wr < 60 and 40 < short_wr < 60: return "lateral"
        return "choppy"

    def get_adjustment_for_regime(self, regime: str) -> dict:
        return {
            "bullish":           {"score_min_delta": -5,  "size_mult": 1.2},
            "bearish":           {"score_min_delta": -5,  "size_mult": 1.2},
            "lateral":           {"score_min_delta": +15, "size_mult": 0.7},
            "choppy":            {"score_min_delta": +20, "size_mult": 0.5},
            "neutral":           {"score_min_delta": 0,   "size_mult": 1.0},
        }.get(regime, {"score_min_delta": 0, "size_mult": 1.0})


class Learner:
    """Orquesta todo el aprendizaje automático."""

    def __init__(self):
        self.trades   = _load_trades()
        self.analyzer = PairAnalyzer(self.trades)
        self.adjuster = ParameterAdjuster(self.analyzer)
        self.regime   = MarketRegimeDetector(self.analyzer)

    def update(self):
        self.trades   = _load_trades()
        self.analyzer = PairAnalyzer(self.trades)
        self.adjuster = ParameterAdjuster(self.analyzer)

    def get_config_for_pair(self, symbol: str) -> dict:
        if self.adjuster.should_skip_pair(symbol):
            return {"skip": True, "reason": "Low performance"}

        market_regime = self.regime.detect_regime()
        regime_adj    = self.regime.get_adjustment_for_regime(market_regime)

        score_min  = self.adjuster.get_score_min_for_pair(symbol) + regime_adj["score_min_delta"]
        size_mult  = self.adjuster.get_size_multiplier_for_pair(symbol) * regime_adj["size_mult"]
        stats      = self.analyzer.get_stats_by_pair(symbol)

        return {
            "skip":            False,
            "symbol":          symbol,
            "score_min":       int(max(30, min(80, score_min))),
            "size_multiplier": round(max(0.3, min(2.0, size_mult)), 2),
            "regime":          market_regime,
            "reason":          f"WR:{stats.get('wr', 0):.1f}% Regime:{market_regime}",
        }

    def get_top_pairs(self, n=10) -> list:
        return self.analyzer.get_top_pairs(n)

    def get_bottom_pairs(self, n=5) -> list:
        return self.analyzer.get_bottom_pairs(n)

    def get_summary(self) -> dict:
        return {
            "timestamp":     datetime.now().isoformat(),
            "total_trades":  len(self.trades),
            "total_pairs":   len(self.analyzer.pair_stats),
            "top_pairs":     self.get_top_pairs(5),
            "bottom_pairs":  self.get_bottom_pairs(3),
            "market_regime": self.regime.detect_regime(),
            "pair_stats": {
                k: {
                    "total":  v["total"],
                    "wr":     round(v["wr"], 1),
                    "pnl":    round(v["pnl_total"], 4),
                    "ratio":  round(v["ratio"], 2),
                    "sharpe": round(v["sharpe"], 2),
                }
                for k, v in self.analyzer.pair_stats.items()
                if v["total"] > 0
            }
        }
