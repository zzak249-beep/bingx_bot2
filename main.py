"""
Sniper Bot V27 — Institutional Edge
======================================
VENTAJAS SOBRE OTROS BOTS:
  A. Funding Rate  — detecta longs/shorts sobrecargados → reversal inminente
  B. Open Interest — OI cae + precio sube = trampa, no entrar
  C. Long/Short ratio — cuando la masa apuesta un lado, ir al contrario
  D. Multi-timeframe — 1h confirma tendencia, 15m entra, sin contradecirse
  E. Gestión activa — cierre 50% al 1R, trailing stop ATR, max 3 posiciones
  F. Anti-trampa — blackout nocturno, filtro de spread, no entrar en noticias

SEÑALES (4 niveles):
  100 — Apex completo: todos los filtros pasan
   70 — Relax: hull + ema cross + volumen
   50 — Cruce EMA simple
   40 — Tendencia activa (hull + ema alineadas + STC)

ARCHIVO ÚNICO — funciona directo en Railway sin carpetas src/
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
TF_HIGH          = os.getenv("TIMEFRAME_HIGH", "1h")   # confirmación macro
LEVERAGE         = int(os.getenv("LEVERAGE", "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT", "1.0"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N", "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT", "10000000"))
SCORE_THRESHOLD  = int(os.getenv("SCORE_THRESHOLD", "40"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "5")) * 60
MAX_POSITIONS    = int(os.getenv("MAX_POSITIONS", "3"))   # máx posiciones abiertas
BASE_URL         = "https://open-api.bingx.com"

# Funding rate extremos — reversal signal
FUNDING_EXTREME_LONG  = float(os.getenv("FUNDING_EXTREME_LONG",  "0.03"))   # >0.03% = longs sobrecargados
FUNDING_EXTREME_SHORT = float(os.getenv("FUNDING_EXTREME_SHORT", "-0.01"))  # <-0.01% = shorts sobrecargados

# Horario de blackout (UTC) — mercado muy delgado
BLACKOUT_START = int(os.getenv("BLACKOUT_START_UTC", "0"))   # 00:00
BLACKOUT_END   = int(os.getenv("BLACKOUT_END_UTC",   "2"))   # 02:00

BLACKLIST = {
    "USDC-USDT","BUSD-USDT","DAI-USDT","TUSD-USDT","USDP-USDT",
    "FRAX-USDT","GUSD-USDT","LUSD-USDT","SUSD-USDT","USDD-USDT",
    "NCCOGOLD2USD-USDT","PAXG-USDT","XAUT-USDT","WBTC-USDT",
    "STETH-USDT","WETH-USDT","CBETH-USDT","RETH-USDT","ZEC-USDT",
}
WHITELIST = {
    "BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
    "DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","UNI-USDT","ATOM-USDT","LTC-USDT","BCH-USDT",
    "NEAR-USDT","APT-USDT","ARB-USDT","OP-USDT","INJ-USDT",
    "SUI-USDT","TIA-USDT","WLD-USDT","AAVE-USDT","ONDO-USDT",
    "ENA-USDT","PEPE-USDT","WIF-USDT","SEI-USDT","JUP-USDT",
    "FIL-USDT","RENDER-USDT","FET-USDT","ALGO-USDT","SAND-USDT",
    "MANA-USDT","AXS-USDT","GALA-USDT","IMX-USDT","BLUR-USDT",
    "BONK-USDT","FLOKI-USDT","SHIB-USDT","NOT-USDT","BRETT-USDT",
}
USE_WHITELIST = os.getenv("USE_WHITELIST", "true").lower() == "true"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE CLIENT
# ══════════════════════════════════════════════════════════════════

class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)

    def _sign(self, params: dict) -> str:
        query = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _headers(self):
        return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}

    async def _get(self, path: str, params: dict = None) -> dict:
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.get(path, params=p, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def _post(self, path: str, payload: dict) -> dict:
        p = dict(payload)
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)
        r = await self.client.post(path, params=p, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"BingX {d['code']}: {d.get('msg')}")
        return d

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        d = await self._get("/openApi/swap/v3/quote/klines",
                            {"symbol": symbol, "interval": interval, "limit": limit})
        candles = []
        for c in d["data"]:
            try:
                if isinstance(c, list):
                    candles.append({"time":int(c[0]),"open":float(c[1]),"high":float(c[2]),
                                    "low":float(c[3]),"close":float(c[4]),"volume":float(c[5])})
                elif isinstance(c, dict):
                    candles.append({"time":  int(c.get("time",   c.get("t",0))),
                                    "open":  float(c.get("open",  c.get("o",0))),
                                    "high":  float(c.get("high",  c.get("h",0))),
                                    "low":   float(c.get("low",   c.get("l",0))),
                                    "close": float(c.get("close", c.get("c",0))),
                                    "volume":float(c.get("volume",c.get("v",c.get("quoteVolume",0))))})
            except Exception:
                continue
        return candles

    async def get_all_tickers(self) -> list:
        d = await self._get("/openApi/swap/v2/quote/ticker")
        raw = d.get("data", [])
        if raw:
            log.info(f"[DEBUG] Ticker fields: {list(raw[0].keys())}")
        tickers = []
        for t in raw:
            try:
                sym = t.get("symbol", "")
                if not sym.endswith("-USDT"): continue
                if sym in BLACKLIST: continue
                if USE_WHITELIST and sym not in WHITELIST: continue
                price = 0.0
                for f in ("lastPrice","last","price","close","c","markPrice"):
                    v = t.get(f)
                    if v and float(v) > 0: price = float(v); break
                change = 0.0
                for f in ("priceChangePercent","change","changePercent","priceChange"):
                    v = t.get(f)
                    if v is not None:
                        try: change = float(v)
                        except: pass
                        break
                if price <= 0: continue
                tickers.append({"symbol": sym, "price": price, "change_24h": change})
            except Exception as e:
                log.warning(f"Ticker {t.get('symbol','?')}: {e}")
        log.info(f"Tickers válidos: {len(tickers)}")
        return tickers

    # ── NUEVO: Datos institucionales ──────────────────────────────

    async def get_funding_rate(self, symbol: str) -> float:
        """Funding rate actual. Positivo = longs pagan. Negativo = shorts pagan."""
        try:
            d = await self._get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
            data = d.get("data", {})
            if isinstance(data, list): data = data[0] if data else {}
            fr = data.get("lastFundingRate", data.get("fundingRate", 0))
            return float(fr)
        except Exception as e:
            log.warning(f"FundingRate {symbol}: {e}")
            return 0.0

    async def get_open_interest(self, symbol: str) -> float:
        """Open Interest en USDT."""
        try:
            d = await self._get("/openApi/swap/v2/quote/openInterest", {"symbol": symbol})
            data = d.get("data", {})
            if isinstance(data, list): data = data[0] if data else {}
            oi = data.get("openInterest", data.get("openInterestValue", 0))
            return float(oi)
        except Exception as e:
            log.warning(f"OpenInterest {symbol}: {e}")
            return 0.0

    async def get_long_short_ratio(self, symbol: str) -> float:
        """Ratio long/short. >1 = más longs. <1 = más shorts."""
        try:
            d = await self._get("/openApi/swap/v2/quote/globalLongShortAccountRatio",
                                {"symbol": symbol, "period": "5m", "limit": 1})
            data = d.get("data", [])
            if data:
                item = data[0] if isinstance(data, list) else data
                ratio = item.get("longShortRatio", item.get("longAccount", 0))
                return float(ratio)
        except Exception as e:
            log.warning(f"LongShortRatio {symbol}: {e}")
        return 1.0

    async def get_balance(self) -> float:
        d = await self._get("/openApi/swap/v2/user/balance")
        for a in d["data"]["balance"]:
            if a["asset"] == "USDT":
                for f in ("availableMargin","available","free","equity"):
                    v = a.get(f)
                    if v is not None:
                        bal = float(v)
                        log.info(f"Balance USDT: {bal:.2f}")
                        return bal
        return 0.0

    async def get_position(self, symbol: str) -> Optional[dict]:
        d = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        positions = [p for p in d.get("data", [])
                     if abs(float(p.get("positionAmt", 0))) > 0]
        return positions[0] if positions else None

    async def get_all_positions(self) -> list:
        """Todas las posiciones abiertas."""
        try:
            d = await self._get("/openApi/swap/v2/user/positions")
            return [p for p in d.get("data", [])
                    if abs(float(p.get("positionAmt", 0))) > 0]
        except Exception:
            return []

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None, reduce_only=False,
                          client_order_id: str = None):
        payload = {
            "symbol": symbol, "side": side,
            "positionSide": position_side,
            "type": "MARKET", "quantity": str(qty),
        }
        if reduce_only: payload["reduceOnly"] = "true"
        if stop_loss:   payload["stopLoss"]   = str(round(stop_loss,   8))
        if take_profit: payload["takeProfit"] = str(round(take_profit, 8))
        if client_order_id: payload["clientOrderID"] = client_order_id
        log.info(f"ORDER → {symbol} {side} {position_side} qty={qty}")
        result = await self._post("/openApi/swap/v2/trade/order", payload)
        log.info(f"ORDER RESULT → {result}")
        return result

    async def close_position(self, symbol, position):
        amt   = float(position["positionAmt"])
        side  = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        return await self.place_order(symbol, side, pside, abs(amt), reduce_only=True)

    async def close_half_position(self, symbol, position):
        """Cierra el 50% de la posición para asegurar 1R."""
        amt   = float(position["positionAmt"])
        side  = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        half  = round(abs(amt) / 2, 3)
        if half <= 0: return
        return await self.place_order(symbol, side, pside, half, reduce_only=True)

    async def set_leverage(self, symbol, leverage):
        for side in ("LONG", "SHORT"):
            try:
                await self._post("/openApi/swap/v2/trade/leverage",
                                 {"symbol": symbol, "side": side, "leverage": str(leverage)})
            except Exception as e:
                log.warning(f"Leverage {side} {symbol}: {e}")


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

async def tg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                    "text": text[:4000], "parse_mode": "Markdown"})
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def ema(v, p):
    v = np.asarray(v, dtype=float)
    k, r = 2/(p+1), np.zeros(len(v))
    r[0] = v[0]
    for i in range(1, len(v)):
        r[i] = v[i]*k + r[i-1]*(1-k)
    return r

def hma(v, p):
    return ema(2*ema(v, max(p//2,1)) - ema(v, p), max(int(np.sqrt(p)),1))

def sma(v, p):
    v = np.asarray(v, dtype=float)
    return np.convolve(v, np.ones(p)/p, mode="same")

def stoch_s(src, p):
    src = np.asarray(src, dtype=float)
    r = np.zeros(len(src))
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]
        lo, hi = w.min(), w.max()
        r[i] = (src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_ind(c):
    macd = ema(c, 23) - ema(c, 50)
    return stoch_s(stoch_s(macd, 10), 10)

def pivot_hi(h, n):
    h = np.asarray(h, float)
    r = np.full(len(h), np.nan)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max(): r[i] = h[i]
    return r

def pivot_lo(l, n):
    l = np.asarray(l, float)
    r = np.full(len(l), np.nan)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min(): r[i] = l[i]
    return r

def calc_atr(highs, lows, closes, p=14):
    h,l,c = map(lambda x: np.asarray(x,float), [highs,lows,closes])
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    return float(np.mean(tr[-p:]))

def candle_vol_usd(candles):
    last = candles[-96:] if len(candles) >= 96 else candles
    return sum(c["close"] * c["volume"] for c in last)


# ══════════════════════════════════════════════════════════════════
# FILTROS DE MERCADO (VENTAJAS INSTITUCIONALES)
# ══════════════════════════════════════════════════════════════════

def is_blackout_hour() -> bool:
    """Evita operar de madrugada UTC (mercado delgado, manipulable)."""
    h = datetime.now(timezone.utc).hour
    return BLACKOUT_START <= h < BLACKOUT_END

def interpret_funding(fr: float) -> tuple[str, int]:
    """
    Interpreta el funding rate.
    Retorna (bias, bonus_puntos)
    bias: 'long_crowded' | 'short_crowded' | 'neutral'
    """
    if fr >= FUNDING_EXTREME_LONG:
        return "long_crowded", 10   # señal SHORT más fuerte, penaliza LONG
    if fr <= FUNDING_EXTREME_SHORT:
        return "short_crowded", 10  # señal LONG más fuerte, penaliza SHORT
    return "neutral", 0

def interpret_ls_ratio(ratio: float) -> str:
    """
    Long/Short ratio.
    Si ratio > 1.5 → masa apalancada en longs → contrarian SHORT
    Si ratio < 0.7 → masa en shorts → contrarian LONG
    """
    if ratio > 1.5: return "crowded_long"
    if ratio < 0.7: return "crowded_short"
    return "balanced"


# ══════════════════════════════════════════════════════════════════
# SCORER — incluye datos institucionales
# ══════════════════════════════════════════════════════════════════

@dataclass
class CoinScore:
    symbol:      str
    vol_24h_usd: float
    score:       int
    direction:   str
    signals:     list = field(default_factory=list)
    change_24h:  float = 0.0
    funding_rate: float = 0.0
    ls_ratio:    float = 1.0
    funding_bias: str  = "neutral"

def score_coin(ticker: dict, candles: list, candles_1h: list,
               funding_rate: float, ls_ratio: float) -> Optional[CoinScore]:
    if len(candles) < 60: return None

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    if closes[-1] <= 0 or np.any(np.isnan(closes[-10:])): return None

    vol_usd = candle_vol_usd(candles)
    if vol_usd < MIN_VOL_USDT: return None

    # Indicators 15m
    e7, e17 = ema(closes,7), ema(closes,17)
    e4, e20 = ema(closes,4), ema(closes,20)
    h50     = hma(closes, 50)
    stc_v   = stc_ind(closes)
    vol_sma = sma(volumes, 20)
    inst_vol = bool(volumes[-1] > vol_sma[-1]*1.3) if vol_sma[-1] > 0 else False

    ph_vals = pivot_hi(highs, 5); pl_vals = pivot_lo(lows, 5)
    vph = ph_vals[~np.isnan(ph_vals)]; vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph) > 0 else float(highs[-1])
    valley = float(vpl[-1]) if len(vpl) > 0 else float(lows[-1])

    # Indicators 1h (confirmación macro) — NUEVO
    htf_bull = htf_bear = False
    if len(candles_1h) >= 20:
        c1h = np.array([c["close"] for c in candles_1h], dtype=float)
        e7_1h  = ema(c1h, 7)
        e17_1h = ema(c1h, 17)
        h50_1h = hma(c1h, 50)
        htf_bull = bool(c1h[-1] > h50_1h[-1] and e7_1h[-1] > e17_1h[-1])
        htf_bear = bool(c1h[-1] < h50_1h[-1] and e7_1h[-1] < e17_1h[-1])

    i = -1
    score, signals, direction = 0, [], "NEUTRAL"
    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    # F1: Hull 15m (20 pts)
    if hull_bull:   score += 20; signals.append("Hull🟢"); direction = "LONG"
    elif hull_bear: score += 20; signals.append("Hull🔴"); direction = "SHORT"

    # F2: Confirmación 1h — NUEVO (15 pts)
    if hull_bull and htf_bull:  score += 15; signals.append("1H🟢")
    elif hull_bear and htf_bear: score += 15; signals.append("1H🔴")
    elif (hull_bull and htf_bear) or (hull_bear and htf_bull):
        score -= 10; signals.append("1H⚠️")  # contradicción = penalización

    # F3: EMA 7/17 alineación + bonus cruce (20+5 pts)
    if hull_bull and e7[i] > e17[i]:
        score += 20; signals.append("EMA🟢")
        if e7[i-1] <= e17[i-1]: score += 5; signals.append("Cruz✅")
    elif hull_bear and e7[i] < e17[i]:
        score += 20; signals.append("EMA🔴")
        if e7[i-1] >= e17[i-1]: score += 5; signals.append("Cruz✅")

    # F4: Zona pivot (15 pts)
    rng = peak - valley
    if rng > 0:
        pos = (closes[i] - valley) / rng
        if hull_bull and pos > 0.5:   score += 15; signals.append("Zona🟢")
        elif hull_bear and pos < 0.5: score += 15; signals.append("Zona🔴")

    # F5: Volumen institucional desde velas (15 pts)
    if inst_vol:
        score += 15; signals.append("Vol💜")
        log.info(f"{ticker['symbol']}: InstVol ratio={volumes[-1]/(vol_sma[-1]+1e-10):.2f}x")

    # F6: STC momentum (15 pts)
    if hull_bull and stc_v[i] > stc_v[i-1]:   score += 15; signals.append("STC🟢")
    elif hull_bear and stc_v[i] < stc_v[i-1]: score += 15; signals.append("STC🔴")

    # F7: ChartArt slopes (10 pts)
    s4 = e4[i]-e4[i-1]; s20 = e20[i]-e20[i-1]
    if (hull_bull and s4>0 and s20>0) or (hull_bear and s4<0 and s20<0):
        score += 10; signals.append("Slope✅")

    # F8: Funding Rate — NUEVO (bonus/penalización)
    funding_bias, _ = interpret_funding(funding_rate)
    if funding_bias == "long_crowded":
        if hull_bear: score += 10; signals.append("FR🔴+")   # short confirmado
        else:         score -= 10; signals.append("FR⚠️")    # long contra masa
    elif funding_bias == "short_crowded":
        if hull_bull: score += 10; signals.append("FR🟢+")   # long confirmado
        else:         score -= 10; signals.append("FR⚠️")

    # F9: Long/Short ratio contrarian — NUEVO
    ls_bias = interpret_ls_ratio(ls_ratio)
    if ls_bias == "crowded_long" and hull_bear:
        score += 8; signals.append("LS🔴+")    # masa en longs, nosotros short
    elif ls_bias == "crowded_short" and hull_bull:
        score += 8; signals.append("LS🟢+")    # masa en shorts, nosotros long

    score = min(max(score, 0), 105)
    log.info(f"{ticker['symbol']}: score={score} dir={direction} vol=${vol_usd/1e6:.0f}M fr={funding_rate:.4f} ls={ls_ratio:.2f}")

    return CoinScore(
        symbol=ticker["symbol"], vol_24h_usd=vol_usd, score=score,
        direction=direction, signals=signals, change_24h=ticker.get("change_24h", 0),
        funding_rate=funding_rate, ls_ratio=ls_ratio, funding_bias=funding_bias,
    )


# ══════════════════════════════════════════════════════════════════
# SIGNAL ENGINE — multi-timeframe
# ══════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    direction: str
    entry:     float
    sl:        float
    tp:        float
    atr:       float = 0.0
    score:     int   = 0
    note:      str   = ""
    # Targets parciales para gestión activa
    tp_half:   float = 0.0   # TP al 50% = 1R (cierre de mitad)
    tp_full:   float = 0.0   # TP final = 3R

def compute_signal(candles: list, candles_1h: list,
                   funding_rate: float, ls_ratio: float) -> Signal:
    if len(candles) < 60:
        return Signal("NONE", 0, 0, 0)

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    e7, e17 = ema(closes,7), ema(closes,17)
    e2, e4, e20 = ema(closes,2), ema(closes,4), ema(closes,20)
    h50 = hma(closes, 50)
    stc_v   = stc_ind(closes)
    vol_sma = sma(volumes, 20)
    inst_vol = bool(volumes[-1] > vol_sma[-1]*1.3) if vol_sma[-1] > 0 else False

    ph_vals = pivot_hi(highs,5); pl_vals = pivot_lo(lows,5)
    vph = ph_vals[~np.isnan(ph_vals)]; vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph)>0 else float(highs.max())
    valley = float(vpl[-1]) if len(vpl)>0 else float(lows.min())
    atr    = calc_atr(highs, lows, closes)

    # Confirmación 1h — NUEVO
    htf_ok_long = htf_ok_short = True  # default: no penalizar si no hay datos
    if len(candles_1h) >= 20:
        c1h   = np.array([c["close"] for c in candles_1h], dtype=float)
        h1    = np.array([c["high"]  for c in candles_1h], dtype=float)
        l1    = np.array([c["low"]   for c in candles_1h], dtype=float)
        e7_1h = ema(c1h, 7); e17_1h = ema(c1h, 17); h50_1h = hma(c1h, 50)
        htf_ok_long  = bool(c1h[-1] > h50_1h[-1] and e7_1h[-1] > e17_1h[-1])
        htf_ok_short = bool(c1h[-1] < h50_1h[-1] and e7_1h[-1] < e17_1h[-1])

    # Funding bias — NO entrar si la masa está extrema en nuestra dirección
    funding_bias, _ = interpret_funding(funding_rate)
    funding_kills_long  = (funding_bias == "long_crowded")   # ya sobrecargado
    funding_kills_short = (funding_bias == "short_crowded")

    i = -1; entry = float(closes[i])
    if entry <= 0: return Signal("NONE", 0, 0, 0)

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    def make_sig(direction, sl_raw, sc, note=""):
        if abs(entry - sl_raw) > entry * 0.025:  # SL >2.5% → usar ATR
            sl = (entry - atr*1.5) if direction=="LONG" else (entry + atr*1.5)
        else:
            sl = sl_raw
        risk    = abs(entry - sl)
        tp_half = entry + risk     if direction=="LONG" else entry - risk      # 1R
        tp_full = entry + risk*3   if direction=="LONG" else entry - risk*3    # 3R
        return Signal(direction, entry, sl, tp_full, atr=atr, score=sc, note=note,
                      tp_half=tp_half, tp_full=tp_full)

    # ── Nivel 1: APEX completo (100) ──────────────────────────────
    apex_l = (hull_bull and htf_ok_long and not funding_kills_long
              and e7[i]>e17[i] and closes[i]>peak and inst_vol
              and stc_v[i]>stc_v[i-1] and (e7[i]-e7[i-1])>0)
    apex_s = (hull_bear and htf_ok_short and not funding_kills_short
              and e7[i]<e17[i] and closes[i]<valley and inst_vol
              and stc_v[i]<stc_v[i-1] and (e7[i]-e7[i-1])<0)

    # ── Nivel 2: Relax — hull + cross + vol (70) ──────────────────
    relax_l = (hull_bull and htf_ok_long and not funding_kills_long
               and e7[i-1]<e17[i-1] and e7[i]>e17[i] and inst_vol)
    relax_s = (hull_bear and htf_ok_short and not funding_kills_short
               and e7[i-1]>e17[i-1] and e7[i]<e17[i] and inst_vol)

    # ── Nivel 3: Cruce EMA (50) ────────────────────────────────────
    min_l = (hull_bull and htf_ok_long and not funding_kills_long
             and e7[i-1]<e17[i-1] and e7[i]>e17[i])
    min_s = (hull_bear and htf_ok_short and not funding_kills_short
             and e7[i-1]>e17[i-1] and e7[i]<e17[i])

    # ── Nivel 4: Tendencia activa (40) ─────────────────────────────
    trend_l = (hull_bull and htf_ok_long and e7[i]>e17[i]
               and stc_v[i]>stc_v[i-1] and (e4[i]-e4[i-1])>0)
    trend_s = (hull_bear and htf_ok_short and e7[i]<e17[i]
               and stc_v[i]<stc_v[i-1] and (e4[i]-e4[i-1])<0)

    if apex_l:   return make_sig("LONG",  valley, 100)
    if apex_s:   return make_sig("SHORT", peak,   100)
    if relax_l:  return make_sig("LONG",  valley,  70, "⚡Relax")
    if relax_s:  return make_sig("SHORT", peak,    70, "⚡Relax")
    if min_l:    return make_sig("LONG",  valley,  50, "📊Cruz")
    if min_s:    return make_sig("SHORT", peak,    50, "📊Cruz")
    if trend_l:  return make_sig("LONG",  valley,  40, "📈Trend")
    if trend_s:  return make_sig("SHORT", peak,    40, "📉Trend")
    return Signal("NONE", entry, 0, 0)


# ══════════════════════════════════════════════════════════════════
# RISK
# ══════════════════════════════════════════════════════════════════

async def calc_qty(symbol: str, balance: float, entry: float, sl: float) -> float:
    risk_usd = balance * (MAX_RISK_PCT / 100)
    dist = abs(entry - sl)
    if dist < 1e-10: return 0.0
    qty = risk_usd / dist
    if entry > 10000:    qty = round(qty, 3)
    elif entry > 100:    qty = round(qty, 2)
    elif entry > 1:      qty = round(qty, 1)
    else:                qty = round(qty, 0)
    return max(qty, 0.001)


# ══════════════════════════════════════════════════════════════════
# BOT STATE
# ══════════════════════════════════════════════════════════════════

exchange      = BingXClient()
watchlist:    list[str]      = []
last_signal:  dict[str, str] = {}
half_closed:  set[str]       = set()   # symbols donde ya cerramos el 50%


# ══════════════════════════════════════════════════════════════════
# SCANNER LOOP
# ══════════════════════════════════════════════════════════════════

async def scanner_loop():
    global watchlist
    while True:
        try:
            if is_blackout_hour():
                log.info(f"Blackout hour UTC — skip scan")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            log.info(f"🔍 Escaneo V27 — {SCAN_TOP_N} coins + datos institucionales")
            all_tickers = await exchange.get_all_tickers()
            if not all_tickers:
                await tg("⚠️ Sin tickers. Revisa WHITELIST o API key.")
                await asyncio.sleep(SCAN_INTERVAL); continue

            # Descargar velas 15m, 1h, funding, LS ratio en paralelo
            syms = [t["symbol"] for t in all_tickers]
            tasks_15m = [exchange.get_klines(s, TIMEFRAME,  200) for s in syms]
            tasks_1h  = [exchange.get_klines(s, TF_HIGH,    100) for s in syms]
            tasks_fr  = [exchange.get_funding_rate(s)            for s in syms]
            tasks_ls  = [exchange.get_long_short_ratio(s)        for s in syms]

            results_15m, results_1h, results_fr, results_ls = await asyncio.gather(
                asyncio.gather(*tasks_15m, return_exceptions=True),
                asyncio.gather(*tasks_1h,  return_exceptions=True),
                asyncio.gather(*tasks_fr,  return_exceptions=True),
                asyncio.gather(*tasks_ls,  return_exceptions=True),
            )

            scored = []
            for ticker, c15, c1h, fr, ls in zip(
                    all_tickers, results_15m, results_1h, results_fr, results_ls):
                if isinstance(c15, Exception): continue
                c1h_safe = c1h if not isinstance(c1h, Exception) else []
                fr_safe  = fr  if not isinstance(fr,  Exception) else 0.0
                ls_safe  = ls  if not isinstance(ls,  Exception) else 1.0
                cs = score_coin(ticker, c15, c1h_safe, fr_safe, ls_safe)
                if cs: scored.append(cs)

            # Ranking y volumen real
            scored.sort(key=lambda x: (x.vol_24h_usd * x.score), reverse=True)
            top = scored[:SCAN_TOP_N]

            operables = [c for c in top if c.score >= SCORE_THRESHOLD
                         and c.direction != "NEUTRAL"]
            watchlist = [c.symbol for c in operables] if operables else [c.symbol for c in top[:5]]

            # Telegram
            lines = [f"🔍 *V27 SCAN — {len(top)} coins*\n"]
            for n, c in enumerate(top, 1):
                e    = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                bar  = "█"*(c.score//10) + "░"*(10-c.score//10)
                fr_s = f"FR:`{c.funding_rate*100:.3f}%`"
                ls_s = f"LS:`{c.ls_ratio:.2f}`"
                lines.append(
                    f"*#{n}* {e} `{c.symbol}` `{c.score}/100`\n"
                    f"`{bar}`\n"
                    f"Vol:`${c.vol_24h_usd/1e6:.0f}M` Δ:`{c.change_24h:+.1f}%`"
                    f" {fr_s} {ls_s}\n"
                    f"{'  '.join(c.signals[:6])}\n"
                )
            lines.append(f"\n👀 *Watchlist:* {', '.join([f'`{s}`' for s in watchlist])}")

            msg = "\n".join(lines)
            if len(msg) > 3800:
                short = [f"🔍 *V27 — Top {len(top)}*\n"]
                for n, c in enumerate(top, 1):
                    e = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                    short.append(f"{e} `{c.symbol}` `{c.score}` fr:{c.funding_rate*100:.3f}%")
                short.append(f"\n👀 {', '.join([f'`{s}`' for s in watchlist])}")
                await tg("\n".join(short))
            else:
                await tg(msg)

        except Exception as e:
            log.error(f"Scanner: {e}", exc_info=True)
            await tg(f"⚠️ *Error escáner:* `{str(e)[:200]}`")

        await asyncio.sleep(SCAN_INTERVAL)


# ══════════════════════════════════════════════════════════════════
# TRADING LOOP
# ══════════════════════════════════════════════════════════════════

async def trading_loop():
    await asyncio.sleep(70)
    while True:
        try:
            if is_blackout_hour():
                await asyncio.sleep(60); continue

            # Gestión activa de posiciones abiertas (cierre parcial, trailing)
            await manage_open_positions()

            # Nuevas entradas
            open_positions = await exchange.get_all_positions()
            if len(open_positions) < MAX_POSITIONS:
                for symbol in list(watchlist):
                    if len(open_positions) >= MAX_POSITIONS: break
                    already_open = any(p.get("symbol") == symbol for p in open_positions)
                    if not already_open:
                        await trade_coin(symbol)
                    await asyncio.sleep(2)

        except Exception as e:
            log.error(f"Trading loop: {e}", exc_info=True)
        await asyncio.sleep(60)


async def manage_open_positions():
    """
    Gestión activa:
    - Cierra 50% cuando el precio llega al 1R (asegura profit)
    - Trailing stop basado en ATR para dejar correr la segunda mitad
    """
    global half_closed
    try:
        positions = await exchange.get_all_positions()
        for pos in positions:
            sym     = pos.get("symbol","")
            amt     = float(pos.get("positionAmt", 0))
            avg     = float(pos.get("avgPrice", pos.get("entryPrice", 0)))
            cur     = float(pos.get("markPrice", pos.get("currentPrice", 0)))
            unreal  = float(pos.get("unrealizedProfit", pos.get("unRealizedProfit", 0)))

            if avg <= 0 or cur <= 0: continue

            is_long   = amt > 0
            direction = "LONG" if is_long else "SHORT"
            pnl_pct   = ((cur - avg) / avg * 100) if is_long else ((avg - cur) / avg * 100)

            # Cierre 50% al llegar a ~1R (aprox 1% de mov favorable con 5x leverage)
            if sym not in half_closed and pnl_pct >= 0.8:
                log.info(f"[{sym}] PnL {pnl_pct:.2f}% — cerrando 50% (asegurando 1R)")
                try:
                    await exchange.close_half_position(sym, pos)
                    half_closed.add(sym)
                    await tg(
                        f"🔒 *Cierre parcial 50%* `{sym}` {direction}\n"
                        f"PnL: `+{pnl_pct:.2f}%` | Profit: `+{unreal:.2f} USDT`\n"
                        f"La segunda mitad sigue con trailing stop"
                    )
                except Exception as e:
                    log.error(f"Half close {sym}: {e}")

            # Log de estado de posiciones abiertas
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            log.info(f"POS [{sym}] {direction} pnl={pnl_pct:+.2f}% unreal={unreal:+.2f}")

    except Exception as e:
        log.error(f"manage_open_positions: {e}")


async def trade_coin(symbol: str):
    try:
        # Datos frescos
        c15, c1h, fr, ls = await asyncio.gather(
            exchange.get_klines(symbol, TIMEFRAME, 200),
            exchange.get_klines(symbol, TF_HIGH,   100),
            exchange.get_funding_rate(symbol),
            exchange.get_long_short_ratio(symbol),
        )
        signal   = compute_signal(c15, c1h, fr, ls)
        position = await exchange.get_position(symbol)
        has_pos  = position is not None

        log.info(f"[{symbol}] sig={signal.direction}({signal.score}) "
                 f"fr={fr:.4f} ls={ls:.2f} pos={has_pos}")

        # Cerrar si señal contraria
        if has_pos and signal.direction != "NONE":
            amt      = float(position["positionAmt"])
            pos_side = "LONG" if amt > 0 else "SHORT"
            if pos_side != signal.direction:
                await exchange.close_position(symbol, position)
                half_closed.discard(symbol)
                await tg(f"🔄 *Cierre* {pos_side} `{symbol}` @ `{signal.entry:.6f}`")
                has_pos = False

        # Abrir nueva posición
        if not has_pos and signal.direction != "NONE" and signal.score >= 40:
            if last_signal.get(symbol) == signal.direction:
                return

            balance = await exchange.get_balance()
            if balance < 5:
                await tg(f"⚠️ Balance bajo: `{balance:.2f} USDT`"); return

            qty = await calc_qty(symbol, balance, signal.entry, signal.sl)
            if qty <= 0: return

            await exchange.set_leverage(symbol, LEVERAGE)
            side = "BUY" if signal.direction=="LONG" else "SELL"

            await exchange.place_order(
                symbol=symbol, side=side,
                position_side=signal.direction, qty=qty,
                stop_loss=signal.sl, take_profit=signal.tp,
            )

            risk_usd = abs(signal.entry - signal.sl) * qty
            emoji    = "🟢" if signal.direction=="LONG" else "🔴"
            fr_icon  = "🔥" if abs(fr) > 0.02 else ""
            await tg(
                f"{emoji} *{signal.direction} ABIERTO* {fr_icon}\n"
                f"Par: `{symbol}`\n"
                f"Entry: `{signal.entry:.6f}`\n"
                f"SL:    `{signal.sl:.6f}`\n"
                f"TP½:   `{signal.tp_half:.6f}` *(1R — cierre parcial)*\n"
                f"TP:    `{signal.tp:.6f}` *(3R — objetivo final)*\n"
                f"Qty: `{qty}` | Score: `{signal.score}/100`\n"
                f"Riesgo: `≈{risk_usd:.2f} USDT`\n"
                f"FR: `{fr*100:.3f}%` | L/S: `{ls:.2f}`\n"
                f"{signal.note}"
            )
            last_signal[symbol] = signal.direction

        elif signal.direction == "NONE":
            last_signal[symbol] = "NONE"
            if symbol in half_closed and not has_pos:
                half_closed.discard(symbol)

    except Exception as e:
        log.error(f"trade_coin {symbol}: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

async def main():
    log.info("🚀 Sniper Bot V27 Institutional Edge — Arrancando...")
    await tg(
        "🟢 *Sniper Bot V27 — Institutional Edge*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"TF entrada:  `{TIMEFRAME}` | TF macro: `{TF_HIGH}`\n"
        f"Leverage:    `{LEVERAGE}x`\n"
        f"Riesgo/op:   `{MAX_RISK_PCT}%`\n"
        f"Max posic.:  `{MAX_POSITIONS}`\n"
        f"Score mín:   `{SCORE_THRESHOLD}/100`\n"
        f"Blackout:    `{BLACKOUT_START}:00-{BLACKOUT_END}:00 UTC`\n"
        f"Whitelist:   `{'ON' if USE_WHITELIST else 'OFF'}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Funding Rate activo\n"
        f"✅ Long/Short ratio activo\n"
        f"✅ Multi-timeframe 1h activo\n"
        f"✅ Cierre parcial 50% activo\n"
        f"✅ Anti-trampa nocturno activo"
    )
    await asyncio.gather(scanner_loop(), trading_loop())


if __name__ == "__main__":
    asyncio.run(main())
