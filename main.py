"""
Sniper Bot V48 — TEST COMPLETO DE API AL ARRANCAR
Si la orden de test falla → muestra el error exacto en Telegram
Si pasa → arranca el bot normal
"""
import asyncio, hashlib, hmac, logging, os, time, urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import httpx, numpy as np

os.makedirs("logs", exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log")])
log = logging.getLogger("SniperBot")

BINGX_API_KEY    = os.environ["BINGX_API_KEY"]
BINGX_API_SECRET = os.environ["BINGX_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TIMEFRAME        = os.getenv("TIMEFRAME",            "15m")
TF_HIGH          = os.getenv("TIMEFRAME_HIGH",       "1h")
LEVERAGE         = int(os.getenv("LEVERAGE",         "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT",   "1.0"))
MAX_POS_USDT     = float(os.getenv("MAX_POS_USDT",   "25"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N",       "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT",   "30000000"))
SCORE_ENTRY      = int(os.getenv("SCORE_ENTRY",      "50"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN","5")) * 60
MAX_POSITIONS    = int(os.getenv("MAX_POSITIONS",    "2"))
BLACKOUT_START   = int(os.getenv("BLACKOUT_START_UTC","0"))
BLACKOUT_END     = int(os.getenv("BLACKOUT_END_UTC",  "2"))
RR_RATIO         = float(os.getenv("RR_RATIO",       "2.0"))
ATR_SL_MULT      = float(os.getenv("ATR_SL_MULT",   "1.0"))
EMA_FAST         = int(os.getenv("EMA_FAST",         "7"))
EMA_SLOW         = int(os.getenv("EMA_SLOW",         "17"))
BASE_URL         = "https://open-api.bingx.com"

WHITELIST = {
    "BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
    "DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","UNI-USDT","ATOM-USDT","LTC-USDT","BCH-USDT",
    "NEAR-USDT","ARB-USDT","OP-USDT","INJ-USDT","AAVE-USDT",
    "SUI-USDT","APT-USDT","FIL-USDT","ENA-USDT","WIF-USDT",
    "PEPE-USDT","SEI-USDT","TIA-USDT","WLD-USDT","FET-USDT",
}
USE_WHITELIST = os.getenv("USE_WHITELIST","true").lower() == "true"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════════
class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=20)

    def _qs(self, params: dict) -> str:
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        qs  = urllib.parse.urlencode(sorted(p.items()))
        sig = hmac.new(BINGX_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _h(self):
        return {"X-BX-APIKEY": BINGX_API_KEY}

    async def _get(self, path, params=None) -> dict:
        url = BASE_URL + path + "?" + self._qs(params or {})
        r = await self.client.get(url, headers=self._h())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def _post(self, path, params: dict) -> dict:
        url = BASE_URL + path + "?" + self._qs(params)
        log.info(f"POST {path} → {list(params.keys())}")
        r = await self.client.post(url, headers=self._h())
        r.raise_for_status()
        d = r.json()
        log.info(f"  code={d.get('code')} msg={d.get('msg','ok')[:80]}")
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def raw_post(self, path, params: dict) -> dict:
        """POST sin lanzar excepción — retorna el dict completo."""
        url = BASE_URL + path + "?" + self._qs(params)
        r = await self.client.post(url, headers=self._h())
        r.raise_for_status()
        return r.json()

    async def get_klines(self, symbol, interval, limit=200) -> list:
        d = await self._get("/openApi/swap/v3/quote/klines",
                            {"symbol":symbol,"interval":interval,"limit":limit})
        out = []
        for c in d.get("data",[]):
            try:
                if isinstance(c, list):
                    out.append({"time":int(c[0]),"open":float(c[1]),"high":float(c[2]),
                                "low":float(c[3]),"close":float(c[4]),"volume":float(c[5])})
                else:
                    out.append({"time":int(c.get("time",c.get("t",0))),
                                "open":float(c.get("open",c.get("o",0))),
                                "high":float(c.get("high",c.get("h",0))),
                                "low":float(c.get("low",c.get("l",0))),
                                "close":float(c.get("close",c.get("c",0))),
                                "volume":float(c.get("volume",c.get("v",c.get("quoteVolume",0))))})
            except: continue
        return out

    async def get_tickers(self) -> list:
        d = await self._get("/openApi/swap/v2/quote/ticker")
        out = []
        for t in d.get("data",[]):
            sym = t.get("symbol","")
            if not sym.endswith("-USDT"): continue
            if USE_WHITELIST and sym not in WHITELIST: continue
            price = 0.0
            for f in ("lastPrice","last","price","close","markPrice"):
                v = t.get(f)
                if v:
                    try:
                        fv=float(v)
                        if fv>0: price=fv; break
                    except: pass
            change = 0.0
            for f in ("priceChangePercent","change","changePercent"):
                v = t.get(f)
                if v is not None:
                    try: change=float(v); break
                    except: pass
            if price>0:
                out.append({"symbol":sym,"price":price,"change_24h":change})
        return out

    async def get_funding_rate(self, symbol) -> float:
        try:
            d = await self._get("/openApi/swap/v2/quote/premiumIndex",{"symbol":symbol})
            data=d.get("data",{})
            if isinstance(data,list): data=data[0] if data else {}
            return float(data.get("lastFundingRate",data.get("fundingRate",0)))
        except: return 0.0

    async def get_balance(self) -> float:
        try:
            d = await self._get("/openApi/swap/v2/user/balance")
            raw = d.get("data",d)
            log.info(f"[BAL]: {str(raw)[:300]}")
            def find(obj,keys,depth=0):
                if depth>5: return None
                if isinstance(obj,dict):
                    for k in keys:
                        v=obj.get(k)
                        if v is not None:
                            try:
                                f=float(str(v).replace(",",""))
                                if f>=0: return f
                            except: pass
                    for k,v in obj.items():
                        if isinstance(v,(dict,list)):
                            r=find(v,keys,depth+1)
                            if r is not None: return r
                if isinstance(obj,list):
                    for item in obj:
                        r=find(item,keys,depth+1)
                        if r is not None: return r
                return None
            bal=find(raw,["availableMargin","available","free","equity",
                          "availableBalance","crossAvailableBalance","walletBalance"])
            if bal is not None and bal>=0:
                log.info(f"Balance: {bal:.4f} USDT"); return bal
            return 0.0
        except Exception as e:
            log.error(f"get_balance: {e}"); return 0.0

    def _parse_pos(self,data)->list:
        if data is None: return []
        items=data if isinstance(data,list) else [data] if isinstance(data,dict) else []
        return [p for p in items if isinstance(p,dict) and
                abs(float(p.get("positionAmt",p.get("positionAmount",p.get("size",0)))))>0]

    async def get_position(self,symbol)->Optional[dict]:
        try:
            d=await self._get("/openApi/swap/v2/user/positions",{"symbol":symbol})
            ps=self._parse_pos(d.get("data")); return ps[0] if ps else None
        except Exception as e:
            log.warning(f"get_position {symbol}: {e}"); return None

    async def get_all_positions(self)->list:
        try:
            d=await self._get("/openApi/swap/v2/user/positions")
            return self._parse_pos(d.get("data"))
        except Exception as e:
            log.warning(f"get_all_positions: {e}"); return []

    async def set_leverage(self,symbol,leverage)->bool:
        try:
            await self._post("/openApi/swap/v2/trade/leverage",
                             {"symbol":symbol,"side":"LONG","leverage":str(leverage)})
            return True
        except Exception as e:
            log.warning(f"Leverage {symbol}: {e}"); return False

    async def market_order(self,symbol,side,qty,reduce_only=False)->dict:
        p={"symbol":symbol,"side":side,"positionSide":"BOTH",
           "type":"MARKET","quantity":str(qty)}
        if reduce_only: p["reduceOnly"]="true"
        return await self._post("/openApi/swap/v2/trade/order",p)

    async def close_position(self,symbol,pos)->dict:
        amt=float(pos.get("positionAmt",pos.get("size",0)))
        return await self.market_order(symbol,"SELL" if amt>0 else "BUY",abs(amt),reduce_only=True)

    async def close_half(self,symbol,pos)->dict:
        amt=float(pos.get("positionAmt",pos.get("size",0)))
        half=round(abs(amt)/2,3)
        if half<0.001: return {}
        return await self.market_order(symbol,"SELL" if amt>0 else "BUY",half,reduce_only=True)


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
async def tg(text:str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id":TELEGRAM_CHAT_ID,"text":text[:4000],"parse_mode":"Markdown"})
    except Exception as e: log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# API TEST — corre al arrancar, prueba una orden real mínima
# ══════════════════════════════════════════════════════════════════
async def api_test(exchange: BingXClient) -> bool:
    """
    Prueba todos los endpoints necesarios y reporta por Telegram.
    Si la orden falla → muestra el error exacto de BingX.
    """
    lines = ["🔬 *TEST API COMPLETO*\n━━━━━━━━━━━━━━━━━━━━\n"]

    # 1. Balance
    try:
        d = await exchange._get("/openApi/swap/v2/user/balance")
        raw = d.get("data",{})
        lines.append(f"✅ *Balance raw:*\n`{str(raw)[:300]}`\n")
        bal = await exchange.get_balance()
        lines.append(f"✅ *Balance parseado:* `{bal:.4f} USDT`")
    except Exception as e:
        lines.append(f"❌ *Balance:* `{e}`")
        await tg("\n".join(lines)); return False

    # 2. Posiciones
    try:
        positions = await exchange.get_all_positions()
        n = len(positions)
        icon = "🔴" if n >= MAX_POSITIONS else "✅"
        lines.append(f"\n{icon} *Posiciones abiertas:* `{n}/{MAX_POSITIONS}`")
        total_unr = 0.0
        for pos in positions:
            sym=pos.get("symbol","?"); amt=float(pos.get("positionAmt",0))
            avg=float(pos.get("avgPrice",pos.get("entryPrice",0)))
            cur=float(pos.get("markPrice",pos.get("currentPrice",0)))
            unr=float(pos.get("unrealizedProfit",pos.get("unRealizedProfit",0)))
            total_unr+=unr
            d2="LONG" if amt>0 else "SHORT"
            pnl=((cur-avg)/avg*100) if amt>0 else ((avg-cur)/avg*100)
            e2="🟢" if unr>=0 else "🔴"
            lines.append(f"  {e2} `{sym}` {d2} {pnl:+.1f}% ({unr:+.2f}$)")
        if positions:
            lines.append(f"  *Total PnL: `{total_unr:+.2f} USDT`*")
        if n >= MAX_POSITIONS:
            lines.append(f"\n⛔ *MAX_POSITIONS={MAX_POSITIONS} alcanzado*")
            lines.append("  → El bot no puede abrir más trades")
            lines.append("  → Sube MAX_POSITIONS o cierra posiciones")
    except Exception as e:
        lines.append(f"❌ *Posiciones:* `{e}`")

    # 3. Test leverage (POST real)
    lev_ok = False
    try:
        d = await exchange.raw_post("/openApi/swap/v2/trade/leverage",
                                    {"symbol":"BTC-USDT","side":"LONG","leverage":"3"})
        if d.get("code",0) == 0:
            lines.append(f"\n✅ *Leverage POST:* OK")
            lev_ok = True
        else:
            lines.append(f"\n❌ *Leverage POST:* code={d.get('code')} `{d.get('msg','')}`")
    except Exception as e:
        lines.append(f"\n❌ *Leverage POST:* `{e}`")

    # 4. Test orden mínima real (solo si leverage funciona)
    if lev_ok:
        try:
            # Obtener precio BTC
            pk = await exchange.get_klines("BTC-USDT","1m",3)
            btc_price = pk[-1]["close"] if pk else 0
            if btc_price > 0:
                # Orden mínima: 0.001 BTC (≈$79 a precio actual)
                # Usamos qty mínima absoluta
                qty = 0.001
                lines.append(f"\n🧪 *Test orden BUY BTC qty={qty}...*")
                d = await exchange.raw_post("/openApi/swap/v2/trade/order", {
                    "symbol":       "BTC-USDT",
                    "side":         "BUY",
                    "positionSide": "BOTH",
                    "type":         "MARKET",
                    "quantity":     str(qty),
                })
                code = d.get("code", -1)
                msg  = d.get("msg","")
                lines.append(f"  code=`{code}` msg=`{msg[:100]}`")
                lines.append(f"  data=`{str(d.get('data',''))[:150]}`")

                if code == 0:
                    lines.append("✅ *ORDEN EJECUTADA* — el bot puede operar")
                    # Cerrar inmediatamente
                    await asyncio.sleep(2)
                    d2 = await exchange.raw_post("/openApi/swap/v2/trade/order", {
                        "symbol":       "BTC-USDT",
                        "side":         "SELL",
                        "positionSide": "BOTH",
                        "type":         "MARKET",
                        "quantity":     str(qty),
                        "reduceOnly":   "true",
                    })
                    lines.append(f"  Cierre test: code=`{d2.get('code')}` `{d2.get('msg','')[:50]}`")
                else:
                    lines.append(f"❌ *ORDEN FALLIDA* — este es el error real")
                    # Desglose del problema
                    if code == 100001:
                        lines.append("  → *100001:* Firma inválida O api key sin permiso Trade")
                        lines.append("  → Ve a BingX → API Management → activa *Futures Trading*")
                        lines.append("  → Asegura que NO hay IP whitelist")
                    elif code == 80012:
                        lines.append("  → *80012:* Cantidad mínima incorrecta")
                    elif code == 80001:
                        lines.append("  → *80001:* Balance insuficiente")
                    elif code == 101204:
                        lines.append("  → *101204:* Cuenta en modo Hedge — necesita positionSide=LONG/SHORT")
                        lines.append("  → Desactiva Hedge Mode en BingX o contacta soporte")
            else:
                lines.append("❌ No se pudo obtener precio BTC")
        except Exception as e:
            lines.append(f"\n❌ *Test orden:* `{e}`")
    else:
        lines.append("\n⚠️ Leverage falló — skipping test de orden")
        lines.append("  → La API key no tiene permiso *Futures Trading*")
        lines.append("  → O hay whitelist de IP en la API key")

    # 5. Config
    lines.append(f"\n⚙️ Score:`{SCORE_ENTRY}` MaxPos:`{MAX_POSITIONS}` VolMin:`${MIN_VOL_USDT/1e6:.0f}M`")
    await tg("\n".join(lines))
    return lev_ok


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════
def ema(v,p):
    v=np.asarray(v,float);k=2/(p+1);r=np.zeros(len(v));r[0]=v[0]
    for i in range(1,len(v)): r[i]=v[i]*k+r[i-1]*(1-k)
    return r

def hma(v,p):
    return ema(2*ema(v,max(p//2,1))-ema(v,p),max(int(np.sqrt(p)),1))

def sma(v,p):
    return np.convolve(np.asarray(v,float),np.ones(p)/p,mode="same")

def stoch_s(src,p):
    src=np.asarray(src,float);r=np.zeros(len(src))
    for i in range(p-1,len(src)):
        w=src[i-p+1:i+1];lo,hi=w.min(),w.max()
        r[i]=(src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_ind(c): return ema(stoch_s(ema(c,23)-ema(c,50),10),3)

def calc_atr(h,l,c,p=14):
    h,l,c=map(lambda x:np.asarray(x,float),[h,l,c])
    tr=np.maximum(h-l,np.maximum(np.abs(h-np.roll(c,1)),np.abs(l-np.roll(c,1))))
    r=np.zeros(len(tr));r[0]=tr[0]
    for i in range(1,len(tr)): r[i]=(r[i-1]*(p-1)+tr[i])/p
    return r

def calc_adx(h,l,c,p=14):
    h,l,c=map(lambda x:np.asarray(x,float),[h,l,c])
    ph,pl,pc=np.roll(h,1),np.roll(l,1),np.roll(c,1)
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    dmp=np.where((h-ph)>(pl-l),np.maximum(h-ph,0),0).astype(float)
    dmm=np.where((pl-l)>(h-ph),np.maximum(pl-l,0),0).astype(float)
    aw=np.zeros(len(tr));dp=np.zeros(len(tr));dm=np.zeros(len(tr))
    if p<len(tr):
        aw[p]=np.sum(tr[1:p+1]);dp[p]=np.sum(dmp[1:p+1]);dm[p]=np.sum(dmm[1:p+1])
    for i in range(p+1,len(tr)):
        aw[i]=aw[i-1]-aw[i-1]/p+tr[i]
        dp[i]=dp[i-1]-dp[i-1]/p+dmp[i]
        dm[i]=dm[i-1]-dm[i-1]/p+dmm[i]
    dip=100*dp/(aw+1e-10);dim=100*dm/(aw+1e-10)
    dx=100*np.abs(dip-dim)/(dip+dim+1e-10)
    adx=np.zeros(len(dx))
    if 2*p<len(dx): adx[2*p]=np.mean(dx[p:2*p+1])
    for i in range(2*p+1,len(dx)): adx[i]=(adx[i-1]*(p-1)+dx[i])/p
    return adx

def pivot_hi(h,n):
    h=np.asarray(h,float);r=np.full(len(h),np.nan)
    for i in range(n,len(h)-n):
        if h[i]==h[i-n:i+n+1].max(): r[i]=h[i]
    return r

def pivot_lo(l,n):
    l=np.asarray(l,float);r=np.full(len(l),np.nan)
    for i in range(n,len(l)-n):
        if l[i]==l[i-n:i+n+1].min(): r[i]=l[i]
    return r

def vol24h(candles):
    last=candles[-96:] if len(candles)>=96 else candles
    return sum(c["close"]*c["volume"] for c in last)

def btc_trend(btc_c)->str:
    if len(btc_c)<50: return "NEUTRAL"
    closes=np.array([c["close"] for c in btc_c],float)
    e7=ema(closes,7);e17=ema(closes,17);h50=hma(closes,50)
    if closes[-1]>h50[-1] and e7[-1]>e17[-1]: return "BULL"
    if closes[-1]<h50[-1] and e7[-1]<e17[-1]: return "BEAR"
    return "NEUTRAL"


# ══════════════════════════════════════════════════════════════════
# STRATEGY
# ══════════════════════════════════════════════════════════════════
@dataclass
class CoinResult:
    symbol:str; direction:str; score:int
    entry:float; sl:float; tp:float
    vol_usd:float; atr_val:float
    signals:list=field(default_factory=list)
    change_24h:float=0.0; funding:float=0.0

def analyze(ticker,candles,candles_1h,funding,market_trend="NEUTRAL")->Optional[CoinResult]:
    sym=ticker["symbol"]
    if len(candles)<60: return None
    closes=np.array([c["close"]  for c in candles],float)
    highs =np.array([c["high"]   for c in candles],float)
    lows  =np.array([c["low"]    for c in candles],float)
    vols  =np.array([c["volume"] for c in candles],float)
    if closes[-1]<=0: return None
    vusd=vol24h(candles)
    if vusd<MIN_VOL_USDT: return None
    e7=ema(closes,EMA_FAST);e17=ema(closes,EMA_SLOW)
    h50=hma(closes,50);stc=stc_ind(closes)
    adx=calc_adx(highs,lows,closes);atr=calc_atr(highs,lows,closes)
    vsma=sma(vols,20);rvol=vols[-1]/(vsma[-1]+1e-10)
    htf_bull=htf_bear=False
    if len(candles_1h)>=20:
        c1=np.array([c["close"] for c in candles_1h],float)
        e7_1=ema(c1,EMA_FAST);e17_1=ema(c1,EMA_SLOW);h50_1=hma(c1,50)
        htf_bull=bool(c1[-1]>h50_1[-1] and e7_1[-1]>e17_1[-1])
        htf_bear=bool(c1[-1]<h50_1[-1] and e7_1[-1]<e17_1[-1])
    i=-1; cn=float(closes[i]); atr_now=float(atr[-1]); adx_now=float(adx[-1])
    hull_bull=cn>float(h50[i]); hull_bear=not hull_bull
    cross_up=e7[i-1]<e17[i-1] and e7[i]>e17[i]
    cross_dn=e7[i-1]>e17[i-1] and e7[i]<e17[i]
    stc_up=stc[i]>stc[i-1]; stc_dn=stc[i]<stc[i-1]
    inst_vol=rvol>1.3; adx_ok=adx_now<40
    score=0;signals=[];direction="NEUTRAL"
    if hull_bull:   direction="LONG";  score+=20;signals.append("Hull🟢")
    elif hull_bear: direction="SHORT"; score+=20;signals.append("Hull🔴")
    else: return None
    if direction=="LONG" and market_trend=="BEAR":  score-=15;signals.append("BTC🔴")
    if direction=="SHORT" and market_trend=="BULL": score-=15;signals.append("BTC🟢")
    if direction=="LONG" and cross_up:   score+=25;signals.append("Cruz🔥")
    elif direction=="SHORT" and cross_dn:score+=25;signals.append("Cruz🔥")
    elif (direction=="LONG" and e7[i]>e17[i]) or (direction=="SHORT" and e7[i]<e17[i]):
        score+=12;signals.append("EMA✅")
    else: score-=10;signals.append("EMA❌")
    if (direction=="LONG" and htf_bull) or (direction=="SHORT" and htf_bear):
        score+=15;signals.append("1H✅")
    elif (direction=="LONG" and htf_bear) or (direction=="SHORT" and htf_bull):
        score-=12;signals.append("1H❌")
    if inst_vol: score+=12;signals.append(f"Vol{rvol:.1f}x✅")
    else:        signals.append(f"Vol{rvol:.1f}x")
    if (direction=="LONG" and stc_up) or (direction=="SHORT" and stc_dn):
        score+=10;signals.append("STC✅")
    if adx_ok: score+=8;signals.append(f"ADX{adx_now:.0f}✅")
    else:      score-=5;signals.append(f"ADX{adx_now:.0f}⚠️")
    if abs(funding)>0.0001:
        if (direction=="LONG" and funding<-0.005) or (direction=="SHORT" and funding>0.03):
            score+=5;signals.append("FR✅")
        elif (direction=="LONG" and funding>0.03) or (direction=="SHORT" and funding<-0.005):
            score-=5;signals.append("FR⚠️")
    score=min(max(score,0),100)
    log.info(f"{sym}: score={score} dir={direction} mkt={market_trend}")
    sl_d=atr_now*ATR_SL_MULT
    if direction=="LONG": sl=cn-sl_d;tp=cn+sl_d*RR_RATIO
    else:                 sl=cn+sl_d;tp=cn-sl_d*RR_RATIO
    return CoinResult(symbol=sym,direction=direction,score=score,
                      entry=cn,sl=sl,tp=tp,vol_usd=vusd,atr_val=atr_now,
                      signals=signals,change_24h=ticker.get("change_24h",0),funding=funding)

def calc_qty(balance,entry,sl)->float:
    dist=abs(entry-sl)
    if dist<1e-10: return 0.0
    qty=min((balance*MAX_RISK_PCT/100)/dist, MAX_POS_USDT/max(entry,1e-10))
    if   entry>=1000: qty=round(qty,4)
    elif entry>=100:  qty=round(qty,3)
    elif entry>=10:   qty=round(qty,2)
    elif entry>=1:    qty=round(qty,1)
    else:             qty=round(qty,0)
    return max(qty,0.001)

def is_blackout():
    return BLACKOUT_START<=datetime.now(timezone.utc).hour<BLACKOUT_END

exchange    =BingXClient()
watchlist:  list[CoinResult]=[]
last_dir:   dict[str,str]={}
trade_sl:   dict[str,float]={}
trade_tp:   dict[str,float]={}
half_closed:set[str]=set()

async def open_trade(cr:CoinResult)->bool:
    sym=cr.symbol
    try:
        if last_dir.get(sym)==cr.direction: return False
        pos=await exchange.get_position(sym)
        if pos: return False
        balance=await exchange.get_balance()
        if balance<5:
            await tg(f"⚠️ Balance bajo: `{balance:.2f} USDT`"); return False
        qty=calc_qty(balance,cr.entry,cr.sl)
        if qty<=0: return False
        await exchange.set_leverage(sym,LEVERAGE)
        side="BUY" if cr.direction=="LONG" else "SELL"
        await exchange.market_order(sym,side,qty)
        risk_usd=abs(cr.entry-cr.sl)*qty; pos_val=cr.entry*qty
        emoji="🟢" if cr.direction=="LONG" else "🔴"
        await tg(
            f"{emoji} *{cr.direction} — V48*\n"
            f"Par:`{sym}` Score:`{cr.score}/100`\n"
            f"Entry:`{cr.entry:.6f}` SL:`{cr.sl:.6f}` TP:`{cr.tp:.6f}`\n"
            f"Qty:`{qty}` Valor:`≈{pos_val:.2f}$` Riesgo:`≈{risk_usd:.2f}$`\n"
            f"{' '.join(cr.signals[:6])}"
        )
        last_dir[sym]=cr.direction; trade_sl[sym]=cr.sl; trade_tp[sym]=cr.tp
        log.info(f"✅ ABIERTO {cr.direction} {sym} qty={qty}"); return True
    except Exception as e:
        log.error(f"open_trade {sym}: {e}",exc_info=True)
        await tg(f"❌ *Error orden* `{sym}`:\n`{str(e)[:300]}`"); return False

async def manage_positions():
    try:
        positions=await exchange.get_all_positions()
        if not positions: return
        for pos in positions:
            sym=pos.get("symbol","")
            amt=float(pos.get("positionAmt",pos.get("size",0)))
            avg=float(pos.get("avgPrice",   pos.get("entryPrice",0)))
            cur=float(pos.get("markPrice",  pos.get("currentPrice",0)))
            unr=float(pos.get("unrealizedProfit",pos.get("unRealizedProfit",0)))
            if avg<=0 or cur<=0: continue
            is_long=amt>0
            pnl_pct=((cur-avg)/avg*100) if is_long else ((avg-cur)/avg*100)
            direction="LONG" if is_long else "SHORT"
            sl=trade_sl.get(sym,0.0); tp=trade_tp.get(sym,0.0)
            log.info(f"POS {sym} {direction} pnl={pnl_pct:+.2f}% unreal={unr:+.2f}")
            if sl>0 and ((is_long and cur<=sl) or (not is_long and cur>=sl)):
                try:
                    await exchange.close_position(sym,pos)
                    await tg(f"🛑 *SL* `{sym}` {direction} {pnl_pct:+.2f}% ({unr:+.2f}$)")
                    trade_sl.pop(sym,None);trade_tp.pop(sym,None)
                    last_dir[sym]="NONE";half_closed.discard(sym); continue
                except Exception as e: log.error(f"SL {sym}: {e}")
            if tp>0 and ((is_long and cur>=tp) or (not is_long and cur<=tp)):
                try:
                    await exchange.close_position(sym,pos)
                    await tg(f"🎯 *TP* `{sym}` {direction} +{pnl_pct:.2f}% (+{unr:.2f}$) 🎉")
                    trade_sl.pop(sym,None);trade_tp.pop(sym,None)
                    last_dir[sym]="NONE";half_closed.discard(sym); continue
                except Exception as e: log.error(f"TP {sym}: {e}")
            if sym not in half_closed and pnl_pct>=0.5:
                try:
                    await exchange.close_half(sym,pos)
                    half_closed.add(sym)
                    await tg(f"🔒 *50%* `{sym}` +{pnl_pct:.2f}% (+{unr:.2f}$)")
                except Exception as e: log.error(f"half {sym}: {e}")
    except Exception as e: log.error(f"manage_positions: {e}")

async def scanner_loop():
    global watchlist
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(SCAN_INTERVAL); continue
            log.info("🔍 Escaneando V48...")
            tickers=await exchange.get_tickers()
            if not tickers:
                await asyncio.sleep(SCAN_INTERVAL); continue
            try:
                btc_c=await exchange.get_klines("BTC-USDT","1h",100)
                market=btc_trend(btc_c)
            except: market="NEUTRAL"
            syms=[t["symbol"] for t in tickers]
            r15,r1h,rfr=await asyncio.gather(
                asyncio.gather(*[exchange.get_klines(s,TIMEFRAME,200) for s in syms],return_exceptions=True),
                asyncio.gather(*[exchange.get_klines(s,TF_HIGH,  100) for s in syms],return_exceptions=True),
                asyncio.gather(*[exchange.get_funding_rate(s)         for s in syms],return_exceptions=True),
            )
            results=[]
            for t,c15,c1h,fr in zip(tickers,r15,r1h,rfr):
                if isinstance(c15,Exception): continue
                cr=analyze(t,c15,
                    c1h if not isinstance(c1h,Exception) else [],
                    fr  if not isinstance(fr, Exception) else 0.0,market)
                if cr: results.append(cr)
            results.sort(key=lambda x:x.score,reverse=True)
            top=results[:SCAN_TOP_N]
            wl=[r for r in top if r.score>=SCORE_ENTRY and r.direction!="NEUTRAL"]
            watchlist=wl if wl else top[:3]
            log.info(f"Watchlist: {[(r.symbol,r.score,r.direction) for r in watchlist]}")
            mkt_e="🐂" if market=="BULL" else "🐻" if market=="BEAR" else "➡️"
            lines=[f"🔍 *V48 — {len(top)} coins* BTC:{mkt_e}{market}\n"]
            for n,r in enumerate(top,1):
                e="🟢" if r.direction=="LONG" else "🔴"
                bar="█"*(r.score//10)+"░"*(10-r.score//10)
                tag=" ⚡*ENTRA*" if r.score>=SCORE_ENTRY else ""
                lines.append(f"*#{n}* {e} `{r.symbol}` `{r.score}/100`{tag}\n"
                             f"`{bar}` Vol:`${r.vol_usd/1e6:.0f}M`\n"
                             f"{' '.join(r.signals[:5])}\n")
            lines.append(f"\n🎯 *Watchlist ({len(watchlist)}):*")
            for r in watchlist:
                e="🟢" if r.direction=="LONG" else "🔴"
                lines.append(f"  {e} `{r.symbol}` `{r.score}` → {r.direction}")
            await tg("\n".join(lines)[:3900])
        except Exception as e:
            log.error(f"Scanner: {e}",exc_info=True)
            await tg(f"⚠️ *Error:* `{str(e)[:200]}`")
        await asyncio.sleep(SCAN_INTERVAL)

async def trading_loop():
    await asyncio.sleep(60)
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(60); continue
            await manage_positions()
            open_pos=await exchange.get_all_positions()
            n_open=len(open_pos)
            open_syms={p.get("symbol","") for p in open_pos}
            log.info(f"Trading: {n_open}/{MAX_POSITIONS} | wl={len(watchlist)}")
            if n_open<MAX_POSITIONS and watchlist:
                for cr in list(watchlist):
                    if n_open>=MAX_POSITIONS: break
                    if cr.symbol in open_syms: continue
                    if cr.score<SCORE_ENTRY: continue
                    opened=await open_trade(cr)
                    if opened: n_open+=1;open_syms.add(cr.symbol)
                    await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Trading loop: {e}",exc_info=True)
        await asyncio.sleep(60)

async def main():
    log.info("🚀 Sniper Bot V48 — Arrancando con test de API...")
    await tg(f"🔄 *V48 arrancando* — ejecutando test API...")

    # Test completo al arrancar
    ok = await api_test(exchange)

    if not ok:
        await tg(
            "⛔ *API no puede ejecutar órdenes*\n\n"
            "*Solución más probable:*\n"
            "1. BingX → API Management\n"
            "2. Edita tu API key\n"
            "3. Activa ✅ *Futures Trading*\n"
            "4. En IP Restrictions → selecciona *No restrictions*\n"
            "5. Guarda y copia el nuevo Secret\n"
            "6. Railway → Variables → actualiza BINGX_API_KEY y BINGX_API_SECRET\n"
            "7. Redeploy"
        )
        # Esperar hasta que funcione, reintentar cada 5 min
        while True:
            await asyncio.sleep(300)
            ok2 = await api_test(exchange)
            if ok2:
                await tg("✅ API funciona — arrancando bot!")
                break
    else:
        await tg("✅ *API OK — bot arrancando en 60s*")

    await asyncio.gather(scanner_loop(), trading_loop())

if __name__ == "__main__":
    asyncio.run(main())
