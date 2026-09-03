"""
Scans a universe of symbols (one, a list, or every active USDT-M swap on
BingX) each cycle. Entries are still decided per-symbol by the wavelet
regime filter; the one thing that is genuinely PORTFOLIO-level is the
concurrent-position cap — with many symbols eligible to fire at once,
that cap is what keeps total exposure bounded instead of unbounded, and
it is enforced across the whole cycle, not per-symbol in isolation (two
symbols firing in the same cycle both see and respect the same count).

One poll = one full scan:
  1. fetch account equity + ALL open positions ONCE (not per-symbol)
  2. update the daily kill switch from that equity
  3. for each symbol in the universe, in order:
       a. fetch its candles, drop the still-forming one
       b. if it has an open position: sweep-exit check, then trailing-stop
       c. compute the wavelet regime + crossover
       d. if a fresh entry signal fires AND no position is already open on
          it AND the portfolio isn't at the concurrent-position cap AND
          the kill switch isn't tripped: place the order
       e. always notify Telegram, whether or not an order was placed

Scanning "all" symbols is inherently slower than one — see README for the
realistic wall-clock cost of a full-market cycle given BingX's rate limit.
"""
import logging
import time

from .config import Config
from .exchange import BingXExchange, ExchangeError
from .risk import DailyKillSwitch, compute_sl_tp
from .sweep_reversal import SweepReversalSignals
from .telegram_notify import TelegramNotifier
from .wavelet import WaveletRegime

log = logging.getLogger(__name__)


class SymbolState:
    """Per-symbol mutable bookkeeping — cooldown timing, the last sweep
    alert handled, and the current trailing-stop level. One of these is
    kept per symbol in the universe for the life of the process."""

    __slots__ = ("last_signal_ts", "last_sweep_alert_ts", "trail_stop_price")

    def __init__(self):
        self.last_signal_ts = None
        self.last_sweep_alert_ts = None
        self.trail_stop_price = None


