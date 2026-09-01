"""
momentum.py
-----------
Ruptura de contracción de volatilidad al estilo Qullamaggie (Kristjan
Kullamägi): comprar fuerza que rompe de una consolidación estrecha,
con la tendencia — no comprar debilidad esperando un rebote.

POR QUÉ ES UN MÓDULO APARTE Y NO UNA MEJORA DE strategy.py: son dos
filosofías opuestas, no una versión mejorada de la otra. La estrategia
existente (que no se toca aquí, y que este archivo ni importa) busca
REVERSIÓN — un precio estirado lejos de su media, con vela de
agotamiento, apostando a que vuelve. Qullamaggie busca CONTINUACIÓN —
un precio fuerte que ha estado subiendo, se toma un respiro en un
rango cada vez más estrecho (la "bandera"), y se compra cuando rompe
ese rango siguiendo la tendencia. Meter las dos cosas en la misma
función sería promediar dos apuestas contrarias; se generan señales
por separado y cada una se etiqueta con su origen (ver Signal.motor).

LO QUE SÍ ESTÁ DOCUMENTADO PÚBLICAMENTE (y es lo que hay aquí) del
enfoque de Qullamaggie:
  1. Contexto de tendencia: precio por encima de una media móvil que a
     su vez tiene pendiente ascendente (para largos; espejo para cortos).
  2. Contracción: el rango de las últimas velas se ha ido estrechando
     frente al rango de un periodo más largo — la "bandera" o
     consolidación apretada antes del movimiento siguiente.
  3. Ruptura: el cierre de la última vela supera el máximo (o mínimo)
     del rango de consolidación.
  4. Gestión: entrada cerca de la ruptura, stop en el otro lado de la
     consolidación (o un múltiplo de ATR si eso queda demasiado lejos),
     tamaño fijado por el riesgo — igual que el resto del proyecto, no
     una regla nueva.

LO QUE NO ES: Qullamaggie opera acciones en diario/semanal con datos
fundamentales y de sector que aquí no existen (no hay "relative
strength" contra un índice, no hay volumen de opciones, no hay
catalizador de resultados). Esto es una adaptación honesta de la
MECÁNICA de ruptura-tras-contracción a velas de 5m en cripto, no una
réplica de su proceso completo.

NO VALIDADO CON DATOS TODAVÍA — igual que xsection.py y wyckoff.py.
Arranca DESACTIVADO (MOMENTUM_ENABLED=false) a propósito: es un modo
nuevo que compite por el mismo hueco de MAX_CONCURRENT, así que no
debe empezar a operar solo porque el archivo existe en el repo.

CONFIGURACIÓN (variables de entorno propias, no depende de config.py):
  MOMENTUM_ENABLED            (false)
  MOMENTUM_MA_LEN             (20)   media móvil para el contexto de tendencia
  MOMENTUM_CONTRACTION_LEN    (10)   velas recientes para medir la contracción
  MOMENTUM_BASE_LEN           (40)   velas más largas de referencia para comparar el rango
  MOMENTUM_MAX_CONTRACTION    (0.6)  rango reciente / rango base máximo para contar como "apretado"
  MOMENTUM_BREAKOUT_LEN       (10)   velas de la consolidación cuyo máximo/mínimo se rompe
  MOMENTUM_SL_ATR             (1.2)  distancia del stop, en ATR, si la consolidación queda muy lejos
  MOMENTUM_RR_FIXED           (2.0)  objetivo como múltiplo del riesgo (igual de simple que RR_FIXED)
  MOMENTUM_MIN_RR             (1.2)
  MOMENTUM_MIN_ATR_PCT        (0.15) amplitud mínima — más baja que la de reversión: aquí no hace
                                       falta un ATR enorme, hace falta tendencia + contracción real
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _i(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _b(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


ENABLED = _b("MOMENTUM_ENABLED", False)
REQUIRE_30M_ALIGNMENT = _b("MOMENTUM_REQUIRE_30M_ALIGNMENT", False)
MA_LEN = _i("MOMENTUM_MA_LEN", 20)
CONTRACTION_LEN = _i("MOMENTUM_CONTRACTION_LEN", 10)
BASE_LEN = _i("MOMENTUM_BASE_LEN", 40)
MAX_CONTRACTION = _f("MOMENTUM_MAX_CONTRACTION", 0.6)
BREAKOUT_LEN = _i("MOMENTUM_BREAKOUT_LEN", 10)
SL_ATR = _f("MOMENTUM_SL_ATR", 1.2)
RR_FIXED = _f("MOMENTUM_RR_FIXED", 2.0)
MIN_RR = _f("MOMENTUM_MIN_RR", 1.2)
MIN_ATR_PCT = _f("MOMENTUM_MIN_ATR_PCT", 0.15)


@dataclass
class Signal:
    """Misma forma que strategy.Signal (duck-typing: scanner.py, score.py y
    main.py.handle_signal() solo acceden a estos atributos, nunca comprueban
    el tipo) — pero con un campo extra, `motor`, para que main.py pueda
    distinguir en los logs y en Telegram de dónde vino cada operación."""

    symbol: str
    side: str  # "BUY" | "SELL"
    entry: float
    sl: float
    tp: float
    rr: float
    atr_pct: float
    cost_cover: float
    stretch: float  # aquí: distancia a la media en ATR (contexto, no "estirón" de reversión)
    motor: str = "momentum"


def _ema(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _atr(highs: list[float], lows: list[float], closes: list[float], length: int) -> list[float]:
    trs: list[float] = []
    prev_close = None
    for h, low, c in zip(highs, lows, closes):
        tr = (h - low) if prev_close is None else max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = c
    if len(trs) < length:
        return []
    out = [sum(trs[:length]) / length]
    for tr in trs[length:]:
        out.append((out[-1] * (length - 1) + tr) / length)
    return [0.0] * (length - 1) + out


def evaluate(symbol: str, candles: list[dict], cost_roundtrip_pct: float = 0.25):
    """
    Misma firma de retorno que se asume de strategy.evaluate(): (Signal|None, motivo).
    candles: mismo formato (dicts con open/high/low/close/volume), la
    última se descarta por estar en curso.
    """
    need = max(MA_LEN, BASE_LEN) + 5
    if len(candles) < need + 1:
        return None, "datos insuficientes"
    c = candles[:-1]
    closes = [x["close"] for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]

    ma = _ema(closes, MA_LEN)
    atr = _atr(highs, lows, closes, 14)
    if not ma or not atr or atr[-1] <= 0 or closes[-1] <= 0:
        return None, "sin datos de ATR/media"

    atr_pct = atr[-1] / closes[-1] * 100.0
    if atr_pct < MIN_ATR_PCT:
        return None, f"amplitud insuficiente ({atr_pct:.2f}% < {MIN_ATR_PCT}%)"

    # Contexto de tendencia: precio y pendiente de la media.
    pendiente = ma[-1] - ma[-MA_LEN] if len(ma) > MA_LEN else 0.0
    tendencia_alcista = closes[-1] > ma[-1] and pendiente > 0
    tendencia_bajista = closes[-1] < ma[-1] and pendiente < 0
    if not tendencia_alcista and not tendencia_bajista:
        return None, "sin tendencia clara"

    # Contracción: rango reciente frente a rango base más largo.
    rango_reciente = max(highs[-CONTRACTION_LEN:]) - min(lows[-CONTRACTION_LEN:])
    rango_base = max(highs[-BASE_LEN:]) - min(lows[-BASE_LEN:])
    if rango_base <= 0:
        return None, "sin rango base"
    contraccion = rango_reciente / rango_base
    if contraccion > MAX_CONTRACTION:
        return None, f"sin contracción suficiente ({contraccion:.2f} > {MAX_CONTRACTION})"

    # Ruptura: el cierre actual supera el rango de consolidación previo
    # (excluyendo la propia vela de ruptura).
    techo = max(highs[-BREAKOUT_LEN - 1 : -1])
    suelo = min(lows[-BREAKOUT_LEN - 1 : -1])
    ultimo = closes[-1]

    side = None
    if tendencia_alcista and ultimo > techo:
        side = "BUY"
    elif tendencia_bajista and ultimo < suelo:
        side = "SELL"
    if side is None:
        return None, f"contraída pero sin ruptura todavía (rango {suelo:.6g}-{techo:.6g})"

    entry = ultimo
    if side == "BUY":
        sl_consolidacion = suelo
        sl = sl_consolidacion if (entry - sl_consolidacion) <= SL_ATR * atr[-1] else entry - SL_ATR * atr[-1]
        riesgo = entry - sl
        tp = entry + riesgo * RR_FIXED
    else:
        sl_consolidacion = techo
        sl = sl_consolidacion if (sl_consolidacion - entry) <= SL_ATR * atr[-1] else entry + SL_ATR * atr[-1]
        riesgo = sl - entry
        tp = entry - riesgo * RR_FIXED

    if riesgo <= 0:
        return None, "riesgo no positivo (stop mal calculado)"

    rr = abs(tp - entry) / riesgo
    if rr < MIN_RR:
        return None, f"R:R insuficiente ({rr:.2f} < {MIN_RR})"

    cost_cover = atr_pct / cost_roundtrip_pct if cost_roundtrip_pct > 0 else 0.0
    stretch_atr = (entry - ma[-1]) / atr[-1]

    sig = Signal(
        symbol=symbol, side=side, entry=entry, sl=sl, tp=tp, rr=rr,
        atr_pct=atr_pct, cost_cover=cost_cover, stretch=stretch_atr,
    )
    return sig, f"ruptura {side} tras contracción {contraccion:.2f}, R:R {rr:.2f}"
