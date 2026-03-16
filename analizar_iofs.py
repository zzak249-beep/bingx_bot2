"""
analizar_iofs.py — Institutional Order Flow Shield Bot
=======================================================
Estrategia basada en el indicador "Institutional Order Flow Shield [MarkitTick]"

Componentes replicados del indicador TradingView:
  1. Order Flow Engine     — Delta de volumen ponderado por posición de cierre
  2. Supertrend            — Dirección macro del mercado
  3. Spoof & Iceberg       — Detección de manipulación institucional
  4. Decision Matrix       — Bull/Bear strength score con decay dinámico
  5. Smart Filters         — RVOL, ATR Gate, VWAP alineación, EMA tendencia
  6. Kill Zones            — Sesiones London / NY

Señales generadas:
  ACM  — ACCUMULATION  (flow alcista confirmado)
  DST  — DISTRIBUTION  (flow bajista confirmado)
  BWL  — BID WALL      (iceberg alcista)
  AWL  — ASK WALL      (iceberg bajista)
  APL  — ASK PULL      (spoof bajista retirado → señal alcista)
  BPL  — BID PULL      (spoof alcista retirado → señal bajista)
  WBD  — WHALE BID     (entrada ballena alcista)
  WAK  — WHALE ASK     (entrada ballena bajista)

Condiciones de entrada (equivalente al Decision Matrix del indicador):
  - Power Balance > STRONG_BUY_LVL  → LONG
  - Power Balance < STRONG_SELL_LVL → SHORT
  - Signal Confidence >= MIN_CONF_ENTRADA
  - RVOL gate activo
  - ATR gate activo
"""

import logging
import os
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

def _ema(prices: list, p: int) -> float | None:
    if len(prices) < p:
        return None
    k = 2 / (p + 1)
    v = sum(prices[:p]) / p
    for x in prices[p:]:
        v = x * k + v * (1 - k)
    return v

def _sma(v: list, p: int) -> float | None:
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
# SUPERTREND — dirección macro
# ══════════════════════════════════════════════════════

def _supertrend(hi: list, lo: list, cl: list, factor: float = 3.0, p: int = 10):
    """
    Retorna (bull, bear, flip_bull, flip_bear, st_line)
    Equivalente exacto al Supertrend del indicador original.
    """
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
# ORDER FLOW ENGINE
# Replica la lógica de request.security_lower_tf del indicador
# usando las velas disponibles directamente
# ══════════════════════════════════════════════════════

def _calcular_order_flow(candles: list) -> dict:
    """
    Calcula el delta de volumen ponderado por posición del cierre en el rango.
    Replica el bloque PART 2 del indicador Pine Script.
    """
    results = []
    for c in candles:
        o = c["open"]; h = c["high"]; l = c["low"]; cl = c["close"]; v = c["volume"]
        rng = max(h - l, 1e-12)
        pos = (cl - l) / rng

        buy_vol  = v * pos
        sell_vol = v * (1.0 - pos)

        # Wick rejection (reduce volumen comprador si hay mecha superior y viceversa)
        u_wick = h - max(cl, o)
        l_wick = min(cl, o) - l
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
    """Agrega el flow en el batch y calcula acumulados, promedios e impacto."""
    batch = flow_data[-batch_len:]
    cum_buy   = sum(f["adj_buy"]  for f in batch)
    cum_sell  = sum(f["adj_sell"] for f in batch)
    buy_count = sum(1 for f in batch if f["bull_bar"])
    sell_count= sum(1 for f in batch if f["bear_bar"])

    avg_buy   = cum_buy  / buy_count  if buy_count  > 0 else 0.0
    avg_sell  = cum_sell / sell_count if sell_count > 0 else 0.0

    ratio = cfg.FLOW_SENSITIVITY_RATIO
    accum  = avg_buy  > (avg_sell * ratio) and cum_buy  > cum_sell
    distri = avg_sell > (avg_buy  * ratio) and cum_sell > cum_buy

    impact = (cum_buy - cum_sell) if accum else (cum_sell - cum_buy) if distri else 0.0

    return {
        "cum_buy": cum_buy, "cum_sell": cum_sell,
        "avg_buy": avg_buy, "avg_sell": avg_sell,
        "accum": accum, "distri": distri, "impact": impact,
    }


