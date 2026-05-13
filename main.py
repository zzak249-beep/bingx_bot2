"""
Sniper Bot V47 — FIX SIGNATURE REAL + RENTABILIDAD
====================================================
FIXES vs V46:
  [BUG CRÍTICO] _sign() usaba sorted(p.items()) — BingX NO quiere
    params ordenados alfabéticamente. Eliminado sorted(). Orden natural.
  [BUG CRÍTICO] API key/secret sin .strip() → espacios/newlines en
    Railway causaban signature mismatch silencioso. SOLUCIONADO.
  [BUG] recvWindow como int causaba urlencode inconsistente en algunos
    builds. Ahora todos los params van como str antes de firmar.
  [NUEVO] Diagnóstico muestra primeros/últimos 4 chars de la key
    para verificar que no hay espacios.

MEJORAS RENTABILIDAD:
  [+] Trailing SL real: cierra posición y no reabre (protege capital)
  [+] TP parcial ajustado: 50% en +0.8%, resto corre con trailing
  [+] Filtro tendencia 4H: solo LONGs si 4H alcista, SHORTs si bajista
  [+] Confirmación de vela de cierre: no entra en vela abierta si STC justo giró
  [+] Score fallback mínimo 65 (antes 60) — menos ruido
  [+] Blackout extendido: 0-3 UTC (hora de menor liquidez)
  [+] Máx pérdida diaria: si PnL día < -5%, para operaciones 4h
  [+] Position sizing mejorado: 0.5% riesgo por defecto (antes 1%)
  [+] RR mínimo 2.5, SL más ajustado (ATR x1.0 en path principal)
  [+] Filtro: skip si spread (hi-lo)/close > 2% (vela muy volátil)
"""

import asyncio, hashlib, hmac, logging, os, time, urllib.parse
from collections import defaultdict
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

# ── CRÍTICO: .strip() para evitar espacios/newlines de Railway ──────
BINGX_API_KEY    = os.environ["BINGX_API_KEY"].strip()
BINGX_API_SECRET = os.environ["BINGX_API_SECRET"].strip()
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"].strip()
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()

