"""
analizar_iofs.py — Institutional Order Flow Shield Bot
=======================================================
VERSION v3.0 — BUGS CORREGIDOS

BUG #1 — Order Flow: avg_buy/avg_sell sesgo matemático IMPOSIBLE
  Problema: avg_buy se calculaba SOLO sobre velas alcistas,
            avg_sell SOLO sobre velas bajistas. En un batch de 8 velas
            con mezcla típica 50/50, avg_buy/avg_sell ≈ 0.45-0.90,
            NUNCA superaba el ratio 1.2. El bot NUNCA generaba accum/distri.
  Solución: Net Pressure sobre el volumen total acumulado:
            net_pressure = (cum_buy - cum_sell) / (cum_buy + cum_sell)
            accum  cuando net_pressure >= +NET_PRESSURE_MIN (ej: +0.08)
            distri cuando net_pressure <= -NET_PRESSURE_MIN

BUG #2 — Iceberg: floor MIN_ICEBERG_VOL=500 imposible en 1m
  Problema: smart_ice_lim = max(500, vol_avg×1.5)
            Con vol_avg típico de 1m BTC ≈ 40-150 contratos,
            smart_ice_lim SIEMPRE era 500. Nunca se disparaba.
  Solución: Threshold puramente relativo: vol_avg × ICEBERG_AVG_MULT
            Con vol_avg=60 y mult=2.5 → lim=150 (alcanzable)

BUG #3 — Power Balance bloqueaba señales como gate duro
  Solución: Solo score bonus, no bloquea (corrección de v2 conservada)

BUG #4 — MIN_SPOOF_VOL=200 fijo incompatible con vol_avg bajo
  Solución: min_spoof = vol_avg × SPOOF_VOL_MULT (relativo)
"""

import logging
import time
from datetime import datetime, timezone
import concurrent.futures

import config_iofs as cfg
import exchange

log = logging.getLogger("analizar_iofs")

_cooldown_ts: dict = {}


# ══════════════════════════════════════════════════════
# INDICADORES BASE
# ══════════════════════════════════════════════════════

def _ema(prices: list, p: int):
    if len(prices) < p:
        return None
    k = 2 / (p + 1)
    v = sum(prices[:p]) / p
    for x in prices[p:]:
        v = x * k + v * (1 - k)
    return v


def _sma(v: list, p: int):
    return sum(v[-p:]) / p if len(v) >= p else None


def _rsi(prices: list, p: int = 14) -> float:
    if len(prices) < p + 1:
        return 50.0
    d  = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(x, 0)       for x in d[:p]) / p
    al = sum(abs(min(x, 0))  for x in d[:p]) / p
    for x in d[p:]:
        ag = (ag*(p-1) + max(x, 0))      / p
        al = (al*(p-1) + abs(min(x, 0))) / p
    return 100.0 if al == 0 else round(100 - 100/(1 + ag/al), 2)


def _atr(hi: list, lo: list, cl: list, p: int = 14) -> float:
    if len(hi) < p + 1:
        return 0.0
    trs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
           for i in range(1, len(hi))]
    return sum(trs[-p:]) / p


# ══════════════════════════════════════════════════════
# SUPERTREND — opcional
# ══════════════════════════════════════════════════════