# ══════════════════════════════════════════════════════
# SPOOF & ICEBERG DETECTION ENGINE
# Replica PART 4 del indicador Pine Script
# ══════════════════════════════════════════════════════

def _detectar_spoof_iceberg(candles: list, rvol: float, vol_avg: float,
                             atr_gate: bool) -> dict:
    """
    Detecta:
      - Spoof Bid Pull (BPL): spike de vol + colapso → precio baja
      - Spoof Ask Pull (APL): spike de vol + colapso → precio sube
      - Iceberg Bid Wall (BWL): volumen masivo sostenido alcista
      - Iceberg Ask Wall (AWL): volumen masivo sostenido bajista
      - Whale Bid (WBD): entrada ballena alcista con nueva zona
      - Whale Ask (WAK): entrada ballena bajista con nueva zona
    """
    if len(candles) < 3:
        return {}

    c    = candles[-1]   # vela actual
    cp   = candles[-2]   # vela anterior

    vol_curr = c["volume"]
    vol_prev = cp["volume"]
    atr14    = _atr([x["high"] for x in candles],
                    [x["low"]  for x in candles],
                    [x["close"]for x in candles], 14)

    # Parámetros configurables
    min_spoof      = max(cfg.MIN_SPOOF_VOL,    vol_avg * 1.5)
    smart_ice_lim  = max(cfg.MIN_ICEBERG_VOL,  vol_avg * cfg.ICEBERG_AVG_MULT)
    prev_rvol      = vol_prev / vol_avg if vol_avg > 0 else 1.0
    vol_diff       = abs(vol_prev - vol_curr)

    # Condiciones base de spoof
    vol_drop       = (vol_curr < vol_prev * cfg.SPOOF_PULL_PCT) and vol_diff >= min_spoof
    prev_was_spike = prev_rvol >= cfg.SPOOF_PREV_RVOL_MIN

    # Reversión de precio
    price_rev_up   = c["close"] > c["open"] and c["close"] > cp["close"]
    price_rev_down = c["close"] <= c["open"] and c["close"] < cp["close"]

    is_spoof_pull = vol_drop and prev_was_spike and atr_gate

    # Spoof Bid Pull → señal bajista (retiraron soporte falso)
    bpl = is_spoof_pull and price_rev_down and (
        not cfg.REQUIRE_PRICE_REVERSAL or price_rev_down)

    # Spoof Ask Pull → señal alcista (retiraron resistencia falsa)
    apl = is_spoof_pull and price_rev_up and (
        not cfg.REQUIRE_PRICE_REVERSAL or price_rev_up)

    # Iceberg wall
    is_iceberg_grow = (vol_curr > vol_prev
                       and vol_curr >= smart_ice_lim
                       and vol_diff >= smart_ice_lim * 0.2
                       and atr_gate)
    bwl = is_iceberg_grow and c["close"] > c["open"]   # Bid Wall alcista
    awl = is_iceberg_grow and c["close"] <= c["open"]  # Ask Wall bajista

    # Whale entry
    is_new_price_zone = (abs(c["close"] - cp["close"]) > atr14 * 0.5) if atr14 > 0 else False
    is_whale = rvol >= (cfg.ICEBERG_AVG_MULT * 0.8) and is_new_price_zone and atr_gate
    wbd = is_whale and c["close"] > c["open"]    # Whale Bid
    wak = is_whale and c["close"] <= c["open"]   # Whale Ask

    return {
        "bpl": bpl, "apl": apl,
        "bwl": bwl, "awl": awl,
        "wbd": wbd, "wak": wak,
        "is_spoof": is_spoof_pull,
        "is_iceberg": is_iceberg_grow or is_whale,
        "prev_rvol": round(prev_rvol, 2),
        "vol_diff": round(vol_diff, 2),
        "smart_ice_lim": round(smart_ice_lim, 2),
    }


# ══════════════════════════════════════════════════════
# DECISION MATRIX
# Replica PART 5 del indicador — Power Balance con decay
# ══════════════════════════════════════════════════════

# Estado global por par (equivalente a var FlowState en Pine)
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
        """Decay pasivo cada ciclo — equivalente al passive_decay del indicador."""
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
    def decision(self) -> str:
        pb = self.power_balance
        if pb > cfg.STRONG_BUY_LVL:  return "STRONG BUY"
        if pb < cfg.STRONG_SELL_LVL: return "STRONG SELL"
        return "WAIT/NEUTRAL"


