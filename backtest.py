"""
backtest.py — reproduce strategy.evaluate() + las confirmaciones que SÍ
se pueden reconstruir con velas históricas, sobre historial real.

POR QUÉ EXISTE ESTE SCRIPT: la disciplina de Renaissance Technologies
(Jim Simons) nunca fue "un indicador mejor" — fue validar cada señal
contra datos masivos ANTES de arriesgar nada. En producción, juntar
100-150 operaciones limpias (el tamaño de muestra donde el intervalo de
confianza deja de tocar cero) tarda semanas. Sobre velas históricas de
5m, un símbolo con meses de histórico puede dar esas mismas 100-150
operaciones en minutos.

QUÉ SÍ SE REPRODUCE, con total fidelidad porque solo dependen de velas:
  - strategy.evaluate() — la base, con TODOS sus filtros tal cual.
  - rsi_confirm.py — el doble cruce de RSI.
  - breakout_fail.py — la ruptura fallida.

QUÉ NO SE REPRODUCE, Y SE DICE CON TODAS LAS LETRAS: liquidations.py y
oi_confirm.py dependen de streams en vivo (liquidaciones) o de
snapshots que el propio bot fue construyendo con el tiempo (Open
Interest) — BingX no ofrece histórico de ninguno de los dos por API
pública. Fingir esos datos hacia atrás sería inventar un resultado. Se
quedan fuera del backtest, honestamente: esto mide un SUBCONJUNTO real
del sistema completo, no el sistema completo.

CÓMO SE SIMULA LA SALIDA: SL/TP más el cierre por tiempo
(MAX_TRADE_BARS / TIME_EXIT_ONLY_LOSING), calcado de
check_time_exits()/reconcile_signal() en main.py — mismo orden de
comprobación (el peor caso, el stop, se mira primero si ambos niveles
caen en la misma vela), para que el backtest no sea más generoso que
lo que el bot haría de verdad.

USO:
    python backtest.py CATE-USDT MERL-USDT --dias 60
    python backtest.py BASECAT-USDT --dias 30 --sin-rsi --sin-ruptura
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

import breakout_fail
import config
import rsi_confirm
import stats
import strategy
from bingx import BingX

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("backtest")

# Misma ventana que usa el bot en vivo cada ciclo (scan_once pide
# limit=300) — pasar más historial del que el bot real vería en cada
# comprobación sería darle al backtest información que en producción
# nunca tuvo.
VENTANA_VIVA = 300


def simular_salida(candles: list[dict], idx_entrada: int, sig: strategy.Signal) -> tuple[float | None, str]:
    """
    La señal en candles[idx_entrada] entra al CIERRE de esa vela —
    igual que el bot real. Recorre las velas siguientes comprobando
    SL/TP y el límite de tiempo, mismo orden que reconcile_signal() en
    main.py: si SL y TP caen en la misma vela, gana el peor caso (el
    stop) — convención conservadora, sin datos de tick no hay forma de
    saber el orden real dentro de la vela.

    Devuelve (None, 'sin_datos') si el historial se acaba antes de
    resolverse — esas señales se descartan del informe, no se inventa
    un resultado con datos que no existen.
    """
    entry, sl, tp, side = sig.entry, sig.sl, sig.tp, sig.side
    limite_barras = config.MAX_TRADE_BARS

    for i in range(idx_entrada + 1, min(idx_entrada + 1 + limite_barras + 1, len(candles))):
        vela = candles[i]
        if side == "BUY":
            tp_hit = vela["high"] >= tp
            sl_hit = vela["low"] <= sl
        else:
            tp_hit = vela["low"] <= tp
            sl_hit = vela["high"] >= sl

        if sl_hit:
            return stats.compute_r(entry, sl, side, sl), "stop"
        if tp_hit:
            return stats.compute_r(entry, sl, side, tp), "objetivo"

        barras_transcurridas = i - idx_entrada
        if config.USE_TIME_EXIT and barras_transcurridas >= limite_barras:
            exit_price = vela["close"]
            a_favor = (exit_price > entry) if side == "BUY" else (exit_price < entry)
            if config.TIME_EXIT_ONLY_LOSING and a_favor:
                continue  # va a favor: se deja correr, igual que en producción
            return stats.compute_r(entry, sl, side, exit_price), "tiempo"

    return None, "sin_datos"


async def backtest_symbol(
    api: BingX, symbol: str, total_velas: int, con_rsi: bool, con_ruptura: bool
) -> list[dict]:
    log.info("%s: descargando %d velas de %s...", symbol, total_velas, config.TIMEFRAME)
    candles = await api.klines_history(symbol, config.TIMEFRAME, total_velas)
    log.info("%s: %d velas descargadas", symbol, len(candles))

    resultados: list[dict] = []
    ventana_minima = max(config.MA_LEN, config.ATR_LEN) + config.MAX_BARS_STRETCH + 20

    for i in range(ventana_minima, len(candles) - 1):
        # Ventana acotada a lo último, igual que ve el bot real cada
        # ciclo (limit=300) — sin esto cada llamada recalcularía sobre
        # TODO el historial acumulado y el backtest sería O(n²).
        ventana = candles[max(0, i + 2 - VENTANA_VIVA) : i + 2]
        sig, _motivo = strategy.evaluate(symbol, ventana)
        if sig is None:
            continue

        rsi_ok = None
        if con_rsi:
            rsi_result = rsi_confirm.evaluate(ventana)
            rsi_ok = rsi_confirm.confirms(sig.side, rsi_result)

        breakout_ok = None
        if con_ruptura:
            breakout_result = breakout_fail.evaluate(ventana)
            breakout_ok = breakout_fail.confirms(sig.side, breakout_result)

        r, razon = simular_salida(candles, i, sig)
        if r is None:
            continue

        resultados.append(
            {
                "symbol": symbol,
                "side": sig.side,
                "r": r,
                "razon": razon,
                "rsi_confirma": rsi_ok,
                "breakout_confirma": breakout_ok,
            }
        )

    log.info("%s: %d señales resueltas", symbol, len(resultados))
    return resultados


def informe(resultados: list[dict]) -> str:
    if not resultados:
        return "Sin señales detectadas en el historial pedido — o el símbolo no cumple el filtro de amplitud casi nunca en ese periodo, o hace falta más historial."

    partes = [f"📈 <b>Backtest</b> — {len(resultados)} señales resueltas\n"]
    partes.append(stats.format_report({"Todas": [t["r"] for t in resultados]}))

    con_rsi = [t["r"] for t in resultados if t.get("rsi_confirma") is True]
    sin_rsi = [t["r"] for t in resultados if t.get("rsi_confirma") is False]
    if con_rsi and sin_rsi:
        partes.append(stats.format_report({"RSI confirma": con_rsi, "RSI no confirma": sin_rsi}))

    con_break = [t["r"] for t in resultados if t.get("breakout_confirma") is True]
    sin_break = [t["r"] for t in resultados if t.get("breakout_confirma") is False]
    if con_break and sin_break:
        partes.append(stats.format_report({"Ruptura fallida confirma": con_break, "No confirma": sin_break}))

    por_simbolo: dict[str, list[float]] = {}
    for t in resultados:
        por_simbolo.setdefault(t["symbol"], []).append(t["r"])
    if len(por_simbolo) > 1:
        partes.append(stats.format_report(por_simbolo))

    return "\n\n".join(partes)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest histórico del bot de reversión")
    parser.add_argument("symbols", nargs="+", help="Símbolos BingX, p.ej. CATE-USDT")
    parser.add_argument("--dias", type=int, default=30, help="Días de historial a descargar (por defecto 30)")
    parser.add_argument("--sin-rsi", action="store_true", help="No calcular la confirmación RSI (más rápido)")
    parser.add_argument("--sin-ruptura", action="store_true", help="No calcular la ruptura fallida (más rápido)")
    args = parser.parse_args()

    minutos_vela = config.MINUTOS_POR_VELA.get(config.TIMEFRAME, 5)
    velas_por_dia = 24 * 60 // minutos_vela
    total_velas = args.dias * velas_por_dia

    async with httpx.AsyncClient() as client:
        api = BingX(client)
        todos_resultados: list[dict] = []
        for symbol in args.symbols:
            try:
                r = await backtest_symbol(
                    api, symbol.upper(), total_velas,
                    con_rsi=not args.sin_rsi, con_ruptura=not args.sin_ruptura,
                )
                todos_resultados.extend(r)
            except Exception as exc:  # noqa: BLE001
                log.error("%s: fallo en el backtest (%s)", symbol, exc)

    print()
    print(informe(todos_resultados))


if __name__ == "__main__":
    asyncio.run(main())
