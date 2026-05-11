"""
Sniper Bot V27.2 — FIXED SIGNALS
=================================
FIX PRINCIPAL: compute_signal ahora usa el MISMO criterio que el scorer.
Si el scorer dice SHORT 70 → compute_signal ABRE SHORT.
No más filtros extra que bloquean señales válidas.

Regla simple y efectiva:
  score >= 65 + direction != NEUTRAL → ENTRA
  SL = ATR * 1.5 desde entry (dinámico, siempre válido)
  TP = SL * 3 (ratio 1:3)
"""

import asyncio, hashlib, hmac, logging, os, time, urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import httpx
import numpy as np

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log")],
)
log = logging.getLogger("SniperBot")

# ── Config ────────────────────────────────────────────────────────
BINGX_API_KEY    = os.environ["BINGX_API_KEY"]
BINGX_API_SECRET = os.environ["BINGX_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TIMEFRAME        = os.getenv("TIMEFRAME", "15m")
TF_HIGH          = os.getenv("TIMEFRAME_HIGH", "1h")
LEVERAGE         = int(os.getenv("LEVERAGE", "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT", "1.0"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N", "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT", "10000000"))
SCORE_ENTRY      = int(os.getenv("SCORE_ENTRY", "55"))      # score mínimo para ABRIR trade
SCORE_SCAN       = int(os.getenv("SCORE_SCAN", "30"))       # score mínimo para watchlist
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "5")) * 60
MAX_POSITIONS    = int(os.getenv("MAX_POSITIONS", "3"))
BLACKOUT_START   = int(os.getenv("BLACKOUT_START_UTC", "0"))
BLACKOUT_END     = int(os.getenv("BLACKOUT_END_UTC", "2"))
BASE_URL         = "https://open-api.bingx.com"

BLACKLIST = {
    "USDC-USDT","BUSD-USDT","DAI-USDT","TUSD-USDT","USDP-USDT",
    "FRAX-USDT","NCCOGOLD2USD-USDT","PAXG-USDT","XAUT-USDT",
    "WBTC-USDT","STETH-USDT","WETH-USDT","CBETH-USDT","ZEC-USDT",
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
}
USE_WHITELIST = os.getenv("USE_WHITELIST", "true").lower() == "true"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════════

class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)

    def _sign(self, params: dict) -> str:
        q = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(BINGX_API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

    def _h(self):
        return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}

    async def _get(self, path, params=None):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.get(path, params=p, headers=self._h())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def _post(self, path, payload):
        p = dict(payload)
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.post(path, params=p, headers=self._h())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def get_klines(self, symbol, interval, limit=200):
        d = await self._get("/openApi/swap/v3/quote/klines",
                            {"symbol": symbol, "interval": interval, "limit": limit})
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

    async def get_tickers(self):
        d = await self._get("/openApi/swap/v2/quote/ticker")
        raw = d.get("data", [])
        if raw: log.info(f"[DEBUG] Ticker fields: {list(raw[0].keys())}")
        out = []
        for t in raw:
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
                out.append({"symbol": sym, "price": price, "change_24h": change})
        log.info(f"Tickers válidos: {len(out)}")
        return out

    async def get_funding_rate(self, symbol):
        try:
            d = await self._get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
            data = d.get("data", {})
            if isinstance(data, list): data = data[0] if data else {}
            return float(data.get("lastFundingRate", data.get("fundingRate", 0)))
        except: return 0.0

    async def get_ls_ratio(self, symbol):
        try:
            d = await self._get("/openApi/swap/v2/quote/globalLongShortAccountRatio",
                                {"symbol": symbol, "period": "5m", "limit": 1})
            data = d.get("data", [])
            if data:
                item = data[0] if isinstance(data, list) else data
                return float(item.get("longShortRatio", item.get("longAccount", 1.0)))
        except: pass
        return 1.0

    async def get_balance(self):
        d = await self._get("/openApi/swap/v2/user/balance")
        for a in d["data"]["balance"]:
            if a["asset"] == "USDT":
                for f in ("availableMargin","available","free","equity"):
                    v = a.get(f)
                    if v is not None:
                        bal = float(v)
                        log.info(f"Balance: {bal:.2f} USDT")
                        return bal
        return 0.0

    async def get_position(self, symbol):
        d = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        ps = [p for p in d.get("data",[]) if abs(float(p.get("positionAmt",0))) > 0]
        return ps[0] if ps else None

    async def get_all_positions(self):
        try:
            d = await self._get("/openApi/swap/v2/user/positions")
            return [p for p in d.get("data",[]) if abs(float(p.get("positionAmt",0))) > 0]
        except: return []

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None, reduce_only=False):
        p = {"symbol":symbol,"side":side,"positionSide":position_side,
             "type":"MARKET","quantity":str(qty)}
        if reduce_only:  p["reduceOnly"]  = "true"
        if stop_loss:    p["stopLoss"]    = str(round(stop_loss,   8))
        if take_profit:  p["takeProfit"]  = str(round(take_profit, 8))
        log.info(f"ORDER → {symbol} {side} {position_side} qty={qty} sl={stop_loss} tp={take_profit}")
        r = await self._post("/openApi/swap/v2/trade/order", p)
        log.info(f"RESULT → {r}")
        return r

    async def close_position(self, symbol, position):
        amt = float(position["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        return await self.place_order(symbol, side, pside, abs(amt), reduce_only=True)

    async def close_half(self, symbol, position):
        amt = float(position["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        half = round(abs(amt)/2, 3)
        if half < 0.001: return
        return await self.place_order(symbol, side, pside, half, reduce_only=True)

    async def set_leverage(self, symbol, leverage):
        for side in ("LONG","SHORT"):
            try:
                await self._post("/openApi/swap/v2/trade/leverage",
                                 {"symbol":symbol,"side":side,"leverage":str(leverage)})
            except Exception as e:
                log.warning(f"Leverage {side} {symbol}: {e}")


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

async def tg(text):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID,
                      "text": text[:4000], "parse_mode": "Markdown"}
            )
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def ema(v, p):
    v = np.asarray(v, float); k = 2/(p+1); r = np.zeros(len(v)); r[0] = v[0]
    for i in range(1, len(v)): r[i] = v[i]*k + r[i-1]*(1-k)
    return r

def hma(v, p):
    return ema(2*ema(v, max(p//2,1)) - ema(v, p), max(int(np.sqrt(p)),1))

def sma(v, p):
    return np.convolve(np.asarray(v,float), np.ones(p)/p, mode="same")

def stoch_s(src, p):
    src = np.asarray(src, float); r = np.zeros(len(src))
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]; lo,hi = w.min(),w.max()
        r[i] = (src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_ind(c):
    return stoch_s(stoch_s(ema(c,23)-ema(c,50), 10), 10)

def pivot_hi(h, n):
    h = np.asarray(h,float); r = np.full(len(h),np.nan)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max(): r[i] = h[i]
    return r

def pivot_lo(l, n):
    l = np.asarray(l,float); r = np.full(len(l),np.nan)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min(): r[i] = l[i]
    return r

def atr(highs, lows, closes, p=14):
    h,l,c = map(lambda x: np.asarray(x,float), [highs,lows,closes])
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    return float(np.mean(tr[-p:]))

def vol_usd_24h(candles):
    last = candles[-96:] if len(candles)>=96 else candles
    return sum(c["close"]*c["volume"] for c in last)


# ══════════════════════════════════════════════════════════════════
# CORE SCORING + SIGNAL — UN SOLO MOTOR, SIN DOBLE FILTRO
# ══════════════════════════════════════════════════════════════════

@dataclass
class CoinResult:
    symbol:      str
    direction:   str     # LONG | SHORT | NEUTRAL
    score:       int
    entry:       float
    sl:          float
    tp:          float
    tp_half:     float   # 1R — para cierre parcial
    vol_usd:     float
    atr_val:     float
    signals:     list = field(default_factory=list)
    change_24h:  float = 0.0
    funding:     float = 0.0
    ls_ratio:    float = 1.0

def analyze(ticker: dict, candles: list, candles_1h: list,
            funding: float, ls: float) -> Optional[CoinResult]:
    """
    Motor único: puntúa Y decide entrada en el mismo paso.
    Sin filtros extra en compute_signal — si score >= SCORE_ENTRY → abre.
    """
    if len(candles) < 60: return None

    closes  = np.array([c["close"]  for c in candles], float)
    highs   = np.array([c["high"]   for c in candles], float)
    lows    = np.array([c["low"]    for c in candles], float)
    volumes = np.array([c["volume"] for c in candles], float)

    if closes[-1] <= 0 or np.any(np.isnan(closes[-5:])): return None

    vusd = vol_usd_24h(candles)
    if vusd < MIN_VOL_USDT: return None

    # Indicadores
    e7,  e17 = ema(closes,7),  ema(closes,17)
    e4,  e20 = ema(closes,4),  ema(closes,20)
    h50      = hma(closes, 50)
    stc_v    = stc_ind(closes)
    vol_sma  = sma(volumes, 20)
    inst_vol = bool(volumes[-1] > vol_sma[-1]*1.3) if vol_sma[-1]>0 else False

    ph_v = pivot_hi(highs,5); pl_v = pivot_lo(lows,5)
    vph = ph_v[~np.isnan(ph_v)]; vpl = pl_v[~np.isnan(pl_v)]
    peak   = float(vph[-1]) if len(vph)>0 else float(highs[-1])
    valley = float(vpl[-1]) if len(vpl)>0 else float(lows[-1])
    atr_v  = atr(highs, lows, closes)

    # HTF 1h — solo como bonus/penalización, NO como bloqueador
    htf_bull = htf_bear = False
    if len(candles_1h) >= 20:
        c1 = np.array([c["close"] for c in candles_1h], float)
        e7_1h = ema(c1,7); e17_1h = ema(c1,17); h50_1h = hma(c1,50)
        htf_bull = bool(c1[-1] > h50_1h[-1] and e7_1h[-1] > e17_1h[-1])
        htf_bear = bool(c1[-1] < h50_1h[-1] and e7_1h[-1] < e17_1h[-1])

    i = -1
    close_now = float(closes[i])
    score = 0; signals = []; direction = "NEUTRAL"

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    # ── SCORING ────────────────────────────────────────────────────

    # F1: Hull MA (20 pts) — REQUERIDO para dirección
    if hull_bull:
        score += 20; signals.append("Hull🟢"); direction = "LONG"
    elif hull_bear:
        score += 20; signals.append("Hull🔴"); direction = "SHORT"
    else:
        # Sin Hull claro → neutral, no operar
        log.info(f"{ticker['symbol']}: Hull neutral, skip")
        return None

    # F2: EMA 7/17 alineación (20 pts) + cruce fresco (+8 pts)
    ema_align_l = hull_bull and e7[i] > e17[i]
    ema_align_s = hull_bear and e7[i] < e17[i]
    ema_cross_l = hull_bull and e7[i-1] <= e17[i-1] and e7[i] > e17[i]
    ema_cross_s = hull_bear and e7[i-1] >= e17[i-1] and e7[i] < e17[i]

    if ema_align_l or ema_align_s:
        score += 20; signals.append("EMA✅")
    else:
        # EMA contradice Hull → penalización fuerte
        score -= 15; signals.append("EMA⚠️")

    if ema_cross_l or ema_cross_s:
        score += 8; signals.append("Cruz🔥")

    # F3: HTF 1h — bonus si confirma, penalización si contradice
    if (hull_bull and htf_bull) or (hull_bear and htf_bear):
        score += 12; signals.append("1H✅")
    elif (hull_bull and htf_bear) or (hull_bear and htf_bull):
        score -= 12; signals.append("1H❌")
    # Si no hay datos 1h → neutro (0 pts), sin penalizar

    # F4: Volumen institucional desde velas (15 pts)
    ratio = volumes[-1]/(vol_sma[-1]+1e-10)
    if inst_vol:
        score += 15; signals.append(f"Vol💜{ratio:.1f}x")
    else:
        signals.append(f"Vol·{ratio:.1f}x")

    # F5: STC momentum (15 pts)
    stc_up   = hull_bull and stc_v[i] > stc_v[i-1]
    stc_down = hull_bear and stc_v[i] < stc_v[i-1]
    if stc_up or stc_down:
        score += 15; signals.append("STC✅")
    else:
        signals.append("STC·")

    # F6: ChartArt slope (10 pts)
    s4  = e4[i]-e4[i-1]; s20 = e20[i]-e20[i-1]
    if (hull_bull and s4>0 and s20>0) or (hull_bear and s4<0 and s20<0):
        score += 10; signals.append("Slope✅")

    # F7: Zona pivot (10 pts)
    rng = peak - valley
    if rng > 0:
        pos = (close_now - valley) / rng
        if (hull_bull and pos > 0.5) or (hull_bear and pos < 0.5):
            score += 10; signals.append("Zona✅")

    # F8: Funding rate (+8 si confirma, -8 si masa en nuestra dirección)
    if abs(funding) > 0.0001:
        if (hull_bull and funding < -0.01) or (hull_bear and funding > 0.03):
            score += 8; signals.append(f"FR🔥{funding*100:.3f}%")
        elif (hull_bull and funding > 0.03) or (hull_bear and funding < -0.01):
            score -= 8; signals.append(f"FR⚠️{funding*100:.3f}%")

    # F9: L/S ratio contrarian (+6 si masa está al lado contrario)
    if (hull_bear and ls > 1.5) or (hull_bull and ls < 0.7):
        score += 6; signals.append(f"LS🎯{ls:.2f}")

    score = min(max(score, 0), 105)

    log.info(f"{ticker['symbol']}: score={score} dir={direction} "
             f"vol=${vusd/1e6:.0f}M fr={funding:.4f} ls={ls:.2f} "
             f"ema_align={ema_align_l or ema_align_s} inst_vol={inst_vol}")

    # ── SL / TP dinámico ───────────────────────────────────────────
    # Siempre usar ATR para SL — evita SL demasiado lejano o inválido
    sl_dist = atr_v * 1.5
    if direction == "LONG":
        sl      = close_now - sl_dist
        tp_half = close_now + sl_dist        # 1R
        tp      = close_now + sl_dist * 3   # 3R
    else:
        sl      = close_now + sl_dist
        tp_half = close_now - sl_dist
        tp      = close_now - sl_dist * 3

    return CoinResult(
        symbol=ticker["symbol"], direction=direction, score=score,
        entry=close_now, sl=sl, tp=tp, tp_half=tp_half,
        vol_usd=vusd, atr_val=atr_v, signals=signals,
        change_24h=ticker.get("change_24h",0),
        funding=funding, ls_ratio=ls,
    )


# ══════════════════════════════════════════════════════════════════
# RISK
# ══════════════════════════════════════════════════════════════════

def calc_qty(balance, entry, sl):
    dist = abs(entry - sl)
    if dist < 1e-10: return 0.0
    raw = (balance * MAX_RISK_PCT / 100) / dist
    if entry > 10000:   return round(raw, 3)
    elif entry > 100:   return round(raw, 2)
    elif entry > 1:     return round(raw, 1)
    else:               return max(round(raw, 0), 1.0)


# ══════════════════════════════════════════════════════════════════
# BOT STATE
# ══════════════════════════════════════════════════════════════════

exchange     = BingXClient()
watchlist:   list[CoinResult] = []
last_dir:    dict[str,str]    = {}
half_closed: set[str]         = set()

def is_blackout():
    h = datetime.now(timezone.utc).hour
    return BLACKOUT_START <= h < BLACKOUT_END


# ══════════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════════

async def scanner_loop():
    global watchlist
    while True:
        try:
            if is_blackout():
                log.info("Blackout UTC — pausa")
                await asyncio.sleep(SCAN_INTERVAL); continue

            log.info(f"🔍 Escaneando mercado...")
            tickers = await exchange.get_tickers()
            if not tickers:
                await tg("⚠️ Sin tickers. Revisa API key o WHITELIST.")
                await asyncio.sleep(SCAN_INTERVAL); continue

            syms = [t["symbol"] for t in tickers]
            r15, r1h, rfr, rls = await asyncio.gather(
                asyncio.gather(*[exchange.get_klines(s,TIMEFRAME,200) for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_klines(s,TF_HIGH,100)  for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_funding_rate(s)         for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_ls_ratio(s)             for s in syms], return_exceptions=True),
            )

            results = []
            for ticker, c15, c1h, fr, ls in zip(tickers, r15, r1h, rfr, rls):
                if isinstance(c15, Exception): continue
                cr = analyze(
                    ticker, c15,
                    c1h if not isinstance(c1h, Exception) else [],
                    fr  if not isinstance(fr,  Exception) else 0.0,
                    ls  if not isinstance(ls,  Exception) else 1.0,
                )
                if cr: results.append(cr)

            results.sort(key=lambda x: x.score, reverse=True)
            top = results[:SCAN_TOP_N]

            # Watchlist: coins operables o top 5 como fallback
            operables = [r for r in top if r.score >= SCORE_ENTRY and r.direction != "NEUTRAL"]
            watchlist = operables if operables else top[:5]

            # Telegram resumen
            lines = [f"🔍 *V27.2 — {len(top)} coins analizadas*\n"]
            for n, r in enumerate(top, 1):
                e   = "🟢" if r.direction=="LONG" else "🔴"
                bar = "█"*(r.score//10) + "░"*(10-r.score//10)
                tag = "⚡ENTRA" if r.score >= SCORE_ENTRY else ""
                lines.append(
                    f"*#{n}* {e} `{r.symbol}` `{r.score}/100` {tag}\n"
                    f"`{bar}`\n"
                    f"Vol:`${r.vol_usd/1e6:.0f}M` Δ:`{r.change_24h:+.1f}%`"
                    f" FR:`{r.funding*100:.3f}%` LS:`{r.ls_ratio:.2f}`\n"
                    f"{' '.join(r.signals[:7])}\n"
                )

            lines.append(f"\n🎯 *Watchlist ({len(watchlist)}):*")
            for r in watchlist:
                e = "🟢" if r.direction=="LONG" else "🔴"
                lines.append(f"  {e} `{r.symbol}` score=`{r.score}` → {r.direction}")

            msg = "\n".join(lines)
            await tg(msg[:3900])

        except Exception as e:
            log.error(f"Scanner: {e}", exc_info=True)
            await tg(f"⚠️ *Error escáner:* `{str(e)[:300]}`")

        await asyncio.sleep(SCAN_INTERVAL)


# ══════════════════════════════════════════════════════════════════
# TRADING
# ══════════════════════════════════════════════════════════════════

async def trading_loop():
    await asyncio.sleep(75)  # esperar primer escaneo
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(60); continue

            await manage_positions()

            open_pos = await exchange.get_all_positions()
            n_open   = len(open_pos)
            log.info(f"Posiciones abiertas: {n_open}/{MAX_POSITIONS}")

            if n_open < MAX_POSITIONS:
                open_syms = {p.get("symbol","") for p in open_pos}
                for cr in list(watchlist):
                    if n_open >= MAX_POSITIONS: break
                    if cr.symbol in open_syms: continue
                    if cr.score >= SCORE_ENTRY:
                        opened = await open_trade(cr)
                        if opened: n_open += 1
                    await asyncio.sleep(2)

        except Exception as e:
            log.error(f"Trading loop: {e}", exc_info=True)
        await asyncio.sleep(60)


async def open_trade(cr: CoinResult) -> bool:
    """Abre una posición. Retorna True si se ejecutó."""
    try:
        # Verificar que no tenemos ya esta señal abierta
        if last_dir.get(cr.symbol) == cr.direction:
            log.info(f"{cr.symbol}: señal {cr.direction} ya activa, skip")
            return False

        # Re-verificar posición por si acaso
        pos = await exchange.get_position(cr.symbol)
        if pos:
            log.info(f"{cr.symbol}: ya tiene posición abierta")
            return False

        balance = await exchange.get_balance()
        if balance < 5:
            await tg(f"⚠️ Balance bajo: `{balance:.2f} USDT`")
            return False

        qty = calc_qty(balance, cr.entry, cr.sl)
        if qty <= 0:
            log.warning(f"{cr.symbol}: qty=0")
            return False

        await exchange.set_leverage(cr.symbol, LEVERAGE)
        side = "BUY" if cr.direction=="LONG" else "SELL"

        await exchange.place_order(
            symbol=cr.symbol, side=side,
            position_side=cr.direction, qty=qty,
            stop_loss=cr.sl, take_profit=cr.tp,
        )

        risk_usd = abs(cr.entry - cr.sl) * qty
        emoji    = "🟢" if cr.direction=="LONG" else "🔴"
        await tg(
            f"{emoji} *{cr.direction} ABIERTO*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Par:   `{cr.symbol}`\n"
            f"Entry: `{cr.entry:.6f}`\n"
            f"SL:    `{cr.sl:.6f}` *(ATR×1.5)*\n"
            f"TP½:   `{cr.tp_half:.6f}` *(1R → cierre 50%)*\n"
            f"TP:    `{cr.tp:.6f}` *(3R → objetivo)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Qty:   `{qty}`\n"
            f"Score: `{cr.score}/100`\n"
            f"Riesgo:`≈{risk_usd:.2f} USDT`\n"
            f"FR:    `{cr.funding*100:.3f}%` | LS: `{cr.ls_ratio:.2f}`\n"
            f"Señales: {' '.join(cr.signals[:6])}"
        )
        last_dir[cr.symbol] = cr.direction
        log.info(f"✅ TRADE ABIERTO {cr.direction} {cr.symbol} qty={qty} score={cr.score}")
        return True

    except Exception as e:
        log.error(f"open_trade {cr.symbol}: {e}", exc_info=True)
        await tg(f"❌ *Error abriendo* `{cr.symbol}`: `{str(e)[:200]}`")
        return False


async def manage_positions():
    """Cierre parcial al 1R, log de PnL."""
    global half_closed
    try:
        positions = await exchange.get_all_positions()
        for pos in positions:
            sym  = pos.get("symbol","")
            amt  = float(pos.get("positionAmt",0))
            avg  = float(pos.get("avgPrice", pos.get("entryPrice",0)))
            cur  = float(pos.get("markPrice", pos.get("currentPrice",0)))
            unr  = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit",0)))
            if avg<=0 or cur<=0: continue

            is_long  = amt > 0
            pnl_pct  = ((cur-avg)/avg*100) if is_long else ((avg-cur)/avg*100)
            direction = "LONG" if is_long else "SHORT"

            log.info(f"POS {sym} {direction} pnl={pnl_pct:+.2f}% unreal={unr:+.2f}")

            # Cierre 50% al llegar a ~0.8% PnL (≈1R con 5x leverage)
            if sym not in half_closed and pnl_pct >= 0.8:
                try:
                    await exchange.close_half(sym, pos)
                    half_closed.add(sym)
                    await tg(
                        f"🔒 *Cierre parcial 50%* `{sym}`\n"
                        f"PnL: `+{pnl_pct:.2f}%` | `+{unr:.2f} USDT`\n"
                        f"Segunda mitad en curso → TP a 3R"
                    )
                except Exception as e:
                    log.error(f"close_half {sym}: {e}")

            # Si la posición se cerró → limpiar estado
            if abs(amt) < 0.001:
                half_closed.discard(sym)
                last_dir[sym] = "NONE"

    except Exception as e:
        log.error(f"manage_positions: {e}")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

async def main():
    log.info("🚀 Sniper Bot V27.2 — Arrancando...")
    await tg(
        "🟢 *Sniper Bot V27.2 — FIXED SIGNALS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"TF: `{TIMEFRAME}` | HTF: `{TF_HIGH}`\n"
        f"Leverage: `{LEVERAGE}x` | Riesgo: `{MAX_RISK_PCT}%`\n"
        f"Score entrada: `{SCORE_ENTRY}/100`\n"
        f"Max posiciones: `{MAX_POSITIONS}`\n"
        f"Blackout: `{BLACKOUT_START}-{BLACKOUT_END}h UTC`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Motor único scorer+signal\n"
        f"✅ SL dinámico ATR×1.5\n"
        f"✅ Cierre parcial 50% al 1R\n"
        f"✅ Funding Rate + L/S ratio\n"
        f"✅ Multi-timeframe 1h\n"
        f"✅ Blackout nocturno UTC"
    )
    await asyncio.gather(scanner_loop(), trading_loop())

if __name__ == "__main__":
    asyncio.run(main())
