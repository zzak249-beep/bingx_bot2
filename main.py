"""
Sniper Bot V26.1 — Fix v4
Cambios críticos:
  - Volumen leído desde velas (no ticker) → InstVol funciona
  - Score recalculado con todos los filtros activos
  - Watchlist ampliada: top 5 por score SIN umbral mínimo
  - Señal de entrada en 3 niveles (100/70/50)
  - SL dinámico con ATR si pivot está muy lejos
  - Log detallado de cada filtro por coin
"""

import asyncio, hashlib, hmac, logging, os, time, urllib.parse
from dataclasses import dataclass, field
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
LEVERAGE         = int(os.getenv("LEVERAGE", "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT", "1.0"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N", "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT", "10000000"))   # 10M
SCORE_THRESHOLD  = int(os.getenv("SCORE_THRESHOLD", "40"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "5")) * 60
BASE_URL         = "https://open-api.bingx.com"

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
}
USE_WHITELIST = os.getenv("USE_WHITELIST", "true").lower() == "true"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE
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
                    candles.append({"time": int(c[0]), "open": float(c[1]),
                                    "high": float(c[2]), "low": float(c[3]),
                                    "close": float(c[4]), "volume": float(c[5])})
                elif isinstance(c, dict):
                    candles.append({
                        "time":   int(c.get("time", c.get("t", 0))),
                        "open":   float(c.get("open",   c.get("o", 0))),
                        "high":   float(c.get("high",   c.get("h", 0))),
                        "low":    float(c.get("low",    c.get("l", 0))),
                        "close":  float(c.get("close",  c.get("c", 0))),
                        "volume": float(c.get("volume", c.get("v", c.get("quoteVolume", 0)))),
                    })
            except Exception:
                continue
        return candles

    async def get_all_tickers(self) -> list:
        """Tickers para obtener la lista de symbols — el volumen real viene de las velas."""
        d = await self._get("/openApi/swap/v2/quote/ticker")
        raw = d.get("data", [])
        if raw:
            log.info(f"[DEBUG] Ticker fields: {list(raw[0].keys())}")

        tickers = []
        for t in raw:
            try:
                sym = t.get("symbol", "")
                if not sym.endswith("-USDT"):
                    continue
                if sym in BLACKLIST:
                    continue
                if USE_WHITELIST and sym not in WHITELIST:
                    continue

                # Precio — intentar todos los campos posibles
                price = 0.0
                for f in ("lastPrice", "last", "price", "close", "c", "markPrice"):
                    v = t.get(f)
                    if v and float(v) > 0:
                        price = float(v)
                        break

                # Cambio 24h
                change = 0.0
                for f in ("priceChangePercent","change","changePercent","priceChange"):
                    v = t.get(f)
                    if v is not None:
                        try: change = float(v)
                        except: pass
                        break

                # Volumen del ticker (puede ser 0 — se complementa con velas)
                vol_ticker = 0.0
                for f in ("quoteVolume","volume","vol","turnover","amount"):
                    v = t.get(f)
                    if v:
                        try:
                            fv = float(v)
                            if fv > 0:
                                vol_ticker = fv
                                break
                        except: pass

                if price <= 0:
                    continue

                tickers.append({
                    "symbol":     sym,
                    "price":      price,
                    "change_24h": change,
                    "vol_ticker": vol_ticker,
                })
            except Exception as e:
                log.warning(f"Ticker parse {t.get('symbol','?')}: {e}")

        log.info(f"Tickers parseados: {len(tickers)} coins válidas")
        return tickers  # devolvemos TODOS, el filtro de volumen lo hacemos con velas

    async def get_balance(self) -> float:
        d = await self._get("/openApi/swap/v2/user/balance")
        for a in d["data"]["balance"]:
            if a["asset"] == "USDT":
                for f in ("availableMargin","available","free","equity"):
                    v = a.get(f)
                    if v is not None:
                        bal = float(v)
                        log.info(f"Balance USDT: {bal}")
                        return bal
        return 0.0

    async def get_position(self, symbol: str) -> Optional[dict]:
        d = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        positions = [p for p in d.get("data", [])
                     if abs(float(p.get("positionAmt", 0))) > 0]
        return positions[0] if positions else None

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None, reduce_only=False):
        payload = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         "MARKET",
            "quantity":     str(qty),
        }
        if reduce_only:
            payload["reduceOnly"] = "true"
        if stop_loss:
            payload["stopLoss"]   = str(round(stop_loss, 8))
        if take_profit:
            payload["takeProfit"] = str(round(take_profit, 8))
        log.info(f"ORDER → {symbol} {side} {position_side} qty={qty} sl={stop_loss} tp={take_profit}")
        result = await self._post("/openApi/swap/v2/trade/order", payload)
        log.info(f"ORDER RESULT → {result}")
        return result

    async def close_position(self, symbol, position):
        amt   = float(position["positionAmt"])
        side  = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        return await self.place_order(symbol, side, pside, abs(amt), reduce_only=True)

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
    h = np.asarray(h, dtype=float)
    r = np.full(len(h), np.nan)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max():
            r[i] = h[i]
    return r

