"""
analizar_iofs.py — Saty Unified Strategy v6
=============================================
Replica exacta del Pine Script "Saty Unified Strategy v6":

  LONG:
    1. close > EMA48          (tendencia alcista)
    2. EMA8 > EMA21           (ribbon alcista)
    3. Oscillator cruzó 0 hacia arriba
    4. buy_vol > sell_vol     (compradores dominan)
    5. NO squeeze             (BB superior > KC superior)

  SHORT:
    1. close < EMA48          (tendencia bajista)
    2. EMA8 < EMA21           (ribbon bajista)
    3. Oscillator cruzó 0 hacia abajo
    4. sell_vol > buy_vol     (vendedores dominan)
    5. NO squeeze

  SL/TP dinámicos basados en ATR.
"""
import logging, time, concurrent.futures
from datetime import datetime, timezone
import exchange, config_iofs as cfg

log = logging.getLogger("analizar_iofs")
_cooldown_ts: dict = {}
_prev_osc: dict = {}   # guarda oscilador anterior por par para detectar cruce


# ── Indicadores ───────────────────────────────────────────────

def _ema(p, n):
    if len(p) < n: return None
    k = 2/(n+1); v = sum(p[:n])/n
    for x in p[n:]: v = x*k + v*(1-k)
    return v

def _ema_series(p, n):
    """Retorna la serie completa de EMA."""
    if len(p) < n: return []
    k = 2/(n+1); v = sum(p[:n])/n
    out = [v]
    for x in p[n:]: v = x*k + v*(1-k); out.append(v)
    return out

def _atr_val(hi, lo, cl, n=14):
    if len(hi) < n+1: return 0.0
    t = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
         for i in range(1, len(hi))]
    return sum(t[-n:]) / n

def _stdev(p, n):
    if len(p) < n: return 0.0
    s = p[-n:]
    m = sum(s)/n
    return (sum((x-m)**2 for x in s)/n) ** 0.5

def _oscillator(cl, ema21_series, atr_series, smooth=3):
    """
    raw = ((close - ema21) / (3 * atr)) * 100
    oscillator = EMA(raw, smooth)
    Retorna serie completa.
    """
    n = min(len(cl), len(ema21_series), len(atr_series))
    if n == 0: return []
    raw = []
    for i in range(n):
        a = atr_series[i]
        if a <= 0: raw.append(0.0)
        else: raw.append(((cl[-n+i] - ema21_series[i]) / (3.0 * a)) * 100.0)
    # EMA del raw con smooth=3
    if len(raw) < smooth: return raw
    k = 2/(smooth+1); v = sum(raw[:smooth])/smooth
    out = [v]
    for x in raw[smooth:]: v = x*k + v*(1-k); out.append(v)
    return out

def _atr_series(hi, lo, cl, n=14):
    """Retorna serie de ATR alineada con las velas."""
    if len(hi) < n+1: return []
    trs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
           for i in range(1, len(hi))]
    if len(trs) < n: return []
    av = sum(trs[:n])/n; out = [av]
    for t in trs[n:]: av = (av*(n-1)+t)/n; out.append(av)
    return out  # len = len(cl) - n


def en_killzone():
    m = datetime.now(timezone.utc); mins = m.hour*60+m.minute
    lon = cfg.KZ_LONDON_START <= mins < cfg.KZ_LONDON_END
    ny  = cfg.KZ_NY_START     <= mins < cfg.KZ_NY_END
    return {"in_kz": lon or ny,
            "nombre": "LONDON" if lon else ("NY" if ny else "FUERA")}

def _cooldown_ok(par):
    return (time.time()-_cooldown_ts.get(par,0)) >= cfg.COOLDOWN_VELAS*60

def registrar_senal_ts(par):
    _cooldown_ts[par] = time.time()


# ── Análisis principal ────────────────────────────────────────