def _get_flow_state(par: str) -> FlowState:
    if par not in _flow_states:
        _flow_states[par] = FlowState()
    return _flow_states[par]


def _calcular_confidence(side: str, flow: dict, spoof: dict,
                         bull: bool, bear: bool, abv_vwap: bool,
                         up_trend: bool, down_trend: bool) -> float:
    """Replica el cálculo de confScore del indicador Pine Script."""
    score = 0.0
    if side == "LONG":
        if flow.get("accum"):    score += 25.0
        if spoof.get("bwl"):     score += 20.0
        if spoof.get("wbd"):     score += 15.0
        if spoof.get("apl"):     score += 10.0
        if bull or up_trend:     score += 15.0
        if abv_vwap:             score += 15.0
    else:
        if flow.get("distri"):   score += 25.0
        if spoof.get("awl"):     score += 20.0
        if spoof.get("wak"):     score += 15.0
        if spoof.get("bpl"):     score += 10.0
        if bear or down_trend:   score += 15.0
        if not abv_vwap:         score += 15.0
    return round(score, 2)


# ══════════════════════════════════════════════════════
# SMART FILTERS — PART 3 del indicador
# ══════════════════════════════════════════════════════

def _smart_filters(candles: list) -> dict:
    """Calcula RVOL, ATR%, VWAP y EMA trend."""
    cl   = [c["close"]  for c in candles]
    hi   = [c["high"]   for c in candles]
    lo   = [c["low"]    for c in candles]
    vols = [c["volume"] for c in candles]

    # RVOL
    vol_avg = _sma(vols[:-1], cfg.VOL_SMA_LEN) or 1.0
    rvol    = vols[-1] / vol_avg
    rvol_ok = (not cfg.USE_RVOL_FILTER) or (rvol >= cfg.RVOL_MIN)

    # ATR Gate
    atr14   = _atr(hi, lo, cl, 14)
    atr_pct = (atr14 / cl[-1] * 100.0) if cl[-1] > 0 else 1.0
    atr_ok  = (not cfg.USE_ATR_FILTER) or (atr_pct >= cfg.ATR_MIN_PCT)

    # VWAP simple (usando hlc3 y volumen)
    hlc3    = [(c["high"]+c["low"]+c["close"])/3 for c in candles]
    vwap_n  = sum(hlc3[i]*vols[i] for i in range(len(candles)))
    vwap_d  = sum(vols) or 1
    vwap    = vwap_n / vwap_d
    abv_vwap = cl[-1] > vwap

    # EMA 50/200 trend
    e50  = _ema(cl, 50)
    e200 = _ema(cl, 200)
    up_trend   = (e50 is not None and e200 is not None and e50 > e200)
    down_trend = (e50 is not None and e200 is not None and e50 < e200)

    return {
        "rvol": round(rvol, 3), "rvol_ok": rvol_ok, "vol_avg": vol_avg,
        "atr": atr14, "atr_pct": round(atr_pct, 3), "atr_ok": atr_ok,
        "base_gate": rvol_ok and atr_ok,
        "vwap": vwap, "abv_vwap": abv_vwap,
        "e50": e50, "e200": e200,
        "up_trend": up_trend, "down_trend": down_trend,
    }


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
    rec = candles[-10:-1]
    buf = atr * 0.2

    if lado == "LONG":
        sl_sw  = min(c["low"] for c in rec) - buf if rec else 0
        opts   = [x for x in [sl_sw] if 0 < x < precio]
        sl     = max(opts) if opts else precio - atr * cfg.SL_ATR_MULT
        if precio - sl > 3 * atr:
            sl = precio - atr * cfg.SL_ATR_MULT
    else:
        sl_sw  = max(c["high"] for c in rec) + buf if rec else 0
        opts   = [x for x in [sl_sw] if x > precio]
        sl     = min(opts) if opts else precio + atr * cfg.SL_ATR_MULT
        if sl - precio > 3 * atr:
            sl = precio + atr * cfg.SL_ATR_MULT

    return sl