def _supertrend(hi: list, lo: list, cl: list, factor: float = 2.5, p: int = 7):
    if len(cl) < p + 2:
        return False, False, False, False, 0.0
    atrs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
            for i in range(1, len(cl))]
    av = sum(atrs[:p]) / p
    atr_s = [av]
    for a in atrs[p:]:
        av = (av*(p-1) + a) / p
        atr_s.append(av)
    n   = len(atr_s)
    off = len(cl) - n
    ub  = [0.0]*n; lb = [0.0]*n; dr = [1]*n; st = [0.0]*n
    for i in range(n):
        ci = i + off
        h2 = (hi[ci] + lo[ci]) / 2
        u  = h2 + factor * atr_s[i]
        l  = h2 - factor * atr_s[i]
        ub[i] = min(u, ub[i-1]) if i > 0 and cl[ci-1] < ub[i-1] else u
        lb[i] = max(l, lb[i-1]) if i > 0 and cl[ci-1] > lb[i-1] else l
        if i == 0:
            dr[i] = 1
        elif st[i-1] == ub[i-1]:
            dr[i] = 1 if cl[ci] < ub[i] else -1
        else:
            dr[i] = -1 if cl[ci] > lb[i] else 1
        st[i] = ub[i] if dr[i] == 1 else lb[i]
    bull      = dr[-1] < 0
    bear      = dr[-1] > 0
    flip_bull = (dr[-1] < 0 and dr[-2] > 0) if len(dr) >= 2 else False
    flip_bear = (dr[-1] > 0 and dr[-2] < 0) if len(dr) >= 2 else False
    return bull, bear, flip_bull, flip_bear, st[-1]


# ══════════════════════════════════════════════════════
# ORDER FLOW ENGINE — v3 (BUG #1 CORREGIDO)
# ══════════════════════════════════════════════════════

def _calcular_order_flow(candles: list) -> list:
    results = []
    for c in candles:
        o  = c["open"]; h = c["high"]; l = c["low"]
        cl = c["close"]; v = c["volume"]
        rng = max(h - l, 1e-12)
        pos = (cl - l) / rng
        buy_vol  = v * pos
        sell_vol = v * (1.0 - pos)
        u_wick      = h - max(cl, o)
        l_wick      = min(cl, o) - l
        wick_rej_up = (u_wick / rng) * v
        wick_rej_dn = (l_wick / rng) * v
        adj_buy  = max(0.0, buy_vol  - wick_rej_up * 0.5)
        adj_sell = max(0.0, sell_vol - wick_rej_dn * 0.5)
        results.append({
            "adj_buy":  adj_buy,
            "adj_sell": adj_sell,
            "delta":    adj_buy - adj_sell,
            "bull_bar": cl > o,
            "bear_bar": cl < o,
        })
    return results


def _calcular_flow_batch(flow_data: list, batch_len: int) -> dict:
    """
    FIX BUG #1: Net Pressure = (cum_buy - cum_sell) / total
    Funciona en cualquier mezcla de velas bull/bear.
    accum  si net_pressure >= +NET_PRESSURE_MIN
    distri si net_pressure <= -NET_PRESSURE_MIN
    """
    batch    = flow_data[-batch_len:]
    cum_buy  = sum(f["adj_buy"]  for f in batch)
    cum_sell = sum(f["adj_sell"] for f in batch)
    total    = cum_buy + cum_sell

    net_pressure = (cum_buy - cum_sell) / total if total > 0 else 0.0

    accum  = net_pressure >= cfg.NET_PRESSURE_MIN
    distri = net_pressure <= -cfg.NET_PRESSURE_MIN
    impact = abs(cum_buy - cum_sell)

    return {
        "cum_buy":      cum_buy,
        "cum_sell":     cum_sell,
        "net_pressure": round(net_pressure, 4),
        "accum":        accum,
        "distri":       distri,
        "impact":       impact,
        "avg_buy":      cum_buy,
        "avg_sell":     cum_sell,
    }


# ══════════════════════════════════════════════════════
# SPOOF & ICEBERG — v3 (BUG #2 CORREGIDO)
# ══════════════════════════════════════════════════════