def analizar_par(par: str):
    try:
        if not _cooldown_ok(par): return None

        candles = exchange.get_candles(par, cfg.TIMEFRAME, cfg.CANDLES_LIMIT)
        if len(candles) < 60:
            log.debug(f"[SKIP] {par} solo {len(candles)} velas")
            return None

        cl  = [c["close"]  for c in candles]
        hi  = [c["high"]   for c in candles]
        lo  = [c["low"]    for c in candles]
        vol = [c["volume"] for c in candles]
        precio = cl[-1]
        if precio <= 0: return None

        # ── EMAs ──────────────────────────────────────
        ema8_s  = _ema_series(cl, 8)
        ema21_s = _ema_series(cl, 21)
        ema48_s = _ema_series(cl, 48)
        if not ema8_s or not ema21_s or not ema48_s: return None

        ema8  = ema8_s[-1]
        ema21 = ema21_s[-1]
        ema48 = ema48_s[-1]

        # ── ATR series alineada con ema21 ─────────────
        atr_s = _atr_series(hi, lo, cl, 14)
        if len(atr_s) < 3: return None
        atr_val = atr_s[-1]
        if atr_val <= 0: return None

        # Alinear series para oscilador
        # ema21_s empieza en índice 21, atr_s empieza en índice 15
        # Usamos los últimos min(len) elementos
        n = min(len(ema21_s), len(atr_s))
        ema21_aligned = ema21_s[-n:]
        atr_aligned   = atr_s[-n:]
        cl_aligned    = cl[-n:]

        osc_s = _oscillator(cl_aligned, ema21_aligned, atr_aligned, smooth=3)
        if len(osc_s) < 2: return None

        osc_now  = osc_s[-1]
        osc_prev = osc_s[-2]

        # ── Cruce del oscilador ───────────────────────
        osc_cross_up   = osc_prev < 0 and osc_now >= 0
        osc_cross_down = osc_prev > 0 and osc_now <= 0

        # ── Volume Stack ──────────────────────────────
        c = candles[-1]
        h = c["high"]; l = c["low"]; cl_ = c["close"]; v = c["volume"]
        rng = max(h - l, 1e-12)
        buy_vol  = v * (cl_ - l) / rng
        sell_vol = v * (h - cl_) / rng
        buyers_dominant  = buy_vol  > sell_vol
        sellers_dominant = sell_vol > buy_vol

        # ── Squeeze ───────────────────────────────────
        stdev_val = _stdev(cl, 21)
        bb_upper  = ema21 + 2.0 * stdev_val
        kc_upper  = ema21 + 2.0 * atr_val
        squeezing = bb_upper < kc_upper

        # ── Ribbon ────────────────────────────────────
        bull_ribbon = ema8 > ema21
        bear_ribbon = ema8 < ema21

        kz = en_killzone()

        # LOG DIAGNÓSTICO (visible en Railway)
        log.info(
            f"[SATY] {par:14s} "
            f"e8{'>'if bull_ribbon else '<'}e21 "
            f"p{'>'if precio>ema48 else '<'}e48 "
            f"osc={osc_now:+.1f}(prev={osc_prev:+.1f}) "
            f"xU={osc_cross_up} xD={osc_cross_down} "
            f"buyD={buyers_dominant} sqz={squeezing}"
        )

        # ── SEÑAL LONG ────────────────────────────────
        long_entry = (
            precio > ema48
            and bull_ribbon
            and osc_cross_up
            and buyers_dominant
            and not squeezing
        )

        # ── SEÑAL SHORT ───────────────────────────────
        short_entry = (
            precio < ema48
            and bear_ribbon
            and osc_cross_down
            and sellers_dominant
            and not squeezing
        )

        if not long_entry and not short_entry: return None

        lado = "LONG" if long_entry else "SHORT"
        if lado == "SHORT" and cfg.SOLO_LONG: return None

        # ── SL / TP dinámicos ATR ─────────────────────
        tp_mult = float(cfg.TP_DIST_MULT)   # reutilizamos TP_DIST_MULT como multiplicador
        sl_mult = float(cfg.SL_ATR_MULT)

        if lado == "LONG":
            tp = precio + atr_val * tp_mult
            sl = precio - atr_val * sl_mult
        else:
            tp = precio - atr_val * tp_mult
            sl = precio + atr_val * sl_mult

        tp1  = precio + atr_val * (tp_mult * 0.5) if lado=="LONG" else precio - atr_val * (tp_mult * 0.5)
        dist = abs(precio - sl)
        if dist <= 0: return None
        rr   = abs(tp - precio) / dist
        if rr < 1.2: return None

        # ── Score ─────────────────────────────────────
        avg_vol = sum(vol[-20:-1])/19 if len(vol)>=20 else vol[-1]
        rvol    = vol[-1]/avg_vol if avg_vol>0 else 1.0
        score   = 5
        if rvol >= 1.5:  score += 1
        if rvol >= 2.5:  score += 1
        if kz["in_kz"]:  score += 1
        if squeezing is False and osc_cross_up: score += 1  # explosión post-squeeze

        tipo    = "SATY_LONG" if lado=="LONG" else "SATY_SHORT"
        motivos = [tipo, f"RV{rvol:.1f}", f"OSC{osc_now:+.1f}"]
        if kz["in_kz"]: motivos.append(f"KZ_{kz['nombre']}")

        registrar_senal_ts(par)
        log.info(
            f"[SEÑAL] {lado:5s} {par:15s} {tipo} "
            f"RV={rvol:.1f} OSC={osc_now:+.1f} sqz={squeezing} "
            f"sc={score} SL={sl:.6f} TP={tp:.6f} RR={rr:.2f} KZ={kz['nombre']}"
        )

        return {
            "par":par,"lado":lado,"precio":precio,
            "sl":round(sl,8),"tp":round(tp,8),
            "tp1":round(tp1,8),"tp2":round(tp,8),
            "atr":round(atr_val,8),"dist_sl":round(dist,8),
            "score":score,"rsi":50.0,"rr":round(rr,2),
            "motivos":motivos,"kz":kz["nombre"],
            "tipo":tipo,"capa":1,"conf":70.0,"power_bal":65.0,
            "rvol":rvol,"atr_pct":0.0,
            "abv_vwap":precio>ema48,"st_flip":False,
            "st_bull":bull_ribbon,"st_bear":bear_ribbon,
            "net_whale":0.0,"spoof_count":0,"ice_count":0,
            "htf":"NEUTRAL","htf_4h":"NEUTRAL",
            "purga_nivel":tipo,"purga_peso":score,"vol_ratio":rvol,
            "bsl_h1":0.0,"ssl_h1":0.0,"bsl_h4":0.0,
            "ssl_h4":0.0,"bsl_d":0.0,"ssl_d":0.0,
            "ema_r":round(ema8,8),"ema_l":round(ema21,8),
            "vwap":round(ema48,8),"sobre_vwap":precio>ema48,
            "fvg_top":0,"fvg_bottom":0,"fvg_rellenado":True,
            "ob_bull":False,"ob_bear":False,
            "ob_fvg_bull":False,"ob_fvg_bear":False,"ob_mitigado":True,
            "bos_bull":lado=="LONG","bos_bear":lado=="SHORT",
            "choch_bull":False,"choch_bear":False,
            "sweep_bull":False,"sweep_bear":False,
            "patron":tipo,"vela_conf":True,
            "premium":False,"discount":False,
            "displacement":not squeezing,"macd_hist":round(osc_now,2),
            "asia_valido":True,"adx":25.0,"inducement":False,
            "liq_bull":buyers_dominant,"liq_bear":sellers_dominant,
            "liq_z_up":rvol,"liq_z_dn":rvol,
            "liq_plot_trnd":1 if lado=="LONG" else -1,
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
                if r: senales.append(r)
            except Exception as e:
                log.error(f"thread: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