def pivot_lo(l, n):
    l = np.asarray(l, dtype=float)
    r = np.full(len(l), np.nan)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min():
            r[i] = l[i]
    return r

def calc_atr(highs, lows, closes, p=14):
    h, l, c = np.asarray(highs,float), np.asarray(lows,float), np.asarray(closes,float)
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    return float(np.mean(tr[-p:]))


# ══════════════════════════════════════════════════════════════════
# SCORER — usa volumen de VELAS, no del ticker
# ══════════════════════════════════════════════════════════════════

@dataclass
class CoinScore:
    symbol:     str
    vol_24h_usd: float   # calculado desde velas
    score:      int
    direction:  str
    signals:    list = field(default_factory=list)
    change_24h: float = 0.0

def candle_volume_usd(candles: list) -> float:
    """Volumen 24h en USD calculado desde las últimas 96 velas de 15m (= 24h)."""
    last96 = candles[-96:] if len(candles) >= 96 else candles
    return sum(c["close"] * c["volume"] for c in last96)

def score_coin(ticker: dict, candles: list) -> Optional[CoinScore]:
    if len(candles) < 60:
        log.warning(f"{ticker['symbol']}: solo {len(candles)} velas")
        return None

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    if closes[-1] <= 0 or np.any(np.isnan(closes[-10:])):
        return None

    # Volumen real desde velas
    vol_usd = candle_volume_usd(candles)

    # Filtrar por volumen mínimo real
    if vol_usd < MIN_VOL_USDT:
        log.info(f"{ticker['symbol']}: vol ${vol_usd/1e6:.1f}M < ${MIN_VOL_USDT/1e6:.0f}M, skip")
        return None

    e7, e17 = ema(closes,7), ema(closes,17)
    e4, e20 = ema(closes,4), ema(closes,20)
    h50     = hma(closes, 50)
    stc_v   = stc_ind(closes)

    # Volumen institucional: vela actual vs SMA20 del volumen — desde velas reales
    vol_sma20 = float(sma(volumes, 20)[-1])
    inst_vol  = bool(volumes[-1] > vol_sma20 * 1.3) if vol_sma20 > 0 else False

    ph_vals = pivot_hi(highs, 5)
    pl_vals = pivot_lo(lows,  5)
    vph     = ph_vals[~np.isnan(ph_vals)]
    vpl     = pl_vals[~np.isnan(pl_vals)]
    peak    = float(vph[-1]) if len(vph) > 0 else float(highs[-1])
    valley  = float(vpl[-1]) if len(vpl) > 0 else float(lows[-1])

    i = -1
    score, signals, direction = 0, [], "NEUTRAL"

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    # F1: Hull (20 pts)
    if hull_bull:
        score += 20; signals.append("Hull🟢"); direction = "LONG"
    elif hull_bear:
        score += 20; signals.append("Hull🔴"); direction = "SHORT"

    # F2: EMA alineación (20 pts) + bonus cruce fresco (5 pts)
    if hull_bull and e7[i] > e17[i]:
        score += 20; signals.append("EMA🟢")
        if e7[i-1] <= e17[i-1]: score += 5; signals.append("Cruz✅")
    elif hull_bear and e7[i] < e17[i]:
        score += 20; signals.append("EMA🔴")
        if e7[i-1] >= e17[i-1]: score += 5; signals.append("Cruz✅")

    # F3: Posición vs rango pivot (15 pts)
    rng = peak - valley
    if rng > 0:
        pos = (closes[i] - valley) / rng  # 0=valley, 1=peak
        if hull_bull and pos > 0.5:
            score += 15; signals.append("Zona🟢")
        elif hull_bear and pos < 0.5:
            score += 15; signals.append("Zona🔴")

    # F4: Volumen institucional desde velas (15 pts)
    if inst_vol:
        score += 15; signals.append("Vol💜")
        log.info(f"{ticker['symbol']}: InstVol ACTIVO vol={volumes[-1]:.0f} sma={vol_sma20:.0f}")
    else:
        log.info(f"{ticker['symbol']}: InstVol OFF vol={volumes[-1]:.0f} sma={vol_sma20:.0f} ratio={volumes[-1]/(vol_sma20+1e-10):.2f}x")

    # F5: STC momentum (15 pts)
    if hull_bull and stc_v[i] > stc_v[i-1]:
        score += 15; signals.append("STC🟢")
    elif hull_bear and stc_v[i] < stc_v[i-1]:
        score += 15; signals.append("STC🔴")

    # F6: Slope ChartArt (10 pts)
    s4  = e4[i]  - e4[i-1]
    s20 = e20[i] - e20[i-1]
    if (hull_bull and s4>0 and s20>0) or (hull_bear and s4<0 and s20<0):
        score += 10; signals.append("Slope✅")

    score = min(score, 100)
    log.info(f"{ticker['symbol']}: score={score} dir={direction} vol_24h=${vol_usd/1e6:.1f}M signals={signals}")

    return CoinScore(
        symbol=ticker["symbol"],
        vol_24h_usd=vol_usd,
        score=score,
        direction=direction,
        signals=signals,
        change_24h=ticker.get("change_24h", 0),
    )


