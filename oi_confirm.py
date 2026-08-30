"""
Confirmación por Open Interest — cuadrante precio+OI.

Cruza la dirección del precio con la dirección del Open Interest (OI)
en la misma ventana temporal. Hay cuatro combinaciones posibles:

    precio ↑ + OI ↑ = LARGOS_NUEVOS       (dinero nuevo, tendencia real)
    precio ↓ + OI ↑ = CORTOS_NUEVOS       (dinero nuevo, tendencia real)
    precio ↑ + OI ↓ = COBERTURA_CORTOS    (squeeze, no es demanda nueva)
    precio ↓ + OI ↓ = LIQUIDACION_LARGOS  (venta forzada, no convicción)

INVESTIGADO ANTES DE CONSTRUIRLO (no es una suposición): de estas
cuatro, solo LIQUIDACION_LARGOS mostró ventaja estadísticamente
validada en backtesting real para comprar después. El cuadrante
espejo, COBERTURA_CORTOS, NO mostró esa misma ventaja — el mercado
tiende a seguir subiendo tras un squeeze de cortos, no a devolverlo.

POR ESO ESTE MÓDULO ES ASIMÉTRICO A PROPÓSITO: confirma con fuerza las
señales BUY (fading un dump causado por liquidación de largos), y
NUNCA confirma señales SELL vía OI — tratar la cobertura de cortos
como confirmación sería inventarse una simetría que los datos no
respaldan. Esto no contradice al resto del bot: es la misma asimetría
que ya se midió de forma independiente en el propio histórico del
proyecto (cortos ~79% de acierto, largos a contra-tendencia ~43%). Dos
líneas de evidencia distintas señalando lo mismo.

BingX no ofrece histórico de Open Interest por API pública — solo el
valor ACTUAL (`/openApi/swap/v2/quote/openInterest`). Este módulo
construye su propio histórico sondeando periódicamente y guardando en
memoria, mismo patrón que liquidations.py con las liquidaciones.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import config


@dataclass
class OIQuadrant:
    cuadrante: str | None   # "LARGOS_NUEVOS" | "CORTOS_NUEVOS" | "COBERTURA_CORTOS" | "LIQUIDACION_LARGOS" | None
    oi_pct: float           # variación % del OI en la ventana
    precio_pct: float       # variación % del precio en la MISMA ventana


def confirms(signal_side: str, quadrant: OIQuadrant | None) -> bool:
    """
    Asimétrico a propósito — ver docstring del módulo. BUY se confirma
    solo por LIQUIDACION_LARGOS. SELL no se confirma por ningún
    cuadrante de OI: la evidencia no respalda tratar la cobertura de
    cortos como señal de que un pump vaya a revertir.
    """
    if quadrant is None or quadrant.cuadrante is None:
        return False
    if signal_side == "BUY":
        return quadrant.cuadrante == "LIQUIDACION_LARGOS"
    return False


class OpenInterestTracker:
    """
    Guarda un historial de snapshots (timestamp, OI) por símbolo,
    construido sondeando la API cada OI_POLL_INTERVAL_MIN — ver
    Bot.maybe_refresh_oi() en main.py. No corre nada por sí solo.
    """

    def __init__(self) -> None:
        self._history: dict[str, deque[tuple[float, float]]] = {}

    def _prune(self, symbol: str) -> None:
        dq = self._history.get(symbol)
        if not dq:
            return
        # Se guarda algo más que la ventana exacta, de margen — el
        # sondeo no es perfectamente regular (depende de cuánto tarde
        # el barrido del universo cada vez).
        limite = time.time() - config.OI_WINDOW_MIN * 60 * 2
        while dq and dq[0][0] < limite:
            dq.popleft()

    def add_snapshot(self, symbol: str, oi: float) -> None:
        if oi <= 0:
            return
        dq = self._history.setdefault(symbol, deque())
        dq.append((time.time(), oi))
        self._prune(symbol)

    def quadrant(self, symbol: str, precio_pct: float) -> OIQuadrant | None:
        """
        precio_pct se calcula FUERA de este módulo (con las velas que
        el bot ya descargó para strategy.evaluate()) y se pasa aquí —
        para no mantener dos fuentes de precio distintas dentro del
        mismo bot. None si no hay historial suficiente todavía (recién
        arrancado, o símbolo nuevo en el universo).
        """
        dq = self._history.get(symbol)
        if not dq or len(dq) < 2:
            return None

        objetivo = time.time() - config.OI_WINDOW_MIN * 60
        referencia = dq[0][1]
        for ts, oi in dq:
            if ts <= objetivo:
                referencia = oi
            else:
                break
        oi_actual = dq[-1][1]
        if referencia <= 0:
            return None

        oi_pct = (oi_actual - referencia) / referencia * 100.0

        oi_sube = oi_pct >= config.OI_MIN_CHANGE_PCT
        oi_baja = oi_pct <= -config.OI_MIN_CHANGE_PCT
        precio_sube = precio_pct >= config.OI_MIN_CHANGE_PCT
        precio_baja = precio_pct <= -config.OI_MIN_CHANGE_PCT

        cuadrante = None
        if precio_sube and oi_sube:
            cuadrante = "LARGOS_NUEVOS"
        elif precio_baja and oi_sube:
            cuadrante = "CORTOS_NUEVOS"
        elif precio_sube and oi_baja:
            cuadrante = "COBERTURA_CORTOS"
        elif precio_baja and oi_baja:
            cuadrante = "LIQUIDACION_LARGOS"

        return OIQuadrant(cuadrante=cuadrante, oi_pct=oi_pct, precio_pct=precio_pct)
