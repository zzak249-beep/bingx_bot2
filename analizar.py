"""
analizar.py — Motor de señales SMC
Replica exactamente la lógica del indicador Pine Script:
  1. Fair Value Gaps (FVG)
  2. Equal Highs / Equal Lows (EQH/EQL)
  3. ICT Killzones (Asia / London / New York)
  4. Pivotes diarios (PP, R1, R2, S1, S2)
  5. Filtros: EMA trend + RSI
  6. Score compuesto → señal LONG / SHORT
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
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas[-period:] if d >= 0]
    losses = [abs(d) for d in deltas[-period:] if d < 0]
    avg_g  = sum(gains)  / period if gains  else 0.0
    avg_l  = sum(losses) / period if losses else 0.001
    rs     = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 2)

def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
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
# FAIR VALUE GAPS
# ══════════════════════════════════════════════════════════════

def detectar_fvg(candles: list) -> dict:
    """
    Bull FVG: low[0] > high[2]  (vela actual, vela -2)
    Bear FVG: high[0] < low[2]
    Busca el FVG más reciente en las últimas 20 velas.
    """
    result = {"bull_fvg": False, "bear_fvg": False,
              "fvg_top": 0.0, "fvg_bottom": 0.0}

    if len(candles) < 3:
        return result

    min_size = config.FVG_MIN_PIPS

    # Buscar el FVG más reciente (últimas 20 velas, excluyendo la última vela abierta)
    for i in range(len(candles) - 1, 1, -1):
        c0 = candles[i]
        c2 = candles[i - 2]

        gap_bull = c0["low"]  - c2["high"]
        gap_bear = c2["low"]  - c0["high"]

        if gap_bull > min_size:
            result["bull_fvg"]    = True
            result["fvg_top"]     = c0["low"]
            result["fvg_bottom"]  = c2["high"]
            break

        if gap_bear > min_size:
            result["bear_fvg"]    = True
            result["fvg_top"]     = c2["low"]
            result["fvg_bottom"]  = c0["high"]
            break

    return result


# ══════════════════════════════════════════════════════════════
# EQUAL HIGHS / EQUAL LOWS
# ══════════════════════════════════════════════════════════════

def _pivot_high(highs: list, length: int, idx: int) -> float | None:
    """Pivot high en posición idx del array highs."""
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
    """
    Busca dos pivot highs / pivot lows dentro del lookback
    con diferencia <= eqThreshold%.
    """
    result = {"is_eqh": False, "eqh_price": 0.0,
              "is_eql": False, "eql_price": 0.0}

    if len(candles) < config.EQ_LOOKBACK:
        return result

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    length = config.EQ_PIVOT_LEN
    thr    = config.EQ_THRESHOLD
    lb     = config.EQ_LOOKBACK

    # Buscar EQH — igual que Pine: ta.pivothigh en los últimos lb índices
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

    # EQH: dos pivot highs similares
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

    # EQL: dos pivot lows similares
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
    """
    Determina si ahora mismo estamos dentro de una killzone UTC.
    """
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
    """
    Calcula PP/R1/R2/S1/S2 del día anterior.
    candles_diarias: lista de velas diarias ordenadas.
    """
    if len(candles_diarias) < 2:
        return None
    prev = candles_diarias[-2]   # día anterior
    return calc_pivotes(prev["high"], prev["low"], prev["close"])


# ══════════════════════════════════════════════════════════════
# SEÑAL PRINCIPAL
# ══════════════════════════════════════════════════════════════

def analizar_par(par: str) -> dict | None:
    """
    Analiza un par y devuelve señal SMC o None.
    Señal = {par, lado, precio, sl, tp, tp1, atr, score, rsi, rr, motivos}
    """
    try:
        # ── Velas 5m (o timeframe configurado) ──
        candles = exchange.get_candles(par, config.TIMEFRAME, config.CANDLES_LIMIT)
        if len(candles) < 60:
            log.debug(f"[{par}] insuficientes velas: {len(candles)}")
            return None

        closes  = [c["close"]  for c in candles]
        highs   = [c["high"]   for c in candles]
        lows    = [c["low"]    for c in candles]
        precio  = closes[-1]

        if precio <= 0:
            return None

        # ── ATR ──
        atr = calc_atr(highs, lows, closes, config.ATR_PERIOD)
        if atr <= 0:
            return None

        # ── EMAs ──
        ema_f = calc_ema(closes, config.EMA_FAST)
        ema_s = calc_ema(closes, config.EMA_SLOW)
        bull_trend = (ema_f is not None and ema_s is not None and ema_f > ema_s)
        bear_trend = (ema_f is not None and ema_s is not None and ema_f < ema_s)

        # ── RSI ──
        rsi = calc_rsi(closes, config.RSI_PERIOD) or 50.0
        rsi_buy_ok  = rsi <= config.RSI_BUY_MAX
        rsi_sell_ok = rsi >= config.RSI_SELL_MIN

        # ── FVG ──
        fvg = detectar_fvg(candles)

        # ── EQH / EQL ──
        eq = detectar_eqh_eql(candles)

        # ── Killzone ──
        kz = en_killzone()

        # ── Pivotes diarios (velas diarias) ──
        candles_d = exchange.get_candles(par, "1d", 5)
        pivotes   = calcular_pivotes_diarios(candles_d) if len(candles_d) >= 2 else None

        near_s1 = near_s2 = near_r1 = False
        if pivotes:
            pct = config.PIVOT_NEAR_PCT / 100
            near_s1 = abs(precio - pivotes["S1"]) / precio < pct
            near_s2 = abs(precio - pivotes["S2"]) / precio < pct
            near_r1 = abs(precio - pivotes["R1"]) / precio < pct

        # ══════════════════════════════════════════
        # CONSTRUCCIÓN DE SEÑAL — exactamente como Pine Script
        # smcBuy  = bullFVG + inKZ + (nearS1 | nearS2 | isEQL) + bullTrend + rsiOk
        # smcSell = bearFVG + inKZ + (nearR1  | isEQH)          + bearTrend + rsiOk
        # ══════════════════════════════════════════

        score_long  = 0
        score_short = 0
        motivos_long  = []
        motivos_short = []

        # Condición OBLIGATORIA: FVG
        if fvg["bull_fvg"]:
            score_long += 2
            motivos_long.append("FVG_BULL")
        if fvg["bear_fvg"]:
            score_short += 2
            motivos_short.append("FVG_BEAR")

        # Condición OBLIGATORIA: Killzone
        if kz["in_kz"]:
            score_long  += 1
            score_short += 1
            motivos_long.append(f"KZ_{kz['nombre']}")
            motivos_short.append(f"KZ_{kz['nombre']}")

        # Soporte/Resistencia + EQ
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

        # Filtros de tendencia
        if bull_trend:
            score_long += 1; motivos_long.append("EMA_BULL")
        if bear_trend:
            score_short += 1; motivos_short.append("EMA_BEAR")

        # Filtro RSI
        if rsi_buy_ok:
            score_long += 1; motivos_long.append(f"RSI={rsi:.1f}")
        if rsi_sell_ok:
            score_short += 1; motivos_short.append(f"RSI={rsi:.1f}")

        # ── Decidir dirección ──
        lado   = None
        score  = 0
        motivos= []

        # FVG + KZ son condiciones base obligatorias (score ≥ 3 antes de filtros)
        fvg_ok_long  = fvg["bull_fvg"] and kz["in_kz"] and (near_s1 or near_s2 or eq["is_eql"])
        fvg_ok_short = fvg["bear_fvg"] and kz["in_kz"] and (near_r1 or eq["is_eqh"])

        if not config.SOLO_LONG:
            if fvg_ok_short and score_short >= config.SCORE_MIN and bear_trend and rsi_sell_ok:
                if score_short > score_long:   # preferir la señal más fuerte
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

        # ── SL / TP / TP1 ──
        if lado == "LONG":
            sl  = precio - atr * config.SL_ATR_MULT
            tp  = precio + atr * config.TP_ATR_MULT
            tp1 = precio + atr * config.PARTIAL_TP1_MULT
        else:
            sl  = precio + atr * config.SL_ATR_MULT
            tp  = precio - atr * config.TP_ATR_MULT
            tp1 = precio - atr * config.PARTIAL_TP1_MULT

        # R:R
        rr = abs(tp - precio) / abs(precio - sl) if abs(precio - sl) > 0 else 0

        # Descartar si R:R < 1.5
        if rr < 1.5:
            log.debug(f"[{par}] R:R={rr:.2f} insuficiente — descartado")
            return None

        return {
            "par":     par,
            "lado":    lado,
            "precio":  precio,
            "sl":      round(sl,  8),
            "tp":      round(tp,  8),
            "tp1":     round(tp1, 8),
            "atr":     round(atr, 8),
            "score":   score,
            "rsi":     rsi,
            "rr":      round(rr, 2),
            "motivos": motivos,
            "kz":      kz["nombre"],
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
    """
    Analiza todos los pares en paralelo (máx workers threads).
    Devuelve lista de señales ordenadas por score descendente.
    """
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