class PortfolioStrategy:
    def __init__(self, config: Config, exchange: BingXExchange, notifier: TelegramNotifier):
        self.config = config
        self.exchange = exchange
        self.notifier = notifier
        self.regime = WaveletRegime(config.lookback_energy, config.k_dominance)
        self.kill_switch = DailyKillSwitch(config.max_daily_loss_pct)

        self.sweep = None
        if config.use_sweep_exit_filter:
            self.sweep = SweepReversalSignals(
                swing_length=config.sweep_swing_length,
                atr_length=config.sweep_atr_length,
                min_penetration=config.sweep_min_penetration,
                structure_length=config.sweep_structure_length,
                max_confirmation_bars=config.sweep_max_confirmation_bars,
                min_displacement=config.sweep_min_displacement,
            )

        self.symbols = self._resolve_universe()
        self.state = {symbol: SymbolState() for symbol in self.symbols}

        self._fetch_limit = max(300, config.lookback_energy + 80)
        log.info("Universe resolved to %d symbol(s): %s", len(self.symbols), self._preview_symbols())

    def _preview_symbols(self) -> str:
        if len(self.symbols) <= 8:
            return ", ".join(self.symbols)
        return ", ".join(self.symbols[:8]) + f", … (+{len(self.symbols) - 8} more)"

    def _resolve_universe(self) -> list:
        raw = self.config.symbol_universe.strip()
        exclude = [s.strip() for s in self.config.symbol_exclude.split(",") if s.strip()]

        if raw.lower() == "all":
            symbols = self.exchange.fetch_active_symbols(
                min_volume_usdt=self.config.min_24h_volume_usdt, exclude=exclude
            )
        else:
            symbols = [s.strip() for s in raw.split(",") if s.strip() and s.strip() not in exclude]

        if not symbols:
            raise SystemExit(
                "Symbol universe resolved to zero symbols — check SYMBOL_UNIVERSE, "
                "SYMBOL_EXCLUDE, and MIN_24H_VOLUME_USDT."
            )
        return symbols

    # ------------------------------------------------------------------ loop
    def run_once(self) -> None:
        equity = self.exchange.fetch_equity_usdt() if self.exchange.has_keys else 0.0
        halted = self.kill_switch.update(equity) if self.exchange.has_keys else False

        open_positions = self.exchange.fetch_all_open_positions() if self.exchange.has_keys else []
        open_by_symbol = {p["symbol"]: p for p in open_positions}
        concurrent_count = len(open_positions)

        start = time.monotonic()
        opened_this_cycle = 0
        errors = 0

        for symbol in self.symbols:
            try:
                opened = self._evaluate_symbol(
                    symbol,
                    equity=equity,
                    halted=halted,
                    current_position=open_by_symbol.get(symbol),
                    concurrent_count=concurrent_count + opened_this_cycle,
                )
                if opened:
                    opened_this_cycle += 1
            except Exception:
                errors += 1
                log.exception("Error evaluating %s — continuing with the rest of the scan.", symbol)

        elapsed = time.monotonic() - start
        log.info(
            "Scan complete: %d symbol(s) in %.1fs, %d new entr%s, %d open position(s), %d error(s).",
            len(self.symbols),
            elapsed,
            opened_this_cycle,
            "y" if opened_this_cycle == 1 else "ies",
            concurrent_count + opened_this_cycle,
            errors,
        )

    # --------------------------------------------------------- per symbol
    def _evaluate_symbol(
        self, symbol: str, equity: float, halted: bool, current_position, concurrent_count: int
    ) -> bool:
        """Returns True if a new live position was opened on this symbol."""
        state = self.state[symbol]

        if not current_position:
            state.last_sweep_alert_ts = None
            state.trail_stop_price = None

        df = self.exchange.fetch_ohlcv_df(symbol, self.config.timeframe, limit=self._fetch_limit)
        if len(df) < 3:
            log.warning("Not enough candles returned for %s (%s) — skipping.", symbol, len(df))
            return False
        closed = df.iloc[:-1]

        if self.sweep is not None and current_position:
            self._run_sweep_exit_check(symbol, state, closed, current_position)

        try:
            sig = self.regime.compute(closed, atr_length=self.config.atr_length)
        except ValueError:
            return False  # not enough history yet for this symbol (e.g. a new listing)
        merged = closed.join(sig)
        last = merged.iloc[-1]
        last_ts = merged.index[-1]

        if current_position and self.config.use_trail:
            self._maybe_update_trailing(symbol, state, current_position, last)

        if current_position:
            return False  # never stack a second entry on a symbol already open

        if self.config.use_vol_filter:
            vol_sma = closed["volume"].rolling(self.config.vol_len).mean()
            vol_ok = bool(closed["volume"].iloc[-1] > vol_sma.iloc[-1] * self.config.vol_mult)
        else:
            vol_ok = True

        cooldown_ok = self._cooldown_ok(state, merged, last_ts)
        long_cond = bool(last["is_trending"] and vol_ok and last["cross_up"] and last["h8"] > 0 and cooldown_ok)
        short_cond = bool(last["is_trending"] and vol_ok and last["cross_down"] and last["h8"] < 0 and cooldown_ok)

        if not (long_cond or short_cond):
            return False

        state.last_signal_ts = last_ts
        side = "long" if long_cond else "short"
        price = float(last["close"])
        atr_val = float(last["atr"])

        sl, tp = compute_sl_tp(
            side, price, atr_val,
            self.config.use_atr_sl, self.config.atr_mult_sl, self.config.atr_mult_tp,
            self.config.sl_percent, self.config.tp_percent,
        )

        live_order_sent = False
        opened = False
        skip_reason = None

        if halted:
            skip_reason = "kill switch diario activo"
            log.warning("%s: kill switch active — %s signal not traded.", symbol, side)
        elif concurrent_count >= self.config.max_concurrent_positions:
            skip_reason = f"límite de {self.config.max_concurrent_positions} posiciones simultáneas alcanzado"
            log.info("%s: %s signal skipped — at MAX_CONCURRENT_POSITIONS.", symbol, side)
        elif self.config.can_trade_live:
            try:
                notional = max(equity, 0.0) * (self.config.qty_pct / 100)
                self.exchange.enter_position(symbol, side, notional, price, sl, tp)
                live_order_sent = True
                opened = True
                state.trail_stop_price = sl
            except ExchangeError:
                pass  # already logged and telegrammed inside exchange.py
            except Exception as e:
                log.exception("Unexpected error entering position on %s", symbol)
                self.notifier.send_error(f"Unexpected error entering {side} on {symbol}: {e}")

        self.notifier.send_signal(
            side=side, symbol=symbol, price=price, sl=sl, tp=tp,
            timeframe=self.config.timeframe, mode_label=self.config.mode_label,
            live_order_sent=live_order_sent, skip_reason=skip_reason,
        )
        return opened

    def _cooldown_ok(self, state: SymbolState, merged, last_ts) -> bool:
        if state.last_signal_ts is None:
            return True
        try:
            bars_since = merged.index.get_loc(last_ts) - merged.index.get_loc(state.last_signal_ts)
        except KeyError:
            return True
        return bars_since >= self.config.cooldown_bars

    def _maybe_update_trailing(self, symbol: str, state: SymbolState, position: dict, last) -> None:
        side = position.get("side")
        entry = float(position.get("entryPrice") or 0)
        price = float(last["close"])
        atr_val = float(last["atr"]) if last["atr"] == last["atr"] else 0.0  # NaN check
        if not entry or not atr_val:
            return

        trigger = self.config.trail_trigger_atr * atr_val
        offset = self.config.trail_offset_atr * atr_val

        if side == "long":
            in_profit_enough = price >= entry + trigger
            candidate_stop = price - offset
            improves = state.trail_stop_price is None or candidate_stop > state.trail_stop_price
        else:
            in_profit_enough = price <= entry - trigger
            candidate_stop = price + offset
            improves = state.trail_stop_price is None or candidate_stop < state.trail_stop_price

        if in_profit_enough and improves:
            state.trail_stop_price = candidate_stop
            self.exchange.update_trailing_stop(symbol, side, candidate_stop)

    # ------------------------------------------------------- sweep exit
    def _run_sweep_exit_check(self, symbol: str, state: SymbolState, closed, position: dict) -> None:
        try:
            sweep_sig = self.sweep.compute(closed)
        except ValueError:
            return
        except Exception:
            log.exception("Sweep-reversal computation failed for %s — skipping this cycle.", symbol)
            return

        sweep_last = closed.join(sweep_sig).iloc[-1]
        self._check_sweep_exit(symbol, state, sweep_last, position)

    def _check_sweep_exit(self, symbol: str, state: SymbolState, sweep_last, position: dict) -> None:
        side = position.get("side")
        contrary = (side == "long" and bool(sweep_last["bearish_confirmed"])) or (
            side == "short" and bool(sweep_last["bullish_confirmed"])
        )
        if not contrary:
            return

        bar_ts = sweep_last.name
        if state.last_sweep_alert_ts == bar_ts:
            return
        state.last_sweep_alert_ts = bar_ts

        price = float(sweep_last["close"])
        kind = "bajista" if side == "long" else "alcista"
        reason = f"Sweep-reversal {kind} confirmado en contra de la posición {side} abierta en {symbol}."
        action = self.config.sweep_exit_action
        log.info("Sweep-reversal exit trigger on %s: side=%s action=%s price=%.6f", symbol, side, action, price)

        if action == "close_position":
            try:
                self.exchange.close_position(symbol, reason=reason)
                self.notifier.send_exit(symbol, side, price, reason + " Posición cerrada automáticamente.")
            except Exception as e:
                log.exception("Failed to auto-close on sweep-reversal signal for %s", symbol)
                self.notifier.send_error(f"Sweep-reversal pidió cerrar {side} en {symbol} pero falló: {e}")

        elif action == "tighten_stop":
            entry = float(position.get("entryPrice") or price)
            try:
                self.exchange.update_trailing_stop(symbol, side, entry)
                self.notifier.send(
                    f"🟠 <b>Sweep-reversal en contra</b> — {symbol} ({side})\n"
                    f"{reason}\nStop movido a breakeven (<code>{entry:.6f}</code>)."
                )
            except Exception as e:
                log.exception("Failed to tighten stop on sweep-reversal signal for %s", symbol)
                self.notifier.send_error(f"Sweep-reversal pidió mover el stop en {symbol} pero falló: {e}")

        else:  # alert_only — the default
            self.notifier.send(
                f"🟠 <b>Alerta de reversión (sweep)</b> — {symbol} ({side})\n"
                f"{reason}\nPrecio: <code>{price:.6f}</code>\n"
                f"Sin acción automática (SWEEP_EXIT_ACTION=alert_only)."
            )
