"""
Motor de la estrategia — traducción literal y SOLO LARGO del script
Pine "ProBorsa: RSI & SuperTrend Özel Dip Stratejisi".

A DIFERENCIA del rsi_confirm.py del bot de reversión (que sí añade el
espejo bajista para poder confirmar señales SELL), aquí NO se añade
nada: este bot reproduce el original tal cual, que solo opera en
largo. Si algún día quieres el lado corto, es la misma idea que ya
está en rsi_confirm.py — pero eso sería otro bot, no una traducción
fiel de este.

QUÉ CUENTA COMO SEÑAL: el RSI cruza por ENCIMA de su propia SMA
mientras sigue por debajo de 50 (zona débil). Se cuenta cada cruce así
desde la última vez que el RSI superó 50; se entra en el 2º cruce
(doble suelo visto en el RSI, no en el precio).

SALIDA: no hay TP. Se cierra cuando el SuperTrend(10, 2.5) gira de
alcista a bajista — el "SL" que se muestra en la señal es solo el
valor ACTUAL del SuperTrend en el momento de entrar, informativo: no
es una orden de stop real colocada en el exchange (el propio script
Pine tampoco la coloca — cierra con strategy.close() cuando cambia la
dirección, no con un stop de precio fijo).
"""
from __future__ import annotations

from dataclasses import dataclass


def _rma(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append((out[-1] * (length - 1) + v) / length)
    return out


def rsi(closes: list[float], length: int) -> list[float]:
    if len(closes) < 2:
        return []
    ups, downs = [0.0], [0.0]
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ups.append(max(ch, 0.0))
        downs.append(max(-ch, 0.0))
    up_rma = _rma(ups, length)
    down_rma = _rma(downs, length)
    out: list[float] = []
    for u, d in zip(up_rma, down_rma):
        if d == 0:
            out.append(100.0)
        elif u == 0:
            out.append(0.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + u / d))
    return out


def sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        out.append(None if i + 1 < length else sum(values[i - length + 1 : i + 1]) / length)
    return out


def _true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return trs


def supertrend(
    highs: list[float], lows: list[float], closes: list[float], period: int, factor: float
) -> tuple[list[float], list[int], list[float]]:
    """
    Traducción de ta.supertrend(factor, period) de Pine. Devuelve
    (línea, dirección, atr) — dirección -1 = alcista (línea = banda
    inferior), dirección 1 = bajista (línea = banda superior). El
    cambio de -1 a 1 es la señal de salida del script original
    (ta.change(stDirection) > 0).
    """
    atr = _rma(_true_range(highs, lows, closes), period)
    n = len(closes)
    upper = [0.0] * n
    lower = [0.0] * n
    st = [0.0] * n
    direction = [1] * n
    for i in range(n):
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_upper = hl2 + factor * atr[i]
        basic_lower = hl2 - factor * atr[i]
        if i == 0:
            upper[i], lower[i] = basic_upper, basic_lower
            direction[i] = 1
            st[i] = upper[i]
            continue
        upper[i] = basic_upper if (basic_upper < upper[i - 1] or closes[i - 1] > upper[i - 1]) else upper[i - 1]
        lower[i] = basic_lower if (basic_lower > lower[i - 1] or closes[i - 1] < lower[i - 1]) else lower[i - 1]
        if st[i - 1] == upper[i - 1]:
            direction[i] = -1 if closes[i] > upper[i] else 1
        else:
            direction[i] = 1 if closes[i] < lower[i] else -1
        st[i] = lower[i] if direction[i] == -1 else upper[i]
    return st, direction, atr


@dataclass
class EntrySignal:
    symbol: str
    entry: float
    st_stop: float       # valor del SuperTrend al entrar — informativo, no es una orden real
    riesgo_pct: float
    rsi_actual: float
    atr_pct: float


def evaluate(
    symbol: str,
    candles: list[dict],
    rsi_length: int = 10,
    sig_length: int = 10,
    trigger: float = 50.0,
    target_count: int = 2,
    st_period: int = 10,
    st_factor: float = 2.5,
) -> EntrySignal | None:
    """Solo velas cerradas — se descarta la última (en curso)."""
    need = max(rsi_length, sig_length, st_period) + target_count + 10
    if len(candles) < need:
        return None
    c = candles[:-1]
    closes = [x["close"] for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]

    r = rsi(closes, rsi_length)
    s = sma(r, sig_length)
    st, _direction, atr = supertrend(highs, lows, closes, st_period, st_factor)
    n = len(r)
    if n < 2:
        return None

    bull_count = 0
    especial = False
    for i in range(1, n):
        if s[i] is None or s[i - 1] is None:
            continue
        bull_cross = r[i - 1] <= s[i - 1] and r[i] > s[i]
        especial = False
        if r[i] > trigger:
            bull_count = 0
        if bull_cross and r[i] < trigger:
            bull_count += 1
            if bull_count == target_count:
                especial = True
                bull_count = 0

    if not especial:
        return None

    entry = closes[-1]
    st_stop = st[-1]
    riesgo_pct = abs(entry - st_stop) / entry * 100.0 if entry > 0 else 0.0
    atr_pct = atr[-1] / entry * 100.0 if entry > 0 else 0.0

    return EntrySignal(
        symbol=symbol, entry=entry, st_stop=st_stop,
        riesgo_pct=riesgo_pct, rsi_actual=r[-1], atr_pct=atr_pct,
    )


def is_bearish_now(candles: list[dict], st_period: int = 10, st_factor: float = 2.5) -> bool:
    """
    Para las posiciones ya abiertas: ¿el SuperTrend está ahora mismo en
    dirección bajista? No hace falta detectar el instante exacto del
    giro — con comprobarlo en cada ciclo basta, igual que el resto del
    proyecto vigila SL/TP por sondeo en vez de por evento.
    """
    c = candles[:-1]
    if len(c) < st_period + 5:
        return False
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]
    closes = [x["close"] for x in c]
    _st, direction, _atr = supertrend(highs, lows, closes, st_period, st_factor)
    return direction[-1] == 1
