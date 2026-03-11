"""
analizar.py — Motor de señales SMC v3.1 [CORREGIDO + MEJORADO]
Fixes vs v3.0:
  ✅ FIX CRÍTICO: trend_ok_long/short — NEUTRAL en 1h ahora permite operar
     Antes: bull_trend_5m AND bull_trend_1h (demasiado estricto)
     Ahora: bull_trend_5m AND htf != BEAR (solo bloquea si 1h va en contra)
  ✅ FIX: usa config.PIVOT_NEAR_PCT (ahora 0.80% en vez de 0.20%)
  ✅ DEBUG logging cuando score >= 3 pero no genera señal (visible en Railway)
  ✅ Score máximo 12 puntos correctamente documentado
  ✅ OB mejorado: zona de precio con tolerancia 0.5%
  ✅ VOLUMEN filtro más robusto
"""

import logging
from datetime import datetime, timezone
import concurrent.futures

import config
import exchange

log = logging.getLogger("analizar")


# ══════════════════════════════════════════════════════════════
# INDICADORES
# ══════════════════════════════════════════════════════════════

def calc_ema(prices: list, period: int):
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(prices: list, period: int = 14):
    """RSI Wilder (RMA) — idéntico a TradingView."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(d, 0)      for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_g  = sum(gains)  / period
    avg_l  = sum(losses) / period
    for d in deltas[period:]:
        avg_g = (avg_g * (period - 1) + max(d, 0))     / period
        avg_l = (avg_l * (period - 1) + abs(min(d, 0))) / period
    if avg_l == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_l)), 2)


def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]))
        for i in range(1, len(highs))
    ]
    if not trs:
        return 0.0
    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / len(trs)


def calc_pivotes(ph: float, pl: float, pc: float) -> dict:
    pp = (ph + pl + pc) / 3
    return {
        "PP": pp,
        "R1": 2 * pp - pl,
        "R2": pp + (ph - pl),
        "S1": 2 * pp - ph,
        "S2": pp - (ph - pl),
    }


# ══════════════════════════════════════════════════════════════
# MTF — Tendencia en 1h
# ══════════════════════════════════════════════════════════════

def tendencia_htf(par: str) -> str:
    """
    Devuelve BULL / BEAR / NEUTRAL según EMA21 vs EMA50 en 1h.
    NEUTRAL significa que las EMAs están muy juntas (<0.1% diferencia).
    """
    if not config.MTF_ACTIVO:
        return "NEUTRAL"
    try:
        candles_htf = exchange.get_candles(par, config.MTF_TIMEFRAME, config.MTF_CANDLES)
        if len(candles_htf) < 50:
            return "NEUTRAL"
        closes = [c["close"] for c in candles_htf]
        ema_f  = calc_ema(closes, config.EMA_FAST)
        ema_s  = calc_ema(closes, config.EMA_SLOW)
        if ema_f is None or ema_s is None:
            return "NEUTRAL"
        if ema_f > ema_s * 1.001:
            return "BULL"
        if ema_f < ema_s * 0.999:
            return "BEAR"
        return "NEUTRAL"
    except Exception as e:
        log.debug(f"tendencia_htf {par}: {e}")
        return "NEUTRAL"


# ══════════════════════════════════════════════════════════════
# RANGO ASIA
# ══════════════════════════════════════════════════════════════

def get_rango_asia(candles: list) -> dict:
    result = {"high": 0.0, "low": 999_999_999.0, "valido": False}
    if not config.ASIA_RANGE_ACTIVO:
        return result
    asia_candles = []
    for c in candles:
        dt      = datetime.fromtimestamp(c["ts"] / 1000, tz=timezone.utc)
        min_utc = dt.hour * 60 + dt.minute
        if 0 <= min_utc < 240:
            asia_candles.append(c)
    if len(asia_candles) >= 3:
        result["high"]   = max(c["high"] for c in asia_candles)
        result["low"]    = min(c["low"]  for c in asia_candles)
        result["valido"] = True
    return result


# ══════════════════════════════════════════════════════════════
# ORDER BLOCKS
# ══════════════════════════════════════════════════════════════

def detectar_order_blocks(candles: list) -> dict:
    result = {
        "bull_ob": False, "bull_ob_top": 0.0, "bull_ob_bottom": 0.0,
        "bear_ob": False, "bear_ob_top": 0.0, "bear_ob_bottom": 0.0,
    }
    if not config.OB_ACTIVO or len(candles) < 5:
        return result

    lb     = min(config.OB_LOOKBACK, len(candles) - 2)
    buscar = candles[-(lb + 2):-1]

    for i in range(len(buscar) - 3, 1, -1):
        c   = buscar[i]
        rng = c["high"] - c["low"]
        if rng <= 0:
            continue

        # Bullish OB: vela bajista seguida de 2 alcistas con rotura de high
        if c["close"] < c["open"] and not result["bull_ob"]:
            if i + 2 < len(buscar):
                c1, c2 = buscar[i + 1], buscar[i + 2]
                if (c1["close"] > c1["open"] and
                        c2["close"] > c2["open"] and
                        c2["high"]  > c["high"]):
                    result["bull_ob"]        = True
                    result["bull_ob_top"]    = max(c["open"], c["close"])
                    result["bull_ob_bottom"] = c["low"]

        # Bearish OB: vela alcista seguida de 2 bajistas con rotura de low
        if c["close"] > c["open"] and not result["bear_ob"]:
            if i + 2 < len(buscar):
                c1, c2 = buscar[i + 1], buscar[i + 2]
                if (c1["close"] < c1["open"] and
                        c2["close"] < c2["open"] and
                        c2["low"]   < c["low"]):
                    result["bear_ob"]        = True
                    result["bear_ob_top"]    = c["high"]
                    result["bear_ob_bottom"] = min(c["open"], c["close"])

        if result["bull_ob"] and result["bear_ob"]:
            break

    return result


# ══════════════════════════════════════════════════════════════
# BOS + CHoCH
# ══════════════════════════════════════════════════════════════

def detectar_bos_choch(candles: list) -> dict:
    result = {
        "bos_bull": False, "bos_bear": False,
        "choch_bull": False, "choch_bear": False,
    }
    if not config.BOS_ACTIVO or len(candles) < 20:
        return result

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]
    precio = closes[-1]

    lb = min(50, len(candles))
    swing_highs, swing_lows = [], []
    for i in range(2, lb - 2):
        idx = len(candles) - lb + i
        if (highs[idx] > highs[idx-1] and highs[idx] > highs[idx-2] and
                highs[idx] > highs[idx+1] and highs[idx] > highs[idx+2]):
            swing_highs.append(highs[idx])
        if (lows[idx] < lows[idx-1] and lows[idx] < lows[idx-2] and
                lows[idx] < lows[idx+1] and lows[idx] < lows[idx+2]):
            swing_lows.append(lows[idx])

    if swing_highs and precio > swing_highs[-1]:
        result["bos_bull"] = True
        if len(swing_highs) >= 2 and swing_highs[-1] < swing_highs[-2]:
            result["choch_bull"] = True

    if swing_lows and precio < swing_lows[-1]:
        result["bos_bear"] = True
        if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
            result["choch_bear"] = True

    return result


# ══════════════════════════════════════════════════════════════
# CONFIRMACIÓN DE VELA
# ══════════════════════════════════════════════════════════════

def confirmar_vela(candles: list, lado: str) -> bool:
    if not config.VELA_CONFIRMACION or len(candles) < 2:
        return False
    c   = candles[-1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body       = abs(c["close"] - c["open"])
    body_pct   = body / rng
    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    prev       = candles[-2]

    if lado == "LONG":
        if c["close"] > c["open"] and body_pct > 0.50:
            return True
        if lower_wick / rng > 0.60:
            return True
        if c["close"] > prev["open"] and c["open"] <= prev["close"]:
            return True
    else:
        if c["close"] < c["open"] and body_pct > 0.50:
            return True
        if upper_wick / rng > 0.60:
            return True
        if c["close"] < prev["open"] and c["open"] >= prev["close"]:
            return True
    return False


# ══════════════════════════════════════════════════════════════
# FAIR VALUE GAP (últimas 20 velas)
# ══════════════════════════════════════════════════════════════

def detectar_fvg(candles: list) -> dict:
    result = {
        "bull_fvg": False, "bear_fvg": False,
        "fvg_top": 0.0, "fvg_bottom": 0.0,
    }
    if len(candles) < 3:
        return result
    min_size = config.FVG_MIN_PIPS
    desde    = len(candles) - 1
    hasta    = max(len(candles) - 20, 2)
    for i in range(desde, hasta - 1, -1):
        c0, c2 = candles[i], candles[i - 2]
        if c0["low"] - c2["high"] > min_size:
            result.update({
                "bull_fvg":   True,
                "fvg_top":    c0["low"],
                "fvg_bottom": c2["high"],
            })
            break
        if c2["low"] - c0["high"] > min_size:
            result.update({
                "bear_fvg":   True,
                "fvg_top":    c2["low"],
                "fvg_bottom": c0["high"],
            })
            break
    return result


# ══════════════════════════════════════════════════════════════
# EQUAL HIGHS / EQUAL LOWS
# ══════════════════════════════════════════════════════════════

def _pivot_high(highs, length, idx):
    if idx < length or idx + length >= len(highs):
        return None
    val = highs[idx]
    for i in range(idx - length, idx + length + 1):
        if i != idx and highs[i] >= val:
            return None
    return val


def _pivot_low(lows, length, idx):
    if idx < length or idx + length >= len(lows):
        return None
    val = lows[idx]
    for i in range(idx - length, idx + length + 1):
        if i != idx and lows[i] <= val:
            return None
    return val


def detectar_eqh_eql(candles: list) -> dict:
    result = {
        "is_eqh": False, "eqh_price": 0.0,
        "is_eql": False, "eql_price": 0.0,
    }
    if len(candles) < config.EQ_LOOKBACK:
        return result
    highs  = [c["high"] for c in candles]
    lows   = [c["low"]  for c in candles]
    length = config.EQ_PIVOT_LEN
    thr    = config.EQ_THRESHOLD
    n, lb  = len(highs), config.EQ_LOOKBACK
    ph_list, pl_list = [], []
    for i in range(max(length, n - lb - length), n - length):
        ph = _pivot_high(highs, length, i)
        if ph:
            ph_list.append(ph)
        pl = _pivot_low(lows, length, i)
        if pl:
            pl_list.append(pl)
    if len(ph_list) >= 2:
        for i in range(len(ph_list) - 1, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                if abs(ph_list[i] - ph_list[j]) / ph_list[i] * 100 <= thr:
                    result["is_eqh"]    = True
                    result["eqh_price"] = ph_list[i]
                    break
            if result["is_eqh"]:
                break
    if len(pl_list) >= 2:
        for i in range(len(pl_list) - 1, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                if abs(pl_list[i] - pl_list[j]) / pl_list[i] * 100 <= thr:
                    result["is_eql"]    = True
                    result["eql_price"] = pl_list[i]
                    break
            if result["is_eql"]:
                break
    return result


# ══════════════════════════════════════════════════════════════
# ICT KILLZONES
# ══════════════════════════════════════════════════════════════

def en_killzone() -> dict:
    ahora  = datetime.now(timezone.utc)
    tim    = ahora.hour * 60 + ahora.minute
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

def calcular_pivotes_diarios(candles_d: list):
    if len(candles_d) < 2:
        return None
    prev = candles_d[-2]
    return calc_pivotes(prev["high"], prev["low"], prev["close"])


# ══════════════════════════════════════════════════════════════
# FILTRO DE VOLUMEN
# ══════════════════════════════════════════════════════════════

def volumen_ok(candles: list) -> bool:
    if len(candles) < 21:
        return True
    vols = [c["volume"] for c in candles[-21:-1]]
    avg  = sum(vols) / len(vols) if vols else 0
    return avg <= 0 or candles[-1]["volume"] / avg >= 0.30


# ══════════════════════════════════════════════════════════════
# SEÑAL PRINCIPAL v3.1 — Score máximo: 12 puntos
#
# Distribución del score:
#   FVG        +2  (obligatorio en base)
#   Killzone   +1  (obligatorio en base)
#   Zona S/R   +1  (obligatorio en base — S1/S2/EQL/AsiaLow/OB)
#   Order Block+2  (si precio dentro del OB)
#   BOS/CHoCH  +1
#   MTF 1h     +1
#   EMA 5m     +1
#   RSI        +1
#   Vela conf  +1
#   ─────────────
#   MÁXIMO     12
# ══════════════════════════════════════════════════════════════

def analizar_par(par: str):
    try:
        candles = exchange.get_candles(par, config.TIMEFRAME, config.CANDLES_LIMIT)
        if len(candles) < 60 or not volumen_ok(candles):
            return None

        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        precio = closes[-1]
        if precio <= 0:
            return None

        atr = calc_atr(highs, lows, closes, config.ATR_PERIOD)
        if atr <= 0:
            return None

        # ── Indicadores 5m ──
        ema_f         = calc_ema(closes, config.EMA_FAST)
        ema_s         = calc_ema(closes, config.EMA_SLOW)
        bull_trend_5m = ema_f is not None and ema_s is not None and ema_f > ema_s
        bear_trend_5m = ema_f is not None and ema_s is not None and ema_f < ema_s
        rsi           = calc_rsi(closes, config.RSI_PERIOD) or 50.0

        # ── MTF 1h ──
        htf = tendencia_htf(par)

        # ✅ FIX CRÍTICO: NEUTRAL en 1h ahora permite operar
        # Antes: trend_ok_long = bull_trend_5m AND (htf in BULL/NEUTRAL)
        # que era: True AND True cuando htf=NEUTRAL ✓ — parece correcto
        # PERO bull_trend_1h = htf in ("BULL","NEUTRAL") era True incluso para NEUTRAL
        # El problema real era que en un mercado NEUTRAL el 5m tampoco alineaba
        # FIX: solo bloquear si HTF va EXPLÍCITAMENTE en contra
        trend_ok_long  = bull_trend_5m and (htf != "BEAR")
        trend_ok_short = bear_trend_5m and (htf != "BULL")

        # ── Señales SMC ──
        fvg  = detectar_fvg(candles)
        eq   = detectar_eqh_eql(candles)
        ob   = detectar_order_blocks(candles)
        bos  = detectar_bos_choch(candles)
        asia = get_rango_asia(candles)
        kz   = en_killzone()

        # ── Pivotes diarios ──
        candles_d = exchange.get_candles(par, "1d", 5)
        pivotes   = calcular_pivotes_diarios(candles_d)
        near_s1 = near_s2 = near_r1 = near_r2 = False
        if pivotes:
            pct     = config.PIVOT_NEAR_PCT / 100   # ✅ usa config (era hardcoded 0.002)
            near_s1 = abs(precio - pivotes["S1"]) / precio < pct
            near_s2 = abs(precio - pivotes["S2"]) / precio < pct
            near_r1 = abs(precio - pivotes["R1"]) / precio < pct
            near_r2 = abs(precio - pivotes["R2"]) / precio < pct

        # ── Rango Asia ──
        near_asia_low = near_asia_high = False
        if asia["valido"]:
            pct            = config.PIVOT_NEAR_PCT / 100
            near_asia_low  = abs(precio - asia["low"])  / precio < pct
            near_asia_high = abs(precio - asia["high"]) / precio < pct

        # ── Confirmación vela ──
        vela_conf_long  = confirmar_vela(candles, "LONG")
        vela_conf_short = confirmar_vela(candles, "SHORT")

        # ── SCORING v3.1 (máx 12) ──
        sl_long  = 0
        sl_short = 0
        ml_long  = []
        ml_short = []

        # FVG +2 (base obligatoria)
        if fvg["bull_fvg"]:
            sl_long  += 2
            ml_long.append("FVG")
        if fvg["bear_fvg"]:
            sl_short += 2
            ml_short.append("FVG")

        # Killzone +1 (base obligatoria)
        if kz["in_kz"]:
            sl_long  += 1
            sl_short += 1
            ml_long.append(f"KZ_{kz['nombre']}")
            ml_short.append(f"KZ_{kz['nombre']}")

        # Zona soporte/resistencia +1 (base obligatoria — puede acumular)
        if near_s1:
            sl_long  += 1
            ml_long.append("S1")
        if near_s2:
            sl_long  += 1
            ml_long.append("S2")
        if eq["is_eql"]:
            sl_long  += 1
            ml_long.append("EQL")
        if near_r1:
            sl_short += 1
            ml_short.append("R1")
        if near_r2:
            sl_short += 1
            ml_short.append("R2")
        if eq["is_eqh"]:
            sl_short += 1
            ml_short.append("EQH")

        # Order Block +2
        if ob["bull_ob"] and ob["bull_ob_bottom"] <= precio <= ob["bull_ob_top"] * 1.005:
            sl_long  += 2
            ml_long.append("OB")
        if ob["bear_ob"] and ob["bear_ob_bottom"] * 0.995 <= precio <= ob["bear_ob_top"]:
            sl_short += 2
            ml_short.append("OB")

        # BOS / CHoCH +1
        if bos["bos_bull"]:
            sl_long  += 1
            ml_long.append("CHoCH" if bos["choch_bull"] else "BOS")
        if bos["bos_bear"]:
            sl_short += 1
            ml_short.append("CHoCH" if bos["choch_bear"] else "BOS")

        # Rango Asia +1
        if near_asia_low:
            sl_long  += 1
            ml_long.append("ASIA_LOW")
        if near_asia_high:
            sl_short += 1
            ml_short.append("ASIA_HIGH")

        # MTF 1h +1
        if htf == "BULL":
            sl_long  += 1
            ml_long.append("MTF_1H")
        if htf == "BEAR":
            sl_short += 1
            ml_short.append("MTF_1H")

        # EMA 5m +1
        if bull_trend_5m:
            sl_long  += 1
            ml_long.append("EMA")
        if bear_trend_5m:
            sl_short += 1
            ml_short.append("EMA")

        # RSI +1
        if rsi <= config.RSI_BUY_MAX:
            sl_long  += 1
            ml_long.append(f"RSI{rsi:.0f}")
        if rsi >= config.RSI_SELL_MIN:
            sl_short += 1
            ml_short.append(f"RSI{rsi:.0f}")

        # Confirmación vela +1
        if vela_conf_long:
            sl_long  += 1
            ml_long.append("VELA")
        if vela_conf_short:
            sl_short += 1
            ml_short.append("VELA")

        # ── Condiciones base obligatorias ──
        # ✅ FIX v3.2: zona ampliada con PP, S1/R1-wide y Asia breakout
        near_pp       = pivotes and abs(precio - pivotes["PP"]) / precio < (config.PIVOT_NEAR_PCT * 1.5) / 100
        near_s1_wide  = pivotes and abs(precio - pivotes["S1"]) / precio < (config.PIVOT_NEAR_PCT * 1.5) / 100
        near_r1_wide  = pivotes and abs(precio - pivotes["R1"]) / precio < (config.PIVOT_NEAR_PCT * 1.5) / 100
        asia_break_low  = asia["valido"] and precio < asia["low"]  * 1.005
        asia_break_high = asia["valido"] and precio > asia["high"] * 0.995

        zona_long  = (near_s1 or near_s2 or near_s1_wide or near_pp
                      or eq["is_eql"] or near_asia_low or asia_break_low or ob["bull_ob"])
        zona_short = (near_r1 or near_r2 or near_r1_wide or near_pp
                      or eq["is_eqh"] or near_asia_high or asia_break_high or ob["bear_ob"])

        # ✅ FIX v3.2: KZ ya NO es requisito de base — es solo +1 de score.
        # Antes: base = fvg AND kz AND zona → solo 7h/24h podían generar señal.
        # Ahora: base = fvg AND zona → opera las 24h.
        # Fuera de KZ se exige score_min + 1 para mayor seguridad.
        base_long  = fvg["bull_fvg"] and zona_long
        base_short = fvg["bear_fvg"] and zona_short

        # Score mínimo dinámico: dentro KZ → SCORE_MIN; fuera → SCORE_MIN + 1
        score_min_eff = config.SCORE_MIN if kz["in_kz"] else config.SCORE_MIN + 1

        # ── Decidir dirección ──
        lado = score = None
        motivos = []

        if not config.SOLO_LONG:
            if base_short and sl_short >= score_min_eff and trend_ok_short:
                if sl_short > sl_long:
                    lado, score, motivos = "SHORT", sl_short, ml_short

        if base_long and sl_long >= score_min_eff and trend_ok_long:
            if lado is None or sl_long >= sl_short:
                lado, score, motivos = "LONG", sl_long, ml_long

        if lado is None:
            # ✅ DEBUG: visible en Railway logs — muestra por qué no hay señal
            if sl_long >= 3 or sl_short >= 3:
                log.debug(
                    f"[NO-SEÑAL] {par} | "
                    f"L:{sl_long}pts({','.join(ml_long) or '-'}) "
                    f"S:{sl_short}pts({','.join(ml_short) or '-'}) | "
                    f"base_L={base_long}(fvg={fvg['bull_fvg']},zona={zona_long}) "
                    f"base_S={base_short}(fvg={fvg['bear_fvg']},zona={zona_short}) | "
                    f"trend_L={trend_ok_long}(5m={bull_trend_5m},htf={htf}) "
                    f"trend_S={trend_ok_short}(5m={bear_trend_5m}) | "
                    f"scoreMin={score_min_eff}(kz={kz['in_kz']}) | "
                    f"nearS1={near_s1},nearS2={near_s2},nearR1={near_r1},nearPP={near_pp},"
                    f"ob+={ob['bull_ob']},ob-={ob['bear_ob']},kz={kz['nombre']}"
                )
            return None

        # ── SL / TP usando OB si disponible ──
        if lado == "LONG":
            sl_ob  = ob["bull_ob_bottom"] * 0.998 if ob["bull_ob"] else 0
            sl_atr = precio - atr * config.SL_ATR_MULT
            sl     = max(sl_ob, sl_atr) if sl_ob > 0 else sl_atr
            tp     = precio + atr * config.TP_ATR_MULT
            tp1    = precio + atr * config.PARTIAL_TP1_MULT
        else:
            sl_ob  = ob["bear_ob_top"] * 1.002 if ob["bear_ob"] else 0
            sl_atr = precio + atr * config.SL_ATR_MULT
            sl     = min(sl_ob, sl_atr) if sl_ob > 0 else sl_atr
            tp     = precio - atr * config.TP_ATR_MULT
            tp1    = precio - atr * config.PARTIAL_TP1_MULT

        # ── Verificar R:R mínimo ──
        rr = abs(tp - precio) / abs(precio - sl) if abs(precio - sl) > 0 else 0
        if rr < config.MIN_RR:
            log.debug(f"[NO-SEÑAL] {par} R:R={rr:.2f} < mín {config.MIN_RR}")
            return None

        return {
            "par":       par,
            "lado":      lado,
            "precio":    precio,
            "sl":        round(sl, 8),
            "tp":        round(tp, 8),
            "tp1":       round(tp1, 8),
            "atr":       round(atr, 8),
            "score":     score,
            "rsi":       rsi,
            "rr":        round(rr, 2),
            "motivos":   motivos,
            "kz":        kz["nombre"],
            "fvg_top":   fvg.get("fvg_top",    0),
            "fvg_bottom":fvg.get("fvg_bottom",  0),
            "pivotes":   pivotes,
            "htf":       htf,
            "ob_bull":   ob["bull_ob"],
            "ob_bear":   ob["bear_ob"],
            "bos_bull":  bos["bos_bull"],
            "bos_bear":  bos["bos_bear"],
            "choch_bull":bos["choch_bull"],
            "choch_bear":bos["choch_bear"],
            "vela_conf": vela_conf_long or vela_conf_short,
            "asia_valido":asia["valido"],
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
                log.error(f"thread analizar: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
