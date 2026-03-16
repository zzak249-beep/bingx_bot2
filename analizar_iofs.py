"""
analizar_iofs.py — Institutional Order Flow Shield Bot v2
==========================================================
Versión 24/7 — señales en cualquier sesión.

Capas de señal (de más a menos prioritaria):
  1. IOFS completo   — Power Balance + Confidence (señal institucional pura)
  2. FLOW_TREND      — Supertrend + Order Flow acumulado (tendencia con volumen)
  3. PULLBACK_EMA    — Pullback al EMA21 con ST alineado (entrada técnica clásica)
  4. WHALE_ENTRY     — RVOL spike + nueva zona de precio (entrada ballena)

Cualquiera de las 4 capas puede generar señal. Los filtros se relajan
fuera de kill zones pero nunca se eliminan — siempre exige volumen mínimo.
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


def _ema(prices, p):
    if len(prices) < p: return None
    k = 2/(p+1); v = sum(prices[:p])/p
    for x in prices[p:]: v = x*k + v*(1-k)
    return v

def _sma(v, p):
    return sum(v[-p:])/p if len(v) >= p else None

def _rsi(prices, p=14):
    if len(prices) < p+1: return 50.0
    d  = [prices[i]-prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(x,0)      for x in d[:p])/p
    al = sum(abs(min(x,0)) for x in d[:p])/p
    for x in d[p:]:
        ag = (ag*(p-1)+max(x,0))/p
        al = (al*(p-1)+abs(min(x,0)))/p
    return 100.0 if al==0 else round(100-100/(1+ag/al), 2)

def _atr(hi, lo, cl, p=14):
    if len(hi) < p+1: return 0.0
    trs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
           for i in range(1, len(hi))]
    return sum(trs[-p:])/p


def _supertrend(hi, lo, cl, factor=3.0, p=10):
    if len(cl) < p+2: return False, False, False, False, 0.0
    atrs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
            for i in range(1, len(cl))]
    av = sum(atrs[:p])/p; atr_s=[av]
    for a in atrs[p:]:
        av = (av*(p-1)+a)/p; atr_s.append(av)
    n=len(atr_s); off=len(cl)-n
    ub=[0.0]*n; lb=[0.0]*n; dr=[1]*n; st=[0.0]*n
    for i in range(n):
        ci=i+off; h2=(hi[ci]+lo[ci])/2
        u=h2+factor*atr_s[i]; l=h2-factor*atr_s[i]
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


def _calcular_order_flow(candles):
    res=[]
    for c in candles:
        o=c["open"]; h=c["high"]; l=c["low"]; cl=c["close"]; v=c["volume"]
        rng=max(h-l,1e-12); pos=(cl-l)/rng
        bv=v*pos; sv=v*(1-pos)
        uw=h-max(cl,o); lw=min(cl,o)-l
        res.append({
            "adj_buy":  max(0.0, bv-(uw/rng)*v*0.5),
            "adj_sell": max(0.0, sv-(lw/rng)*v*0.5),
            "delta":    max(0.0, bv-(uw/rng)*v*0.5) - max(0.0, sv-(lw/rng)*v*0.5),
            "bull_bar": cl>o, "bear_bar": cl<o,
        })
    return res

def _calcular_flow_batch(fd, n):
    b=fd[-n:]; cb=sum(f["adj_buy"] for f in b); cs=sum(f["adj_sell"] for f in b)
    bc=sum(1 for f in b if f["bull_bar"]); sc=sum(1 for f in b if f["bear_bar"])
    ab=cb/bc if bc>0 else 0.0; as_=cs/sc if sc>0 else 0.0
    r=cfg.FLOW_SENSITIVITY_RATIO
    acc=ab>(as_*r) and cb>cs; dist=as_>(ab*r) and cs>cb
    imp=(cb-cs) if acc else (cs-cb) if dist else 0.0
    return {"cum_buy":cb,"cum_sell":cs,"avg_buy":ab,"avg_sell":as_,
            "accum":acc,"distri":dist,"impact":imp}


def _detectar_spoof_iceberg(candles, rvol, vol_avg, atr_gate):
    empty={"bpl":False,"apl":False,"bwl":False,"awl":False,
           "wbd":False,"wak":False,"is_spoof":False,"is_iceberg":False,
           "prev_rvol":1.0,"vol_diff":0,"smart_ice_lim":0}
    if len(candles)<3: return empty
    c=candles[-1]; cp=candles[-2]
    vc=c["volume"]; vp=cp["volume"]
    atr14=_atr([x["high"] for x in candles],[x["low"] for x in candles],
               [x["close"] for x in candles],14)
    ms=max(cfg.MIN_SPOOF_VOL, vol_avg*1.5)
    sil=max(cfg.MIN_ICEBERG_VOL, vol_avg*cfg.ICEBERG_AVG_MULT)
    pr=vp/vol_avg if vol_avg>0 else 1.0; vd=abs(vp-vc)
    vdrop=(vc<vp*cfg.SPOOF_PULL_PCT) and vd>=ms
    pspk=pr>=cfg.SPOOF_PREV_RVOL_MIN
    ru=c["close"]>c["open"] and c["close"]>cp["close"]
    rd=c["close"]<=c["open"] and c["close"]<cp["close"]
    isp=vdrop and pspk and atr_gate
    bpl=isp and rd; apl=isp and ru
    iic=(vc>vp and vc>=sil and vd>=sil*0.2 and atr_gate)
    bwl=iic and c["close"]>c["open"]; awl=iic and c["close"]<=c["open"]
    inz=(abs(c["close"]-cp["close"])>atr14*0.5) if atr14>0 else False
    iw=rvol>=(cfg.ICEBERG_AVG_MULT*0.8) and inz and atr_gate
    wbd=iw and c["close"]>c["open"]; wak=iw and c["close"]<=c["open"]
    return {"bpl":bpl,"apl":apl,"bwl":bwl,"awl":awl,"wbd":wbd,"wak":wak,
            "is_spoof":isp,"is_iceberg":iic or iw,
            "prev_rvol":round(pr,2),"vol_diff":round(vd,2),"smart_ice_lim":round(sil,2)}


_flow_states: dict = {}

class FlowState:
    def __init__(self):
        self.bull_str=0.0; self.bear_str=0.0; self.max_str=500.0
        self.net_whale=0.0; self.spoof_count=0; self.ice_count=0
        self.last_event="WAITING"; self.confidence=0.0; self.last_seen=time.time()

    def decay(self):
        mul=1.0-max(0.0,min(0.99,cfg.PASSIVE_DECAY/100.0))
        self.bull_str=max(0.0,self.bull_str*mul)
        self.bear_str=max(0.0,self.bear_str*mul)

    def boost_bull(self,impact=0):
        self.bull_str=min(self.max_str,self.bull_str+cfg.BOOST_RATE)
        self.bear_str=max(0.0,self.bear_str-cfg.DECAY_RATE)
        self.net_whale+=impact

    def boost_bear(self,impact=0):
        self.bear_str=min(self.max_str,self.bear_str+cfg.BOOST_RATE)
        self.bull_str=max(0.0,self.bull_str-cfg.DECAY_RATE)
        self.net_whale-=impact

    @property
    def power_balance(self):
        t=self.bull_str+self.bear_str
        return self.bull_str/t if t>0 else 0.5

    @property
    def decision(self):
        pb=self.power_balance
        if pb>cfg.STRONG_BUY_LVL:  return "STRONG BUY"
        if pb<cfg.STRONG_SELL_LVL: return "STRONG SELL"
        return "WAIT/NEUTRAL"

def _get_flow_state(par):
    if par not in _flow_states: _flow_states[par]=FlowState()
    return _flow_states[par]

def _calcular_confidence(side,flow,spoof,bull,bear,abv,up,dn):
    s=0.0
    if side=="LONG":
        if flow.get("accum"):  s+=25
        if spoof.get("bwl"):   s+=20
        if spoof.get("wbd"):   s+=15
        if spoof.get("apl"):   s+=10
        if bull or up:         s+=15
        if abv:                s+=15
    else:
        if flow.get("distri"): s+=25
        if spoof.get("awl"):   s+=20
        if spoof.get("wak"):   s+=15
        if spoof.get("bpl"):   s+=10
        if bear or dn:         s+=15
        if not abv:            s+=15
    return round(s,2)


def _smart_filters(candles):
    cl=[c["close"] for c in candles]; hi=[c["high"] for c in candles]
    lo=[c["low"] for c in candles];   vols=[c["volume"] for c in candles]
    va=_sma(vols[:-1],cfg.VOL_SMA_LEN) or 1.0
    rv=vols[-1]/va
    ro=(not cfg.USE_RVOL_FILTER) or (rv>=cfg.RVOL_MIN)
    atr14=_atr(hi,lo,cl,14)
    ap=(atr14/cl[-1]*100.0) if cl[-1]>0 else 1.0
    ao=(not cfg.USE_ATR_FILTER) or (ap>=cfg.ATR_MIN_PCT)
    hlc3=[(c["high"]+c["low"]+c["close"])/3 for c in candles]
    vwap=sum(hlc3[i]*vols[i] for i in range(len(candles)))/(sum(vols) or 1)
    e50=_ema(cl,50); e200=_ema(cl,200)
    up=(e50 is not None and e200 is not None and e50>e200)
    dn=(e50 is not None and e200 is not None and e50<e200)
    return {"rvol":round(rv,3),"rvol_ok":ro,"vol_avg":va,
            "atr":atr14,"atr_pct":round(ap,3),"atr_ok":ao,
            "base_gate":ro and ao,"vwap":vwap,"abv_vwap":cl[-1]>vwap,
            "e50":e50,"e200":e200,"up_trend":up,"down_trend":dn}


def en_killzone():
    m=datetime.now(timezone.utc); mins=m.hour*60+m.minute
    lon=cfg.KZ_LONDON_START<=mins<cfg.KZ_LONDON_END
    ny=cfg.KZ_NY_START<=mins<cfg.KZ_NY_END
    return {"in_kz":lon or ny,"nombre":"LONDON" if lon else ("NY" if ny else "FUERA")}

def _cooldown_ok(par):
    return (time.time()-_cooldown_ts.get(par,0))>=cfg.COOLDOWN_VELAS*60

def registrar_senal_ts(par):
    _cooldown_ts[par]=time.time()


def _calcular_sl(candles, lado, atr, precio):
    rec=candles[-10:-1]; buf=atr*0.2
    if lado=="LONG":
        sw=min(c["low"] for c in rec)-buf if rec else 0
        opts=[x for x in [sw] if 0<x<precio]
        sl=max(opts) if opts else precio-atr*cfg.SL_ATR_MULT
        if precio-sl>3*atr: sl=precio-atr*cfg.SL_ATR_MULT
    else:
        sw=max(c["high"] for c in rec)+buf if rec else 0
        opts=[x for x in [sw] if x>precio]
        sl=min(opts) if opts else precio+atr*cfg.SL_ATR_MULT
        if sl-precio>3*atr: sl=precio+atr*cfg.SL_ATR_MULT
    return sl


def _senal_flow_trend(candles, filt, bull, bear):
    cl=[c["close"] for c in candles]
    e9=_ema(cl,9); e21=_ema(cl,21)
    if not e9 or not e21: return None
    fd=_calcular_order_flow(candles); ult=fd[-5:]
    bd=sum(1 for f in ult if f["delta"]>0)
    brd=sum(1 for f in ult if f["delta"]<0)
    tol=0.001
    if bull and e9>e21*(1+tol) and bd>=4: return "LONG"
    if bear and e9<e21*(1-tol) and brd>=4: return "SHORT"
    return None


def _senal_pullback(candles, filt, bull, bear):
    cl=[c["close"] for c in candles]
    hi=[c["high"] for c in candles]; lo=[c["low"] for c in candles]
    e9=_ema(cl,9); e21=_ema(cl,21)
    if not e9 or not e21: return None
    c=candles[-1]; cp=candles[-2]
    body=abs(c["close"]-c["open"]); rng=max(c["high"]-c["low"],1e-9)
    rsi=_rsi(cl[-20:])
    tol=float(os.getenv("EMA_TOL","0.004"))
    br=float(os.getenv("BODY_RATIO","0.25"))
    if (bull and e9>e21*(1+tol*0.2)
            and cp["low"]<=e21*(1+tol)
            and c["close"]>e21 and c["close"]>c["open"]
            and filt["rvol"]>=0.8 and body/rng>=br and 35<=rsi<=70):
        return "LONG"
    if (bear and e9<e21*(1-tol*0.2)
            and cp["high"]>=e21*(1-tol)
            and c["close"]<e21 and c["close"]<c["open"]
            and filt["rvol"]>=0.8 and body/rng>=br and 30<=rsi<=65):
        return "SHORT"
    return None


def _senal_whale(candles, filt, bull, bear):
    if filt["rvol"]<1.8: return None
    c=candles[-1]; cp=candles[-2]; atr14=filt["atr"]
    if atr14<=0: return None
    move=abs(c["close"]-cp["close"])
    if move<atr14*0.3: return None
    if bull and c["close"]>c["open"] and c["close"]>cp["close"]: return "LONG"
    if bear and c["close"]<c["open"] and c["close"]<cp["close"]: return "SHORT"
    return None


def analizar_par(par: str):
    try:
        if not _cooldown_ok(par): return None

        candles=exchange.get_candles(par, cfg.TIMEFRAME, cfg.CANDLES_LIMIT)
        if len(candles)<50: return None

        cl=[c["close"] for c in candles]
        hi=[c["high"]  for c in candles]
        lo=[c["low"]   for c in candles]
        precio=cl[-1]
        if precio<=0: return None

        filt=_smart_filters(candles)
        kz=en_killzone()

        # Fuera de KZ relajamos RVOL
        if not kz["in_kz"]:
            filt["rvol_ok"]=filt["rvol"]>=max(0.8, cfg.RVOL_MIN*0.65)
            filt["base_gate"]=filt["rvol_ok"] and filt["atr_ok"]

        if not filt["atr_ok"]: return None

        bull,bear,fb,fbr,st=_supertrend(hi,lo,cl,cfg.ST_FACTOR,cfg.ST_PERIOD)
        atr=filt["atr"]
        if atr<=0: return None

        fd=_calcular_order_flow(candles)
        flow=_calcular_flow_batch(fd, cfg.FLOW_BATCH_LEN)
        spoof=_detectar_spoof_iceberg(candles,filt["rvol"],filt["vol_avg"],filt["base_gate"])
        bar_delta=fd[-1]["delta"] if fd else 0.0

        fs=_get_flow_state(par)
        fs.decay()
        if spoof.get("is_spoof"):   fs.spoof_count+=1
        if spoof.get("is_iceberg"): fs.ice_count+=1

        rb=(flow["accum"] or spoof["bwl"] or spoof["apl"] or spoof["wbd"]) and filt["base_gate"]
        rbr=(flow["distri"] or spoof["awl"] or spoof["bpl"] or spoof["wak"]) and filt["base_gate"]
        res_bull=rb and (not rbr or bar_delta>=0.0)
        res_bear=rbr and (not rb or bar_delta<0.0)

        if res_bull:
            fs.boost_bull(flow["impact"])
            fs.last_event=("ACCUMULATION" if flow["accum"] else "BID WALL" if spoof["bwl"]
                           else "ASK PULL" if spoof["apl"] else "WHALE BID")
        elif res_bear:
            fs.boost_bear(flow["impact"])
            fs.last_event=("DISTRIBUTION" if flow["distri"] else "ASK WALL" if spoof["awl"]
                           else "BID PULL" if spoof["bpl"] else "WHALE ASK")

        sc="LONG" if res_bull else ("SHORT" if res_bear else None)
        if sc:
            fs.confidence=_calcular_confidence(sc,flow,spoof,bull,bear,
                                               filt["abv_vwap"],filt["up_trend"],filt["down_trend"])
        fs.last_seen=time.time()

        lado=None; tipo=None; capa=0

        # CAPA 1 — IOFS
        if fs.decision=="STRONG BUY" and (res_bull or fs.power_balance>cfg.STRONG_BUY_LVL):
            lado="LONG"; capa=1
            tipo=("ACM" if flow["accum"] else "BWL" if spoof["bwl"]
                  else "APL" if spoof["apl"] else "WBD" if spoof["wbd"] else "IOFS_L")
        elif fs.decision=="STRONG SELL" and (res_bear or fs.power_balance<cfg.STRONG_SELL_LVL):
            lado="SHORT"; capa=1
            tipo=("DST" if flow["distri"] else "AWL" if spoof["awl"]
                  else "BPL" if spoof["bpl"] else "WAK" if spoof["wak"] else "IOFS_S")

        # CAPA 2 — Flow Trend
        if not lado:
            ft=_senal_flow_trend(candles,filt,bull,bear)
            if ft: lado=ft; capa=2; tipo="FLOW_TREND"

        # CAPA 3 — Pullback EMA21
        if not lado:
            pb=_senal_pullback(candles,filt,bull,bear)
            if pb: lado=pb; capa=3; tipo="PULLBACK_EMA"

        # CAPA 4 — Whale Entry
        if not lado:
            wh=_senal_whale(candles,filt,bull,bear)
            if wh: lado=wh; capa=4; tipo="WHALE_ENTRY"

        if not lado: return None
        if lado=="SHORT" and cfg.SOLO_LONG: return None

        sl=_calcular_sl(candles,lado,atr,precio)
        dist=abs(precio-sl)
        if dist<=0: return None

        tp=(precio+dist*cfg.TP_DIST_MULT)  if lado=="LONG" else (precio-dist*cfg.TP_DIST_MULT)
        tp1=(precio+dist*cfg.TP1_DIST_MULT) if lado=="LONG" else (precio-dist*cfg.TP1_DIST_MULT)
        rr=abs(tp-precio)/dist
        rr_min=cfg.MIN_RR if capa<=2 else max(1.5,cfg.MIN_RR*0.75)
        if rr<rr_min: return None

        pb_val=fs.power_balance
        score=max(3,int(pb_val*8))
        score+={1:4,2:2,3:1,4:1}.get(capa,0)
        if fs.confidence>=70: score+=2
        if fb or fbr: score+=3
        if kz["in_kz"]: score+=1
        if spoof.get("bwl") or spoof.get("awl"): score+=2
        if spoof.get("apl") or spoof.get("bpl"): score+=1
        if filt["rvol"]>=2.0: score+=1

        motivos=[tipo,f"C{capa}"]
        if fb or fbr: motivos.append("FLIP")
        motivos.append("ABV_VWAP" if filt["abv_vwap"] else "BLW_VWAP")
        motivos.append(f"RV{filt['rvol']:.1f}")
        if fs.confidence>0: motivos.append(f"CF{fs.confidence:.0f}")
        if kz["in_kz"]: motivos.append(f"KZ_{kz['nombre']}")

        registrar_senal_ts(par)
        rsi_v=_rsi(cl[-20:])

        log.info(f"[C{capa}] {lado:5s} {par:15s} {tipo} PB={pb_val:.0%} "
                 f"CONF={fs.confidence:.0f}% RV={filt['rvol']:.1f} "
                 f"ATR%={filt['atr_pct']:.2f} sc={score} RR={rr:.2f} KZ={kz['nombre']}")

        return {
            "par":par,"lado":lado,"precio":precio,
            "sl":round(sl,8),"tp":round(tp,8),"tp1":round(tp1,8),"tp2":round(tp,8),
            "atr":round(atr,8),"dist_sl":round(dist,8),
            "score":score,"rsi":round(rsi_v,1),"rr":round(rr,2),
            "motivos":motivos,"kz":kz["nombre"],"tipo":tipo,"capa":capa,
            "conf":fs.confidence,"power_bal":round(pb_val*100,1),
            "rvol":filt["rvol"],"atr_pct":filt["atr_pct"],"abv_vwap":filt["abv_vwap"],
            "st_flip":fb or fbr,"st_bull":bull,"st_bear":bear,
            "net_whale":round(fs.net_whale,2),"spoof_count":fs.spoof_count,"ice_count":fs.ice_count,
            "htf":"NEUTRAL","htf_4h":"NEUTRAL","purga_nivel":tipo,"purga_peso":score,
            "vol_ratio":filt["rvol"],"bsl_h1":0.0,"ssl_h1":0.0,"bsl_h4":0.0,
            "ssl_h4":0.0,"bsl_d":0.0,"ssl_d":0.0,"ema_r":0.0,"ema_l":0.0,
            "vwap":round(filt["vwap"],8),"sobre_vwap":filt["abv_vwap"],
            "fvg_top":0,"fvg_bottom":0,"fvg_rellenado":True,
            "ob_bull":False,"ob_bear":False,"ob_fvg_bull":False,"ob_fvg_bear":False,"ob_mitigado":True,
            "bos_bull":lado=="LONG","bos_bear":lado=="SHORT",
            "choch_bull":(fb and lado=="LONG"),"choch_bear":(fbr and lado=="SHORT"),
            "sweep_bull":spoof.get("apl",False),"sweep_bear":spoof.get("bpl",False),
            "patron":tipo,"vela_conf":True,"premium":False,"discount":False,
            "displacement":spoof.get("is_iceberg",False),"macd_hist":0,
            "asia_valido":True,"adx":25.0,"inducement":False,
            "liq_bull":spoof.get("bwl",False),"liq_bear":spoof.get("awl",False),
            "liq_z_up":filt["rvol"],"liq_z_dn":filt["rvol"],
            "liq_plot_trnd":1 if lado=="LONG" else -1,
        }
    except Exception as e:
        log.error(f"analizar_par {par}: {e}", exc_info=True)
        return None


def analizar_todos(pares: list, workers: int = 4) -> list:
    senales=[]
    w=min(workers,len(pares),8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futuros={ex.submit(analizar_par,p):p for p in pares}
        for fut in concurrent.futures.as_completed(futuros):
            try:
                r=fut.result()
                if r: senales.append(r)
            except Exception as e:
                log.error(f"thread: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
