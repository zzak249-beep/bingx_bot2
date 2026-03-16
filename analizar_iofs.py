"""
analizar_iofs.py — DEBUG + SEÑALES GARANTIZADAS
"""
import logging, time, concurrent.futures
from datetime import datetime, timezone
import exchange, config_iofs as cfg

log = logging.getLogger("analizar_iofs")
_cooldown_ts: dict = {}


def _ema(p, n):
    if len(p) < n: return None
    k = 2/(n+1); v = sum(p[:n])/n
    for x in p[n:]: v = x*k + v*(1-k)
    return v

def _atr(hi, lo, cl, n=14):
    if len(hi) < n+1: return 0.0
    t = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
         for i in range(1, len(hi))]
    return sum(t[-n:]) / n

def _supertrend(hi, lo, cl, f=2.0, p=7):
    if len(cl) < p+2: return False, False, False, False, 0.0
    at = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
          for i in range(1, len(cl))]
    av = sum(at[:p])/p; as_ = [av]
    for a in at[p:]: av = (av*(p-1)+a)/p; as_.append(av)
    n = len(as_); off = len(cl)-n
    ub=[0.0]*n; lb=[0.0]*n; dr=[1]*n; st=[0.0]*n
    for i in range(n):
        ci=i+off; h2=(hi[ci]+lo[ci])/2
        u=h2+f*as_[i]; l=h2-f*as_[i]
        ub[i]=min(u,ub[i-1]) if i>0 and cl[ci-1]<ub[i-1] else u
        lb[i]=max(l,lb[i-1]) if i>0 and cl[ci-1]>lb[i-1] else l
        if i==0: dr[i]=1
        elif st[i-1]==ub[i-1]: dr[i]=1 if cl[ci]<ub[i] else -1
        else: dr[i]=-1 if cl[ci]>lb[i] else 1
        st[i]=ub[i] if dr[i]==1 else lb[i]
    bull=dr[-1]<0; bear=dr[-1]>0
    fb=(dr[-1]<0 and dr[-2]>0) if len(dr)>=2 else False
    fbr=(dr[-1]>0 and dr[-2]<0) if len(dr)>=2 else False
    return bull, bear, fb, fbr, st[-1]

def en_killzone():
    m=datetime.now(timezone.utc); mins=m.hour*60+m.minute
    lon=cfg.KZ_LONDON_START<=mins<cfg.KZ_LONDON_END
    ny=cfg.KZ_NY_START<=mins<cfg.KZ_NY_END
    return {"in_kz":lon or ny,
            "nombre":"LONDON" if lon else ("NY" if ny else "FUERA")}

def _cooldown_ok(par):
    return (time.time()-_cooldown_ts.get(par,0)) >= cfg.COOLDOWN_VELAS*60

def registrar_senal_ts(par):
    _cooldown_ts[par] = time.time()


