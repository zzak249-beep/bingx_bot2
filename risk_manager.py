import json
import os
from datetime import datetime, date
from config import (
    MAX_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT, MAX_CONCURRENT_POS,
    ATR_SIZING, ATR_SIZING_BASE, CIRCUIT_BREAKER_LOSS,
    RISK_PCT, LEVERAGE, INITIAL_BAL
)

# ══════════════════════════════════════════════════════
# risk_manager.py — Gestión de riesgo avanzada v12.3
# Circuit breaker, drawdown, sizing dinámico por ATR
# ══════════════════════════════════════════════════════

_STATE_FILE = "risk_state.json"


def _load() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "peak_balance":      INITIAL_BAL,
        "daily_start_bal":   INITIAL_BAL,
        "daily_date":        str(date.today()),
        "consecutive_losses": 0,
        "paused":            False,
        "pause_reason":      "",
    }


def _save(state: dict):
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


_state = _load()


def reset_daily_if_needed(balance: float):
    """Resetea contadores diarios si es un nuevo día."""
    global _state
    today = str(date.today())
    if _state.get("daily_date") != today:
        _state["daily_date"]      = today
        _state["daily_start_bal"] = balance
        _save(_state)


def update_peak(balance: float):
    """Actualiza el balance máximo histórico."""
    global _state
    if balance > _state["peak_balance"]:
        _state["peak_balance"] = balance
        _save(_state)


def record_loss():
    global _state
    _state["consecutive_losses"] += 1
    _save(_state)


def record_win():
    global _state
    _state["consecutive_losses"] = 0
    _save(_state)


def check_circuit_breaker(balance: float) -> tuple[bool, str]:
    """
    Retorna (bloqueado: bool, razón: str).
    Bloquea si:
      - Pérdida diaria > MAX_DAILY_LOSS_PCT
      - Drawdown desde máximo > MAX_DRAWDOWN_PCT
    """
    global _state
    reset_daily_if_needed(balance)
    update_peak(balance)

    # Pérdida diaria
    daily_start = _state["daily_start_bal"]
    if daily_start > 0:
        daily_loss = (daily_start - balance) / daily_start
        if daily_loss >= MAX_DAILY_LOSS_PCT:
            reason = f"Circuit breaker: pérdida diaria {daily_loss*100:.1f}% >= {MAX_DAILY_LOSS_PCT*100:.0f}%"
            _state["paused"] = True
            _state["pause_reason"] = reason
            _save(_state)
            return True, reason

    # Drawdown máximo
    peak = _state["peak_balance"]
    if peak > 0:
        drawdown = (peak - balance) / peak
        if drawdown >= MAX_DRAWDOWN_PCT:
            reason = f"Circuit breaker: drawdown {drawdown*100:.1f}% >= {MAX_DRAWDOWN_PCT*100:.0f}%"
            _state["paused"] = True
            _state["pause_reason"] = reason
            _save(_state)
            return True, reason

    # Si estaba pausado por circuit breaker pero se recuperó un poco, auto-resume
    if _state.get("paused") and "Circuit breaker" in _state.get("pause_reason", ""):
        _state["paused"] = False
        _state["pause_reason"] = ""
        _save(_state)

    return False, ""


def is_manually_paused() -> bool:
    return _state.get("paused", False) and "Circuit breaker" not in _state.get("pause_reason", "")


def pause(reason: str = "manual"):
    global _state
    _state["paused"] = True
    _state["pause_reason"] = reason
    _save(_state)


def resume():
    global _state
    _state["paused"] = False
    _state["pause_reason"] = ""
    _save(_state)


def get_state() -> dict:
    return dict(_state)


def can_open_position(open_count: int, balance: float) -> tuple[bool, str]:
    """Verifica si se puede abrir una nueva posición."""
    blocked, reason = check_circuit_breaker(balance)
    if blocked:
        return False, reason
    if _state.get("paused"):
        return False, f"Bot pausado: {_state.get('pause_reason', 'manual')}"
    if open_count >= MAX_CONCURRENT_POS:
        return False, f"Máximo de posiciones abiertas ({MAX_CONCURRENT_POS}) alcanzado"
    return True, ""


def calc_position_size(balance: float, price: float, sl: float, atr: float) -> float:
    """
    Calcula el tamaño de posición.
    - Si ATR_SIZING=True: ajusta por volatilidad (ATR normalizado)
    - Si hay racha de pérdidas: reduce tamaño 50%
    Retorna qty en moneda base.
    """
    if not ATR_SIZING or atr <= 0 or price <= 0:
        risk = RISK_PCT
    else:
        # Normalizar ATR: ATR/precio = % de movimiento
        atr_pct = atr / price
        # Comparar con ATR% de referencia (0.02 = 2%)
        # Si el par es más volátil, reducimos el tamaño
        ref_atr_pct = 0.02
        volatility_ratio = ref_atr_pct / atr_pct if atr_pct > 0 else 1.0
        # Clamp entre 0.5x y 2x del riesgo base
        volatility_ratio = max(0.5, min(2.0, volatility_ratio))
        risk = ATR_SIZING_BASE * volatility_ratio

    # Circuit breaker por racha de pérdidas
    if _state["consecutive_losses"] >= CIRCUIT_BREAKER_LOSS:
        risk *= 0.5   # reducir tamaño 50% en racha perdedora

    qty = (balance * risk * LEVERAGE) / price
    return qty


def get_stats(balance: float) -> dict:
    reset_daily_if_needed(balance)
    peak = _state["peak_balance"]
    daily_start = _state["daily_start_bal"]
    return {
        "peak_balance":       round(peak, 2),
        "drawdown_pct":       round((peak - balance) / peak * 100, 2) if peak > 0 else 0,
        "daily_pnl":          round(balance - daily_start, 4),
        "daily_pnl_pct":      round((balance - daily_start) / daily_start * 100, 2) if daily_start > 0 else 0,
        "consecutive_losses": _state["consecutive_losses"],
        "paused":             _state.get("paused", False),
        "pause_reason":       _state.get("pause_reason", ""),
    }