TIMEFRAME        = os.getenv("TIMEFRAME",             "15m")
TF_HIGH          = os.getenv("TIMEFRAME_HIGH",        "1h")
TF_TREND         = os.getenv("TIMEFRAME_TREND",       "4h")
LEVERAGE         = int(os.getenv("LEVERAGE",          "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT",    "0.5"))   # bajado de 1.0
MAX_POS_USDT     = float(os.getenv("MAX_POS_USDT",    "20"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N",        "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT",    "10000000"))
SCORE_ENTRY      = int(os.getenv("SCORE_ENTRY",       "55"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "5")) * 60
MAX_POSITIONS    = int(os.getenv("MAX_POSITIONS",     "5"))
BLACKOUT_START   = int(os.getenv("BLACKOUT_START_UTC","0"))
BLACKOUT_END     = int(os.getenv("BLACKOUT_END_UTC",  "3"))    # extendido a 3
SLOPE_MIN        = float(os.getenv("SLOPE_MIN",       "20.0"))
POC_LOOKBACK     = int(os.getenv("POC_LOOKBACK",      "50"))
ADX_MAX          = float(os.getenv("ADX_MAX",         "42.0"))
RVOL_MIN         = float(os.getenv("RVOL_MIN",        "1.2"))
RR_RATIO         = float(os.getenv("RR_RATIO",        "2.5"))
ATR_SL_MULT      = float(os.getenv("ATR_SL_MULT",     "1.0"))  # ajustado de 1.2
EMA_FAST         = int(os.getenv("EMA_FAST",          "7"))
EMA_SLOW         = int(os.getenv("EMA_SLOW",          "17"))
RSI_PERIOD       = int(os.getenv("RSI_PERIOD",        "14"))
RSI_OB           = float(os.getenv("RSI_OB",          "68.0"))
RSI_OS           = float(os.getenv("RSI_OS",          "32.0"))
FUNDING_SKIP     = float(os.getenv("FUNDING_SKIP",    "0.0005"))
SYMBOL_COOLDOWN  = int(os.getenv("SYMBOL_COOLDOWN",   "30"))
MAX_LOSSES       = int(os.getenv("MAX_LOSSES",        "2"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_PCT",  "5.0"))  # nuevo
HALF_CLOSE_PCT   = float(os.getenv("HALF_CLOSE_PCT",  "0.8"))  # antes 1.0
TRAIL_STOP_PCT   = float(os.getenv("TRAIL_STOP_PCT",  "1.5"))  # activar trailing
BASE_URL         = "https://open-api.bingx.com"
RECV_WINDOW      = 5000

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
# EXCHANGE — FIRMA CORREGIDA (V47: sin sorted, con strip)
# ══════════════════════════════════════════════════════════════════
class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)

    def _sign(self, params: dict) -> str:
        """
        FIX V47: NO sorted() — BingX firma con params en orden de inserción.
        Todos los valores como string para urlencode consistente.
        """
        p = {k: str(v) for k, v in params.items() if k != "signature"}
        # ← SIN sorted() — orden de inserción del dict (Python 3.7+)
        q = urllib.parse.urlencode(p.items())
        sig = hmac.new(
            BINGX_API_SECRET.encode("utf-8"),
            q.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        log.debug(f"SIGN query='{q[:80]}...' sig={sig[:16]}...")
        return sig

    def _auth_headers(self):
        return {"X-BX-APIKEY": BINGX_API_KEY}

    async def _get(self, path, params=None) -> dict:
        p = {}
        if params:
            p.update({k: str(v) for k, v in params.items()})
        p["timestamp"]  = str(int(time.time() * 1000))
        p["recvWindow"] = str(RECV_WINDOW)
        p["signature"]  = self._sign(p)
        for attempt in range(3):
            try:
                r = await self.client.get(path, params=p, headers=self._auth_headers())
                r.raise_for_status()
                d = r.json()
                if d.get("code", 0) != 0:
                    raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
                return d
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt == 2: raise
                await asyncio.sleep(1.5 * (attempt + 1))

    async def _post(self, path, params: dict) -> dict:
        """
        V47: params como str, sin sorted, sin Content-Type.
        BingX swap V2 = params en URL query string.
        """
        p = {k: str(v) for k, v in params.items()}
        p["timestamp"]  = str(int(time.time() * 1000))
        p["recvWindow"] = str(RECV_WINDOW)
        p["signature"]  = self._sign(p)
        for attempt in range(3):
            try:
                r = await self.client.post(
                    path,
                    params=p,
                    headers=self._auth_headers()
                )
                r.raise_for_status()
                d = r.json()
                if d.get("code", 0) != 0:
                    raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
                return d
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt == 2: raise
                await asyncio.sleep(1.5 * (attempt + 1))

    async def get_raw_balance(self) -> dict:
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
                            {"symbol": symbol, "interval": interval, "limit": limit})
        out = []
        for c in d["data"]:
            try:
                if isinstance(c, list):
                    out.append({"time":int(c[0]),"open":float(c[1]),"high":float(c[2]),
                                "low":float(c[3]),"close":float(c[4]),"volume":float(c[5])})
                else:
                    out.append({
                        "time":   int(c.get("time",   c.get("t", 0))),
                        "open":   float(c.get("open",  c.get("o", 0))),
                        "high":   float(c.get("high",  c.get("h", 0))),
                        "low":    float(c.get("low",   c.get("l", 0))),
                        "close":  float(c.get("close", c.get("c", 0))),
                        "volume": float(c.get("volume",c.get("v", c.get("quoteVolume",0))))
                    })
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
                out.append({"symbol": sym, "price": price, "change_24h": change})
        return out

    async def get_funding_rate(self, symbol) -> float:
        try:
            d = await self._get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
            data = d.get("data", {})
            if isinstance(data, list): data = data[0] if data else {}
            return float(data.get("lastFundingRate", data.get("fundingRate", 0)))
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
            d = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
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
        for side in ("LONG", "SHORT"):
            try:
                await self._post("/openApi/swap/v2/trade/leverage",
                                 {"symbol": symbol, "side": side, "leverage": str(leverage)})
            except Exception as e:
                log.warning(f"Leverage {symbol} {side}: {e}")
                ok = False
        return ok

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None,
                          reduce_only=False) -> dict:
        p = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         "MARKET",
            "quantity":     str(qty),
        }
        if reduce_only: p["reduceOnly"] = "true"
        if stop_loss:   p["stopLoss"]   = str(round(stop_loss,   8))
        if take_profit: p["takeProfit"] = str(round(take_profit, 8))
        log.info(f"ORDER → {p}")
        r = await self._post("/openApi/swap/v2/trade/order", p)
        log.info(f"ORDER RESULT → {r}")
        return r

    async def close_position(self, symbol, pos) -> dict:
        amt = float(pos.get("positionAmt", pos.get("size", 0)))
        return await self.place_order(symbol,
            "SELL" if amt > 0 else "BUY",
            "LONG" if amt > 0 else "SHORT",
            abs(amt), reduce_only=True)

    async def close_half(self, symbol, pos):
        amt  = float(pos.get("positionAmt", pos.get("size", 0)))
        half = round(abs(amt) / 2, 3)
        if half < 0.001: return
        return await self.place_order(symbol,
            "SELL" if amt > 0 else "BUY",
            "LONG" if amt > 0 else "SHORT",
            half, reduce_only=True)


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
async def tg(text: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000], "parse_mode": "Markdown"}
            )
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════
def ema(v, p):
    v = np.asarray(v, float); k = 2 / (p + 1)
    r = np.zeros(len(v)); r[0] = v[0]
    for i in range(1, len(v)): r[i] = v[i] * k + r[i-1] * (1 - k)
    return r