# ══════════════════════════════════════════════════════════════════
# SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    direction: str
    entry:     float
    sl:        float
    tp:        float
    score:     int = 0
    note:      str = ""

def compute_signal(candles: list) -> Signal:
    if len(candles) < 60:
        return Signal("NONE", 0, 0, 0)

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    e7, e17 = ema(closes,7), ema(closes,17)
    e2, e4, e20 = ema(closes,2), ema(closes,4), ema(closes,20)
    h50     = hma(closes, 50)
    stc_v   = stc_ind(closes)
    vol_sma = sma(volumes, 20)
    inst_vol = bool(volumes[-1] > vol_sma[-1] * 1.3) if vol_sma[-1] > 0 else False

    ph_vals = pivot_hi(highs, 5); pl_vals = pivot_lo(lows, 5)
    vph = ph_vals[~np.isnan(ph_vals)]; vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph) > 0 else float(highs.max())
    valley = float(vpl[-1]) if len(vpl) > 0 else float(lows.min())
    atr    = calc_atr(highs, lows, closes)

    i     = -1
    entry = float(closes[i])
    if entry <= 0:
        return Signal("NONE", 0, 0, 0)

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    def make_sig(direction, sl_raw, sc, note=""):
        # Si SL está a más del 3% del entry, usar ATR*1.5 en su lugar
        if abs(entry - sl_raw) > entry * 0.03:
            sl = (entry - atr*1.5) if direction=="LONG" else (entry + atr*1.5)
        else:
            sl = sl_raw
        risk = abs(entry - sl)
        tp = entry + risk*3 if direction=="LONG" else entry - risk*3
        return Signal(direction, entry, sl, tp, sc, note)

    # Nivel 1: APEX completo (100)
    apex_l = (hull_bull and e7[i]>e17[i] and closes[i]>peak
              and inst_vol and stc_v[i]>stc_v[i-1] and (e7[i]-e7[i-1])>0)
    apex_s = (hull_bear and e7[i]<e17[i] and closes[i]<valley
              and inst_vol and stc_v[i]<stc_v[i-1] and (e7[i]-e7[i-1])<0)

    # Nivel 2: Hull + cruce EMA + vol (70)
    relax_l = hull_bull and e7[i-1]<e17[i-1] and e7[i]>e17[i] and inst_vol
    relax_s = hull_bear and e7[i-1]>e17[i-1] and e7[i]<e17[i] and inst_vol

    # Nivel 3: Hull + cruce EMA solamente (50) — entra aunque no haya vol inst
    min_l = hull_bull and e7[i-1]<e17[i-1] and e7[i]>e17[i]
    min_s = hull_bear and e7[i-1]>e17[i-1] and e7[i]<e17[i]

    # Nivel 4: Hull + EMA alineadas + STC (40) — mercado tendencial sin cruce fresco
    trend_l = hull_bull and e7[i]>e17[i] and stc_v[i]>stc_v[i-1] and (e4[i]-e4[i-1])>0
    trend_s = hull_bear and e7[i]<e17[i] and stc_v[i]<stc_v[i-1] and (e4[i]-e4[i-1])<0

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

