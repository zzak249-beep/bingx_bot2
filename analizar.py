"""
analizar.py — Motor de señales SMC v4.0 [PRECISION ENTRY]
Integra estrategia Pine Script v5:
  ✅ Pin Bar + Engulfing detection
  ✅ EMA 9/21 local (tendencia inmediata)
  ✅ VWAP como nivel de referencia
  ✅ Liquidity Sweeps
  ✅ Cooldown por par (evita señales consecutivas)
  ✅ ATR rápido (7) para SL más ajustados
  ✅ Momentum de velas (3 previas)
  ✅ MACD + volumen spike
  ✅ Score máximo 14 puntos
"""

import logging
from datetime import datetime, timezone
import concurrent.futures

import config
import exchange

log = logging.getLogger("analizar")

# Cooldown por par: guarda el índice de barra de última señal
_last_signal_ts: dict = {}


# ══════════════════════════════════════════════════════════════
# INDICADORES TÉCNICOS
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
    """RSI Wilder — idéntico a TradingView."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(d, 0)      for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_g  = sum(gains)  / period
    avg_l  = sum(losses) / period
    for d in deltas[period:]:
        avg_g = (avg_g * (period - 1) + max(d, 0))      / period
        avg_l = (avg_l * (period - 1) + abs(min(d, 0))) / period
    if avg_l == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_l)), 2)


def calc_atr(highs, lows, closes, period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]))
        for i in range(1, len(highs))
    ]
    return sum(trs[-period:]) / period if len(trs) >= period else (sum(trs) / len(trs) if trs else 0.0)


def calc_vwap(candles: list) -> float:
    """VWAP del día actual."""
    today = datetime.now(timezone.utc).date()
    hoy   = [c for c in candles
             if datetime.fromtimestamp(c["ts"]/1000, tz=timezone.utc).date() == today]
    if not hoy:
        hoy = candles[-50:]
    vol_total  = sum(c["volume"] for c in hoy)
    if vol_total <= 0:
        return candles[-1]["close"]
    hlc3_total = sum(((c["high"]+c["low"]+c["close"])/3) * c["volume"] for c in hoy)
    return hlc3_total / vol_total


def calc_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return None, None, None
    macd_s = []
    for i in range(slow - 1, len(prices)):
        ef = calc_ema(prices[:i+1], fast)
        es = calc_ema(prices[:i+1], slow)
        if ef and es:
            macd_s.append(ef - es)
    if len(macd_s) < signal:
        return None, None, None
    ml   = macd_s[-1]
    sl   = calc_ema(macd_s, signal)
    if sl is None:
        return None, None, None
    return round(ml, 8), round(sl, 8), round(ml - sl, 8)


def calc_volumen_ratio(candles, periodo=20) -> float:
    if len(candles) < periodo + 1:
        return 1.0
    vols = [c["volume"] for c in candles[-(periodo+1):-1]]
    avg  = sum(vols) / len(vols) if vols else 0
    return (candles[-1]["volume"] / avg) if avg > 0 else 1.0


def calc_pivotes(ph, pl, pc) -> dict:
    pp = (ph + pl + pc) / 3
    return {
        "PP": pp,
        "R1": 2*pp - pl,
        "R2": pp + (ph - pl),
        "S1": 2*pp - ph,
        "S2": pp - (ph - pl),
    }


# ══════════════════════════════════════════════════════════════
# PATRONES DE VELA v4.0
# ══════════════════════════════════════════════════════════════

def detectar_patron_vela(candles: list, lado: str) -> dict:
    """
    Detecta Pin Bar, Engulfing y vela de momentum.
    Retorna dict con tipo y confianza.
    """
    result = {"patron": None, "confianza": 0}
    if len(candles) < 2:
        return result

    c    = candles[-1]
    prev = candles[-2]
    rng  = c["high"] - c["low"]
    if rng <= 0:
        return result

    body        = abs(c["close"] - c["open"])
    upper_wick  = c["high"]  - max(c["close"], c["open"])
    lower_wick  = min(c["close"], c["open"]) - c["low"]
    body_pct    = body / rng

    if lado == "LONG":
        # Pin Bar alcista: mecha inferior >= 55%, body pequeño, cierra en mitad superior
        if (lower_wick / rng >= config.PINBAR_RATIO and
                body_pct < 0.35 and
                c["close"] > (c["high"] + c["low"]) / 2):
            result = {"patron": "PIN_BAR", "confianza": 2}

        # Engulfing alcista: vela alcista que supera el body bajista anterior
        elif (config.ENGULF_ACTIVO and
              c["close"] > c["open"] and
              prev["close"] < prev["open"] and
              c["close"] > prev["open"] and
              c["open"]  < prev["close"]):
            result = {"patron": "ENGULFING", "confianza": 2}

        # Vela alcista fuerte (body > 50%)
        elif c["close"] > c["open"] and body_pct > 0.50:
            result = {"patron": "BULL_STRONG", "confianza": 1}

    else:  # SHORT
        # Pin Bar bajista: mecha superior >= 55%, body pequeño, cierra en mitad inferior
        if (upper_wick / rng >= config.PINBAR_RATIO and
                body_pct < 0.35 and
                c["close"] < (c["high"] + c["low"]) / 2):
            result = {"patron": "PIN_BAR", "confianza": 2}

        # Engulfing bajista
        elif (config.ENGULF_ACTIVO and
              c["close"] < c["open"] and
              prev["close"] > prev["open"] and
              c["close"] < prev["open"] and
              c["open"]  > prev["close"]):
            result = {"patron": "ENGULFING", "confianza": 2}

        # Vela bajista fuerte
        elif c["close"] < c["open"] and body_pct > 0.50:
            result = {"patron": "BEAR_STRONG", "confianza": 1}

    return result


def momentum_ok(candles: list, lado: str) -> bool:
    """Al menos 1 de las 2 velas anteriores va en dirección de la señal."""
    if not config.MOMENTUM_ACTIVO or len(candles) < 3:
        return True
    if lado == "LONG":
        return candles[-2]["close"] > candles[-2]["open"] or candles[-3]["close"] > candles[-3]["open"]
    else:
        return candles[-2]["close"] < candles[-2]["open"] or candles[-3]["close"] < candles[-3]["open"]


# ══════════════════════════════════════════════════════════════
# LIQUIDITY SWEEPS v4.0
# ══════════════════════════════════════════════════════════════

def detectar_sweep(candles: list) -> dict:
    """
    Sweep alcista: mecha toca mínimos del lookback pero cierra por encima.
    Sweep bajista: mecha toca máximos del lookback pero cierra por debajo.
    """
    result = {"sweep_bull": False, "sweep_bear": False}
    if not config.SWEEP_ACTIVO or len(candles) < config.SWEEP_LOOKBACK + 2:
        return result

    c   = candles[-1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return result

    lb          = candles[-(config.SWEEP_LOOKBACK+1):-1]
    highest_h   = max(x["high"] for x in lb)
    lowest_l    = min(x["low"]  for x in lb)

    if (c["low"] < lowest_l and c["close"] > lowest_l and
            (c["close"] - c["low"]) / rng > 0.60):
        result["sweep_bull"] = True

    if (c["high"] > highest_h and c["close"] < highest_h and
            (c["high"] - c["close"]) / rng > 0.60):
        result["sweep_bear"] = True

    return result


# ══════════════════════════════════════════════════════════════
# MTF — TENDENCIA 1H
# ══════════════════════════════════════════════════════════════

def tendencia_htf(par: str) -> str:
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
    asia_c = []
    for c in candles:
        dt     = datetime.fromtimestamp(c["ts"]/1000, tz=timezone.utc)
        m_utc  = dt.hour * 60 + dt.minute
        if 0 <= m_utc < 240:
            asia_c.append(c)
    if len(asia_c) >= 3:
        result["high"]   = max(c["high"] for c in asia_c)
        result["low"]    = min(c["low"]  for c in asia_c)
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

    lb    = min(config.OB_LOOKBACK, len(candles) - 2)
    buscar = candles[-(lb+2):-1]

    for i in range(len(buscar)-3, 1, -1):
        c   = buscar[i]
        rng = c["high"] - c["low"]
        if rng <= 0:
            continue
        if c["close"] < c["open"] and not result["bull_ob"]:
            if i + 2 < len(buscar):
                c1, c2 = buscar[i+1], buscar[i+2]
                if (c1["close"] > c1["open"] and c2["close"] > c2["open"] and c2["high"] > c["high"]):
                    result["bull_ob"]        = True
                    result["bull_ob_top"]    = max(c["open"], c["close"])
                    result["bull_ob_bottom"] = c["low"]
        if c["close"] > c["open"] and not result["bear_ob"]:
            if i + 2 < len(buscar):
                c1, c2 = buscar[i+1], buscar[i+2]
                if (c1["close"] < c1["open"] and c2["close"] < c2["open"] and c2["low"] < c["low"]):
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
    result = {"bos_bull": False, "bos_bear": False, "choch_bull": False, "choch_bear": False}
    if not config.BOS_ACTIVO or len(candles) < 20:
        return result

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]
    precio = closes[-1]
    lb     = min(50, len(candles))

    swing_highs, swing_lows = [], []
    for i in range(2, lb-2):
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
# EQUAL HIGHS / LOWS
# ══════════════════════════════════════════════════════════════

def _pivot_high(highs, length, idx):
    if idx < length or idx + length >= len(highs):
        return None
    val = highs[idx]
    for i in range(idx-length, idx+length+1):
        if i != idx and highs[i] >= val:
            return None
    return val

def _pivot_low(lows, length, idx):
    if idx < length or idx + length >= len(lows):
        return None
    val = lows[idx]
    for i in range(idx-length, idx+length+1):
        if i != idx and lows[i] <= val:
            return None
    return val

def detectar_eqh_eql(candles: list) -> dict:
    result = {"is_eqh": False, "eqh_price": 0.0, "is_eql": False, "eql_price": 0.0}
    if len(candles) < config.EQ_LOOKBACK:
        return result
    highs  = [c["high"] for c in candles]
    lows   = [c["low"]  for c in candles]
    length = config.EQ_PIVOT_LEN
    thr    = config.EQ_THRESHOLD
    n, lb  = len(highs), config.EQ_LOOKBACK
    ph_list, pl_list = [], []
    for i in range(max(length, n-lb-length), n-length):
        ph = _pivot_high(highs, length, i)
        if ph:
            ph_list.append(ph)
        pl = _pivot_low(lows, length, i)
        if pl:
            pl_list.append(pl)
    if len(ph_list) >= 2:
        for i in range(len(ph_list)-1, 0, -1):
            for j in range(i-1, max(i-10, -1), -1):
                if abs(ph_list[i]-ph_list[j])/ph_list[i]*100 <= thr:
                    result["is_eqh"]    = True
                    result["eqh_price"] = ph_list[i]
                    break
            if result["is_eqh"]:
                break
    if len(pl_list) >= 2:
        for i in range(len(pl_list)-1, 0, -1):
            for j in range(i-1, max(i-10, -1), -1):
                if abs(pl_list[i]-pl_list[j])/pl_list[i]*100 <= thr:
                    result["is_eql"]    = True
                    result["eql_price"] = pl_list[i]
                    break
            if result["is_eql"]:
                break
    return result


# ══════════════════════════════════════════════════════════════
# FAIR VALUE GAP
# ══════════════════════════════════════════════════════════════

def detectar_fvg(candles: list) -> dict:
    result = {"bull_fvg": False, "bear_fvg": False, "fvg_top": 0.0, "fvg_bottom": 0.0}
    if len(candles) < 3:
        return result
    desde = len(candles) - 1
    hasta = max(len(candles) - 20, 2)
    for i in range(desde, hasta-1, -1):
        c0, c2 = candles[i], candles[i-2]
        if c0["low"] - c2["high"] > config.FVG_MIN_PIPS:
            result.update({"bull_fvg": True, "fvg_top": c0["low"], "fvg_bottom": c2["high"]})
            break
        if c2["low"] - c0["high"] > config.FVG_MIN_PIPS:
            result.update({"bear_fvg": True, "fvg_top": c2["low"], "fvg_bottom": c0["high"]})
            break
    return result

def fvg_grande(fvg: dict, atr: float) -> bool:
    gap = abs(fvg.get("fvg_top", 0) - fvg.get("fvg_bottom", 0))
    return atr > 0 and gap >= atr * 0.3


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
# VOLUMEN
# ══════════════════════════════════════════════════════════════

def volumen_ok(candles: list) -> bool:
    if len(candles) < 21:
        return True
    vols = [c["volume"] for c in candles[-21:-1]]
    avg  = sum(vols) / len(vols) if vols else 0
    return avg <= 0 or candles[-1]["volume"] / avg >= 0.30


# ══════════════════════════════════════════════════════════════
# COOLDOWN POR PAR
# ══════════════════════════════════════════════════════════════

def cooldown_ok(par: str) -> bool:
    """Evita señales consecutivas en el mismo par (mínimo N minutos)."""
    import time
    last = _last_signal_ts.get(par, 0)
    secs = config.COOLDOWN_VELAS * int(config.TIMEFRAME.replace("m","").replace("h","")) * 60
    return (time.time() - last) >= secs

def registrar_senal_ts(par: str):
    import time
    _last_signal_ts[par] = time.time()


# ══════════════════════════════════════════════════════════════
# SEÑAL PRINCIPAL v4.0 — Score máximo 14 puntos
#
# FVG            +2  (base obligatoria)
# Zona S/R       +1  (base obligatoria)
# Sweep          +2  ← NUEVO
# OB             +2
# BOS/CHoCH      +1
# Patrón vela    +1/+2 (Bull_strong=1, Pin/Engulf=2)
# MTF 1h         +1
# EMA local      +1  ← NUEVO (EMA9>21 en 5m)
# RSI            +1
# MACD           +1
# Volumen spike  +1
# FVG grande     +1
# Killzone       +1
# ═════════════  14  MÁXIMO
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

        # ── ATR (14 normal + 7 rápido) ──
        atr  = calc_atr(highs, lows, closes, config.ATR_PERIOD)
        atr7 = calc_atr(highs, lows, closes, config.ATR_FAST)
        if atr <= 0:
            return None

        # ── EMAs 5m (21/50 tendencia) ──
        ema_f         = calc_ema(closes, config.EMA_FAST)
        ema_s         = calc_ema(closes, config.EMA_SLOW)
        bull_trend_5m = ema_f is not None and ema_s is not None and ema_f > ema_s
        bear_trend_5m = ema_f is not None and ema_s is not None and ema_f < ema_s

        # ── EMA local 9/21 (señal inmediata) ──
        ema_loc_f  = calc_ema(closes, config.EMA_LOCAL_FAST)
        ema_loc_s  = calc_ema(closes, config.EMA_LOCAL_SLOW)
        ema9_bull  = ema_loc_f is not None and ema_loc_s is not None and ema_loc_f > ema_loc_s
        ema9_bear  = ema_loc_f is not None and ema_loc_s is not None and ema_loc_f < ema_loc_s

        # ── RSI ──
        rsi = calc_rsi(closes, config.RSI_PERIOD) or 50.0

        # ── VWAP ──
        vwap        = calc_vwap(candles)
        sobre_vwap  = precio > vwap
        bajo_vwap   = precio < vwap

        # ── MACD + Volumen ──
        macd_l, macd_sig, macd_hist = calc_macd(closes)
        macd_bull  = macd_hist is not None and macd_hist > 0
        macd_bear  = macd_hist is not None and macd_hist < 0
        vol_ratio  = calc_volumen_ratio(candles)
        vol_spike  = vol_ratio >= 1.3

        # ── MTF 1h ──
        htf            = tendencia_htf(par)
        trend_ok_long  = htf != "BEAR"
        trend_ok_short = htf != "BULL"

        # ── Detecciones SMC ──
        fvg   = detectar_fvg(candles)
        eq    = detectar_eqh_eql(candles)
        ob    = detectar_order_blocks(candles)
        bos   = detectar_bos_choch(candles)
        asia  = get_rango_asia(candles)
        sweep = detectar_sweep(candles)
        kz    = en_killzone()

        # ── Patrones de vela ──
        pat_long  = detectar_patron_vela(candles, "LONG")
        pat_short = detectar_patron_vela(candles, "SHORT")

        # ── Pivotes diarios ──
        candles_d = exchange.get_candles(par, "1d", 5)
        pivotes   = None
        near_s1 = near_s2 = near_r1 = near_r2 = near_pp = False
        if len(candles_d) >= 2:
            prev    = candles_d[-2]
            pivotes = calc_pivotes(prev["high"], prev["low"], prev["close"])
            pct     = config.PIVOT_NEAR_PCT / 100
            pct_w   = pct * 1.5
            near_s1 = abs(precio - pivotes["S1"]) / precio < pct
            near_s2 = abs(precio - pivotes["S2"]) / precio < pct
            near_r1 = abs(precio - pivotes["R1"]) / precio < pct
            near_r2 = abs(precio - pivotes["R2"]) / precio < pct
            near_pp = abs(precio - pivotes["PP"]) / precio < pct_w

        # ── Rango Asia ──
        near_asia_low = near_asia_high = False
        asia_brk_low  = asia_brk_high  = False
        if asia["valido"]:
            pct            = config.PIVOT_NEAR_PCT / 100
            near_asia_low  = abs(precio - asia["low"])  / precio < pct
            near_asia_high = abs(precio - asia["high"]) / precio < pct
            asia_brk_low   = precio < asia["low"]  * 1.005
            asia_brk_high  = precio > asia["high"] * 0.995

        # ── Cooldown ──
        if not cooldown_ok(par):
            return None

        # ══════════════════════════════════════════════════════
        # SCORING v4.0 — LONG (máx 14)
        # ══════════════════════════════════════════════════════
        sl_long  = 0
        ml_long  = []

        # FVG +2 (base)
        if fvg["bull_fvg"]:
            sl_long += 2
            ml_long.append("FVG")
            if fvg_grande(fvg, atr):
                sl_long += 1
                ml_long.append("FVG+")

        # Sweep de mínimos +2 (señal fuerte de reversal)
        if sweep["sweep_bull"]:
            sl_long += 2
            ml_long.append("SWEEP")

        # Order Block +2
        if ob["bull_ob"] and ob["bull_ob_bottom"] <= precio <= ob["bull_ob_top"] * 1.005:
            sl_long += 2
            ml_long.append("OB")

        # BOS / CHoCH +1
        if bos["bos_bull"]:
            sl_long += 1
            ml_long.append("CHoCH" if bos["choch_bull"] else "BOS")

        # Patrón vela +1 o +2
        if pat_long["patron"]:
            sl_long += pat_long["confianza"]
            ml_long.append(pat_long["patron"])

        # MTF 1h +1
        if htf == "BULL":
            sl_long += 1
            ml_long.append("MTF1H")

        # EMA local 9/21 + sobre VWAP +1
        if ema9_bull and sobre_vwap:
            sl_long += 1
            ml_long.append("EMA9+VWAP")

        # EMA 5m +1
        if bull_trend_5m:
            sl_long += 1
            ml_long.append("EMA21")

        # RSI +1
        if rsi <= config.RSI_BUY_MAX:
            sl_long += 1
            ml_long.append(f"RSI{rsi:.0f}")

        # MACD +1
        if macd_bull and config.MACD_ACTIVO:
            sl_long += 1
            ml_long.append("MACD")

        # Volumen spike +1
        if vol_spike:
            sl_long += 1
            ml_long.append(f"VOL{vol_ratio:.1f}x")

        # Killzone +1
        if kz["in_kz"]:
            sl_long += 1
            ml_long.append(f"KZ_{kz['nombre']}")

        # Zona soporte (acumulativa)
        if near_s1:     sl_long += 1; ml_long.append("S1")
        if near_s2:     sl_long += 1; ml_long.append("S2")
        if eq["is_eql"]:sl_long += 1; ml_long.append("EQL")
        if near_asia_low:sl_long += 1;ml_long.append("ASIA_LOW")
        if asia_brk_low: sl_long += 1;ml_long.append("ASIA_BRK")
        if near_pp:      sl_long += 1;ml_long.append("PP")

        # ══════════════════════════════════════════════════════
        # SCORING v4.0 — SHORT (máx 14)
        # ══════════════════════════════════════════════════════
        sl_short = 0
        ml_short = []

        if fvg["bear_fvg"]:
            sl_short += 2
            ml_short.append("FVG")
            if fvg_grande(fvg, atr):
                sl_short += 1
                ml_short.append("FVG+")

        if sweep["sweep_bear"]:
            sl_short += 2
            ml_short.append("SWEEP")

        if ob["bear_ob"] and ob["bear_ob_bottom"]*0.995 <= precio <= ob["bear_ob_top"]:
            sl_short += 2
            ml_short.append("OB")

        if bos["bos_bear"]:
            sl_short += 1
            ml_short.append("CHoCH" if bos["choch_bear"] else "BOS")

        if pat_short["patron"]:
            sl_short += pat_short["confianza"]
            ml_short.append(pat_short["patron"])

        if htf == "BEAR":
            sl_short += 1
            ml_short.append("MTF1H")

        if ema9_bear and bajo_vwap:
            sl_short += 1
            ml_short.append("EMA9+VWAP")

        if bear_trend_5m:
            sl_short += 1
            ml_short.append("EMA21")

        if rsi >= config.RSI_SELL_MIN:
            sl_short += 1
            ml_short.append(f"RSI{rsi:.0f}")

        if macd_bear and config.MACD_ACTIVO:
            sl_short += 1
            ml_short.append("MACD")

        if vol_spike:
            sl_short += 1
            ml_short.append(f"VOL{vol_ratio:.1f}x")

        if kz["in_kz"]:
            sl_short += 1
            ml_short.append(f"KZ_{kz['nombre']}")

        if near_r1:      sl_short += 1; ml_short.append("R1")
        if near_r2:      sl_short += 1; ml_short.append("R2")
        if eq["is_eqh"]: sl_short += 1; ml_short.append("EQH")
        if near_asia_high:sl_short += 1;ml_short.append("ASIA_HIGH")
        if asia_brk_high: sl_short += 1;ml_short.append("ASIA_BRK")
        if near_pp:       sl_short += 1;ml_short.append("PP")

        # ══════════════════════════════════════════════════════
        # CONDICIONES BASE — lo mínimo para generar señal
        # ══════════════════════════════════════════════════════
        zona_long  = (near_s1 or near_s2 or near_pp or eq["is_eql"] or
                      near_asia_low or asia_brk_low or ob["bull_ob"])
        zona_short = (near_r1 or near_r2 or near_pp or eq["is_eqh"] or
                      near_asia_high or asia_brk_high or ob["bear_ob"])

        base_long  = fvg["bull_fvg"] and zona_long
        base_short = fvg["bear_fvg"] and zona_short

        # Filtros de precisión obligatorios
        mech_ok_long  = (candles[-1]["open"] - candles[-1]["low"]) / max(candles[-1]["high"]-candles[-1]["low"], 1e-10) < 0.40
        mech_ok_short = (candles[-1]["high"] - candles[-1]["close"]) / max(candles[-1]["high"]-candles[-1]["low"], 1e-10) < 0.40
        conf_long     = candles[-1]["close"] > candles[-1]["open"] and candles[-1]["close"] > candles[-2]["low"]
        conf_short    = candles[-1]["close"] < candles[-1]["open"] and candles[-1]["close"] < candles[-2]["high"]
        mom_long      = momentum_ok(candles, "LONG")
        mom_short     = momentum_ok(candles, "SHORT")
        rsi_ok_long   = rsi < config.RSI_BUY_MAX
        rsi_ok_short  = rsi > config.RSI_SELL_MIN

        score_min = config.SCORE_MIN

        # ── Elegir dirección ──
        lado = score = None
        motivos = []

        if (not config.SOLO_LONG and base_short and
                sl_short >= score_min and trend_ok_short and
                conf_short and mech_ok_short and mom_short and rsi_ok_short):
            if sl_short > sl_long:
                lado, score, motivos = "SHORT", sl_short, ml_short

        if (base_long and sl_long >= score_min and trend_ok_long and
                conf_long and mech_ok_long and mom_long and rsi_ok_long):
            if lado is None or sl_long >= sl_short:
                lado, score, motivos = "LONG", sl_long, ml_long

        if lado is None:
            if sl_long >= 3 or sl_short >= 3:
                log.info(
                    f"[NO-SE] {par} L:{sl_long}pts S:{sl_short}pts | "
                    f"bL={base_long}(fvg={fvg['bull_fvg']},zona={zona_long},conf={conf_long}) "
                    f"bS={base_short}(fvg={fvg['bear_fvg']},zona={zona_short},conf={conf_short}) "
                    f"htf={htf} rsi={rsi:.1f} kz={kz['nombre']}"
                )
            return None

        # ── SL / TP usando ATR7 (más preciso en timeframes cortos) ──
        atr_sl = atr7 if atr7 > 0 else atr
        if lado == "LONG":
            sl_ob  = ob["bull_ob_bottom"] * 0.998 if ob["bull_ob"] else 0
            sl_atr = precio - atr_sl * config.SL_ATR_MULT
            sl     = max(sl_ob, sl_atr) if sl_ob > 0 else sl_atr
            tp     = precio + atr_sl * config.TP_ATR_MULT
            tp1    = precio + atr_sl * config.PARTIAL_TP1_MULT
        else:
            sl_ob  = ob["bear_ob_top"] * 1.002 if ob["bear_ob"] else 0
            sl_atr = precio + atr_sl * config.SL_ATR_MULT
            sl     = min(sl_ob, sl_atr) if sl_ob > 0 else sl_atr
            tp     = precio - atr_sl * config.TP_ATR_MULT
            tp1    = precio - atr_sl * config.PARTIAL_TP1_MULT

        rr = abs(tp - precio) / abs(precio - sl) if abs(precio - sl) > 0 else 0
        if rr < config.MIN_RR:
            log.debug(f"[R:R] {par} {rr:.2f} < mín {config.MIN_RR}")
            return None

        # Registrar cooldown
        registrar_senal_ts(par)

        return {
            "par":        par,
            "lado":       lado,
            "precio":     precio,
            "sl":         round(sl, 8),
            "tp":         round(tp, 8),
            "tp1":        round(tp1, 8),
            "atr":        round(atr_sl, 8),
            "score":      score,
            "rsi":        rsi,
            "rr":         round(rr, 2),
            "motivos":    motivos,
            "kz":         kz["nombre"],
            "vwap":       round(vwap, 8),
            "sobre_vwap": sobre_vwap,
            "fvg_top":    fvg.get("fvg_top", 0),
            "fvg_bottom": fvg.get("fvg_bottom", 0),
            "pivotes":    pivotes,
            "htf":        htf,
            "ob_bull":    ob["bull_ob"],
            "ob_bear":    ob["bear_ob"],
            "bos_bull":   bos["bos_bull"],
            "bos_bear":   bos["bos_bear"],
            "choch_bull": bos["choch_bull"],
            "choch_bear": bos["choch_bear"],
            "sweep_bull": sweep["sweep_bull"],
            "sweep_bear": sweep["sweep_bear"],
            "patron":     pat_long["patron"] if lado == "LONG" else pat_short["patron"],
            "vela_conf":  pat_long["patron"] is not None if lado == "LONG" else pat_short["patron"] is not None,
            "macd_hist":  macd_hist,
            "vol_ratio":  round(vol_ratio, 2),
            "asia_valido":asia["valido"],
        }

    except Exception as e:
        log.info(f"[ERR-PAR] {par}: {type(e).__name__}: {e}")
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