def _detectar_spoof_iceberg(candles: list, rvol: float,
                             vol_avg: float, atr_gate: bool) -> dict:
    """
    FIX BUG #2: Thresholds relativos al vol_avg real, sin floor absoluto.
    smart_ice_lim = vol_avg × ICEBERG_AVG_MULT
    min_spoof     = vol_avg × SPOOF_VOL_MULT
    """
    _empty = {"bpl": False, "apl": False, "bwl": False, "awl": False,
              "wbd": False, "wak": False, "is_spoof": False, "is_iceberg": False,
              "prev_rvol": 0.0, "vol_diff": 0.0, "smart_ice_lim": 0.0}
    if len(candles) < 3:
        return _empty

    c    = candles[-1]
    cp   = candles[-2]

    vol_curr = c["volume"]
    vol_prev = cp["volume"]
    atr14    = _atr([x["high"]  for x in candles],
                    [x["low"]   for x in candles],
                    [x["close"] for x in candles], 14)

    # FIX: puramente relativo, sin max() con valor absoluto fijo
    min_spoof     = vol_avg * cfg.SPOOF_VOL_MULT
    smart_ice_lim = vol_avg * cfg.ICEBERG_AVG_MULT

    prev_rvol = vol_prev / vol_avg if vol_avg > 0 else 1.0
    vol_diff  = abs(vol_prev - vol_curr)

    vol_drop       = (vol_curr < vol_prev * cfg.SPOOF_PULL_PCT) and vol_diff >= min_spoof
    prev_was_spike = prev_rvol >= cfg.SPOOF_PREV_RVOL_MIN

    price_rev_up   = c["close"] > c["open"]  and c["close"] > cp["close"]
    price_rev_down = c["close"] <= c["open"] and c["close"] < cp["close"]

    is_spoof_pull = vol_drop and prev_was_spike and atr_gate

    bpl = is_spoof_pull and price_rev_down and (
        not cfg.REQUIRE_PRICE_REVERSAL or price_rev_down)
    apl = is_spoof_pull and price_rev_up and (
        not cfg.REQUIRE_PRICE_REVERSAL or price_rev_up)

    is_iceberg_grow = (vol_curr > vol_prev
                       and vol_curr >= smart_ice_lim
                       and vol_diff >= smart_ice_lim * 0.15
                       and atr_gate)
    bwl = is_iceberg_grow and c["close"] > c["open"]
    awl = is_iceberg_grow and c["close"] <= c["open"]

    is_new_zone = (abs(c["close"] - cp["close"]) > atr14 * 0.4) if atr14 > 0 else False
    is_whale    = rvol >= cfg.WHALE_RVOL_MIN and is_new_zone and atr_gate
    wbd = is_whale and c["close"] > c["open"]
    wak = is_whale and c["close"] <= c["open"]

    return {
        "bpl": bpl, "apl": apl,
        "bwl": bwl, "awl": awl,
        "wbd": wbd, "wak": wak,
        "is_spoof":    is_spoof_pull,
        "is_iceberg":  is_iceberg_grow or is_whale,
        "prev_rvol":   round(prev_rvol, 2),
        "vol_diff":    round(vol_diff, 2),
        "smart_ice_lim": round(smart_ice_lim, 2),
    }


# ══════════════════════════════════════════════════════
# DECISION MATRIX — Power Balance (score bonus, no bloquea)
# ══════════════════════════════════════════════════════

_flow_states: dict = {}


class FlowState:
    def __init__(self):
        self.bull_str    = 0.0
        self.bear_str    = 0.0
        self.max_str     = 500.0
        self.net_whale   = 0.0
        self.spoof_count = 0
        self.ice_count   = 0
        self.last_event  = "WAITING"
        self.confidence  = 0.0
        self.last_seen   = time.time()

    def decay(self):
        mul = 1.0 - max(0.0, min(0.99, cfg.PASSIVE_DECAY / 100.0))
        self.bull_str = max(0.0, self.bull_str * mul)
        self.bear_str = max(0.0, self.bear_str * mul)

    def boost_bull(self, impact: float = 0):
        self.bull_str = min(self.max_str, self.bull_str + cfg.BOOST_RATE)
        self.bear_str = max(0.0, self.bear_str - cfg.DECAY_RATE)
        self.net_whale += impact

    def boost_bear(self, impact: float = 0):
        self.bear_str = min(self.max_str, self.bear_str + cfg.BOOST_RATE)
        self.bull_str = max(0.0, self.bull_str - cfg.DECAY_RATE)
        self.net_whale -= impact

    @property
    def power_balance(self) -> float:
        total = self.bull_str + self.bear_str
        return self.bull_str / total if total > 0 else 0.5

    @property
    def pb_label(self) -> str:
        pb = self.power_balance
        if pb > cfg.STRONG_BUY_LVL:  return "PB:BULL"
        if pb < cfg.STRONG_SELL_LVL: return "PB:BEAR"
        return "PB:NEUT"


