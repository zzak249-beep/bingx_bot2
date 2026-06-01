"""
Risk Manager — Position sizing, drawdown control, portfolio limits
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from src.engine import SignalResult, Signal

logger = logging.getLogger("risk")


@dataclass
class Position:
    symbol:      str
    side:        str          # LONG / SHORT
    entry:       float
    sl:          float
    tp1:         float
    tp2:         float
    size:        float        # units
    score:       int
    signal_type: str
    tp1_hit:     bool = False
    be_moved:    bool = False  # SL moved to breakeven after TP0.5


class RiskManager:
    def __init__(self, config: dict):
        self.cfg       = config
        self.positions: dict[str, Position] = {}  # symbol -> Position
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.equity    = config.get("capital", 1000.0)

    # ── POSITION SIZING ──────────────────────────────────────────────

    def compute_size(self, result: SignalResult, direction: str) -> float:
        """
        Uses Kelly sizing from engine result, capped by:
        - Max position % of capital
        - Max open positions
        - Daily loss limit
        """
        if self._is_blocked():
            return 0.0

        max_pos_pct = self.cfg.get("max_pos_pct", 0.05)   # 5% per trade
        max_open    = self.cfg.get("max_open_positions", 5)

        if len(self.positions) >= max_open:
            logger.warning("Max open positions reached")
            return 0.0

        # Kelly size from engine
        raw_size = result.pos_size

        # Cap to max_pos_pct of equity
        sl_dist = (result.close - result.sl_long) if direction == "LONG" else (result.sl_short - result.close)
        if sl_dist <= 0:
            return 0.0

        max_risk_usdt = self.equity * max_pos_pct
        max_size      = max_risk_usdt / sl_dist
        size          = min(raw_size, max_size)

        # Minimum position size
        min_size = self.cfg.get("min_pos_size", 0.001)
        if size < min_size:
            return 0.0

        return round(size, 4)

    def _is_blocked(self) -> bool:
        """Block trading on daily loss limit or max trades"""
        max_daily_loss = self.cfg.get("max_daily_loss_pct", 3.0)
        max_daily_trd  = self.cfg.get("max_daily_trades", 20)

        if self.equity > 0:
            loss_pct = (self.daily_pnl / self.equity) * 100
            if loss_pct <= -max_daily_loss:
                logger.warning(f"Daily loss limit hit: {loss_pct:.1f}%")
                return True

        if self.daily_trades >= max_daily_trd:
            logger.warning("Daily trade limit hit")
            return True

        return False

    def can_trade(self, symbol: str, direction: str) -> bool:
        """Check if we can open a new position for this symbol"""
        if symbol in self.positions:
            existing = self.positions[symbol]
            if existing.side == direction:
                return False  # Already in same direction
        return not self._is_blocked()

    def register_open(self, result: SignalResult, direction: str, size: float):
        """Register a newly opened position"""
        sl  = result.sl_long  if direction == "LONG"  else result.sl_short
        tp1 = result.tp1_long if direction == "LONG"  else result.tp1_short
        tp2 = result.tp2_long if direction == "LONG"  else result.tp2_short
        score = result.score_long if direction == "LONG" else result.score_short

        self.positions[result.symbol] = Position(
            symbol=result.symbol,
            side=direction,
            entry=result.close,
            sl=sl, tp1=tp1, tp2=tp2,
            size=size,
            score=score,
            signal_type=result.signal.value,
        )
        self.daily_trades += 1
        logger.info(f"Position opened: {result.symbol} {direction} size={size} entry={result.close}")

    def register_close(self, symbol: str, exit_price: float):
        """Register position close and update PnL"""
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        if pos.side == "LONG":
            pnl = (exit_price - pos.entry) * pos.size
        else:
            pnl = (pos.entry - exit_price) * pos.size

        self.daily_pnl += pnl
        self.equity    += pnl
        del self.positions[symbol]
        logger.info(f"Position closed: {symbol} pnl={pnl:.4f} USDT")

    def check_partial_tp(self, symbol: str, current_price: float) -> Optional[float]:
        """
        PTP: Partial TP at TP0.5 (25% of position)
        Returns partial size if triggered, else None
        """
        if symbol not in self.positions:
            return None
        pos = self.positions[symbol]
        if pos.tp1_hit:
            return None

        tp05_mult = self.cfg.get("ptp_mult", 0.5)
        # Compute TP0.5 price
        atr_approx = abs(pos.tp1 - pos.entry) / self.cfg.get("tp1_mult", 1.5)
        if pos.side == "LONG":
            tp05 = pos.entry + atr_approx * tp05_mult
            if current_price >= tp05:
                partial_size = pos.size * 0.25
                pos.tp1_hit  = True
                pos.be_moved = True
                pos.sl       = pos.entry  # Move SL to breakeven
                logger.info(f"Partial TP triggered: {symbol} at {current_price}")
                return partial_size
        else:
            tp05 = pos.entry - atr_approx * tp05_mult
            if current_price <= tp05:
                partial_size = pos.size * 0.25
                pos.tp1_hit  = True
                pos.be_moved = True
                pos.sl       = pos.entry
                logger.info(f"Partial TP triggered: {symbol} at {current_price}")
                return partial_size
        return None

    def reset_daily(self):
        """Call at start of each trading day"""
        logger.info(f"Daily reset — PnL: {self.daily_pnl:.2f} USDT, Trades: {self.daily_trades}")
        self.daily_pnl    = 0.0
        self.daily_trades = 0

    def summary(self) -> str:
        lines = [
            f"💼 Capital: {self.equity:.2f} USDT",
            f"📊 Open positions: {len(self.positions)}",
            f"📅 Daily PnL: {self.daily_pnl:+.2f} USDT",
            f"🔢 Daily trades: {self.daily_trades}",
        ]
        for sym, pos in self.positions.items():
            lines.append(f"  • {sym} {pos.side} @{pos.entry:.4g} SL:{pos.sl:.4g} size:{pos.size}")
        return "\n".join(lines)
