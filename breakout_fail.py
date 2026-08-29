"""
Detector de ruptura fallida — adaptado del "Failure Engine" del script
Pine "Breakout Momentum Engine [TRADION]".

QUÉ MIDE, Y POR QUÉ IMPORTA PARA UN BOT DE REVERSIÓN: TRADION es un
motor de CONFIRMACIÓN de rupturas — score alto significa "esta ruptura
tiene calidad, síguela". Este bot hace lo contrario: apuesta a que el
estirón revierte. Pero mirado del revés, la pieza de TRADION que
detecta cuándo una ruptura FALLA (rompe un nivel, no aguanta, vuelve
adentro) es exactamente la misma idea que ya vive en el trasfondo de
este proyecto — un barrido de liquidez que revierte, visto con
estructura de precio en vez de con la vela de agotamiento sola.

CÓMO SE USA: como CONFIRMACIÓN adicional sobre la señal que ya genera
strategy.evaluate() — mismo patrón que rsi_confirm.py y
liquidations.py. No decide nada por sí solo, no gatea ninguna entrada
salvo que se configure explícitamente. Reevalúa sobre las MISMAS velas
de 5m ya descargadas, sin llamadas extra a la API, y reutiliza
strategy.atr() en vez de reimplementar el ATR.

SIMPLIFICADO A PROPÓSITO respecto al original: TRADION lleva encima
una máquina de estados completa (evento activo, reintento, expiración,
grado de calidad, score de 0-100 con MACD/RSI/volumen/compresión). Aquí
solo se traduce la pieza estructural — ¿hubo una ruptura reciente que
falló? — porque es la única parte que aporta algo NUEVO a este bot; el
resto (momentum, volumen) ya está cubierto por rsi_confirm.py y
liquidations.py con sus propias fuentes de datos.
"""
from __future__ import annotations

from dataclasses import dataclass

import strategy


@dataclass
class BreakoutFailResult:
    confirma: str | None      # "SELL" | "BUY" | None
    velas_desde_fallo: int
    nivel: float | None        # el nivel de estructura que se rompió y no aguantó
    distancia_atr: float | None  # cuánto llegó a romper, en ATR, antes de fallar


def evaluate(
    candles: list[dict],
    structure_len: int = 20,
    min_break_atr: float = 0.05,
    failure_bars: int = 5,
    failure_atr: float = 0.25,
    failure_confirm_closes: int = 2,
    ventana: int = 5,
) -> BreakoutFailResult | None:
    """
    Solo velas cerradas — igual que el resto del proyecto, se descarta
    la última (en curso) para no repintar.

    1. Estructura: máximo/mínimo de las `structure_len` velas ANTERIORES
       a cada vela (igual que ta.highest(...)[1] en el Pine original —
       no incluye la vela actual, si no toda ruptura sería "romper su
       propio máximo").
    2. Ruptura: el cierre supera esa estructura por al menos
       `min_break_atr` × ATR — filtra rupturas de un tick que no son
       ruptura de verdad, solo ruido.
    3. Fallo: dentro de `failure_bars` velas desde la ruptura, el precio
       cierra de vuelta más allá del nivel (con margen `failure_atr` ×
       ATR) durante `failure_confirm_closes` cierres SEGUIDOS — una
       vela sola metiéndose de vuelta no basta, podría ser ruido.
    """
    need = structure_len + failure_bars + failure_confirm_closes + ventana + 15
    if len(candles) < need:
        return None
    c = candles[:-1]
    closes = [x["close"] for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]
    n = len(c)

    atr = strategy.atr(highs, lows, closes, 14)
    if len(atr) < n:
        return None

    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(structure_len, n):
        upper[i] = max(highs[i - structure_len : i])
        lower[i] = min(lows[i - structure_len : i])

    raw_long = [False] * n
    raw_short = [False] * n
    for i in range(structure_len, n):
        if upper[i] is not None and atr[i] > 0:
            raw_long[i] = closes[i] > upper[i] and (closes[i] - upper[i]) / atr[i] >= min_break_atr
        if lower[i] is not None and atr[i] > 0:
            raw_short[i] = closes[i] < lower[i] and (lower[i] - closes[i]) / atr[i] >= min_break_atr

    nuevo_long = [raw_long[i] and not (i > 0 and raw_long[i - 1]) for i in range(n)]
    nuevo_short = [raw_short[i] and not (i > 0 and raw_short[i - 1]) for i in range(n)]

    fallos: list[tuple[int, str, float, float]] = []  # (índice del fallo, confirma, nivel, distancia)

    for j in range(structure_len, n):
        if nuevo_long[j]:
            nivel = upper[j]
            distancia = (closes[j] - nivel) / atr[j] if atr[j] > 0 else 0.0
            umbral_fallo = nivel - atr[j] * failure_atr
            consecutivas = 0
            for k in range(j + 1, min(j + 1 + failure_bars, n)):
                if closes[k] < umbral_fallo:
                    consecutivas += 1
                    if consecutivas >= failure_confirm_closes:
                        # Ruptura ALCISTA que falló -> confirma una
                        # señal SELL (el estirón al alza no tenía
                        # sustento real, ya se vio rechazado antes).
                        fallos.append((k, "SELL", nivel, distancia))
                        break
                else:
                    consecutivas = 0
        if nuevo_short[j]:
            nivel = lower[j]
            distancia = (nivel - closes[j]) / atr[j] if atr[j] > 0 else 0.0
            umbral_fallo = nivel + atr[j] * failure_atr
            consecutivas = 0
            for k in range(j + 1, min(j + 1 + failure_bars, n)):
                if closes[k] > umbral_fallo:
                    consecutivas += 1
                    if consecutivas >= failure_confirm_closes:
                        fallos.append((k, "BUY", nivel, distancia))
                        break
                else:
                    consecutivas = 0

    if not fallos:
        return BreakoutFailResult(confirma=None, velas_desde_fallo=999, nivel=None, distancia_atr=None)

    idx_fallo, direccion, nivel, distancia = max(fallos, key=lambda t: t[0])
    velas_desde = (n - 1) - idx_fallo

    if velas_desde > ventana:
        return BreakoutFailResult(confirma=None, velas_desde_fallo=velas_desde, nivel=nivel, distancia_atr=distancia)
    return BreakoutFailResult(confirma=direccion, velas_desde_fallo=velas_desde, nivel=nivel, distancia_atr=distancia)


def confirms(signal_side: str, result: BreakoutFailResult | None) -> bool:
    """¿La ruptura fallida reciente confirma la dirección de la señal?"""
    return result is not None and result.confirma == signal_side