def _get_flow_state(par: str) -> FlowState:
    if par not in _flow_states:
        _flow_states[par] = FlowState()
    return _flow_states[par]


# ══════════════════════════════════════════════════════
# SMART FILTERS — ATR + RVOL obligatorios
# ══════════════════════════════════════════════════════

def _smart_filters(candles: list) -> dict:
    cl   = [c["close"]  for c in candles]
    hi   = [c["high"]   for c in candles]
    lo   = [c["low"]    for c in candles]
    vols = [c["volume"] for c in candles]

    vol_avg = _sma(vols[:-1], cfg.VOL_SMA_LEN) or 1.0
    rvol    = vols[-1] / vol_avg
    rvol_ok = (not cfg.USE_RVOL_FILTER) or (rvol >= cfg.RVOL_MIN)

    atr14   = _atr(hi, lo, cl, 14)
    atr_pct = (atr14 / cl[-1] * 100.0) if cl[-1] > 0 else 1.0
    atr_ok  = (not cfg.USE_ATR_FILTER) or (atr_pct >= cfg.ATR_MIN_PCT)

    hlc3   = [(c["high"]+c["low"]+c["close"])/3 for c in candles]
    vwap_n = sum(hlc3[i]*vols[i] for i in range(len(candles)))
    vwap_d = sum(vols) or 1
    vwap   = vwap_n / vwap_d
    abv_vwap = cl[-1] > vwap

    e50  = _ema(cl, 50)
    e200 = _ema(cl, 200)
    up_trend   = (e50 is not None and e200 is not None and e50 > e200)
    down_trend = (e50 is not None and e200 is not None and e50 < e200)

    return {
        "rvol":      round(rvol, 3),
        "rvol_ok":   rvol_ok,
        "vol_avg":   vol_avg,
        "atr":       atr14,
        "atr_pct":   round(atr_pct, 3),
        "atr_ok":    atr_ok,
        "base_gate": rvol_ok and atr_ok,
        "vwap":      vwap,
        "abv_vwap":  abv_vwap,
        "e50":       e50,
        "e200":      e200,
        "up_trend":  up_trend,
        "down_trend": down_trend,
    }


# ══════════════════════════════════════════════════════
# CONFIDENCE — calibrada para 1m
# ══════════════════════════════════════════════════════

def _calcular_confidence(side: str, flow: dict, spoof: dict,
                          bull: bool, bear: bool,
                          abv_vwap: bool,
                          flip_bull: bool, flip_bear: bool) -> float:
    score = 0.0
    if side == "LONG":
        if flow.get("accum"):    score += 30.0
        if spoof.get("bwl"):     score += 25.0
        if spoof.get("wbd"):     score += 20.0
        if spoof.get("apl"):     score += 15.0
        if bull:                 score += 10.0
        if abv_vwap:             score += 10.0
        if flip_bull:            score += 15.0
    else:
        if flow.get("distri"):   score += 30.0
        if spoof.get("awl"):     score += 25.0
        if spoof.get("wak"):     score += 20.0
        if spoof.get("bpl"):     score += 15.0
        if bear:                 score += 10.0
        if not abv_vwap:         score += 10.0
        if flip_bear:            score += 15.0
    return round(min(score, 100.0), 2)


# ══════════════════════════════════════════════════════
# KILL ZONES + COOLDOWN
# ══════════════════════════════════════════════════════

def en_killzone() -> dict:
    m    = datetime.now(timezone.utc)
    mins = m.hour * 60 + m.minute
    london = cfg.KZ_LONDON_START <= mins < cfg.KZ_LONDON_END
    ny     = cfg.KZ_NY_START     <= mins < cfg.KZ_NY_END
    return {
        "in_kz":  london or ny,
        "nombre": "LONDON" if london else ("NY" if ny else "FUERA"),
    }


