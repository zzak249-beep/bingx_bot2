import os, json
from datetime import datetime, timezone
from pathlib import Path
from config import (RISK_PCT, MAX_POSITIONS, MAX_DAILY_LOSS_PCT,
                    MAX_DRAWDOWN_PCT, MAX_CONSEC_LOSSES, INITIAL_BAL)

STATE_DIR  = Path("bot_state")
RISK_FILE  = STATE_DIR / "risk_state.json"
PAUSE_FILE = STATE_DIR / "pause.flag"

_state = {"peak_balance": INITIAL_BAL, "daily_start": INITIAL_BAL,
          "daily_date": None, "consecutive_losses": 0,
          "total_wins": 0, "total_losses": 0, "manually_paused": False}

def _load_state():
    global _state
    STATE_DIR.mkdir(exist_ok=True)
    try:
        with open(RISK_FILE) as f: _state.update(json.load(f))
    except: pass

def _save_state():
    STATE_DIR.mkdir(exist_ok=True)
    with open(RISK_FILE, "w") as f: json.dump(_state, f, indent=2)

_load_state()

def reset_daily_if_needed(balance: float):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _state.get("daily_date") != today:
        _state["daily_date"] = today
        _state["daily_start"] = balance
        _save_state()

def update_peak(balance: float):
    if balance > _state["peak_balance"]:
        _state["peak_balance"] = balance
        _save_state()

def record_win():
    _state["consecutive_losses"] = 0
    _state["total_wins"] += 1
    _save_state()

def record_loss():
    _state["consecutive_losses"] += 1
    _state["total_losses"] += 1
    _save_state()

def calc_position_size(balance, price, sl_price, atr, size_mult=1.0):
    if price <= 0 or sl_price <= 0: return 0.001
    risk_amount = balance * RISK_PCT * size_mult
    sl_distance = abs(price - sl_price)
    if sl_distance <= 0: return 0.001
    return max(risk_amount / sl_distance, 0.001)

def can_open_position(open_count, balance):
    if open_count >= MAX_POSITIONS: return False, f"max posiciones"
    if _state.get("manually_paused"): return False, "pausado"
    peak = _state["peak_balance"]
    if peak > 0 and (peak - balance) / peak >= MAX_DRAWDOWN_PCT:
        return False, "drawdown"
    daily_start = _state.get("daily_start", balance)
    if daily_start > 0 and (daily_start - balance) / daily_start >= MAX_DAILY_LOSS_PCT:
        return False, "perdida diaria"
    if _state["consecutive_losses"] >= MAX_CONSEC_LOSSES:
        return False, "perdidas consecutivas"
    return True, ""

def check_circuit_breaker(balance):
    peak = _state["peak_balance"]
    if peak > 0 and (peak - balance) / peak >= MAX_DRAWDOWN_PCT:
        return True, f"Drawdown critico: {(peak-balance)/peak*100:.1f}%"
    daily_start = _state.get("daily_start", balance)
    if daily_start > 0 and (daily_start - balance) / daily_start >= MAX_DAILY_LOSS_PCT:
        return True, f"Perdida diaria: {(daily_start-balance)/daily_start*100:.1f}%"
    if _state.get("manually_paused") or PAUSE_FILE.exists():
        return True, "Pausa manual"
    return False, ""

def is_manually_paused():
    return _state.get("manually_paused", False) or PAUSE_FILE.exists()

def pause():
    _state["manually_paused"] = True
    _save_state()
    PAUSE_FILE.touch()

def resume():
    _state["manually_paused"] = False
    _save_state()
    if PAUSE_FILE.exists(): PAUSE_FILE.unlink()

def get_stats(balance):
    peak = _state["peak_balance"]
    daily_start = _state.get("daily_start", balance)
    total = _state["total_wins"] + _state["total_losses"]
    return {
        "balance": round(balance, 2),
        "peak_balance": round(peak, 2),
        "drawdown_pct": round((peak-balance)/peak*100, 2) if peak > 0 else 0,
        "daily_pnl": round(balance - daily_start, 4),
        "daily_pnl_pct": round((balance-daily_start)/daily_start*100, 2) if daily_start > 0 else 0,
        "consecutive_losses": _state["consecutive_losses"],
        "total_wins": _state["total_wins"],
        "total_losses": _state["total_losses"],
        "overall_wr": round(_state["total_wins"]/total*100, 1) if total > 0 else 0,
    }