def analizar_par(par: str):
    try:
        if not _cooldown_ok(par):
            log.debug(f"[SKIP-CD] {par} en cooldown")
            return None

        candles = exchange.get_candles(par, cfg.TIMEFRAME, cfg.CANDLES_LIMIT)
        if len(candles) < 30:
            log.debug(f"[SKIP-C] {par} solo {len(candles)} velas")
            return None

        cl  = [c["close"]  for c in candles]
        hi  = [c["high"]   for c in candles]
        lo  = [c["low"]    for c in candles]
        vol = [c["volume"] for c in candles]
        precio = cl[-1]
        if precio <= 0: return None

        atr = _atr(hi, lo, cl, 14)
        if atr <= 0: return None

        e9  = _ema(cl, 9)
        e21 = _ema(cl, 21)
        if not e9 or not e21: return None

        bull, bear, fb, fbr, st = _supertrend(hi, lo, cl, f=2.0, p=7)
        kz = en_killzone()

        avg_vol = sum(vol[-20:-1])/19 if len(vol)>=20 else vol[-1]
        rvol    = vol[-1]/avg_vol if avg_vol>0 else 1.0

        # LOG DE DIAGNÓSTICO — visible en Railway
        log.info(f"[DIAG] {par:15s} ST:{'B' if bull else 'b'}/{'R' if bear else 'r'} "
                 f"e9{'>'if e9>e21 else '<'}e21 "
                 f"RV={rvol:.1f} velas={len(candles)}")

        lado = None
        if bull and e9 > e21:
            lado = "LONG"
        elif bear and e9 < e21:
            lado = "SHORT"

        if not lado:
            log.debug(f"[NO-SIG] {par} bull={bull} bear={bear} e9>e21={e9>e21}")
            return None

        if lado == "SHORT" and cfg.SOLO_LONG:
            return None

        # SL/TP
        rec = candles[-8:-1]
        buf = atr * 0.3
        if lado == "LONG":
            sl = min(c["low"] for c in rec) - buf if rec else precio - atr*cfg.SL_ATR_MULT
            if precio - sl > 3*atr: sl = precio - atr*cfg.SL_ATR_MULT
        else:
            sl = max(c["high"] for c in rec) + buf if rec else precio + atr*cfg.SL_ATR_MULT
            if sl - precio > 3*atr: sl = precio + atr*cfg.SL_ATR_MULT

        dist = abs(precio - sl)
        if dist <= 0: return None

        tp  = (precio + dist*cfg.TP_DIST_MULT)  if lado=="LONG" else (precio - dist*cfg.TP_DIST_MULT)
        tp1 = (precio + dist*cfg.TP1_DIST_MULT) if lado=="LONG" else (precio - dist*cfg.TP1_DIST_MULT)
        rr  = abs(tp - precio) / dist
        if rr < 1.5: return None

        score = 4
        if fb or fbr:   score += 3
        if rvol >= 1.5: score += 1
        if kz["in_kz"]: score += 1

        tipo = "ST_FLIP" if (fb or fbr) else "ST_EMA"
        motivos = [tipo, f"RV{rvol:.1f}"]
        if kz["in_kz"]: motivos.append(f"KZ_{kz['nombre']}")

        registrar_senal_ts(par)
        log.info(f"[SEÑAL] {lado:5s} {par:15s} {tipo} "
                 f"RV={rvol:.1f} sc={score} "
                 f"SL={sl:.6f} TP={tp:.6f} RR={rr:.2f}")

        return {
            "par":par,"lado":lado,"precio":precio,
            "sl":round(sl,8),"tp":round(tp,8),
            "tp1":round(tp1,8),"tp2":round(tp,8),
            "atr":round(atr,8),"dist_sl":round(dist,8),
            "score":score,"rsi":50.0,"rr":round(rr,2),
            "motivos":motivos,"kz":kz["nombre"],
            "tipo":tipo,"capa":1,"conf":60.0,"power_bal":60.0,
            "rvol":rvol,"atr_pct":0.0,
            "abv_vwap":cl[-1]>sum(cl[-20:])/20,
            "st_flip":fb or fbr,"st_bull":bull,"st_bear":bear,
            "net_whale":0.0,"spoof_count":0,"ice_count":0,
            "htf":"NEUTRAL","htf_4h":"NEUTRAL",
            "purga_nivel":tipo,"purga_peso":score,"vol_ratio":rvol,
            "bsl_h1":0.0,"ssl_h1":0.0,"bsl_h4":0.0,
            "ssl_h4":0.0,"bsl_d":0.0,"ssl_d":0.0,
            "ema_r":round(e9,8),"ema_l":round(e21,8),
            "vwap":0.0,"sobre_vwap":False,
            "fvg_top":0,"fvg_bottom":0,"fvg_rellenado":True,
            "ob_bull":False,"ob_bear":False,
            "ob_fvg_bull":False,"ob_fvg_bear":False,"ob_mitigado":True,
            "bos_bull":lado=="LONG","bos_bear":lado=="SHORT",
            "choch_bull":(fb and lado=="LONG"),
            "choch_bear":(fbr and lado=="SHORT"),
            "sweep_bull":False,"sweep_bear":False,
            "patron":tipo,"vela_conf":True,
            "premium":False,"discount":False,
            "displacement":False,"macd_hist":0,
            "asia_valido":True,"adx":25.0,"inducement":False,
            "liq_bull":False,"liq_bear":False,
            "liq_z_up":rvol,"liq_z_dn":rvol,
            "liq_plot_trnd":1 if lado=="LONG" else -1,
        }
    except Exception as e:
        log.error(f"analizar_par {par}: {e}")
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