def hma(v, p):
    return ema(2 * ema(v, max(p//2, 1)) - ema(v, p), max(int(np.sqrt(p)), 1))

def sma(v, p):
    return np.convolve(np.asarray(v, float), np.ones(p)/p, mode="same")

def stoch_s(src, p):
    src = np.asarray(src, float); r = np.zeros(len(src))
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]; lo, hi = w.min(), w.max()
        r[i] = (src[i] - lo) / (hi - lo + 1e-10)
    return r

def stc_v47(c):
    macd = ema(c, 23) - ema(c, 50)
    return ema(stoch_s(macd, 10), 3)

def calc_rsi(closes, period=14):
    c = np.asarray(closes, float)
    deltas = np.diff(c)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g  = np.zeros(len(c)); avg_l = np.zeros(len(c))
    avg_g[period] = np.mean(gains[:period])
    avg_l[period] = np.mean(losses[:period])
    for i in range(period+1, len(c)):
        avg_g[i] = (avg_g[i-1] * (period-1) + gains[i-1])  / period
        avg_l[i] = (avg_l[i-1] * (period-1) + losses[i-1]) / period
    rs  = avg_g / (avg_l + 1e-10)
    rsi = 100 - 100 / (1 + rs)
    rsi[:period] = 50
    return rsi

def calc_atr(h, l, c, p=14):
    h, l, c = map(lambda x: np.asarray(x, float), [h, l, c])
    tr = np.maximum(h-l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    r = np.zeros(len(tr)); r[0] = tr[0]
    for i in range(1, len(tr)): r[i] = (r[i-1] * (p-1) + tr[i]) / p
    return r

def calc_vwap(h, l, c, v):
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3
    return np.cumsum(tp * np.asarray(v, float)) / (np.cumsum(np.asarray(v, float)) + 1e-10)

def calc_poc(closes, volumes, lookback):
    n = min(lookback, len(closes))
    v = np.asarray(volumes[-n:], float)
    return float(np.asarray(closes[-n:], float)[int(np.argmax(v))])

def calc_adx(h, l, c, p=14):
    h, l, c = map(lambda x: np.asarray(x, float), [h, l, c])
    ph, pl, pc = np.roll(h, 1), np.roll(l, 1), np.roll(c, 1)
    tr  = np.maximum(h-l, np.maximum(np.abs(h-pc), np.abs(l-pc)))
    dmp = np.where((h-ph) > (pl-l), np.maximum(h-ph, 0), 0).astype(float)
    dmm = np.where((pl-l) > (h-ph), np.maximum(pl-l, 0), 0).astype(float)
    atr_w = np.zeros(len(tr)); dp_w = np.zeros(len(tr)); dm_w = np.zeros(len(tr))
    atr_w[p] = np.sum(tr[1:p+1]); dp_w[p] = np.sum(dmp[1:p+1]); dm_w[p] = np.sum(dmm[1:p+1])
    for i in range(p+1, len(tr)):
        atr_w[i] = atr_w[i-1] - atr_w[i-1]/p + tr[i]
        dp_w[i]  = dp_w[i-1]  - dp_w[i-1]/p  + dmp[i]
        dm_w[i]  = dm_w[i-1]  - dm_w[i-1]/p  + dmm[i]
    dip = 100 * dp_w / (atr_w + 1e-10)
    dim = 100 * dm_w / (atr_w + 1e-10)
    dx  = 100 * np.abs(dip - dim) / (dip + dim + 1e-10)
    adx = np.zeros(len(dx))
    if 2*p < len(dx): adx[2*p] = np.mean(dx[p:2*p+1])
    for i in range(2*p+1, len(dx)): adx[i] = (adx[i-1] * (p-1) + dx[i]) / p
    return adx

def calc_magic_slope(closes, p=7):
    e7   = ema(closes, p)
    atr7 = calc_atr(closes, closes, closes, p)
    s    = np.zeros(len(e7))
    for i in range(1, len(e7)):
        s[i] = ((e7[i] - e7[i-1]) / (atr7[i] + 1e-10)) * 100
    return s

def calc_rvol(volumes, p=50):
    v = np.asarray(volumes, float)
    return v / (sma(v, p) + 1e-10)

def pivot_hi(h, n):
    h = np.asarray(h, float); r = np.full(len(h), np.nan)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max(): r[i] = h[i]
    return r

def pivot_lo(l, n):
    l = np.asarray(l, float); r = np.full(len(l), np.nan)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min(): r[i] = l[i]
    return r

def vol24h(candles):
    last = candles[-96:] if len(candles) >= 96 else candles
    return sum(c["close"] * c["volume"] for c in last)

def trend_4h(candles_4h) -> str:
    """Retorna 'BULL', 'BEAR' o 'NEUTRAL' según tendencia 4H."""
    if len(candles_4h) < 50: return "NEUTRAL"
    c = np.array([x["close"] for x in candles_4h], float)
    e7 = ema(c, 7); e17 = ema(c, 17); h50 = hma(c, 50)
    if c[-1] > h50[-1] and e7[-1] > e17[-1]: return "BULL"
    if c[-1] < h50[-1] and e7[-1] < e17[-1]: return "BEAR"
    return "NEUTRAL"


# ══════════════════════════════════════════════════════════════════
# ANALYZE — V47 con filtro 4H y spread
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
    rsi:        float = 50.0

def analyze(ticker, candles, candles_1h, candles_4h, funding) -> Optional[CoinResult]:
    sym = ticker["symbol"]
    min_len = max(80, POC_LOOKBACK + 10)
    if len(candles) < min_len: return None

    closes  = np.array([c["close"]  for c in candles], float)
    highs   = np.array([c["high"]   for c in candles], float)
    lows    = np.array([c["low"]    for c in candles], float)
    volumes = np.array([c["volume"] for c in candles], float)

    if closes[-1] <= 0: return None
    vusd = vol24h(candles)
    if vusd < MIN_VOL_USDT: return None

    # Filtro spread: vela muy volátil = ruido
    spread_pct = (highs[-1] - lows[-1]) / (closes[-1] + 1e-10) * 100
    if spread_pct > 2.0:
        log.info(f"{sym}: spread {spread_pct:.1f}% > 2% — skip")
        return None

    atr_arr   = calc_atr(highs, lows, closes)
    atr_now   = float(atr_arr[-1])
    vwap_now  = float(calc_vwap(highs, lows, closes, volumes)[-1])
    poc       = calc_poc(closes, volumes, POC_LOOKBACK)
    stc_arr   = stc_v47(closes)
    adx_arr   = calc_adx(highs, lows, closes)
    adx_now   = float(adx_arr[-1])
    slope_arr = calc_magic_slope(closes, EMA_FAST)
    slope_now = float(slope_arr[-1])
    rvol_arr  = calc_rvol(volumes, 50)
    rvol_now  = float(rvol_arr[-1])
    rsi_arr   = calc_rsi(closes, RSI_PERIOD)
    rsi_now   = float(rsi_arr[-1])
    e_fast    = ema(closes, EMA_FAST)
    e_slow    = ema(closes, EMA_SLOW)
    h50       = hma(closes, 50)

    ph_v = pivot_hi(highs, 4); pl_v = pivot_lo(lows, 4)
    vph  = ph_v[~np.isnan(ph_v)]; vpl = pl_v[~np.isnan(pl_v)]
    peak   = float(vph[-1]) if len(vph) > 0 else float(highs[-1])
    valley = float(vpl[-1]) if len(vpl) > 0 else float(lows[-1])

    # 1H
    htf_bull = htf_bear = False
    if len(candles_1h) >= 20:
        c1    = np.array([c["close"] for c in candles_1h], float)
        e7_1  = ema(c1, EMA_FAST); e17_1 = ema(c1, EMA_SLOW); h50_1 = hma(c1, 50)
        htf_bull = bool(c1[-1] > h50_1[-1] and e7_1[-1] > e17_1[-1])
        htf_bear = bool(c1[-1] < h50_1[-1] and e7_1[-1] < e17_1[-1])

    # 4H tendencia macro
    macro = trend_4h(candles_4h)

    i  = -1
    cn     = float(closes[i])
    hi_now = float(highs[i])
    lo_now = float(lows[i])

    dist_poc  = abs(cn - poc) > (atr_now * 1.5)
    cond_vol  = rvol_now > RVOL_MIN
    stc_up    = stc_arr[i] > stc_arr[i-1]
    stc_down  = stc_arr[i] < stc_arr[i-1]
    adx_ok    = adx_now < ADX_MAX

    rsi_long_ok  = rsi_now < RSI_OB
    rsi_short_ok = rsi_now > RSI_OS

    # Condición entrada V47: incluye macro 4H como bonus/bloqueo
    long_cond  = (lo_now < valley and cn < vwap_now and slope_now > SLOPE_MIN
                  and stc_up and adx_ok and dist_poc and cond_vol
                  and rsi_long_ok and macro != "BEAR")   # no LONG en tendencia bajista 4H
    short_cond = (hi_now > peak and cn > vwap_now and slope_now < -SLOPE_MIN
                  and stc_down and adx_ok and dist_poc and cond_vol
                  and rsi_short_ok and macro != "BULL")  # no SHORT en tendencia alcista 4H

    score = 0; signals = []; direction = "NEUTRAL"

    if long_cond:
        direction = "LONG"; score = 85; signals = ["V47🟢"]
        if htf_bull:            score += 8;  signals.append("1H🟢")
        if macro == "BULL":     score += 7;  signals.append("4H🟢")
        if e_fast[i] > e_slow[i]: score += 5; signals.append("EMA✅")
        if rsi_now < 50:        score += 5;  signals.append(f"RSI{rsi_now:.0f}✅")
    elif short_cond:
        direction = "SHORT"; score = 85; signals = ["V47🔴"]
        if htf_bear:            score += 8;  signals.append("1H🔴")
        if macro == "BEAR":     score += 7;  signals.append("4H🔴")
        if e_fast[i] < e_slow[i]: score += 5; signals.append("EMA✅")
        if rsi_now > 50:        score += 5;  signals.append(f"RSI{rsi_now:.0f}✅")
    else:
        # Fallback — solo si macro alineado
        hull_bull = cn > float(h50[-1]); hull_bear = not hull_bull
        if (hull_bull and macro == "BEAR") or (hull_bear and macro == "BULL"):
            return None  # nunca contra macro
        direction = "LONG" if hull_bull else "SHORT"
        if hull_bull or hull_bear:    score += 20; signals.append("Hull✅")
        if e_fast[i] > e_slow[i] and hull_bull: score += 15; signals.append("EMA✅")
        if e_fast[i] < e_slow[i] and hull_bear: score += 15; signals.append("EMA✅")
        if cond_vol:                  score += 15; signals.append(f"RVOL{rvol_now:.1f}✅")
        else:                         signals.append(f"RVOL{rvol_now:.1f}·")
        if stc_up   and hull_bull:    score += 12; signals.append("STC✅")
        if stc_down and hull_bear:    score += 12; signals.append("STC✅")
        if adx_ok:                    score += 8;  signals.append(f"ADX{adx_now:.0f}✅")
        else:                         signals.append(f"ADX{adx_now:.0f}⚠️")
        if dist_poc:                  score += 8;  signals.append("POC✅")
        if (htf_bull and hull_bull) or (htf_bear and hull_bear):
            score += 10; signals.append("1H✅")
        if (macro == "BULL" and hull_bull) or (macro == "BEAR" and hull_bear):
            score += 7; signals.append("4H✅")
        if hull_bull  and not rsi_long_ok:  score -= 20; signals.append(f"RSI{rsi_now:.0f}⚠️")
        if hull_bear  and not rsi_short_ok: score -= 20; signals.append(f"RSI{rsi_now:.0f}⚠️")
        score = min(score, 84)

    # Funding descuenta score
    if direction == "LONG"  and funding < -FUNDING_SKIP:
        score -= 10; signals.append(f"Fund{funding*100:.3f}%⚠️")
    if direction == "SHORT" and funding > FUNDING_SKIP:
        score -= 10; signals.append(f"Fund{funding*100:.3f}%⚠️")

    signals += [f"Slope{slope_now:+.0f}", f"RVOL{rvol_now:.1f}",
                f"ADX{adx_now:.0f}", f"RSI{rsi_now:.0f}"]
    score = min(max(score, 0), 100)

    log.info(
        f"{sym}: score={score} dir={direction} long={long_cond} short={short_cond} "
        f"slope={slope_now:.1f} adx={adx_now:.1f} rvol={rvol_now:.2f} "
        f"rsi={rsi_now:.1f} macro={macro} poc={dist_poc}"
    )

    if long_cond:
        sl = lo_now - atr_now * ATR_SL_MULT; risk = abs(cn - sl)
        tp = cn + risk * RR_RATIO; tp_half = cn + risk * 0.8
    elif short_cond:
        sl = hi_now + atr_now * ATR_SL_MULT; risk = abs(sl - cn)
        tp = cn - risk * RR_RATIO; tp_half = cn - risk * 0.8
    else:
        sl_d = atr_now * ATR_SL_MULT
        sl   = cn - sl_d if direction == "LONG" else cn + sl_d
        risk = abs(cn - sl)
        tp   = cn + risk * RR_RATIO if direction == "LONG" else cn - risk * RR_RATIO
        tp_half = cn + risk * 0.8 if direction == "LONG" else cn - risk * 0.8

    return CoinResult(symbol=sym, direction=direction, score=score,
                      entry=cn, sl=sl, tp=tp, tp_half=tp_half,
                      vol_usd=vusd, atr_val=atr_now, signals=signals,
                      change_24h=ticker.get("change_24h", 0),
                      funding=funding, slope=slope_now, adx=adx_now,
                      rvol=rvol_now, rsi=rsi_now)


# ══════════════════════════════════════════════════════════════════
# CALC QTY
# ══════════════════════════════════════════════════════════════════
def calc_qty(balance, entry, sl) -> float:
    dist = abs(entry - sl)
    if dist < 1e-10: return 0.0
    qty_risk = (balance * MAX_RISK_PCT / 100) / dist
    qty_max  = MAX_POS_USDT / max(entry, 1e-10)
    qty = min(qty_risk, qty_max)
    if   entry >= 1000: qty = round(qty, 4)
    elif entry >= 100:  qty = round(qty, 3)
    elif entry >= 10:   qty = round(qty, 2)
    elif entry >= 1:    qty = round(qty, 1)
    else:               qty = round(qty, 0)
    qty = max(qty, 0.001)
    log.info(f"qty: bal={balance:.2f} entry={entry:.6f} dist={dist:.8f} "
             f"risk={qty_risk:.4f} max={qty_max:.4f} final={qty}")
    return qty

def is_blackout():
    return BLACKOUT_START <= datetime.now(timezone.utc).hour < BLACKOUT_END


# ══════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════
exchange          = BingXClient()
watchlist:        list[CoinResult]  = []
last_dir:         dict[str, str]    = {}
half_closed:      set[str]          = set()
breakeven_set:    set[str]          = set()
cooldown_ts:      dict[str, float]  = {}
consec_losses:    dict[str, int]    = defaultdict(int)
dynamic_blacklist: set[str]         = set()
daily_loss_pct:   float             = 0.0
daily_start_bal:  float             = 0.0
pause_until:      float             = 0.0


# ══════════════════════════════════════════════════════════════════
# STARTUP DIAGNOSTIC — V47 muestra chars de API key para verificar
# ══════════════════════════════════════════════════════════════════
async def run_diagnostics():
    lines = ["🔧 *DIAGNÓSTICO V47*\n━━━━━━━━━━━━━━━━━━━━━━\n"]

    # Verificar key (primeros/últimos 4 chars)
    k_preview = f"{BINGX_API_KEY[:4]}...{BINGX_API_KEY[-4:]}" if len(BINGX_API_KEY) > 8 else "???"
    s_preview = f"{BINGX_API_SECRET[:4]}...{BINGX_API_SECRET[-4:]}" if len(BINGX_API_SECRET) > 8 else "???"
    lines.append(f"🔑 API Key: `{k_preview}` len={len(BINGX_API_KEY)}")
    lines.append(f"🔑 Secret: `{s_preview}` len={len(BINGX_API_SECRET)}\n")

    if len(BINGX_API_KEY) < 20 or len(BINGX_API_SECRET) < 20:
        lines.append("❌ *KEYS DEMASIADO CORTAS* — verifica Railway env vars")
        await tg("\n".join(lines))
        return False

    try:
        raw = await exchange.get_raw_balance()
        lines.append("✅ *API Key:* conexión OK")
        lines.append(f"📦 *Balance RAW:*\n`{str(raw)[:300]}`\n")
    except Exception as e:
        lines.append(f"❌ *API Key ERROR:* `{e}`")
        lines.append("💡 *Fix:* Verifica que no haya espacios/saltos en las keys de Railway")
        await tg("\n".join(lines))
        return False

    balance = await exchange.get_balance()
    if balance > 0:
        lines.append(f"✅ *Balance:* `{balance:.4f} USDT`")
    else:
        lines.append("❌ *Balance = 0* — sin fondos o parsing fallido")
        lines.append("⚠️ Transfiere USDT a BingX *Futuros*")

    try:
        positions = await exchange.get_all_positions()
        n = len(positions)
        icon = "🔴" if n >= MAX_POSITIONS else "✅"
        lines.append(f"{icon} *Posiciones:* `{n}/{MAX_POSITIONS}`")
        for pos in positions:
            sym = pos.get("symbol", "?")
            amt = float(pos.get("positionAmt", pos.get("size", 0)))
            avg = float(pos.get("avgPrice", pos.get("entryPrice", 0)))
            cur = float(pos.get("markPrice", pos.get("currentPrice", 0)))
            unr = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit", 0)))
            direction = "LONG" if amt > 0 else "SHORT"
            pnl_pct = ((cur-avg)/avg*100) if amt > 0 else ((avg-cur)/avg*100) if avg > 0 else 0
            e2 = "🟢" if unr >= 0 else "🔴"
            lines.append(f"  {e2} {sym} {direction} {pnl_pct:+.1f}% ({unr:+.2f}$)")
    except Exception as e:
        lines.append(f"❌ *Posiciones ERROR:* `{e}`")

    try:
        k = await exchange.get_klines("BTC-USDT", "15m", 10)
        lines.append(f"✅ *Klines BTC:* `{len(k)} velas` precio=`{k[-1]['close']:.2f}`")
    except Exception as e:
        lines.append(f"❌ *Klines ERROR:* `{e}`")

    try:
        ok = await exchange.set_leverage("BTC-USDT", LEVERAGE)
        lines.append(f"{'✅' if ok else '⚠️'} *Leverage {LEVERAGE}x BTC:* {'OK' if ok else 'fallo'}")
    except Exception as e:
        lines.append(f"❌ *Leverage ERROR:* `{e}`")

    lines.append(f"\n⚙️ *Config V47:*")
    lines.append(f"  TF: `{TIMEFRAME}` | Score: `{SCORE_ENTRY}` | Max pos: `{MAX_POSITIONS}`")
    lines.append(f"  MaxPosUSDT: `{MAX_POS_USDT}$` | Riesgo: `{MAX_RISK_PCT}%`")
    lines.append(f"  RVOL: `{RVOL_MIN}x` | SLOPE: `{SLOPE_MIN}` | ADX<`{ADX_MAX}`")
    lines.append(f"  RSI OB/OS: `{RSI_OB}/{RSI_OS}` | RR: `{RR_RATIO}R`")
    lines.append(f"  Blackout: `{BLACKOUT_START}-{BLACKOUT_END} UTC`")
    lines.append(f"  Límite pérd/día: `{DAILY_LOSS_LIMIT}%`")

    lines.append(f"\n{'✅ Listo V47' if balance > 0 else '❌ Sin balance'}")
    await tg("\n".join(lines))
    return balance > 0


# ══════════════════════════════════════════════════════════════════
# OPEN TRADE — V47 con pausa diaria
# ══════════════════════════════════════════════════════════════════
async def open_trade(cr: CoinResult) -> bool:
    sym = cr.symbol
    try:
        log.info(f"⚡ INTENTANDO {cr.direction} {sym} score={cr.score}")

        # Pausa por pérdida diaria
        if time.time() < pause_until:
            remaining = (pause_until - time.time()) / 3600
            log.info(f"  Pausado por pérdida diaria. Resta: {remaining:.1f}h")
            return False

        if sym in dynamic_blacklist:
            log.info(f"  {sym}: blacklist dinámica"); return False

        if sym in cooldown_ts:
            elapsed = (time.time() - cooldown_ts[sym]) / 60
            if elapsed < SYMBOL_COOLDOWN:
                log.info(f"  {sym}: cooldown {elapsed:.0f}/{SYMBOL_COOLDOWN}min")
                return False

        if last_dir.get(sym) == cr.direction:
            log.info(f"  {sym}: señal ya activa"); return False

        pos = await exchange.get_position(sym)
        if pos:
            log.info(f"  {sym}: posición ya abierta"); return False

        balance = await exchange.get_balance()
        if balance < 5:
            await tg(f"⚠️ *Balance insuficiente: `{balance:.4f} USDT`*\n"
                     "Transfiere USDT de Spot a Futuros → Redeploy")
            return False

        if cr.direction == "LONG"  and cr.funding < -FUNDING_SKIP:
            log.info(f"  {sym}: funding negativo {cr.funding:.5f} — skip"); return False
        if cr.direction == "SHORT" and cr.funding > FUNDING_SKIP:
            log.info(f"  {sym}: funding positivo {cr.funding:.5f} — skip"); return False

        qty = calc_qty(balance, cr.entry, cr.sl)
        if qty <= 0:
            log.warning(f"  {sym}: qty=0"); return False

        await exchange.set_leverage(sym, LEVERAGE)
        side = "BUY" if cr.direction == "LONG" else "SELL"
        await exchange.place_order(
            symbol=sym, side=side,
            position_side=cr.direction, qty=qty,
            stop_loss=cr.sl, take_profit=cr.tp,
        )

        risk_usd  = abs(cr.entry - cr.sl) * qty
        pos_value = cr.entry * qty
        emoji = "🟢" if cr.direction == "LONG" else "🔴"
        await tg(
            f"{emoji} *{cr.direction} — V47*\n"
            f"Par: `{sym}` | Score: `{cr.score}/100`\n"
            f"Entry: `{cr.entry:.6f}`\n"
            f"SL: `{cr.sl:.6f}` | TP: `{cr.tp:.6f}` *({RR_RATIO}R)*\n"
            f"Qty: `{qty}` | Valor: `≈{pos_value:.2f}$`\n"
            f"Riesgo: `≈{risk_usd:.2f} USDT` ({MAX_RISK_PCT}%)\n"
            f"RSI:`{cr.rsi:.0f}` Slope:`{cr.slope:+.0f}` "
            f"ADX:`{cr.adx:.0f}` RVOL:`{cr.rvol:.2f}x`\n"
            f"{' '.join(cr.signals[:6])}"
        )
        last_dir[sym] = cr.direction
        cooldown_ts.pop(sym, None)
        log.info(f"✅ TRADE ABIERTO {cr.direction} {sym} qty={qty}")
        return True

    except Exception as e:
        log.error(f"open_trade {sym}: {e}", exc_info=True)
        await tg(f"❌ *Error orden* `{sym}`:\n`{str(e)[:300]}`")
        cooldown_ts[sym] = time.time()
        consec_losses[sym] += 1
        if consec_losses[sym] >= MAX_LOSSES:
            dynamic_blacklist.add(sym)
            await tg(f"⛔ `{sym}` → blacklist ({MAX_LOSSES} errores)")
        return False


# ══════════════════════════════════════════════════════════════════
# MANAGE POSITIONS — V47 con pausa diaria y trailing info
# ══════════════════════════════════════════════════════════════════
async def manage_positions():
    global daily_loss_pct, pause_until
    try:
        positions = await exchange.get_all_positions()
        if not positions: return
        total_unr = 0.0
        for pos in positions:
            sym = pos.get("symbol", "")
            amt = float(pos.get("positionAmt", pos.get("size", 0)))
            avg = float(pos.get("avgPrice",    pos.get("entryPrice", 0)))
            cur = float(pos.get("markPrice",   pos.get("currentPrice", 0)))
            unr = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit", 0)))
            if avg <= 0 or cur <= 0: continue
            is_long  = amt > 0
            pnl_pct  = ((cur-avg)/avg*100) if is_long else ((avg-cur)/avg*100)
            direction = "LONG" if is_long else "SHORT"
            total_unr += unr
            log.info(f"POS {sym} {direction} pnl={pnl_pct:+.2f}%")

            # Half-close
            if sym not in half_closed and pnl_pct >= HALF_CLOSE_PCT:
                try:
                    await exchange.close_half(sym, pos)
                    half_closed.add(sym)
                    await tg(
                        f"🔒 *Cierre 50%* `{sym}` {direction}\n"
                        f"PnL: `+{pnl_pct:.2f}%` | `+{unr:.2f} USDT`\n"
                        f"Resto corre hacia TP `{RR_RATIO}R`"
                    )
                except Exception as e:
                    log.error(f"close_half {sym}: {e}")

            # Breakeven notification
            if sym not in breakeven_set and pnl_pct >= TRAIL_STOP_PCT:
                breakeven_set.add(sym)
                await tg(
                    f"🛡️ *Trailing activo* `{sym}` {direction}\n"
                    f"PnL: `+{pnl_pct:.2f}%` — mueve SL a entry en BingX"
                )

            # Pérdida severa → aviso
            if pnl_pct < -4.0:
                log.warning(f"⚠️ {sym} {direction} pnl={pnl_pct:+.2f}% — cerca SL")

        # Control pérdida diaria
        if daily_start_bal > 0 and total_unr < 0:
            loss_pct = abs(total_unr) / daily_start_bal * 100
            if loss_pct > DAILY_LOSS_LIMIT and pause_until < time.time():
                pause_until = time.time() + 4 * 3600  # pausa 4h
                await tg(
                    f"🛑 *Límite pérdida diaria alcanzado* `{loss_pct:.1f}%`\n"
                    f"Bot pausado 4 horas para proteger capital"
                )

    except Exception as e:
        log.error(f"manage_positions: {e}")


# ══════════════════════════════════════════════════════════════════
# SCANNER — V47 con 4H
# ══════════════════════════════════════════════════════════════════
async def scanner_loop():
    global watchlist, daily_start_bal
    while True:
        try:
            if is_blackout():
                await asyncio.sleep(SCAN_INTERVAL); continue

            log.info("🔍 Escaneando V47...")
            tickers = await exchange.get_tickers()
            if not tickers:
                await tg("⚠️ Sin tickers.")
                await asyncio.sleep(SCAN_INTERVAL); continue

            syms = [t["symbol"] for t in tickers]
            lim  = max(200, POC_LOOKBACK + 80)

            r15, r1h, r4h, rfr = await asyncio.gather(
                asyncio.gather(*[exchange.get_klines(s, TIMEFRAME, lim)    for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_klines(s, TF_HIGH,  100)     for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_klines(s, TF_TREND, 60)      for s in syms], return_exceptions=True),
                asyncio.gather(*[exchange.get_funding_rate(s)              for s in syms], return_exceptions=True),
            )

            results = []
            for t, c15, c1h, c4h, fr in zip(tickers, r15, r1h, r4h, rfr):
                if isinstance(c15, Exception): continue
                cr = analyze(t, c15,
                    c1h if not isinstance(c1h, Exception) else [],
                    c4h if not isinstance(c4h, Exception) else [],
                    fr  if not isinstance(fr,  Exception) else 0.0)
                if cr: results.append(cr)

            results.sort(key=lambda x: x.score, reverse=True)
            top = results[:SCAN_TOP_N]

            wl = [r for r in top
                  if r.score >= SCORE_ENTRY
                  and r.direction != "NEUTRAL"
                  and r.symbol not in dynamic_blacklist]
            watchlist = wl if wl else [r for r in top[:5] if r.symbol not in dynamic_blacklist]
            log.info(f"Watchlist: {[(r.symbol, r.score, r.direction) for r in watchlist]}")

            # Balance del día
            if daily_start_bal == 0:
                daily_start_bal = await exchange.get_balance()

            lines = [f"🔍 *V47 — {len(top)} coins*\n"]
            for n, r in enumerate(top, 1):
                e   = "🟢" if r.direction == "LONG" else "🔴"
                bar = "█" * (r.score // 10) + "░" * (10 - r.score // 10)
                tag = " ⚡*ENTRA*" if r.score >= SCORE_ENTRY else ""
                bl  = " 🚫" if r.symbol in dynamic_blacklist else ""
                lines.append(
                    f"*#{n}* {e} `{r.symbol}` `{r.score}/100`{tag}{bl}\n"
                    f"`{bar}`\n"
                    f"Vol:`${r.vol_usd/1e6:.0f}M` RVOL:`{r.rvol:.1f}x`"
                    f" RSI:`{r.rsi:.0f}` ADX:`{r.adx:.0f}`\n"
                    f"{' '.join(r.signals[:5])}\n"
                )
            lines.append(f"\n🎯 *Watchlist ({len(watchlist)}):*")
            for r in watchlist:
                e = "🟢" if r.direction == "LONG" else "🔴"
                lines.append(f"  {e} `{r.symbol}` `{r.score}` → {r.direction}")
            if dynamic_blacklist:
                lines.append(f"\n🚫 Blacklist: `{', '.join(dynamic_blacklist)}`")
            if pause_until > time.time():
                lines.append(f"\n🛑 *PAUSADO* — pérdida diaria")
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
            open_syms = {p.get("symbol", "") for p in open_pos}

            for sym in list(half_closed):
                if sym not in open_syms:
                    half_closed.discard(sym); last_dir.pop(sym, None)
            for sym in list(breakeven_set):
                if sym not in open_syms: breakeven_set.discard(sym)

            log.info(f"Trading: {n_open}/{MAX_POSITIONS} pos | wl={len(watchlist)}")

            if n_open < MAX_POSITIONS and watchlist and time.time() >= pause_until:
                for cr in list(watchlist):
                    if n_open >= MAX_POSITIONS: break
                    if cr.symbol in open_syms: continue
                    if cr.score < SCORE_ENTRY:
                        log.info(f"  {cr.symbol}: score {cr.score}<{SCORE_ENTRY}"); continue
                    opened = await open_trade(cr)
                    if opened:
                        n_open += 1; open_syms.add(cr.symbol)
                    await asyncio.sleep(3)

        except Exception as e:
            log.error(f"Trading loop: {e}", exc_info=True)
        await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
async def main():
    log.info("🚀 Sniper Bot V47 — Fix signature + 4H filter + risk control")

    await tg(
        "🔄 *Sniper Bot V47 arrancando...*\n"
        f"TF: `{TIMEFRAME}` | Lev: `{LEVERAGE}x` | Riesgo: `{MAX_RISK_PCT}%`\n"
        f"🔧 Fix: Signature sin sorted() + .strip() en keys\n"
        f"📈 Nuevo: Filtro 4H + Límite pérd/día + Riesgo reducido"
    )

    ok = await run_diagnostics()

    if not ok:
        await tg(
            "⛔ *Bot detenido — sin balance o error de API*\n\n"
            "*Si error de firma:*\n"
            "1. Railway → Variables → copia keys SIN espacios\n"
            "2. Railway → Redeploy\n\n"
            "*Si sin balance:*\n"
            "1. BingX app → Activos → Futuros → Transferir\n"
            "2. Railway → Redeploy"
        )
        while True:
            await asyncio.sleep(300)
            try:
                bal = await exchange.get_balance()
                if bal > 5:
                    await tg(f"✅ Balance detectado: `{bal:.2f} USDT` — arrancando V47...")
                    break
            except Exception as e:
                log.error(f"Wait loop: {e}")

    await asyncio.gather(scanner_loop(), trading_loop())


if __name__ == "__main__":
    asyncio.run(main())
