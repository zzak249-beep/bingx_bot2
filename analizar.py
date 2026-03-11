"""
analizar.py — Motor de señales SMC v2.1 [FIXED]
Correcciones:
  ✅ RSI con suavizado Wilder (no promedio simple)
  ✅ FVG limitado a últimas 20 velas (no toda la historia)
  ✅ Filtro de volumen en la vela actual (evita entradas en velas muertas)
  ✅ Score mínimo efectivo mejorado con condiciones más estrictas
"""

import logging
import math
from datetime import datetime, timezone
import concurrent.futures

import config
import exchange

log = logging.getLogger("analizar")


# ══════════════════════════════════════════════════════════════
# INDICADORES TÉCNICOS
# ══════════════════════════════════════════════════════════════

def calc_ema(prices: list, period: int) -> float | None:
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices: list, period: int = 14) -> float | None:
    """
    RSI con suavizado Wilder (RMA) — método correcto usado por TradingView.
    El RSI simple con promedio genera lecturas erróneas en trending markets.
    """
    if len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Seed: promedio simple de las primeras `period` velas
    gains  = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_g  = sum(gains)  / period
    avg_l  = sum(losses) / period

    # Suavizado Wilder (RMA) para el resto
    for d in deltas[period:]:
        g = max(d, 0)
        l = abs(min(d, 0))
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period

    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 2)

def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period

def calc_pivotes(prev_high: float, prev_low: float, prev_close: float) -> dict:
    pp = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pp - prev_low
    r2 = pp + (prev_high - prev_low)
    s1 = 2 * pp - prev_high
    s2 = pp - (prev_high - prev_low)
    return {"PP": pp, "R1": r1, "R2": r2, "S1": s1, "S2": s2}


# ══════════════════════════════════════════════════════════════
# FAIR VALUE GAPS  ✅ CORREGIDO — limitado a últimas 20 velas
# ══════════════════════════════════════════════════════════════

def detectar_fvg(candles: list) -> dict:
    """
    Bull FVG: low[i] > high[i-2]
    Bear FVG: high[i] < low[i-2]
    Busca el FVG más reciente en las últimas 20 velas exclusivamente.
    """
    result = {"bull_fvg": False, "bear_fvg": False,
              "fvg_top": 0.0, "fvg_bottom": 0.0}

    if len(candles) < 3:
        return result

    min_size = config.FVG_MIN_PIPS

    # ✅ Limitar búsqueda a las últimas 20 velas (no toda la historia)
    buscar_desde = max(len(candles) - 1, 2)
    buscar_hasta = max(len(candles) - 20, 2)

    for i in range(buscar_desde, buscar_hasta - 1, -1):
        c0 = candles[i]
        c2 = candles[i - 2]

        gap_bull = c0["low"]  - c2["high"]
        gap_bear = c2["low"]  - c0["high"]

        if gap_bull > min_size:
            result["bull_fvg"]   = True
            result["fvg_top"]    = c0["low"]
            result["fvg_bottom"] = c2["high"]
            break

        if gap_bear > min_size:
            result["bear_fvg"]   = True
            result["fvg_top"]    = c2["low"]
            result["fvg_bottom"] = c0["high"]
            break

    return result


# ══════════════════════════════════════════════════════════════
# EQUAL HIGHS / EQUAL LOWS
# ══════════════════════════════════════════════════════════════

def _pivot_high(highs: list, length: int, idx: int) -> float | None:
    if idx < length or idx + length >= len(highs):
        return None
    val = highs[idx]
    for i in range(idx - length, idx + length + 1):
        if i == idx:
            continue
        if highs[i] >= val:
            return None
    return val

def _pivot_low(lows: list, length: int, idx: int) -> float | None:
    if idx < length or idx + length >= len(lows):
        return None
    val = lows[idx]
    for i in range(idx - length, idx + length + 1):
        if i == idx:
            continue
        if lows[i] <= val:
            return None
    return val