def _cooldown_ok(par: str) -> bool:
    return (time.time() - _cooldown_ts.get(par, 0)) >= cfg.COOLDOWN_VELAS * 60


def registrar_senal_ts(par: str):
    _cooldown_ts[par] = time.time()


# ══════════════════════════════════════════════════════
# SL INTELIGENTE
# ══════════════════════════════════════════════════════

def _calcular_sl(candles: list, lado: str, atr: float, precio: float) -> float:
    rec = candles[-7:-1]
    buf = atr * 0.15
    if lado == "LONG":
        sl_sw = min(c["low"] for c in rec) - buf if rec else 0
        opts  = [x for x in [sl_sw] if 0 < x < precio]
        sl    = max(opts) if opts else precio - atr * cfg.SL_ATR_MULT
        if precio - sl > 3 * atr:
            sl = precio - atr * cfg.SL_ATR_MULT
    else:
        sl_sw = max(c["high"] for c in rec) + buf if rec else 0
        opts  = [x for x in [sl_sw] if x > precio]
        sl    = min(opts) if opts else precio + atr * cfg.SL_ATR_MULT
        if sl - precio > 3 * atr:
            sl = precio + atr * cfg.SL_ATR_MULT
    return sl


# ══════════════════════════════════════════════════════
# ANÁLISIS PRINCIPAL
# ══════════════════════════════════════════════════════