# ══════════════════════════════════════════════════════
# ANÁLISIS PRINCIPAL DE UN PAR
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

        # ── 1. SMART FILTERS ──────────────────────────────────
        filt = _smart_filters(candles)
        if not filt["base_gate"]:
            return None   # RVOL o ATR gate bloqueados

        # ── 2. SUPERTREND ─────────────────────────────────────
        bull, bear, flip_bull, flip_bear, st_line = _supertrend(
            hi, lo, cl, cfg.ST_FACTOR, cfg.ST_PERIOD)

        # ── 3. ORDER FLOW ENGINE ──────────────────────────────
        flow_data = _calcular_order_flow(candles)
        flow      = _calcular_flow_batch(flow_data, cfg.FLOW_BATCH_LEN)

        # ── 4. SPOOF & ICEBERG ────────────────────────────────
        spoof = _detectar_spoof_iceberg(
            candles, filt["rvol"], filt["vol_avg"], filt["base_gate"])

        # ── 5. DECISION MATRIX ────────────────────────────────
        fs = _get_flow_state(par)
        fs.decay()

        # Contar eventos para el dashboard
        if spoof.get("is_spoof"):   fs.spoof_count += 1
        if spoof.get("is_iceberg"): fs.ice_count   += 1

        # Evento bruto
        raw_bull = (flow["accum"] or spoof["bwl"] or spoof["apl"] or spoof["wbd"]) and filt["base_gate"]
        raw_bear = (flow["distri"] or spoof["awl"] or spoof["bpl"] or spoof["wak"]) and filt["base_gate"]

        # Desambiguación con delta
        bar_delta = flow_data[-1]["delta"] if flow_data else 0.0
        resolved_bull = raw_bull and (not raw_bear or bar_delta >= 0.0)
        resolved_bear = raw_bear and (not raw_bull or bar_delta < 0.0)

        if resolved_bull:
            fs.boost_bull(flow["impact"])
            fs.last_event = (
                "ACCUMULATION" if flow["accum"] else
                "BID WALL"     if spoof["bwl"]  else
                "ASK PULL"     if spoof["apl"]  else
                "WHALE BID"
            )
        elif resolved_bear:
            fs.boost_bear(flow["impact"])
            fs.last_event = (
                "DISTRIBUTION" if flow["distri"] else
                "ASK WALL"     if spoof["awl"]  else
                "BID PULL"     if spoof["bpl"]  else
                "WHALE ASK"
            )

        # Confidence score
        side_for_conf = "LONG" if resolved_bull else ("SHORT" if resolved_bear else None)
        if side_for_conf:
            fs.confidence = _calcular_confidence(
                side_for_conf, flow, spoof,
                bull, bear,
                filt["abv_vwap"],
                filt["up_trend"], filt["down_trend"],
            )
        fs.last_seen = time.time()

        # ── 6. VEREDICTO FINAL ────────────────────────────────
        decision = fs.decision
        pb        = fs.power_balance

        # Solo entrar cuando el Decision Matrix es claro
        if decision not in ("STRONG BUY", "STRONG SELL"):
            return None

        lado = "LONG" if decision == "STRONG BUY" else "SHORT"

        # Filtro de dirección
        if lado == "SHORT" and cfg.SOLO_LONG:
            return None

        # Verificar alineación VWAP (si filtro activo)
        if cfg.USE_VWAP_FILTER:
            if lado == "LONG"  and not filt["abv_vwap"]: return None
            if lado == "SHORT" and filt["abv_vwap"]:     return None

        # Verificar trend EMA (si filtro activo)
        if cfg.USE_TREND_FILTER:
            if lado == "LONG"  and not filt["up_trend"]:   return None
            if lado == "SHORT" and not filt["down_trend"]: return None

        # Confidence mínima
        if fs.confidence < cfg.MIN_CONF_ENTRADA:
            return None

        # Necesitamos al menos una señal activa en esta vela
        has_signal = resolved_bull if lado == "LONG" else resolved_bear
        if not has_signal:
            return None

        # ── 7. SL / TP ────────────────────────────────────────
        atr  = filt["atr"]
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
            return None

        # ── 8. SCORE PARA PRIORIZACIÓN ───────────────────────
        kz    = en_killzone()
        score = int(pb * 10)                       # base: power balance 0-10
        if fs.confidence >= 70.0:  score += 2
        if fs.confidence >= 90.0:  score += 2
        if flip_bull or flip_bear: score += 3      # ST flip = señal más fuerte
        if kz["in_kz"]:            score += 1
        if spoof.get("bwl") or spoof.get("awl"):   score += 2  # iceberg confirmado
        if spoof.get("apl") or spoof.get("bpl"):   score += 1  # spoof confirmado

        # Tipo de señal predominante
        if lado == "LONG":
            tipo = ("ACM" if flow["accum"] else
                    "BWL" if spoof["bwl"]  else
                    "APL" if spoof["apl"]  else
                    "WBD" if spoof["wbd"]  else "BULL")
        else:
            tipo = ("DST" if flow["distri"] else
                    "AWL" if spoof["awl"]  else
                    "BPL" if spoof["bpl"]  else
                    "WAK" if spoof["wak"]  else "BEAR")

        motivos = [tipo]
        if flip_bull or flip_bear: motivos.append("ST_FLIP")
        if filt["abv_vwap"]:      motivos.append("ABOVE_VWAP")
        else:                     motivos.append("BELOW_VWAP")
        motivos.append(f"RVOL×{filt['rvol']:.1f}")
        motivos.append(f"CONF{fs.confidence:.0f}%")
        if kz["in_kz"]:           motivos.append(f"KZ_{kz['nombre']}")

        registrar_senal_ts(par)

        log.info(
            f"[IOFS] {lado:5s} {par:15s} | {tipo} | "
            f"PB={pb:.2%} CONF={fs.confidence:.0f}% RVOL×{filt['rvol']:.1f} "
            f"ATR%={filt['atr_pct']:.2f}% {'FLIP ' if flip_bull or flip_bear else ''}"
            f"score={score} SL={sl:.6f} TP={tp:.6f} RR={rr:.2f} "
            f"{'KZ_'+kz['nombre'] if kz['in_kz'] else ''}"
        )

        return {
            "par": par, "lado": lado, "precio": precio,
            "sl":  round(sl,  8), "tp":  round(tp,  8),
            "tp1": round(tp1, 8), "tp2": round(tp,  8),
            "atr": round(atr, 8), "dist_sl": round(dist, 8),
            "score": score,
            "rsi":   round(_rsi(cl[-20:]), 1),
            "rr":    round(rr, 2),
            "motivos":     motivos,
            "kz":          kz["nombre"],
            "tipo":        tipo,
            "conf":        fs.confidence,
            "power_bal":   round(pb * 100, 1),
            "rvol":        filt["rvol"],
            "atr_pct":     filt["atr_pct"],
            "abv_vwap":    filt["abv_vwap"],
            "st_flip":     flip_bull or flip_bear,
            "st_bull":     bull, "st_bear": bear,
            "net_whale":   round(fs.net_whale, 2),
            "spoof_count": fs.spoof_count,
            "ice_count":   fs.ice_count,
            # Campos compatibles con main_smc.py
            "htf": "NEUTRAL", "htf_4h": "NEUTRAL",
            "purga_nivel": tipo, "purga_peso": score,
            "vol_ratio": filt["rvol"],
            "bsl_h1": 0.0, "ssl_h1": 0.0, "bsl_h4": 0.0,
            "ssl_h4": 0.0, "bsl_d":  0.0, "ssl_d":  0.0,
            "ema_r": 0.0, "ema_l": 0.0,
            "vwap": round(filt["vwap"], 8), "sobre_vwap": filt["abv_vwap"],
            "fvg_top": 0, "fvg_bottom": 0, "fvg_rellenado": True,
            "ob_bull": False, "ob_bear": False,
            "ob_fvg_bull": False, "ob_fvg_bear": False, "ob_mitigado": True,
            "bos_bull": lado == "LONG", "bos_bear": lado == "SHORT",
            "choch_bull": (flip_bull and lado == "LONG"),
            "choch_bear": (flip_bear and lado == "SHORT"),
            "sweep_bull": spoof.get("apl", False),
            "sweep_bear": spoof.get("bpl", False),
            "patron": tipo, "vela_conf": True,
            "premium": False, "discount": False,
            "displacement": spoof.get("is_iceberg", False),
            "macd_hist": 0,
            "asia_valido": True, "adx": 25.0, "inducement": False,
            "liq_bull": spoof.get("bwl", False),
            "liq_bear": spoof.get("awl", False),
            "liq_z_up": filt["rvol"], "liq_z_dn": filt["rvol"],
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