def detectar_eqh_eql(candles: list) -> dict:
    result = {"is_eqh": False, "eqh_price": 0.0,
              "is_eql": False, "eql_price": 0.0}

    if len(candles) < config.EQ_LOOKBACK:
        return result

    highs  = [c["high"] for c in candles]
    lows   = [c["low"]  for c in candles]
    length = config.EQ_PIVOT_LEN
    thr    = config.EQ_THRESHOLD
    lb     = config.EQ_LOOKBACK

    n = len(highs)
    pivot_highs = []
    pivot_lows  = []

    for i in range(max(length, n - lb - length), n - length):
        ph = _pivot_high(highs, length, i)
        if ph is not None:
            pivot_highs.append(ph)
        pl = _pivot_low(lows, length, i)
        if pl is not None:
            pivot_lows.append(pl)

    if len(pivot_highs) >= 2:
        for i in range(len(pivot_highs) - 1, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                diff = abs(pivot_highs[i] - pivot_highs[j]) / pivot_highs[i] * 100
                if diff <= thr:
                    result["is_eqh"]    = True
                    result["eqh_price"] = pivot_highs[i]
                    break
            if result["is_eqh"]:
                break

    if len(pivot_lows) >= 2:
        for i in range(len(pivot_lows) - 1, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                diff = abs(pivot_lows[i] - pivot_lows[j]) / pivot_lows[i] * 100
                if diff <= thr:
                    result["is_eql"]    = True
                    result["eql_price"] = pivot_lows[i]
                    break
            if result["is_eql"]:
                break

    return result


# ══════════════════════════════════════════════════════════════
# ICT KILLZONES
# ══════════════════════════════════════════════════════════════

def en_killzone() -> dict:
    ahora = datetime.now(timezone.utc)
    tim   = ahora.hour * 60 + ahora.minute

    asia   = config.KZ_ASIA_START   <= tim < config.KZ_ASIA_END
    london = config.KZ_LONDON_START <= tim < config.KZ_LONDON_END
    ny     = config.KZ_NY_START     <= tim < config.KZ_NY_END

    return {
        "in_asia":   asia,
        "in_london": london,
        "in_ny":     ny,
        "in_kz":     asia or london or ny,
        "nombre":    "ASIA" if asia else ("LONDON" if london else ("NY" if ny else "FUERA")),
    }


# ══════════════════════════════════════════════════════════════
# PIVOTES DIARIOS
# ══════════════════════════════════════════════════════════════

def calcular_pivotes_diarios(candles_diarias: list) -> dict | None:
    if len(candles_diarias) < 2:
        return None
    prev = candles_diarias[-2]
    return calc_pivotes(prev["high"], prev["low"], prev["close"])


# ══════════════════════════════════════════════════════════════
# FILTRO DE VOLUMEN  ✅ NUEVO — evita velas sin actividad
# ══════════════════════════════════════════════════════════════

def volumen_ok(candles: list) -> bool:
    """
    Comprueba que la vela actual tenga volumen razonable
    comparado con el promedio de las últimas 20 velas.
    Descarta velas 'muertas' con < 30% del volumen medio.
    """
    if len(candles) < 21:
        return True   # no podemos juzgar, dejamos pasar
    vols = [c["volume"] for c in candles[-21:-1]]  # 20 velas previas
    avg  = sum(vols) / len(vols) if vols else 0
    if avg <= 0:
        return True
    ratio = candles[-1]["volume"] / avg
    if ratio < 0.30:
        log.debug(f"Volumen bajo: {ratio:.2f}x del promedio — descartado")
        return False
    return True


# ══════════════════════════════════════════════════════════════
# SEÑAL PRINCIPAL
# ══════════════════════════════════════════════════════════════

def analizar_par(par: str) -> dict | None:
    try:
        candles = exchange.get_candles(par, config.TIMEFRAME, config.CANDLES_LIMIT)
        if len(candles) < 60:
            return None

        closes = [c["close"]  for c in candles]
        highs  = [c["high"]   for c in candles]
        lows   = [c["low"]    for c in candles]
        precio = closes[-1]

        if precio <= 0:
            return None

        # ✅ Filtro de volumen — descartar velas muertas
        if not volumen_ok(candles):
            return None

        # ATR
        atr = calc_atr(highs, lows, closes, config.ATR_PERIOD)
        if atr <= 0:
            return None

        # EMAs
        ema_f = calc_ema(closes, config.EMA_FAST)
        ema_s = calc_ema(closes, config.EMA_SLOW)
        bull_trend = (ema_f is not None and ema_s is not None and ema_f > ema_s)
        bear_trend = (ema_f is not None and ema_s is not None and ema_f < ema_s)

        # RSI ✅ Wilder correcto
        rsi = calc_rsi(closes, config.RSI_PERIOD) or 50.0
        rsi_buy_ok  = rsi <= config.RSI_BUY_MAX
        rsi_sell_ok = rsi >= config.RSI_SELL_MIN

        # FVG ✅ limitado 20 velas
        fvg = detectar_fvg(candles)

        # EQH / EQL
        eq = detectar_eqh_eql(candles)

        # Killzone
        kz = en_killzone()

        # Pivotes diarios
        candles_d = exchange.get_candles(par, "1d", 5)
        pivotes   = calcular_pivotes_diarios(candles_d) if len(candles_d) >= 2 else None

        near_s1 = near_s2 = near_r1 = False
        if pivotes:
            pct = config.PIVOT_NEAR_PCT / 100
            near_s1 = abs(precio - pivotes["S1"]) / precio < pct
            near_s2 = abs(precio - pivotes["S2"]) / precio < pct
            near_r1 = abs(precio - pivotes["R1"]) / precio < pct

        # ── Score ──
        score_long  = 0
        score_short = 0
        motivos_long  = []
        motivos_short = []

        if fvg["bull_fvg"]:
            score_long += 2; motivos_long.append("FVG_BULL")
        if fvg["bear_fvg"]:
            score_short += 2; motivos_short.append("FVG_BEAR")

        if kz["in_kz"]:
            score_long  += 1; motivos_long.append(f"KZ_{kz['nombre']}")
            score_short += 1; motivos_short.append(f"KZ_{kz['nombre']}")

        if near_s1:
            score_long += 1; motivos_long.append("NEAR_S1")
        if near_s2:
            score_long += 1; motivos_long.append("NEAR_S2")
        if eq["is_eql"]:
            score_long += 1; motivos_long.append("EQL")
        if near_r1:
            score_short += 1; motivos_short.append("NEAR_R1")
        if eq["is_eqh"]:
            score_short += 1; motivos_short.append("EQH")

        if bull_trend:
            score_long += 1; motivos_long.append("EMA_BULL")
        if bear_trend:
            score_short += 1; motivos_short.append("EMA_BEAR")

        if rsi_buy_ok:
            score_long += 1; motivos_long.append(f"RSI={rsi:.1f}")
        if rsi_sell_ok:
            score_short += 1; motivos_short.append(f"RSI={rsi:.1f}")

        # ── Condiciones base OBLIGATORIAS ──
        fvg_ok_long  = fvg["bull_fvg"] and kz["in_kz"] and (near_s1 or near_s2 or eq["is_eql"])
        fvg_ok_short = fvg["bear_fvg"] and kz["in_kz"] and (near_r1 or eq["is_eqh"])

        lado    = None
        score   = 0
        motivos = []

        if not config.SOLO_LONG:
            if fvg_ok_short and score_short >= config.SCORE_MIN and bear_trend and rsi_sell_ok:
                if score_short > score_long:
                    lado    = "SHORT"
                    score   = score_short
                    motivos = motivos_short

        if fvg_ok_long and score_long >= config.SCORE_MIN and bull_trend and rsi_buy_ok:
            if lado is None or score_long >= score_short:
                lado    = "LONG"
                score   = score_long
                motivos = motivos_long

        if lado is None:
            return None

        # SL / TP
        if lado == "LONG":
            sl  = precio - atr * config.SL_ATR_MULT
            tp  = precio + atr * config.TP_ATR_MULT
            tp1 = precio + atr * config.PARTIAL_TP1_MULT
        else:
            sl  = precio + atr * config.SL_ATR_MULT
            tp  = precio - atr * config.TP_ATR_MULT
            tp1 = precio - atr * config.PARTIAL_TP1_MULT

        rr = abs(tp - precio) / abs(precio - sl) if abs(precio - sl) > 0 else 0

        if rr < 1.5:
            log.debug(f"[{par}] R:R={rr:.2f} insuficiente")
            return None

        return {
            "par":        par,
            "lado":       lado,
            "precio":     precio,
            "sl":         round(sl,  8),
            "tp":         round(tp,  8),
            "tp1":        round(tp1, 8),
            "atr":        round(atr, 8),
            "score":      score,
            "rsi":        rsi,
            "rr":         round(rr, 2),
            "motivos":    motivos,
            "kz":         kz["nombre"],
            "fvg_top":    fvg.get("fvg_top",    0),
            "fvg_bottom": fvg.get("fvg_bottom",  0),
            "pivotes":    pivotes,
        }

    except Exception as e:
        log.error(f"analizar_par {par}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# ANÁLISIS MASIVO CON THREADS
# ══════════════════════════════════════════════════════════════

def analizar_todos(pares: list, workers: int = 4) -> list:
    senales = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = {ex.submit(analizar_par, p): p for p in pares}
        for fut in concurrent.futures.as_completed(futuros):
            try:
                res = fut.result()
                if res:
                    senales.append(res)
            except Exception as e:
                log.error(f"analizar_todos thread: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