def analizar_par(par: str) -> dict | None:
    try:
        if not _cooldown_ok(par):
            return None

        candles = exchange.get_candles(par, cfg.TIMEFRAME, cfg.CANDLES_LIMIT)
        if len(candles) < cfg.WARMUP_BARS + 10:
            return None

        cl  = [c["close"] for c in candles]
        hi  = [c["high"]  for c in candles]
        lo  = [c["low"]   for c in candles]
        precio = cl[-1]
        if precio <= 0:
            return None

        # ── GATE ATR + RVOL (únicos obligatorios) ────────────
        filt = _smart_filters(candles)
        if not filt["atr_ok"]:
            log.debug(f"[ATR] {par} skip ATR%={filt['atr_pct']:.3f}%")
            return None
        if not filt["rvol_ok"]:
            log.debug(f"[RVOL] {par} skip RVOL={filt['rvol']:.2f}x")
            return None

        # ── SUPERTREND ────────────────────────────────────────
        bull, bear, flip_bull, flip_bear, st_line = _supertrend(
            hi, lo, cl, cfg.ST_FACTOR, cfg.ST_PERIOD)

        # ── ORDER FLOW v3 (net pressure) ─────────────────────
        flow_data = _calcular_order_flow(candles)
        flow      = _calcular_flow_batch(flow_data, cfg.FLOW_BATCH_LEN)

        # ── SPOOF & ICEBERG v3 (thresholds relativos) ────────
        spoof = _detectar_spoof_iceberg(
            candles, filt["rvol"], filt["vol_avg"], filt["atr_ok"])

        # ── RESOLVER DIRECCIÓN ────────────────────────────────
        raw_bull = flow["accum"] or spoof["bwl"] or spoof["apl"] or spoof["wbd"]
        raw_bear = flow["distri"] or spoof["awl"] or spoof["bpl"] or spoof["wak"]

        if not raw_bull and not raw_bear:
            return None

        bar_delta     = flow_data[-1]["delta"] if flow_data else 0.0
        resolved_bull = raw_bull and (not raw_bear or bar_delta >= 0.0)
        resolved_bear = raw_bear and (not raw_bull or bar_delta <  0.0)

        if not resolved_bull and not resolved_bear:
            return None

        lado = "LONG" if resolved_bull else "SHORT"
        if lado == "SHORT" and cfg.SOLO_LONG:
            return None

        # ── FILTRO ST OPCIONAL ────────────────────────────────
        if cfg.USE_ST_FILTER:
            if lado == "LONG"  and not bull:  return None
            if lado == "SHORT" and not bear:  return None

        # ── DECISION MATRIX (score, no bloquea) ──────────────
        fs = _get_flow_state(par)
        fs.decay()
        if spoof.get("is_spoof"):   fs.spoof_count += 1
        if spoof.get("is_iceberg"): fs.ice_count   += 1
        if resolved_bull:
            fs.boost_bull(flow["impact"])
            fs.last_event = (
                "ACCUMULATION" if flow["accum"] else
                "BID WALL"     if spoof["bwl"]  else
                "ASK PULL"     if spoof["apl"]  else "WHALE BID")
        else:
            fs.boost_bear(flow["impact"])
            fs.last_event = (
                "DISTRIBUTION" if flow["distri"] else
                "ASK WALL"     if spoof["awl"]   else
                "BID PULL"     if spoof["bpl"]   else "WHALE ASK")
        fs.last_seen = time.time()

        # ── CONFIDENCE ────────────────────────────────────────
        conf = _calcular_confidence(
            lado, flow, spoof, bull, bear,
            filt["abv_vwap"], flip_bull, flip_bear)
        fs.confidence = conf

        if conf < cfg.MIN_CONF_ENTRADA:
            log.debug(f"[CONF] {par} {lado} conf={conf:.0f}% < {cfg.MIN_CONF_ENTRADA}%")
            return None

        # ── SL / TP / RR ──────────────────────────────────────
        atr = filt["atr"]
        if atr <= 0:
            return None
        sl   = _calcular_sl(candles, lado, atr, precio)
        dist = abs(precio - sl)
        if dist <= 0:
            return None
        tp   = (precio + dist * cfg.TP_DIST_MULT)  if lado == "LONG" else (precio - dist * cfg.TP_DIST_MULT)
        tp1  = (precio + dist * cfg.TP1_DIST_MULT) if lado == "LONG" else (precio - dist * cfg.TP1_DIST_MULT)
        rr   = abs(tp - precio) / dist
        if rr < cfg.MIN_RR:
            log.debug(f"[RR] {par} {lado} RR={rr:.2f} < {cfg.MIN_RR}")
            return None

        # ── SCORE ─────────────────────────────────────────────
        pb    = fs.power_balance
        kz    = en_killzone()
        score = 0
        if flow["accum"] or flow["distri"]:               score += 3
        if spoof["bwl"]  or spoof["awl"]:                 score += 3
        if spoof["apl"]  or spoof["bpl"]:                 score += 2
        if spoof["wbd"]  or spoof["wak"]:                 score += 2
        if conf >= 55.0:                                   score += 1
        if conf >= 75.0:                                   score += 1
        if flip_bull or flip_bear:                         score += 2
        if kz["in_kz"]:                                   score += 1
        if pb > cfg.STRONG_BUY_LVL  and lado == "LONG":   score += 2
        if pb < cfg.STRONG_SELL_LVL and lado == "SHORT":   score += 2
        if pb > cfg.STRONG_BUY_LVL  and lado == "SHORT":  score -= 1
        if pb < cfg.STRONG_SELL_LVL and lado == "LONG":   score -= 1

        if score < cfg.MIN_SCORE_ENTRADA:
            log.debug(f"[SCORE] {par} {lado} score={score} < {cfg.MIN_SCORE_ENTRADA}")
            return None

        # ── TIPO ──────────────────────────────────────────────
        if lado == "LONG":
            tipo = ("ACM" if flow["accum"]  else
                    "BWL" if spoof["bwl"]   else
                    "APL" if spoof["apl"]   else
                    "WBD" if spoof["wbd"]   else "BULL")
        else:
            tipo = ("DST" if flow["distri"] else
                    "AWL" if spoof["awl"]   else
                    "BPL" if spoof["bpl"]   else
                    "WAK" if spoof["wak"]   else "BEAR")

        motivos = [tipo]
        if flip_bull or flip_bear: motivos.append("ST_FLIP")
        motivos.append("ABOVE_VWAP" if filt["abv_vwap"] else "BELOW_VWAP")
        motivos.append(f"RVOL×{filt['rvol']:.1f}")
        motivos.append(f"CONF{conf:.0f}%")
        motivos.append(f"NP{flow['net_pressure']:+.2f}")
        motivos.append(fs.pb_label)
        if kz["in_kz"]: motivos.append(f"KZ_{kz['nombre']}")

        registrar_senal_ts(par)

        log.info(
            f"[IOFS] {lado:5s} {par:15s} | {tipo} | "
            f"NP={flow['net_pressure']:+.3f} "
            f"conf={conf:.0f}% RVOL×{filt['rvol']:.2f} "
            f"ATR%={filt['atr_pct']:.2f}% {fs.pb_label} "
            f"score={score} SL={sl:.6f} TP={tp:.6f} RR={rr:.2f}"
            + (" FLIP" if flip_bull or flip_bear else "")
            + (f" KZ_{kz['nombre']}" if kz["in_kz"] else "")
        )

        return {
            "par":      par, "lado":     lado, "precio":   precio,
            "sl":       round(sl,  8),   "tp":     round(tp,  8),
            "tp1":      round(tp1, 8),   "tp2":    round(tp,  8),
            "atr":      round(atr, 8),   "dist_sl": round(dist, 8),
            "score":    score,
            "rsi":      round(_rsi(cl[-20:]), 1),
            "rr":       round(rr, 2),
            "motivos":      motivos,
            "kz":           kz["nombre"],
            "tipo":         tipo,
            "conf":         conf,
            "power_bal":    round(pb * 100, 1),
            "net_pressure": flow["net_pressure"],
            "rvol":         filt["rvol"],
            "atr_pct":      filt["atr_pct"],
            "abv_vwap":     filt["abv_vwap"],
            "st_flip":      flip_bull or flip_bear,
            "st_bull":      bull, "st_bear": bear,
            "net_whale":    round(fs.net_whale, 2),
            "spoof_count":  fs.spoof_count,
            "ice_count":    fs.ice_count,
            "htf": "NEUTRAL", "htf_4h": "NEUTRAL",
            "purga_nivel": tipo, "purga_peso": score,
            "vol_ratio": filt["rvol"],
            "bsl_h1": 0.0, "ssl_h1": 0.0, "bsl_h4": 0.0,
            "ssl_h4": 0.0, "bsl_d":  0.0, "ssl_d":  0.0,
            "ema_r": 0.0, "ema_l": 0.0,
            "vwap":          round(filt["vwap"], 8),
            "sobre_vwap":    filt["abv_vwap"],
            "fvg_top":       0, "fvg_bottom": 0, "fvg_rellenado": True,
            "ob_bull":       False, "ob_bear": False,
            "ob_fvg_bull":   False, "ob_fvg_bear": False, "ob_mitigado": True,
            "bos_bull":      lado == "LONG", "bos_bear": lado == "SHORT",
            "choch_bull":    flip_bull and lado == "LONG",
            "choch_bear":    flip_bear and lado == "SHORT",
            "sweep_bull":    spoof.get("apl", False),
            "sweep_bear":    spoof.get("bpl", False),
            "patron":        tipo, "vela_conf": True,
            "premium":       False, "discount": False,
            "displacement":  spoof.get("is_iceberg", False),
            "macd_hist":     0,
            "asia_valido":   True, "adx": 25.0, "inducement": False,
            "liq_bull":      spoof.get("bwl", False),
            "liq_bear":      spoof.get("awl", False),
            "liq_z_up":      filt["rvol"], "liq_z_dn": filt["rvol"],
            "liq_plot_trnd": 1 if lado == "LONG" else -1,
        }

    except Exception as e:
        log.error(f"analizar_par {par}: {e}", exc_info=True)
        return None


def analizar_todos(pares: list, workers: int = 4) -> list:
    senales = []
    w = min(workers, len(pares), 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futuros = {ex.submit(analizar_par, p): p for p in pares}
        for fut in concurrent.futures.as_completed(futuros):
            try:
                r = fut.result()
                if r:
                    senales.append(r)
            except Exception as e:
                log.error(f"thread: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
