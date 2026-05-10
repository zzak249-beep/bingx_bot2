"""
Sniper Bot V26.1 - Institutional Apex Multi-Coin
ARCHIVO ÚNICO para Railway
Fixes v3:
  - Score mínimo bajado a 45 para operar en cualquier condición
  - Modo fallback: si no hay coins con score alto, opera el TOP 3 por volumen con señal Apex simple
  - Debug de campos reales de BingX ticker
  - Filtro de coins basura (stablecoins, coins raras)
  - Señal LONG/SHORT independiente del scorer (Apex directo sobre watchlist)
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
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
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT", "20000000"))   # 20M mínimo
SCORE_THRESHOLD  = int(os.getenv("SCORE_THRESHOLD", "45"))        # bajado de 65 a 45
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "5")) * 60  # cada 5 min

BASE_URL = "https://open-api.bingx.com"

# Coins que NUNCA operar (stablecoins, coins raras, wrapped)
BLACKLIST = {
    "USDC-USDT","BUSD-USDT","DAI-USDT","TUSD-USDT","USDP-USDT",
    "FRAX-USDT","GUSD-USDT","LUSD-USDT","SUSD-USDT","USDD-USDT",
    "NCCOGOLD2USD-USDT","PAXG-USDT","XAUT-USDT","WBTC-USDT",
    "STETH-USDT","WETH-USDT","CBETH-USDT","RETH-USDT",
}

# Solo operar estas coins conocidas y líquidas (whitelist modo seguro)
WHITELIST = {
    "BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
    "DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","UNI-USDT","ATOM-USDT","LTC-USDT","BCH-USDT",
    "FIL-USDT","NEAR-USDT","APT-USDT","ARB-USDT","OP-USDT",
    "INJ-USDT","SUI-USDT","TIA-USDT","WLD-USDT","JTO-USDT",
    "AAVE-USDT","ONDO-USDT","ENA-USDT","PEPE-USDT","WIF-USDT",
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
                # BingX v3 puede devolver lista o dict según versión
                if isinstance(c, list):
                    candles.append({"time": int(c[0]), "open": float(c[1]),
                                    "high": float(c[2]), "low": float(c[3]),
                                    "close": float(c[4]), "volume": float(c[5])})
                elif isinstance(c, dict):
                    candles.append({"time": int(c.get("time",0)),
                                    "open":   float(c.get("open",   c.get("o",0))),
                                    "high":   float(c.get("high",   c.get("h",0))),
                                    "low":    float(c.get("low",    c.get("l",0))),
                                    "close":  float(c.get("close",  c.get("c",0))),
                                    "volume": float(c.get("volume", c.get("v",0)))})
            except Exception:
                continue
        return candles

    async def get_all_tickers(self) -> list:
        """Obtiene todos los tickers y loguea los campos reales para debug."""
        d = await self._get("/openApi/swap/v2/quote/ticker")
        raw = d.get("data", [])

        # Debug: loguear campos del primer ticker
        if raw:
            log.info(f"[DEBUG] Ticker fields: {list(raw[0].keys())}")
            log.info(f"[DEBUG] Sample ticker: {raw[0]}")

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

                # BingX puede usar distintos nombres de campo según endpoint
                vol = 0.0
                for field_name in ("quoteVolume","volume","vol","turnover","amount","tradeAmount"):
                    v = t.get(field_name)
                    if v and float(v) > 0:
                        vol = float(v)
                        break

                price = 0.0
                for field_name in ("lastPrice","last","price","close","c"):
                    v = t.get(field_name)
                    if v and float(v) > 0:
                        price = float(v)
                        break

                change = 0.0
                for field_name in ("priceChangePercent","change","changePercent","priceChange24hPercent"):
                    v = t.get(field_name)
                    if v is not None:
                        change = float(v)
                        break

                if vol < MIN_VOL_USDT or price <= 0:
                    continue

                tickers.append({"symbol": sym, "volume_24h": vol,
                                 "price": price, "change_24h": change})
            except Exception as e:
                log.warning(f"Ticker parse error {t.get('symbol','?')}: {e}")
                continue

        tickers.sort(key=lambda x: x["volume_24h"], reverse=True)
        log.info(f"Tickers válidos: {len(tickers)} → top: {[t['symbol'] for t in tickers[:SCAN_TOP_N]]}")
        return tickers[:SCAN_TOP_N]

    async def get_balance(self) -> float:
        d = await self._get("/openApi/swap/v2/user/balance")
        for a in d["data"]["balance"]:
            if a["asset"] == "USDT":
                avail = float(a.get("availableMargin", a.get("available", a.get("free", 0))))
                log.info(f"Balance USDT disponible: {avail}")
                return avail
        return 0.0

    async def get_position(self, symbol: str) -> Optional[dict]:
        d = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        positions = [p for p in d.get("data", [])
                     if abs(float(p.get("positionAmt", 0))) > 0]
        return positions[0] if positions else None

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None, reduce_only=False):
        payload = {
            "symbol": symbol, "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": str(qty),
        }
        if reduce_only:
            payload["reduceOnly"] = "true"
        if stop_loss:
            payload["stopLoss"]   = str(round(stop_loss, 6))
        if take_profit:
            payload["takeProfit"] = str(round(take_profit, 6))
        log.info(f"PLACE ORDER → {payload}")
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
                log.warning(f"Leverage {side} error: {e}")

    async def get_min_qty(self, symbol: str) -> float:
        """Obtiene la cantidad mínima de orden para el símbolo."""
        try:
            d = await self._get("/openApi/swap/v2/quote/contracts")
            for c in d.get("data", []):
                if c.get("symbol") == symbol:
                    return float(c.get("tradeMinQuantity", 0.001))
        except Exception:
            pass
        return 0.001


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

async def tg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                        "text": text[:4000], "parse_mode": "Markdown"})
            if r.status_code != 200:
                log.error(f"Telegram error: {r.text}")
    except Exception as e:
        log.error(f"Telegram: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def ema(v, p):
    k, r = 2/(p+1), np.zeros_like(v, dtype=float)
    r[0] = v[0]
    for i in range(1, len(v)):
        r[i] = v[i]*k + r[i-1]*(1-k)
    return r

def hma(v, p):
    return ema(2*ema(v, p//2) - ema(v, p), max(int(np.sqrt(p)),1))

def sma(v, p):
    return np.convolve(v, np.ones(p)/p, mode="same")

def stoch_s(src, p):
    r = np.zeros_like(src, dtype=float)
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]
        lo, hi = w.min(), w.max()
        r[i] = (src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_ind(c):
    macd = ema(c,23) - ema(c,50)
    return stoch_s(stoch_s(macd, 10), 10)

def pivot_hi(h, n):
    r = np.full_like(h, np.nan, dtype=float)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max():
            r[i] = h[i]
    return r

def pivot_lo(l, n):
    r = np.full_like(l, np.nan, dtype=float)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min():
            r[i] = l[i]
    return r


# ══════════════════════════════════════════════════════════════════
# SCORER (para rankear coins)
# ══════════════════════════════════════════════════════════════════

@dataclass
class CoinScore:
    symbol:     str
    volume_24h: float
    score:      int
    direction:  str
    signals:    list = field(default_factory=list)
    change_24h: float = 0.0

def score_coin(ticker: dict, candles: list) -> Optional["CoinScore"]:
    if len(candles) < 55:
        log.warning(f"{ticker['symbol']}: solo {len(candles)} velas, skip")
        return None

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    # Sanity check: datos válidos
    if closes[-1] <= 0 or np.any(np.isnan(closes)):
        return None

    e7, e17 = ema(closes,7), ema(closes,17)
    e4, e20 = ema(closes,4), ema(closes,20)
    h50     = hma(closes,50)
    stc_v   = stc_ind(closes)
    vol_ma  = sma(volumes,20)

    # Volumen institucional: >1.5x media 20
    inst_vol = bool(volumes[-1] > vol_ma[-1]*1.5) if vol_ma[-1] > 0 else False

    ph_vals = pivot_hi(highs, 5)
    pl_vals = pivot_lo(lows,  5)
    vph = ph_vals[~np.isnan(ph_vals)]
    vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph) > 0 else float(highs[-1])
    valley = float(vpl[-1]) if len(vpl) > 0 else float(lows[-1])

    i = -1
    score, signals, direction = 0, [], "NEUTRAL"

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    # FILTRO 1: Hull (20 pts)
    if hull_bull:
        score += 20; signals.append("Hull🟢"); direction = "LONG"
    elif hull_bear:
        score += 20; signals.append("Hull🔴"); direction = "SHORT"

    # FILTRO 2: EMA alineación (20 pts) — más fácil que exigir cruce exacto
    if hull_bull and e7[i] > e17[i]:
        score += 20; signals.append("EMA🟢")
        if e7[i-1] < e17[i-1]:  # cruce fresco = bonus
            score += 5; signals.append("Cruz✅")
    elif hull_bear and e7[i] < e17[i]:
        score += 20; signals.append("EMA🔴")
        if e7[i-1] > e17[i-1]:
            score += 5; signals.append("Cruz✅")

    # FILTRO 3: Cerca de pivot o rotura (15 pts)
    rng = peak - valley
    if rng > 0:
        if hull_bull and closes[i] > (valley + rng*0.6):
            score += 15; signals.append("Zona🟢")
        elif hull_bear and closes[i] < (peak - rng*0.6):
            score += 15; signals.append("Zona🔴")

    # FILTRO 4: Volumen institucional (15 pts)
    if inst_vol:
        score += 15; signals.append("Vol💜")

    # FILTRO 5: STC momentum (15 pts)
    if hull_bull and stc_v[i] > stc_v[i-1]:
        score += 15; signals.append("STC🟢")
    elif hull_bear and stc_v[i] < stc_v[i-1]:
        score += 15; signals.append("STC🔴")

    # FILTRO 6: Slope ChartArt (10 pts)
    s4  = (e4[i]  - e4[i-1])
    s20 = (e20[i] - e20[i-1])
    if (hull_bull and s4>0 and s20>0) or (hull_bear and s4<0 and s20<0):
        score += 10; signals.append("Slope✅")

    log.info(f"{ticker['symbol']}: score={score} dir={direction} signals={signals}")

    return CoinScore(
        symbol=ticker["symbol"],
        volume_24h=ticker["volume_24h"],
        score=min(score, 100),
        direction=direction,
        signals=signals,
        change_24h=ticker.get("change_24h", 0),
    )


# ══════════════════════════════════════════════════════════════════
# SIGNAL ENGINE (entrada real)
# ══════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    direction: str
    entry: float
    sl: float
    tp: float
    score: int = 0
    note: str = ""

def compute_signal(candles: list) -> Signal:
    if len(candles) < 55:
        return Signal("NONE", 0, 0, 0)

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    e7, e17 = ema(closes,7), ema(closes,17)
    e2, e4, e20 = ema(closes,2), ema(closes,4), ema(closes,20)
    h50     = hma(closes,50)
    stc_v   = stc_ind(closes)
    vol_ma  = sma(volumes,20)
    inst_vol = bool(volumes[-1] > vol_ma[-1]*1.3)  # bajado a 1.3x

    ph_vals = pivot_hi(highs,5); pl_vals = pivot_lo(lows,5)
    vph = ph_vals[~np.isnan(ph_vals)]; vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph)>0 else float(highs.max())
    valley = float(vpl[-1]) if len(vpl)>0 else float(lows.min())

    i = -1
    entry = float(closes[i])
    if entry <= 0:
        return Signal("NONE", 0, 0, 0)

    hull_bull = bool(closes[i] > h50[i])
    hull_bear = bool(closes[i] < h50[i])

    # Señal APEX completa (score 100)
    apex_l = (hull_bull and e7[i]>e17[i] and closes[i]>peak
              and inst_vol and stc_v[i]>stc_v[i-1] and (e7[i]-e7[i-1])>0)
    apex_s = (hull_bear and e7[i]<e17[i] and closes[i]<valley
              and inst_vol and stc_v[i]<stc_v[i-1] and (e7[i]-e7[i-1])<0)

    # Señal RELAJADA: hull + ema cross + volumen (score 70) — NUEVA
    relax_l = (hull_bull and e7[i-1]<e17[i-1] and e7[i]>e17[i] and inst_vol)
    relax_s = (hull_bear and e7[i-1]>e17[i-1] and e7[i]<e17[i] and inst_vol)

    # Señal MÍNIMA: solo hull + ema cross (score 50) — para no quedarse sin operar
    min_l = (hull_bull and e7[i-1]<e17[i-1] and e7[i]>e17[i])
    min_s = (hull_bear and e7[i-1]>e17[i-1] and e7[i]<e17[i])

    def make_signal(direction, sl_level, sc, note=""):
        sl   = sl_level
        risk = abs(entry - sl)
        if risk < entry*0.001:  # SL demasiado cercano (<0.1%), usar ATR
            tr   = np.mean(np.abs(np.diff(closes[-14:])))
            risk = tr * 1.5
            sl   = entry - risk if direction=="LONG" else entry + risk
        tp = entry + risk*3 if direction=="LONG" else entry - risk*3
        return Signal(direction, entry, sl, tp, sc, note)

    if apex_l:   return make_signal("LONG",  valley, 100)
    if apex_s:   return make_signal("SHORT", peak,   100)
    if relax_l:  return make_signal("LONG",  valley,  70, "⚡Relax")
    if relax_s:  return make_signal("SHORT", peak,    70, "⚡Relax")
    if min_l:    return make_signal("LONG",  valley,  50, "📊MinSignal")
    if min_s:    return make_signal("SHORT", peak,    50, "📊MinSignal")

    return Signal("NONE", entry, 0, 0)


# ══════════════════════════════════════════════════════════════════
# RISK
# ══════════════════════════════════════════════════════════════════

async def calc_qty(exchange: BingXClient, symbol: str,
                   balance: float, entry: float, sl: float) -> float:
    risk_usd = balance * (MAX_RISK_PCT / 100)
    dist = abs(entry - sl)
    if dist < 1e-10:
        return 0.0
    qty = round(risk_usd / dist, 3)
    min_q = await exchange.get_min_qty(symbol)
    if qty < min_q:
        log.warning(f"Qty {qty} < min {min_q} para {symbol}, usando mínimo")
        qty = min_q
    return qty


# ══════════════════════════════════════════════════════════════════
# MAIN BOT
# ══════════════════════════════════════════════════════════════════

exchange     = BingXClient()
watchlist:   list[str] = []
last_signal: dict[str,str] = {}

async def scanner_loop():
    global watchlist
    while True:
        try:
            log.info(f"🔍 Escaneando TOP {SCAN_TOP_N} coins...")
            tickers = await exchange.get_all_tickers()

            if not tickers:
                log.warning("No hay tickers válidos — revisando MIN_VOL_USDT o WHITELIST")
                await tg("⚠️ Sin tickers válidos. Revisa MIN_VOL_USDT o USE_WHITELIST en Railway.")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            tasks   = [exchange.get_klines(t["symbol"], TIMEFRAME, 200) for t in tickers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            scored = []
            for ticker, candles in zip(tickers, results):
                if isinstance(candles, Exception):
                    log.warning(f"{ticker['symbol']} klines error: {candles}")
                    continue
                cs = score_coin(ticker, candles)
                if cs:
                    scored.append(cs)

            scored.sort(key=lambda x: x.score, reverse=True)

            # Watchlist = coins con score >= umbral, o top 5 si nadie llega
            operables = [c for c in scored if c.score >= SCORE_THRESHOLD and c.direction != "NEUTRAL"]
            watchlist = [c.symbol for c in operables] if operables else [c.symbol for c in scored[:5]]

            # Mensaje Telegram
            lines = [f"🔍 *ESCANEO — TOP {len(scored)} coins*\n"]
            for n, c in enumerate(scored, 1):
                emoji = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                bar   = "█"*(c.score//10) + "░"*(10-c.score//10)
                lines.append(
                    f"*#{n}* {emoji} `{c.symbol}` `{c.score}/100`\n"
                    f"`{bar}` {' '.join(c.signals)}\n"
                    f"Vol: `${c.volume_24h/1e6:.0f}M`  Δ:`{c.change_24h:+.1f}%`\n"
                )

            lines.append(f"\n👀 *Watchlist activa:*")
            for s in watchlist:
                lines.append(f"  • `{s}`")

            await tg("\n".join(lines))

        except Exception as e:
            log.error(f"Scanner error: {e}", exc_info=True)
            await tg(f"⚠️ *Error escáner:* `{str(e)[:200]}`")

        await asyncio.sleep(SCAN_INTERVAL)


async def trading_loop():
    await asyncio.sleep(45)  # esperar primer escaneo
    while True:
        try:
            for symbol in list(watchlist):
                await trade_coin(symbol)
                await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Trading loop error: {e}", exc_info=True)
        await asyncio.sleep(60)


async def trade_coin(symbol: str):
    try:
        candles  = await exchange.get_klines(symbol, TIMEFRAME, 200)
        signal   = compute_signal(candles)
        position = await exchange.get_position(symbol)
        has_pos  = position is not None

        log.info(f"{symbol}: signal={signal.direction} score={signal.score} has_pos={has_pos}")

        # Cerrar posición contraria
        if has_pos and signal.direction != "NONE":
            amt      = float(position["positionAmt"])
            pos_side = "LONG" if amt > 0 else "SHORT"
            if pos_side != signal.direction:
                await exchange.close_position(symbol, position)
                await tg(f"🔄 *Cierre* {pos_side} `{symbol}` @ `{signal.entry:.6f}`")
                has_pos = False

        # Abrir nueva posición
        if not has_pos and signal.direction != "NONE" and signal.score >= 50:
            if last_signal.get(symbol) == signal.direction:
                return  # ya abrimos esta señal, no duplicar

            balance = await exchange.get_balance()
            if balance < 5:
                log.warning(f"Balance insuficiente: {balance} USDT")
                await tg(f"⚠️ Balance insuficiente: `{balance:.2f} USDT`")
                return

            qty = await calc_qty(exchange, symbol, balance, signal.entry, signal.sl)
            if qty <= 0:
                log.warning(f"{symbol}: qty=0, SL muy cerca del entry")
                return

            await exchange.set_leverage(symbol, LEVERAGE)

            side = "BUY" if signal.direction=="LONG" else "SELL"
            await exchange.place_order(
                symbol=symbol, side=side,
                position_side=signal.direction,
                qty=qty,
                stop_loss=signal.sl,
                take_profit=signal.tp,
            )

            emoji = "🟢" if signal.direction=="LONG" else "🔴"
            risk_usd = abs(signal.entry - signal.sl) * qty
            await tg(
                f"{emoji} *{signal.direction} ABIERTO*\n"
                f"Par: `{symbol}`\n"
                f"Entry: `{signal.entry:.6f}`\n"
                f"SL: `{signal.sl:.6f}`  TP: `{signal.tp:.6f}`\n"
                f"Qty: `{qty}`  Score: `{signal.score}/100`\n"
                f"Riesgo: `~{risk_usd:.2f} USDT`\n"
                f"{signal.note}"
            )
            log.info(f"✅ ORDEN ABIERTA {signal.direction} {symbol} qty={qty}")
            last_signal[symbol] = signal.direction

        elif signal.direction == "NONE":
            last_signal[symbol] = "NONE"

    except Exception as e:
        log.error(f"trade_coin {symbol}: {e}", exc_info=True)
        # No enviar al telegram cada error de coin individual para no spamear


async def main():
    log.info("🚀 Sniper Bot V26.1 — Iniciando...")
    await tg(
        "🟢 *Sniper Bot V26.1 ACTIVO*\n"
        f"Timeframe: `{TIMEFRAME}`\n"
        f"Leverage: `{LEVERAGE}x`\n"
        f"Riesgo/trade: `{MAX_RISK_PCT}%`\n"
        f"Score mínimo: `{SCORE_THRESHOLD}/100`\n"
        f"Vol mínimo: `${MIN_VOL_USDT/1e6:.0f}M`\n"
        f"Whitelist: `{'ON' if USE_WHITELIST else 'OFF'}`\n"
        f"Scan cada: `{SCAN_INTERVAL//60}min`"
    )
    await asyncio.gather(scanner_loop(), trading_loop())


if __name__ == "__main__":
    asyncio.run(main())
