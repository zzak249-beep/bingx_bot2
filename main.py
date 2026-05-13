"""
Sniper Bot V45 — DEBUG MODE
============================
Esta versión tiene un test completo al arrancar:
1. Prueba get_balance → muestra raw exacto
2. Prueba place_order con qty mínima en MODO DEMO (sin ejecutar)
3. Muestra exactamente por qué no abre trades
4. Si todo OK → arranca el bot normal
"""

import asyncio, hashlib, hmac, logging, os, time, urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import httpx, numpy as np

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log")],
)
log = logging.getLogger("SniperBot")

BINGX_API_KEY    = os.environ["BINGX_API_KEY"]
BINGX_API_SECRET = os.environ["BINGX_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TIMEFRAME        = os.getenv("TIMEFRAME",            "15m")
TF_HIGH          = os.getenv("TIMEFRAME_HIGH",       "1h")
LEVERAGE         = int(os.getenv("LEVERAGE",         "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT",   "1.0"))
MAX_POS_USDT     = float(os.getenv("MAX_POS_USDT",   "50"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N",       "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT",   "10000000"))
SCORE_ENTRY      = int(os.getenv("SCORE_ENTRY",      "55"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN","5")) * 60
MAX_POSITIONS    = int(os.getenv("MAX_POSITIONS",    "3"))
BLACKOUT_START   = int(os.getenv("BLACKOUT_START_UTC","0"))
BLACKOUT_END     = int(os.getenv("BLACKOUT_END_UTC",  "2"))
SLOPE_MIN        = float(os.getenv("SLOPE_MIN",      "30.0"))
POC_LOOKBACK     = int(os.getenv("POC_LOOKBACK",     "50"))
ADX_MAX          = float(os.getenv("ADX_MAX",        "35.0"))
RVOL_MIN         = float(os.getenv("RVOL_MIN",       "1.5"))
RR_RATIO         = float(os.getenv("RR_RATIO",       "2.5"))
ATR_SL_MULT      = float(os.getenv("ATR_SL_MULT",   "1.2"))
EMA_FAST         = int(os.getenv("EMA_FAST",         "7"))
EMA_SLOW         = int(os.getenv("EMA_SLOW",         "17"))
BASE_URL         = "https://open-api.bingx.com"

BLACKLIST = {
    "USDC-USDT","BUSD-USDT","DAI-USDT","TUSD-USDT","FRAX-USDT",
    "NCCOGOLD2USD-USDT","PAXG-USDT","XAUT-USDT","WBTC-USDT",
    "STETH-USDT","WETH-USDT","CBETH-USDT","ZEC-USDT","USDP-USDT",
}
WHITELIST = {
    "BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
    "DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","UNI-USDT","ATOM-USDT","LTC-USDT","BCH-USDT",
    "NEAR-USDT","APT-USDT","ARB-USDT","OP-USDT","INJ-USDT",
    "SUI-USDT","TIA-USDT","WLD-USDT","AAVE-USDT","ONDO-USDT",
    "ENA-USDT","PEPE-USDT","WIF-USDT","SEI-USDT","JUP-USDT",
    "FIL-USDT","RENDER-USDT","FET-USDT","SHIB-USDT","BONK-USDT",
    "NOT-USDT","FLOKI-USDT","SAND-USDT","MANA-USDT","IMX-USDT",
    "BLUR-USDT","GALA-USDT","AXS-USDT","ALGO-USDT",
}
USE_WHITELIST = os.getenv("USE_WHITELIST","true").lower() == "true"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════════
class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)

    def _sign(self, params: dict) -> str:
        q = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(BINGX_API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

    def _headers(self):
        return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}

    async def _get(self, path, params=None) -> dict:
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.get(path, params=p, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def _post(self, path, params: dict) -> dict:
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.post(path, params=p, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def get_raw_balance(self) -> dict:
        """Retorna el raw completo para debug."""
        return await self._get("/openApi/swap/v2/user/balance")

    async def get_balance(self) -> float:
        try:
            d = await self._get("/openApi/swap/v2/user/balance")
            raw = d.get("data", d)
            log.info(f"[BALANCE RAW]: {str(raw)[:500]}")

            def find_num(obj, keys, depth=0):
                if depth > 6: return None
                if isinstance(obj, dict):
                    for k in keys:
                        v = obj.get(k)
                        if v is not None:
                            try:
                                f = float(str(v).replace(",",""))
                                if f >= 0: return f
                            except: pass
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            r = find_num(v, keys, depth+1)
                            if r is not None: return r
                if isinstance(obj, list):
                    for item in obj:
                        r = find_num(item, keys, depth+1)
                        if r is not None: return r
                return None

            fields = [
                "availableMargin","available","free","equity",
                "availableBalance","crossAvailableBalance",
                "walletBalance","balance","crossWalletBalance",
            ]
            bal = find_num(raw, fields)
            if bal is not None and bal >= 0:
                log.info(f"Balance OK: {bal:.4f} USDT")
                return bal
            log.error(f"Balance NO encontrado. Raw={str(raw)[:400]}")
            return 0.0
        except Exception as e:
            log.error(f"get_balance: {e}", exc_info=True)
            return 0.0

    async def get_klines(self, symbol, interval, limit=200) -> list:
        d = await self._get("/openApi/swap/v3/quote/klines",
                            {"symbol":symbol,"interval":interval,"limit":limit})
        out = []
        for c in d["data"]:
            try:
                if isinstance(c, list):
                    out.append({"time":int(c[0]),"open":float(c[1]),"high":float(c[2]),
                                "low":float(c[3]),"close":float(c[4]),"volume":float(c[5])})
                else:
                    out.append({"time":  int(c.get("time",   c.get("t",0))),
                                "open":  float(c.get("open",  c.get("o",0))),
                                "high":  float(c.get("high",  c.get("h",0))),
                                "low":   float(c.get("low",   c.get("l",0))),
                                "close": float(c.get("close", c.get("c",0))),
                                "volume":float(c.get("volume",c.get("v",c.get("quoteVolume",0))))})
            except: continue
        return out

    async def get_tickers(self) -> list:
        d = await self._get("/openApi/swap/v2/quote/ticker")
        out = []
        for t in d.get("data", []):
            sym = t.get("symbol","")
            if not sym.endswith("-USDT"): continue
            if sym in BLACKLIST: continue
            if USE_WHITELIST and sym not in WHITELIST: continue
            price = 0.0
            for f in ("lastPrice","last","price","close","markPrice"):
                v = t.get(f)
                if v:
                    try:
                        fv = float(v)
                        if fv > 0: price = fv; break
                    except: pass
            change = 0.0
            for f in ("priceChangePercent","change","changePercent"):
                v = t.get(f)
                if v is not None:
                    try: change = float(v); break
                    except: pass
            if price > 0:
                out.append({"symbol":sym,"price":price,"change_24h":change})
        return out

    async def get_funding_rate(self, symbol) -> float:
        try:
            d = await self._get("/openApi/swap/v2/quote/premiumIndex",{"symbol":symbol})
            data = d.get("data",{})
            if isinstance(data,list): data = data[0] if data else {}
            return float(data.get("lastFundingRate", data.get("fundingRate",0)))
        except: return 0.0

    def _parse_pos(self, data) -> list:
        if data is None: return []
        items = data if isinstance(data, list) else \
                [data] if isinstance(data, dict) else []
        return [p for p in items
                if isinstance(p, dict)
                and abs(float(p.get("positionAmt",
                               p.get("positionAmount",
                               p.get("size", 0))))) > 0]

    async def get_position(self, symbol) -> Optional[dict]:
        try:
            d = await self._get("/openApi/swap/v2/user/positions",{"symbol":symbol})
            ps = self._parse_pos(d.get("data"))
            return ps[0] if ps else None
        except Exception as e:
            log.warning(f"get_position {symbol}: {e}")
            return None

    async def get_all_positions(self) -> list:
        try:
            d = await self._get("/openApi/swap/v2/user/positions")
            return self._parse_pos(d.get("data"))
        except Exception as e:
            log.warning(f"get_all_positions: {e}")
            return []

    async def set_leverage(self, symbol, leverage) -> bool:
        ok = True
        for side in ("LONG","SHORT"):
            try:
                await self._post("/openApi/swap/v2/trade/leverage",
                                 {"symbol":symbol,"side":side,"leverage":str(leverage)})
            except Exception as e:
                log.warning(f"Leverage {symbol} {side}: {e}")
                ok = False
        return ok

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None,
                          reduce_only=False) -> dict:
        p = {"symbol":symbol,"side":side,"positionSide":position_side,
             "type":"MARKET","quantity":str(qty)}
        if reduce_only: p["reduceOnly"] = "true"
        if stop_loss:   p["stopLoss"]   = str(round(stop_loss,   8))
        if take_profit: p["takeProfit"] = str(round(take_profit, 8))
        log.info(f"ORDER → {p}")
        r = await self._post("/openApi/swap/v2/trade/order", p)
        log.info(f"ORDER RESULT → {r}")
        return r

    async def close_position(self, symbol, pos) -> dict:
        amt = float(pos.get("positionAmt", pos.get("size",0)))
        return await self.place_order(symbol,
            "SELL" if amt>0 else "BUY",
            "LONG" if amt>0 else "SHORT",
            abs(amt), reduce_only=True)

    async def close_half(self, symbol, pos):
        amt  = float(pos.get("positionAmt", pos.get("size",0)))
        half = round(abs(amt)/2, 3)
        if half < 0.001: return
        return await self.place_order(symbol,
            "SELL" if amt>0 else "BUY",
            "LONG" if amt>0 else "SHORT",
            half, reduce_only=True)


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
async def tg(text: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id":TELEGRAM_CHAT_ID,"text":text[:4000],"parse_mode":"Markdown"}
            )
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════
def ema(v, p):
    v = np.asarray(v, float); k = 2/(p+1)
    r = np.zeros(len(v)); r[0] = v[0]
    for i in range(1, len(v)): r[i] = v[i]*k + r[i-1]*(1-k)
    return r

def hma(v, p):
    return ema(2*ema(v,max(p//2,1))-ema(v,p), max(int(np.sqrt(p)),1))

def sma(v, p):
    return np.convolve(np.asarray(v,float), np.ones(p)/p, mode="same")

def stoch_s(src, p):
    src = np.asarray(src, float); r = np.zeros(len(src))
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]; lo,hi = w.min(),w.max()
        r[i] = (src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_v45(c):
    macd = ema(c,23) - ema(c,50)
    return ema(stoch_s(macd, 10), 3)

def calc_atr(h, l, c, p=14):
    h,l,c = map(lambda x: np.asarray(x,float), [h,l,c])
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    r = np.zeros(len(tr)); r[0] = tr[0]
    for i in range(1, len(tr)): r[i] = (r[i-1]*(p-1)+tr[i])/p
    return r

def calc_vwap(h, l, c, v):
    tp = (np.asarray(h,float)+np.asarray(l,float)+np.asarray(c,float))/3
    return np.cumsum(tp*np.asarray(v,float))/(np.cumsum(np.asarray(v,float))+1e-10)

def calc_poc(closes, volumes, lookback):
    n = min(lookback, len(closes))
    v = np.asarray(volumes[-n:], float)
    return float(np.asarray(closes[-n:], float)[int(np.argmax(v))])

def calc_adx(h, l, c, p=14):
    h,l,c = map(lambda x: np.asarray(x,float), [h,l,c])
    ph,pl,pc = np.roll(h,1),np.roll(l,1),np.roll(c,1)
    tr  = np.maximum(h-l, np.maximum(np.abs(h-pc), np.abs(l-pc)))
    dmp = np.where((h-ph)>(pl-l), np.maximum(h-ph,0), 0).astype(float)
    dmm = np.where((pl-l)>(h-ph), np.maximum(pl-l,0), 0).astype(float)
    atr_w=np.zeros(len(tr)); dp_w=np.zeros(len(tr)); dm_w=np.zeros(len(tr))
    atr_w[p]=np.sum(tr[1:p+1]); dp_w[p]=np.sum(dmp[1:p+1]); dm_w[p]=np.sum(dmm[1:p+1])
    for i in range(p+1,len(tr)):
        atr_w[i]=atr_w[i-1]-atr_w[i-1]/p+tr[i]
        dp_w[i] =dp_w[i-1] -dp_w[i-1]/p +dmp[i]
        dm_w[i] =dm_w[i-1] -dm_w[i-1]/p +dmm[i]
    dip=100*dp_w/(atr_w+1e-10); dim=100*dm_w/(atr_w+1e-10)
    dx=100*np.abs(dip-dim)/(dip+dim+1e-10)
    adx=np.zeros(len(dx))
    if 2*p < len(dx): adx[2*p]=np.mean(dx[p:2*p+1])
    for i in range(2*p+1,len(dx)): adx[i]=(adx[i-1]*(p-1)+dx[i])/p
    return adx

def calc_magic_slope(closes, p=7):
    e7 = ema(closes, p)
    atr7 = calc_atr(closes, closes, closes, p)
    s = np.zeros(len(e7))
    for i in range(1, len(e7)): s[i]=((e7[i]-e7[i-1])/(atr7[i]+1e-10))*100
    return s

def calc_rvol(volumes, p=50):
    v = np.asarray(volumes, float)
    return v/(sma(v,p)+1e-10)

def pivot_hi(h, n):
    h=np.asarray(h,float); r=np.full(len(h),np.nan)
    for i in range(n,len(h)-n):
        if h[i]==h[i-n:i+n+1].max(): r[i]=h[i]
    return r

def pivot_lo(l, n):
    l=np.asarray(l,float); r=np.full(len(l),np.nan)
    for i in range(n,len(l)-n):
        if l[i]==l[i-n:i+n+1].min(): r[i]=l[i]
    return r

def vol24h(candles):
    last=candles[-96:] if len(candles)>=96 else candles
    return sum(c["close"]*c["volume"] for c in last)


# ══════════════════════════════════════════════════════════════════
# ANALYZE
# ══════════════════════════════════════════════════════════════════
@dataclass
class CoinResult:
    symbol:     str
    direction:  str
    score:      int
    entry:      float
    sl:         float
    tp:         float
    tp_half:    float
    vol_usd:    float
    atr_val:    float
    signals:    list  = field(default_factory=list)
    change_24h: float = 0.0
    funding:    float = 0.0
    slope:      float = 0.0
    adx:        float = 0.0
    rvol:       float = 0.0

def analyze(ticker, candles, candles_1h, funding) -> Optional[CoinResult]:
    sym = ticker["symbol"]
    min_len = max(80, POC_LOOKBACK+10)
    if len(candles) < min_len: return None

    closes  = np.array([c["close"]  for c in candles], float)
    highs   = np.array([c["high"]   for c in candles], float)
    lows    = np.array([c["low"]    for c in candles], float)
    volumes = np.array([c["volume"] for c in candles], float)

    if closes[-1] <= 0: return None
    vusd = vol24h(candles)
    if vusd < MIN_VOL_USDT: return None

    atr_arr   = calc_atr(highs, lows, closes)
    atr_now   = float(atr_arr[-1])
    vwap_now  = float(calc_vwap(highs, lows, closes, volumes)[-1])
    poc       = calc_poc(closes, volumes, POC_LOOKBACK)
    stc_arr   = stc_v45(closes)
    adx_arr   = calc_adx(highs, lows, closes)
    adx_now   = float(adx_arr[-1])
    slope_arr = calc_magic_slope(closes, EMA_FAST)
    slope_now = float(slope_arr[-1])
    rvol_arr  = calc_rvol(volumes, 50)
    rvol_now  = float(rvol_arr[-1])
    e_fast    = ema(closes, EMA_FAST)
    e_slow    = ema(closes, EMA_SLOW)
    h50       = hma(closes, 50)

    ph_v=pivot_hi(highs,4); pl_v=pivot_lo(lows,4)
    vph=ph_v[~np.isnan(ph_v)]; vpl=pl_v[~np.isnan(pl_v)]
    peak   = float(vph[-1]) if len(vph)>0 else float(highs[-1])
    valley = float(vpl[-1]) if len(vpl)>0 else float(lows[-1])

    htf_bull=htf_bear=False
    if len(candles_1h)>=20:
        c1=np.array([c["close"] for c in candles_1h],float)
        e7_1=ema(c1,EMA_FAST); e17_1=ema(c1,EMA_SLOW); h50_1=hma(c1,50)
        htf_bull=bool(c1[-1]>h50_1[-1] and e7_1[-1]>e17_1[-1])
        htf_bear=bool(c1[-1]<h50_1[-1] and e7_1[-1]<e17_1[-1])

    i=-1
    cn=float(closes[i]); hi_now=float(highs[i]); lo_now=float(lows[i])

    dist_poc = abs(cn-poc) > (atr_now*1.5)
    cond_vol = rvol_now > RVOL_MIN
    stc_up   = stc_arr[i] > stc_arr[i-1]
    stc_down = stc_arr[i] < stc_arr[i-1]
    adx_ok   = adx_now < ADX_MAX

    long_cond  = (lo_now<valley and cn<vwap_now and slope_now>SLOPE_MIN
                  and stc_up and adx_ok and dist_poc and cond_vol)
    short_cond = (hi_now>peak and cn>vwap_now and slope_now<-SLOPE_MIN
                  and stc_down and adx_ok and dist_poc and cond_vol)

    score=0; signals=[]; direction="NEUTRAL"

    if long_cond:
        direction="LONG"; score=85; signals=["V45🟢"]
        if htf_bull: score+=10; signals.append("1H🟢")
        if e_fast[i]>e_slow[i]: score+=5; signals.append("EMA✅")
    elif short_cond:
        direction="SHORT"; score=85; signals=["V45🔴"]
        if htf_bear: score+=10; signals.append("1H🔴")
        if e_fast[i]<e_slow[i]: score+=5; signals.append("EMA✅")
    else:
        hull_bull=cn>float(h50[-1]); hull_bear=not hull_bull
        direction="LONG" if hull_bull else "SHORT"
        if hull_bull or hull_bear:    score+=20; signals.append("Hull✅")
        if e_fast[i]>e_slow[i] and hull_bull: score+=15; signals.append("EMA✅")
        if e_fast[i]<e_slow[i] and hull_bear: score+=15; signals.append("EMA✅")
        if cond_vol:                  score+=15; signals.append(f"RVOL{rvol_now:.1f}✅")
        else:                         signals.append(f"RVOL{rvol_now:.1f}·")
        if stc_up and hull_bull:      score+=12; signals.append("STC✅")
        if stc_down and hull_bear:    score+=12; signals.append("STC✅")
        if adx_ok:                    score+=8;  signals.append(f"ADX{adx_now:.0f}✅")
        else:                         signals.append(f"ADX{adx_now:.0f}⚠️")
        if dist_poc:                  score+=8;  signals.append("POC✅")
        if (htf_bull and hull_bull) or (htf_bear and hull_bear):
            score+=12; signals.append("1H✅")
        score=min(score,84)

    signals += [f"Slope{slope_now:+.0f}", f"RVOL{rvol_now:.1f}", f"ADX{adx_now:.0f}"]
    score=min(max(score,0),100)

    log.info(f"{sym}: score={score} dir={direction} long={long_cond} short={short_cond} "
             f"slope={slope_now:.1f} adx={adx_now:.1f} rvol={rvol_now:.2f} "
             f"poc={dist_poc} vwap_ok={cn<vwap_now if direction=='LONG' else cn>vwap_now}")

    if long_cond:
        sl=lo_now-atr_now*ATR_SL_MULT; risk=abs(cn-sl)
        tp=cn+risk*RR_RATIO; tp_half=cn+risk
    elif short_cond:
        sl=hi_now+atr_now*ATR_SL_MULT; risk=abs(sl-cn)
        tp=cn-risk*RR_RATIO; tp_half=cn-risk
    else:
        sl_d=atr_now*ATR_SL_MULT
        sl=cn-sl_d if direction=="LONG" else cn+sl_d
        risk=abs(cn-sl); tp=cn+risk*RR_RATIO if direction=="LONG" else cn-risk*RR_RATIO
        tp_half=cn+risk if direction=="LONG" else cn-risk

    return CoinResult(symbol=sym, direction=direction, score=score,
                      entry=cn, sl=sl, tp=tp, tp_half=tp_half,
                      vol_usd=vusd, atr_val=atr_now, signals=signals,
                      change_24h=ticker.get("change_24h",0),
                      funding=funding, slope=slope_now, adx=adx_now, rvol=rvol_now)


# ══════════════════════════════════════════════════════════════════
# CALC QTY
# ══════════════════════════════════════════════════════════════════
def calc_qty(balance, entry, sl) -> float:
    dist = abs(entry-sl)
    if dist < 1e-10: return 0.0
    qty_risk = (balance*MAX_RISK_PCT/100)/dist
    qty_max  = MAX_POS_USDT/max(entry,1e-10)
    qty = min(qty_risk, qty_max)
    if   entry>=1000: qty=round(qty,4)
    elif entry>=100:  qty=round(qty,3)
    elif entry>=10:   qty=round(qty,2)
    elif entry>=1:    qty=round(qty,1)
    else:             qty=round(qty,0)
    qty=max(qty,0.001)
    log.info(f"qty: bal={balance:.2f} entry={entry:.6f} dist={dist:.8f} "
             f"risk={qty_risk:.4f} max={qty_max:.4f} final={qty}")
    return qty

def is_blackout():
    return BLACKOUT_START<=datetime.now(timezone.utc).hour<BLACKOUT_END


# ══════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════
exchange    = BingXClient()
watchlist:  list[CoinResult] = []
last_dir:   dict[str,str]    = {}
half_closed:set[str]         = set()


# ══════════════════════════════════════════════════════════════════
# STARTUP DIAGNOSTIC — corre al arrancar
# ══════════════════════════════════════════════════════════════════
async def run_diagnostics():
    """Test completo al arrancar — muestra exactamente qué falla."""
    lines = ["🔧 *DIAGNÓSTICO DE ARRANQUE*\n━━━━━━━━━━━━━━━━━━━━━━\n"]

    # 1. Test API key
    try:
        raw = await exchange.get_raw_balance()
        lines.append(f"✅ *API Key:* conexión OK")
        lines.append(f"📦 *Balance RAW:*\n`{str(raw)[:300]}`\n")
    except Exception as e:
        lines.append(f"❌ *API Key ERROR:* `{e}`")
        await tg("\n".join(lines))
        return False

    # 2. Test balance parsing
    balance = await exchange.get_balance()
    if balance > 0:
        lines.append(f"✅ *Balance:* `{balance:.4f} USDT`")
    else:
        lines.append(f"❌ *Balance = 0* — parsing fallido o cuenta vacía")
        lines.append(f"⚠️ Asegúrate de tener fondos en BingX *Futuros* (no spot)")

    # 3. Test posiciones con detalle
    try:
        positions = await exchange.get_all_positions()
        n = len(positions)
        bloq = n >= MAX_POSITIONS
        icon = "🔴" if bloq else "✅"
        lines.append(f"{icon} *Posiciones abiertas:* `{n}/{MAX_POSITIONS}`")
        if bloq:
            lines.append(f"⛔ *BLOQUEADO — {n} pos >= MAX={MAX_POSITIONS}*")
            lines.append(f"   → Sube MAX_POSITIONS en Railway")
        total_unr = 0.0
        for pos in positions:
            sym = pos.get("symbol","?")
            amt = float(pos.get("positionAmt", pos.get("size",0)))
            avg = float(pos.get("avgPrice",    pos.get("entryPrice",0)))
            cur = float(pos.get("markPrice",   pos.get("currentPrice",0)))
            unr = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit",0)))
            total_unr += unr
            direction = "LONG" if amt>0 else "SHORT"
            pnl_pct = ((cur-avg)/avg*100) if amt>0 else ((avg-cur)/avg*100)
            e2 = "🟢" if unr>=0 else "🔴"
            lines.append(f"  {e2} {sym} {direction} {pnl_pct:+.1f}% ({unr:+.2f}$)")
        if positions:
            lines.append(f"  Total PnL: {total_unr:+.2f} USDT")
    except Exception as e:
        lines.append(f"❌ *Posiciones ERROR:* `{e}`")

    # 4. Test klines
    try:
        k = await exchange.get_klines("BTC-USDT", "15m", 10)
        lines.append(f"✅ *Klines BTC:* `{len(k)} velas` precio=`{k[-1]['close']:.2f}`")
    except Exception as e:
        lines.append(f"❌ *Klines ERROR:* `{e}`")

    # 5. Test leverage (sin ejecutar orden)
    try:
        ok = await exchange.set_leverage("BTC-USDT", LEVERAGE)
        lines.append(f"{'✅' if ok else '⚠️'} *Leverage {LEVERAGE}x:* {'OK' if ok else 'fallo parcial (normal)'}")
    except Exception as e:
        lines.append(f"❌ *Leverage ERROR:* `{e}`")

    # 6. Verificar config
    lines.append(f"\n⚙️ *Config activa:*")
    lines.append(f"  TF: `{TIMEFRAME}` | Score: `{SCORE_ENTRY}` | Max pos: `{MAX_POSITIONS}`")
    lines.append(f"  MaxPosUSDT: `{MAX_POS_USDT}` | Riesgo: `{MAX_RISK_PCT}%`")
    lines.append(f"  RVOL_MIN: `{RVOL_MIN}` | SLOPE_MIN: `{SLOPE_MIN}`")
    lines.append(f"  ADX_MAX: `{ADX_MAX}` | RR: `{RR_RATIO}R`")

    if balance > 0:
        # Simular qty para BTC
        try:
            k = await exchange.get_klines("BTC-USDT","15m",5)
            entry = k[-1]["close"]
            sl    = entry - entry*0.01
            qty   = calc_qty(balance, entry, sl)
            lines.append(f"\n📐 *Sim qty BTC:* entry=`{entry:.0f}` sl_dist=`{entry*0.01:.0f}` → qty=`{qty}`")
        except: pass

    lines.append(f"\n{'✅ Bot listo para operar' if balance>0 else '❌ Sin balance — no puede abrir trades'}")
    await tg("\n".join(lines))
    return balance > 0


# ══════════════════════════════════════════════════════════════════
# OPEN TRADE
# ══════════════════════════════════════════════════════════════════
async def open_trade(cr: CoinResult) -> bool:
    sym = cr.symbol
    try:
        log.info(f"⚡ INTENTANDO {cr.direction} {sym} score={cr.score}")

        if last_dir.get(sym) == cr.direction:
            log.info(f"  {sym}: señal ya activa"); return False

        pos = await exchange.get_position(sym)
        if pos:
            log.info(f"  {sym}: posición ya abierta"); return False

        balance = await exchange.get_balance()
        log.info(f"  {sym}: balance={balance:.4f} USDT")
        if balance < 5:
            msg = (f"⚠️ *Balance insuficiente: `{balance:.4f} USDT`*\n"
                   f"Necesitas fondos en BingX *Futuros Perpetuos*\n"
                   f"Ve a BingX → Activos → Transferir a Futuros")
            await tg(msg)
            return False

        qty = calc_qty(balance, cr.entry, cr.sl)
        if qty <= 0:
            log.warning(f"  {sym}: qty=0"); return False

        await exchange.set_leverage(sym, LEVERAGE)
        side = "BUY" if cr.direction=="LONG" else "SELL"
        await exchange.place_order(
            symbol=sym, side=side,
            position_side=cr.direction, qty=qty,
            stop_loss=cr.sl, take_profit=cr.tp,
        )

        risk_usd  = abs(cr.entry-cr.sl)*qty
        pos_value = cr.entry*qty
        emoji = "🟢" if cr.direction=="LONG" else "🔴"
        await tg(
            f"{emoji} *{cr.direction} — V45*\n"
            f"Par: `{sym}` | Score: `{cr.score}/100`\n"
            f"Entry: `{cr.entry:.6f}`\n"
            f"SL: `{cr.sl:.6f}` | TP: `{cr.tp:.6f}` *({RR_RATIO}R)*\n"
            f"Qty: `{qty}` | Valor: `≈{pos_value:.2f}$`\n"
            f"Riesgo: `≈{risk_usd:.2f} USDT`\n"
            f"Slope:`{cr.slope:+.0f}` ADX:`{cr.adx:.0f}` RVOL:`{cr.rvol:.2f}x`\n"
            f"{' '.join(cr.signals[:6])}"
        )
        last_dir[sym] = cr.direction
        log.info(f"✅ TRADE ABIERTO {cr.direction} {sym} qty={qty}")
        return True

    except Exception as e:
        log.error(f"open_trade {sym}: {e}", exc_info=True)
        await tg(f"❌ *Error orden* `{sym}`:\n`{str(e)[:300]}`")
        return False


# ══════════════════════════════════════════════════════════════════
# MANAGE POSITIONS
# ══════════════════════════════════════════════════════════════════
async def manage_positions():
    try:
        positions = await exchange.get_all_positions()
        if not positions: return
        for pos in positions:
            sym = pos.get("symbol","")
            amt = float(pos.get("positionAmt", pos.get("size",0)))
            avg = float(pos.get("avgPrice",    pos.get("entryPrice",0)))
            cur = float(pos.get("markPrice",   pos.get("currentPrice",0)))
            unr = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit",0)))
            if avg<=0 or cur<=0: continue
            is_long  = amt>0
            pnl_pct  = ((cur-avg)/avg*100) if is_long else ((avg-cur)/avg*100)
            direction= "LONG" if is_long else "SHORT"
            log.info(f"POS {sym} {direction} pnl={pnl_pct:+.2f}%")
            if sym not in half_closed and pnl_pct >= 0.6:
                try:
                    await exchange.close_half(sym, pos)
                    half_closed.add(sym)
                    await tg(f"🔒 *Cierre 50%* `{sym}` {direction}\n"
                             f"PnL: `+{pnl_pct:.2f}%` | `+{unr:.2f} USDT`")
                except Exception as e:
                    log.error(f"close_half {sym}: {e}")
    except Exception as e:
        log.error(f"manage_positions: {e}")


# ══════════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════════
async def scanner_loop():
    global watchlist
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(SCAN_INTERVAL); continue

            log.info("🔍 Escaneando V45...")
            tickers = await exchange.get_tickers()
            if not tickers:
                await tg("⚠️ Sin tickers.")
                await asyncio.sleep(SCAN_INTERVAL); continue

            syms = [t["symbol"] for t in tickers]
            lim  = max(200, POC_LOOKBACK+80)
            r15,r1h,rfr = await asyncio.gather(
                asyncio.gather(*[exchange.get_klines(s,TIMEFRAME,lim) for s in syms],return_exceptions=True),
                asyncio.gather(*[exchange.get_klines(s,TF_HIGH,  100) for s in syms],return_exceptions=True),
                asyncio.gather(*[exchange.get_funding_rate(s)         for s in syms],return_exceptions=True),
            )

            results=[]
            for t,c15,c1h,fr in zip(tickers,r15,r1h,rfr):
                if isinstance(c15,Exception): continue
                cr=analyze(t,c15,
                    c1h if not isinstance(c1h,Exception) else [],
                    fr  if not isinstance(fr, Exception) else 0.0)
                if cr: results.append(cr)

            results.sort(key=lambda x: x.score, reverse=True)
            top=results[:SCAN_TOP_N]

            wl=[r for r in top if r.score>=SCORE_ENTRY and r.direction!="NEUTRAL"]
            watchlist=wl if wl else top[:5]
            log.info(f"Watchlist: {[(r.symbol,r.score,r.direction) for r in watchlist]}")

            lines=[f"🔍 *V45 — {len(top)} coins*\n"]
            for n,r in enumerate(top,1):
                e  ="🟢" if r.direction=="LONG" else "🔴"
                bar="█"*(r.score//10)+"░"*(10-r.score//10)
                tag=" ⚡*ENTRA*" if r.score>=SCORE_ENTRY else ""
                lines.append(
                    f"*#{n}* {e} `{r.symbol}` `{r.score}/100`{tag}\n"
                    f"`{bar}`\n"
                    f"Vol:`${r.vol_usd/1e6:.0f}M` RVOL:`{r.rvol:.1f}x`"
                    f" ADX:`{r.adx:.0f}` Slope:`{r.slope:+.0f}`\n"
                    f"{' '.join(r.signals[:5])}\n"
                )
            lines.append(f"\n🎯 *Watchlist ({len(watchlist)}):*")
            for r in watchlist:
                e="🟢" if r.direction=="LONG" else "🔴"
                lines.append(f"  {e} `{r.symbol}` `{r.score}` → {r.direction}")
            await tg("\n".join(lines)[:3900])

        except Exception as e:
            log.error(f"Scanner: {e}", exc_info=True)
            await tg(f"⚠️ *Error escáner:* `{str(e)[:200]}`")

        await asyncio.sleep(SCAN_INTERVAL)


# ══════════════════════════════════════════════════════════════════
# TRADING LOOP
# ══════════════════════════════════════════════════════════════════
async def trading_loop():
    await asyncio.sleep(50)
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(60); continue

            await manage_positions()

            open_pos  = await exchange.get_all_positions()
            n_open    = len(open_pos)
            open_syms = {p.get("symbol","") for p in open_pos}
            log.info(f"Trading: {n_open}/{MAX_POSITIONS} pos | watchlist={len(watchlist)}")

            if n_open < MAX_POSITIONS and watchlist:
                for cr in list(watchlist):
                    if n_open >= MAX_POSITIONS: break
                    if cr.symbol in open_syms: continue
                    if cr.score < SCORE_ENTRY:
                        log.info(f"  {cr.symbol}: score {cr.score}<{SCORE_ENTRY}"); continue
                    opened = await open_trade(cr)
                    if opened:
                        n_open+=1; open_syms.add(cr.symbol)
                    await asyncio.sleep(3)

        except Exception as e:
            log.error(f"Trading loop: {e}", exc_info=True)
        await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
async def main():
    log.info("🚀 Sniper Bot V45 — Arrancando con diagnóstico...")

    await tg(
        "🔄 *Sniper Bot V45 arrancando...*\n"
        f"TF: `{TIMEFRAME}` | Lev: `{LEVERAGE}x` | Riesgo: `{MAX_RISK_PCT}%`\n"
        f"Ejecutando diagnóstico completo..."
    )

    # Diagnóstico al arrancar
    ok = await run_diagnostics()

    if not ok:
        await tg(
            "⛔ *Bot detenido — sin balance*\n\n"
            "*Pasos para solucionar:*\n"
            "1. Abre BingX app\n"
            "2. Ve a `Activos` → `Futuros`\n"
            "3. Pulsa `Transferir` y mueve USDT de Spot a Futuros\n"
            "4. Vuelve a Railway y haz `Redeploy`"
        )
        # No detener el bot — sigue intentando cada 5 min
        while True:
            await asyncio.sleep(300)
            bal = await exchange.get_balance()
            if bal > 5:
                await tg(f"✅ Balance detectado: `{bal:.2f} USDT` — arrancando bot...")
                break

    await asyncio.gather(scanner_loop(), trading_loop())

if __name__ == "__main__":
    asyncio.run(main())