async def calc_qty(exchange, symbol: str, balance: float,
                   entry: float, sl: float) -> float:
    risk_usd = balance * (MAX_RISK_PCT / 100)
    dist = abs(entry - sl)
    if dist < 1e-10:
        return 0.0
    qty = risk_usd / dist
    # Redondear según precio (contratos grandes necesitan menos decimales)
    if entry > 10000:   qty = round(qty, 3)
    elif entry > 100:   qty = round(qty, 2)
    elif entry > 1:     qty = round(qty, 1)
    else:               qty = round(qty, 0)
    return max(qty, 0.001)


# ══════════════════════════════════════════════════════════════════
# BOT STATE
# ══════════════════════════════════════════════════════════════════

exchange     = BingXClient()
watchlist:   list[str]   = []
last_signal: dict[str,str] = {}


# ══════════════════════════════════════════════════════════════════
# SCANNER LOOP
# ══════════════════════════════════════════════════════════════════

async def scanner_loop():
    global watchlist
    while True:
        try:
            log.info(f"🔍 Escaneo iniciado — {SCAN_TOP_N} coins objetivo")
            all_tickers = await exchange.get_all_tickers()

            if not all_tickers:
                log.warning("Sin tickers — revisa WHITELIST o API key")
                await tg("⚠️ Sin tickers válidos. Revisa variables en Railway.")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # Descargar velas en paralelo para TODAS las coins de la whitelist
            tasks   = [exchange.get_klines(t["symbol"], TIMEFRAME, 200) for t in all_tickers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            scored = []
            for ticker, candles in zip(all_tickers, results):
                if isinstance(candles, Exception):
                    log.warning(f"{ticker['symbol']} klines: {candles}")
                    continue
                cs = score_coin(ticker, candles)
                if cs:
                    scored.append(cs)

            # Ordenar por score
            scored.sort(key=lambda x: x.score, reverse=True)
            top = scored[:SCAN_TOP_N]

            # Watchlist: coins con score >= umbral, o top 5 sin umbral
            operables = [c for c in top if c.score >= SCORE_THRESHOLD and c.direction != "NEUTRAL"]
            watchlist = [c.symbol for c in operables] if operables else [c.symbol for c in top[:5]]

            log.info(f"Watchlist: {watchlist}")

            # Telegram: resumen top 10
            lines = [f"🔍 *ESCANEO — {len(top)} coins analizadas*\n"]
            for n, c in enumerate(top, 1):
                e = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                bar = "█"*(c.score//10) + "░"*(10-c.score//10)
                lines.append(
                    f"*#{n}* {e} `{c.symbol}` `{c.score}/100`\n"
                    f"`{bar}`\n"
                    f"Vol24h: `${c.vol_24h_usd/1e6:.0f}M`  Δ:`{c.change_24h:+.1f}%`\n"
                    f"{'  '.join(c.signals)}\n"
                )

            lines.append(f"\n👀 *Watchlist ({len(watchlist)} coins):*")
            for s in watchlist:
                lines.append(f"  • `{s}`")

            # Enviar en chunks si es largo
            msg = "\n".join(lines)
            if len(msg) > 3800:
                # Enviar resumen corto
                short = [f"🔍 *TOP {len(top)} — Watchlist activa:*\n"]
                for n, c in enumerate(top, 1):
                    e = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                    short.append(f"{e} `{c.symbol}` `{c.score}` {' '.join(c.signals[:3])}")
                short.append(f"\n👀 Watchlist: {', '.join([f'`{s}`' for s in watchlist])}")
                await tg("\n".join(short))
            else:
                await tg(msg)

        except Exception as e:
            log.error(f"Scanner error: {e}", exc_info=True)
            await tg(f"⚠️ *Error escáner:* `{str(e)[:200]}`")

        await asyncio.sleep(SCAN_INTERVAL)


# ══════════════════════════════════════════════════════════════════
# TRADING LOOP
# ══════════════════════════════════════════════════════════════════

async def trading_loop():
    await asyncio.sleep(60)  # esperar primer escaneo completo
    while True:
        try:
            for symbol in list(watchlist):
                await trade_coin(symbol)
                await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Trading loop: {e}", exc_info=True)
        await asyncio.sleep(60)


async def trade_coin(symbol: str):
    try:
        candles  = await exchange.get_klines(symbol, TIMEFRAME, 200)
        signal   = compute_signal(candles)
        position = await exchange.get_position(symbol)
        has_pos  = position is not None

        log.info(f"[{symbol}] signal={signal.direction}({signal.score}) pos={has_pos}")

        # Cerrar si señal contraria
        if has_pos and signal.direction != "NONE":
            amt      = float(position["positionAmt"])
            pos_side = "LONG" if amt > 0 else "SHORT"
            if pos_side != signal.direction:
                await exchange.close_position(symbol, position)
                await tg(f"🔄 *Cierre* {pos_side} `{symbol}` @ `{signal.entry:.6f}`")
                has_pos = False

        # Abrir nueva posición
        if not has_pos and signal.direction != "NONE" and signal.score >= 40:
            if last_signal.get(symbol) == signal.direction:
                return  # ya está abierta esta señal

            balance = await exchange.get_balance()
            if balance < 5:
                await tg(f"⚠️ Balance insuficiente: `{balance:.2f} USDT`")
                return

            qty = await calc_qty(exchange, symbol, balance, signal.entry, signal.sl)
            if qty <= 0:
                log.warning(f"{symbol}: qty=0")
                return

            await exchange.set_leverage(symbol, LEVERAGE)

            side = "BUY" if signal.direction == "LONG" else "SELL"
            await exchange.place_order(
                symbol=symbol, side=side,
                position_side=signal.direction,
                qty=qty,
                stop_loss=signal.sl,
                take_profit=signal.tp,
            )

            risk_usd = abs(signal.entry - signal.sl) * qty
            emoji = "🟢" if signal.direction == "LONG" else "🔴"
            await tg(
                f"{emoji} *{signal.direction} ABIERTO*\n"
                f"Par: `{symbol}`\n"
                f"Entry: `{signal.entry:.6f}`\n"
                f"SL:    `{signal.sl:.6f}`\n"
                f"TP:    `{signal.tp:.6f}` *(3R)*\n"
                f"Qty:   `{qty}` | Score: `{signal.score}/100`\n"
                f"Riesgo: `≈{risk_usd:.2f} USDT`\n"
                f"{signal.note}"
            )
            last_signal[symbol] = signal.direction

        elif signal.direction == "NONE":
            last_signal[symbol] = "NONE"

    except Exception as e:
        log.error(f"trade_coin {symbol}: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

async def main():
    log.info("🚀 Sniper Bot V26.1 Fix-v4 — Arrancando...")
    await tg(
        "🟢 *Sniper Bot V26.1 — Fix v4 ACTIVO*\n"
        f"Timeframe: `{TIMEFRAME}`\n"
        f"Leverage:  `{LEVERAGE}x`\n"
        f"Riesgo:    `{MAX_RISK_PCT}%/trade`\n"
        f"Score min: `{SCORE_THRESHOLD}/100`\n"
        f"Vol min:   `${MIN_VOL_USDT/1e6:.0f}M` *(desde velas)*\n"
        f"Whitelist: `{'ON' if USE_WHITELIST else 'OFF'}`\n"
        f"Scan:      `cada {SCAN_INTERVAL//60}min`"
    )
    await asyncio.gather(scanner_loop(), trading_loop())


if __name__ == "__main__":
    asyncio.run(main())
