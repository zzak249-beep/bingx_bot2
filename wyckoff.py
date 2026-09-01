"""
wyckoff.py
----------
Confirmación por volumen y estructura al estilo Wyckoff: climax de
volumen, spring/upthrust, y esfuerzo-vs-resultado.

QUÉ ES ESTO Y QUÉ NO ES: el método de Wyckoff original son esquemas de
acumulación/distribución de varias semanas, leídos de forma visual y
discrecional (fases A-E, "composite operator", etc.) — no es algo que
se pueda codificar entero en unas pocas funciones, y nadie debería
prometer que esto "es" el método Wyckoff. Lo que sí es codificable —
y es lo único que hay aquí — son sus tres piezas más citadas y más
objetivas:

  1. CLIMAX DE VOLUMEN: una vela con volumen muy por encima de lo normal
     en un extremo del rango reciente — el "selling climax" / "buying
     climax" de Wyckoff. Misma idea de agotamiento que ya usa (se
     asume) strategy.evaluate() para su propia vela de agotamiento,
     pero medida en volumen en vez de en rango de precio.
  2. SPRING / UPTHRUST: un pinchazo breve por debajo del soporte (o por
     encima de la resistencia) reciente que cierra de vuelta DENTRO del
     rango en la misma vela — la trampa clásica de Wyckoff a quien
     vendió/compró el falso quiebre.
  3. ESFUERZO VS RESULTADO: mucho volumen para poco recorrido de precio
     sugiere absorción — alguien grande operando contra la corriente
     sin que el precio se mueva en su contra. Se devuelve como número
     (no dispara señal por sí solo); sirve como dato adicional en el
     desglose del score.

CÓMO SE USA: igual que rsi_confirm.py — es una CONFIRMACIÓN sobre la
señal que ya genera strategy.evaluate(), no la sustituye. Se reevalúa
contra las MISMAS velas de 5m, sin llamadas a la API extra.

CONFIGURACIÓN: lee sus propias variables de entorno directamente (no
depende del config.py del proyecto, que este módulo no tiene forma de
ver desde aquí). Variables, todas opcionales:
  WYCKOFF_VOLUME_LOOKBACK        (30)   velas para la media de volumen
  WYCKOFF_VOLUME_CLIMAX_MULT     (2.5)  x sobre la media para contar como climax
  WYCKOFF_RANGE_LEN              (20)   velas para el rango soporte/resistencia
  WYCKOFF_SPRING_MAX_PENETRATION_ATR (0.5)  penetración máxima (en ATR) para que
                                             cuente como spring/upthrust y no como
                                             una ruptura de verdad

NO VALIDADO CON DATOS TODAVÍA: igual que xsection.py, esto es una
hipótesis razonable apoyada en literatura ampliamente citada, no un
resultado medido en este proyecto. Por eso se integra en score.py como
una pieza más que suma o resta puntos — medible después con
stats.buckets_por_score() — y NO como un bloqueo duro. El histórico de
este mismo proyecto (ver comentarios en main.py) ya enseñó que un
bloqueo nuevo sin datos propios detrás es la forma más fácil de
repetir el error que costó caro con el filtro de contra-tendencia.
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


VOLUME_LOOKBACK = _i("WYCKOFF_VOLUME_LOOKBACK", 30)
VOLUME_CLIMAX_MULT = _f("WYCKOFF_VOLUME_CLIMAX_MULT", 2.5)
RANGE_LEN = _i("WYCKOFF_RANGE_LEN", 20)
SPRING_MAX_PENETRATION_ATR = _f("WYCKOFF_SPRING_MAX_PENETRATION_ATR", 0.5)


@dataclass
class WyckoffConfirm:
    señal: str | None       # "BUY" | "SELL" | None — spring o upthrust en la última vela cerrada
    climax_volumen: bool
    volumen_ratio: float     # volumen de la última vela / media reciente
    esfuerzo_resultado: float  # alto = mucho volumen, poco recorrido -> posible absorción
    detalle: str


def _true_ranges(candles: list[dict]) -> list[float]:
    trs: list[float] = []
    prev_close: float | None = None
    for bar in candles:
        h, low = bar["high"], bar["low"]
        tr = (h - low) if prev_close is None else max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = bar["close"]
    return trs


def evaluate(
    candles: list[dict],
    volume_lookback: int = VOLUME_LOOKBACK,
    volume_climax_mult: float = VOLUME_CLIMAX_MULT,
    range_len: int = RANGE_LEN,
    spring_max_penetration_atr: float = SPRING_MAX_PENETRATION_ATR,
) -> WyckoffConfirm | None:
    """
    candles: mismo formato que usa strategy.evaluate() (dicts con
    open/high/low/close/volume). Se descarta la última vela (en curso),
    igual que allí, para no repintar.
    """
    need = max(volume_lookback, range_len) + 5
    if len(candles) < need + 1:
        return None
    c = candles[:-1]

    vols = [float(x.get("volume", 0.0) or 0.0) for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]

    media_vol = sum(vols[-volume_lookback - 1 : -1]) / volume_lookback
    vol_actual = vols[-1]
    volumen_ratio = (vol_actual / media_vol) if media_vol > 0 else 0.0
    climax = volumen_ratio >= volume_climax_mult

    trs = _true_ranges(c[-volume_lookback:])
    atr_reciente = sum(trs) / len(trs) if trs else 0.0

    rango_hi = max(highs[-range_len - 1 : -1])
    rango_lo = min(lows[-range_len - 1 : -1])

    ultimo = c[-1]
    señal: str | None = None
    detalle = "sin patrón"

    # Spring: pincha por debajo del soporte reciente pero cierra de
    # vuelta dentro del rango, con volumen de climax -> trampa bajista,
    # sesgo alcista. La penetración debe ser PEQUEÑA (en ATR) — un
    # pinchazo grande ya no es un spring, es una ruptura de verdad.
    if ultimo["low"] < rango_lo and ultimo["close"] > rango_lo and climax:
        penetracion_atr = (rango_lo - ultimo["low"]) / atr_reciente if atr_reciente > 0 else 999
        if penetracion_atr <= spring_max_penetration_atr:
            señal = "BUY"
            detalle = f"spring: pinchó {penetracion_atr:.2f} ATR bajo soporte de {range_len} velas, cerró dentro, volumen {volumen_ratio:.1f}x la media"

    # Upthrust: el espejo, arriba.
    if señal is None and ultimo["high"] > rango_hi and ultimo["close"] < rango_hi and climax:
        penetracion_atr = (ultimo["high"] - rango_hi) / atr_reciente if atr_reciente > 0 else 999
        if penetracion_atr <= spring_max_penetration_atr:
            señal = "SELL"
            detalle = f"upthrust: pinchó {penetracion_atr:.2f} ATR sobre resistencia de {range_len} velas, cerró dentro, volumen {volumen_ratio:.1f}x la media"

    rango_precio = ultimo["high"] - ultimo["low"]
    if media_vol > 0 and atr_reciente > 0 and rango_precio > 0:
        esfuerzo_resultado = (vol_actual / media_vol) / (rango_precio / atr_reciente)
    else:
        esfuerzo_resultado = 0.0

    return WyckoffConfirm(
        señal=señal,
        climax_volumen=climax,
        volumen_ratio=volumen_ratio,
        esfuerzo_resultado=esfuerzo_resultado,
        detalle=detalle,
    )


def confirms(signal_side: str, result: WyckoffConfirm | None) -> bool:
    """¿La estructura de Wyckoff en la última vela confirma la dirección de la operación?"""
    if result is None or result.señal is None:
        return False
    return result.señal == signal_side
