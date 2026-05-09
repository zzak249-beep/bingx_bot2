"""
Sniper Bot V26.1 - Institutional Apex Multi-Coin
ARCHIVO ÚNICO - Sin dependencias de carpetas src/
Funciona directamente en Railway sin estructura de paquetes.
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

# ── Logging ───────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log")],
)
log = logging.getLogger("SniperBot")

# ── Config desde variables de entorno ─────────────────────────────
BINGX_API_KEY    = os.environ["BINGX_API_KEY"]
BINGX_API_SECRET = os.environ["BINGX_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SYMBOL           = os.getenv("SYMBOL", "BTC-USDT")
TIMEFRAME        = os.getenv("TIMEFRAME", "15m")
LEVERAGE         = int(os.getenv("LEVERAGE", "5"))
MAX_RISK_PCT     = float(os.getenv("MAX_RISK_PCT", "1.0"))
SCAN_TOP_N       = int(os.getenv("SCAN_TOP_N", "10"))
MIN_VOL_USDT     = float(os.getenv("MIN_VOL_USDT", "50000000"))
SCORE_THRESHOLD  = int(os.getenv("SCORE_THRESHOLD", "65"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MIN", "15")) * 60

BASE_URL = "https://open-api.bingx.com"


# ══════════════════════════════════════════════════════════════════
# EXCHANGE CLIENT
# ══════════════════════════════════════════════════════════════════

class BingXClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=15)

    def _sign(self, params: dict) -> str:
        query = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _headers(self) -> dict:
        return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}

    async def _get(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)
        r = await self.client.get(path, params=params, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"BingX {data['code']}: {data.get('msg')}")
        return data

    async def _post(self, path: str, payload: dict) -> dict:
        payload["timestamp"] = int(time.time() * 1000)
        payload["signature"] = self._sign(payload)
        r = await self.client.post(path, params=payload, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"BingX {data['code']}: {data.get('msg')}")
        return data

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        data = await self._get("/openApi/swap/v3/quote/klines",
                               {"symbol": symbol, "interval": interval, "limit": limit})
        return [{"time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                 "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                for c in data["data"]]

    async def get_all_tickers(self) -> list:
        data = await self._get("/openApi/swap/v2/quote/ticker")
        tickers = []
        for t in data.get("data", []):
            try:
                vol = float(t.get("quoteVolume", 0) or t.get("volume", 0))
                sym = t.get("symbol", "")
                if not sym.endswith("-USDT") or vol < MIN_VOL_USDT:
                    continue
                tickers.append({"symbol": sym, "volume_24h": vol,
                                 "price": float(t.get("lastPrice", 0)),
                                 "change_24h": float(t.get("priceChangePercent", 0))})
            except Exception:
                continue
        tickers.sort(key=lambda x: x["volume_24h"], reverse=True)
        return tickers[:SCAN_TOP_N]

    async def get_balance(self) -> float:
        data = await self._get("/openApi/swap/v2/user/balance")
        for a in data["data"]["balance"]:
            if a["asset"] == "USDT":
                return float(a["availableMargin"])
        return 0.0

    async def get_position(self, symbol: str) -> Optional[dict]:
        data = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        positions = data.get("data", [])
        return positions[0] if positions else None

    async def place_order(self, symbol, side, position_side, qty,
                          stop_loss=None, take_profit=None, reduce_only=False) -> dict:
        payload = {"symbol": symbol, "side": side, "positionSide": position_side,
                   "type": "MARKET", "quantity": str(qty),
                   "reduceOnly": str(reduce_only).lower()}
        if stop_loss:    payload["stopLoss"]    = str(stop_loss)
        if take_profit:  payload["takeProfit"]  = str(take_profit)
        log.info(f"Order: {payload}")
        return await self._post("/openApi/swap/v2/trade/order", payload)

    async def close_position(self, symbol: str, position: dict) -> dict:
        amt  = float(position["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        pside = "LONG" if amt > 0 else "SHORT"
        return await self.place_order(symbol, side, pside, abs(amt), reduce_only=True)

    async def set_leverage(self, symbol: str, leverage: int):
        for side in ("LONG", "SHORT"):
            await self._post("/openApi/swap/v2/trade/leverage",
                             {"symbol": symbol, "side": side, "leverage": str(leverage)})


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

async def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                    "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        log.error(f"Telegram error: {e}")


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def ema(v: np.ndarray, p: int) -> np.ndarray:
    k, r = 2/(p+1), np.zeros_like(v)
    r[0] = v[0]
    for i in range(1, len(v)):
        r[i] = v[i]*k + r[i-1]*(1-k)
    return r

def hma(v: np.ndarray, p: int) -> np.ndarray:
    return ema(2*ema(v, p//2) - ema(v, p), int(np.sqrt(p)))

def sma(v: np.ndarray, p: int) -> np.ndarray:
    return np.convolve(v, np.ones(p)/p, mode="same")

def stoch_s(src: np.ndarray, p: int) -> np.ndarray:
    r = np.zeros_like(src)
    for i in range(p-1, len(src)):
        w = src[i-p+1:i+1]
        lo, hi = w.min(), w.max()
        r[i] = (src[i]-lo)/(hi-lo+1e-10)
    return r

def stc_ind(c: np.ndarray) -> np.ndarray:
    return stoch_s(stoch_s(ema(c,23)-ema(c,50), 10), 10)

def pivot_hi(h: np.ndarray, n: int) -> np.ndarray:
    r = np.full_like(h, np.nan)
    for i in range(n, len(h)-n):
        if h[i] == h[i-n:i+n+1].max(): r[i] = h[i]
    return r

def pivot_lo(l: np.ndarray, n: int) -> np.ndarray:
    r = np.full_like(l, np.nan)
    for i in range(n, len(l)-n):
        if l[i] == l[i-n:i+n+1].min(): r[i] = l[i]
    return r


# ══════════════════════════════════════════════════════════════════
# RISK MANAGER
# ══════════════════════════════════════════════════════════════════

def calc_qty(balance: float, entry: float, sl: float) -> float:
    risk_usd = balance * (MAX_RISK_PCT / 100)
    dist = abs(entry - sl)
    if dist < 1e-8: return 0.0
    return max(round(risk_usd / dist, 3), 0.001)


# ══════════════════════════════════════════════════════════════════
# SCORER
# ══════════════════════════════════════════════════════════════════

@dataclass
class CoinScore:
    symbol:     str
    volume_24h: float
    price:      float
    change_24h: float
    score:      int
    direction:  str
    signals:    list = field(default_factory=list)
    sl:         float = 0.0
    tp:         float = 0.0
    atr:        float = 0.0

def score_coin(ticker: dict, candles: list) -> Optional[CoinScore]:
    if len(candles) < 60: return None
    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    e7, e17  = ema(closes,7), ema(closes,17)
    e4, e20  = ema(closes,4), ema(closes,20)
    h50      = hma(closes,50)
    stc_v    = stc_ind(closes)
    vol_ma   = sma(volumes,20)
    inst_vol = volumes[-1] > vol_ma[-1]*1.5

    ph_vals  = pivot_hi(highs,5)
    pl_vals  = pivot_lo(lows,5)
    vph = ph_vals[~np.isnan(ph_vals)]
    vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph)>0 else highs[-1]
    valley = float(vpl[-1]) if len(vpl)>0 else lows[-1]

    tr    = np.maximum(highs-lows, np.abs(highs-np.roll(closes,1)), np.abs(lows-np.roll(closes,1)))
    atr14 = float(np.mean(tr[-14:]))
    rel_atr = atr14/closes[-1]

    i = -1
    score, signals, direction = 0, [], "NEUTRAL"
    hull_bull = closes[i] > h50[i]
    hull_bear = closes[i] < h50[i]

    if hull_bull or hull_bear:
        score += 20; signals.append("Hull✅")
        direction = "LONG" if hull_bull else "SHORT"

    cross_up   = e7[i-1]<e17[i-1] and e7[i]>e17[i]
    cross_down = e7[i-1]>e17[i-1] and e7[i]<e17[i]
    if (hull_bull and cross_up) or (hull_bear and cross_down):
        score += 20; signals.append("EMACross✅")
    elif (hull_bull and e7[i]>e17[i]) or (hull_bear and e7[i]<e17[i]):
        score += 10; signals.append("EMAAlign✅")

    if (closes[i]>peak and hull_bull) or (closes[i]<valley and hull_bear):
        score += 15; signals.append("PivotBreak✅")

    if inst_vol:
        score += 15; signals.append("InstVol✅")

    if (stc_v[i]>stc_v[i-1] and hull_bull) or (stc_v[i]<stc_v[i-1] and hull_bear):
        score += 15; signals.append("STC✅")

    s4up = (e4[i]-e4[i-1])>0; s20up = (e20[i]-e20[i-1])>0
    if (hull_bull and s4up and s20up) or (hull_bear and not s4up and not s20up):
        score += 10; signals.append("CASlope✅")

    if rel_atr > 0.03:
        score = max(0, score-15); signals.append("⚠️HiVol")

    sl = valley if direction=="LONG" else peak
    risk = abs(closes[i]-sl)
    tp = closes[i]+risk*3 if direction=="LONG" else closes[i]-risk*3

    return CoinScore(
        symbol=ticker["symbol"], volume_24h=ticker["volume_24h"],
        price=closes[i], change_24h=ticker["change_24h"],
        score=min(score,100), direction=direction, signals=signals,
        sl=sl, tp=tp, atr=atr14
    )


# ══════════════════════════════════════════════════════════════════
# SIGNAL ENGINE
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
    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    e7, e17 = ema(closes,7), ema(closes,17)
    e2, e4, e20 = ema(closes,2), ema(closes,4), ema(closes,20)
    h50 = hma(closes,50)
    stc_v = stc_ind(closes)
    vol_ma = sma(volumes,20)
    inst_vol = volumes[-1] > vol_ma[-1]*1.5

    ph_vals = pivot_hi(highs,5); pl_vals = pivot_lo(lows,5)
    vph = ph_vals[~np.isnan(ph_vals)]; vpl = pl_vals[~np.isnan(pl_vals)]
    peak   = float(vph[-1]) if len(vph)>0 else highs[-1]
    valley = float(vpl[-1]) if len(vpl)>0 else lows[-1]

    i = -1
    entry = closes[i]

    apex_l = (e7[i-1]<e17[i-1] and e7[i]>e17[i] and closes[i]>peak
              and inst_vol and closes[i]>h50[i]
              and stc_v[i]>stc_v[i-1] and (e7[i]-e7[i-1])>0)
    apex_s = (e7[i-1]>e17[i-1] and e7[i]<e17[i] and closes[i]<valley
              and inst_vol and closes[i]<h50[i]
              and stc_v[i]<stc_v[i-1] and (e7[i]-e7[i-1])<0)
    ca_l = ((closes[i]<e20[i] and closes[i-1]>=e20[i-1]) or
            ((closes[i]-closes[i-1])<0 and (e2[i]-e2[i-1])<0
             and closes[i-1]>=e2[i-1] and closes[i]<e2[i] and (e4[i]-e4[i-1])>0))
    ca_s = ((closes[i]>e20[i] and closes[i-1]<=e20[i-1]) or
            ((closes[i]-closes[i-1])>0 and (e2[i]-e2[i-1])>0
             and closes[i-1]<=e2[i-1] and closes[i]>e2[i] and (e4[i]-e4[i-1])<0))

    if apex_l and ca_l:
        sl=valley; return Signal("LONG",  entry,sl, entry+abs(entry-sl)*3, score=100)
    if apex_s and ca_s:
        sl=peak;   return Signal("SHORT", entry,sl, entry-abs(sl-entry)*3, score=100)
    if apex_l:
        sl=valley; return Signal("LONG",  entry,sl, entry+abs(entry-sl)*3, score=70, note="⚠️ Sin CA")
    if apex_s:
        sl=peak;   return Signal("SHORT", entry,sl, entry-abs(sl-entry)*3, score=70, note="⚠️ Sin CA")
    return Signal("NONE", entry, 0, 0)


# ══════════════════════════════════════════════════════════════════
# MAIN LOOPS
# ══════════════════════════════════════════════════════════════════

exchange     = BingXClient()
watchlist:   list[CoinScore] = []
last_signal: dict[str,str]   = {}

async def scanner_loop():
    global watchlist
    while True:
        try:
            log.info(f"🔍 Escaneando TOP {SCAN_TOP_N} coins...")
            tickers = await exchange.get_all_tickers()
            log.info(f"Tickers: {[t['symbol'] for t in tickers]}")

            tasks   = [exchange.get_klines(t["symbol"], TIMEFRAME, 200) for t in tickers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            scored = []
            for ticker, candles in zip(tickers, results):
                if isinstance(candles, Exception):
                    log.warning(f"{ticker['symbol']}: {candles}")
                    continue
                cs = score_coin(ticker, candles)
                if cs: scored.append(cs)

            scored.sort(key=lambda x: x.score, reverse=True)

            # Notificar resumen
            lines = [f"🔍 *ESCANEO TOP {SCAN_TOP_N}*\n"]
            operables = []
            for n, c in enumerate(scored, 1):
                emoji = "🟢" if c.direction=="LONG" else "🔴" if c.direction=="SHORT" else "⚪"
                bar   = "█"*(c.score//10) + "░"*(10-c.score//10)
                lines.append(
                    f"*#{n}* {emoji} `{c.symbol}` `{c.score}/100`\n"
                    f"`{bar}`\n"
                    f"Vol: `${c.volume_24h/1e6:.0f}M`  Δ: `{c.change_24h:+.1f}%`\n"
                    f"Señales: {' '.join(c.signals)}\n"
                )
                if c.score >= SCORE_THRESHOLD and c.direction != "NEUTRAL":
                    operables.append(c)

            if operables:
                lines.append(f"🚨 *OPERABLES (≥{SCORE_THRESHOLD}):*")
                for c in operables:
                    lines.append(f"  → `{c.symbol}` {c.direction} `{c.score}pts`")

            await tg_send("\n".join(lines))
            watchlist = operables if operables else scored[:3]  # fallback: top 3

        except Exception as e:
            log.error(f"Scanner error: {e}", exc_info=True)
            await tg_send(f"⚠️ *Error escáner:* `{e}`")

        log.info(f"Próximo escaneo en {SCAN_INTERVAL//60}min")
        await asyncio.sleep(SCAN_INTERVAL)


async def trading_loop():
    await asyncio.sleep(30)  # esperar primer escaneo
    while True:
        try:
            for coin in list(watchlist):
                await trade_coin(coin.symbol)
                await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Trading error: {e}", exc_info=True)
        await asyncio.sleep(60)


async def trade_coin(symbol: str):
    try:
        candles  = await exchange.get_klines(symbol, TIMEFRAME, 200)
        signal   = compute_signal(candles)
        position = await exchange.get_position(symbol)
        has_pos  = position and abs(float(position.get("positionAmt", 0))) > 0

        if has_pos and signal.direction != "NONE":
            pos_side = "LONG" if float(position["positionAmt"])>0 else "SHORT"
            if pos_side != signal.direction:
                await exchange.close_position(symbol, position)
                await tg_send(f"🔄 *Cierre* {pos_side} `{symbol}` @ `{signal.entry:.4f}`")
                has_pos = False

        if not has_pos and signal.direction != "NONE":
            if last_signal.get(symbol) == signal.direction:
                return
            balance = await exchange.get_balance()
            qty     = calc_qty(balance, signal.entry, signal.sl)
            if qty <= 0:
                return
            await exchange.set_leverage(symbol, LEVERAGE)
            side = "BUY" if signal.direction=="LONG" else "SELL"
            await exchange.place_order(
                symbol=symbol, side=side, position_side=signal.direction,
                qty=qty, stop_loss=round(signal.sl,4), take_profit=round(signal.tp,4)
            )
            emoji = "🟢" if signal.direction=="LONG" else "🔴"
            await tg_send(
                f"{emoji} *{signal.direction}* `{symbol}`\n"
                f"Entry: `{signal.entry:.4f}`\n"
                f"SL: `{signal.sl:.4f}`  TP: `{signal.tp:.4f}` (3R)\n"
                f"Qty: `{qty}`  Score: `{signal.score}/100`\n{signal.note}"
            )
            last_signal[symbol] = signal.direction
        elif signal.direction == "NONE":
            last_signal[symbol] = "NONE"

    except Exception as e:
        log.error(f"trade_coin {symbol}: {e}")


async def main():
    log.info("🚀 Sniper Bot V26.1 Multi-Coin - Iniciando...")
    await tg_send(
        "🟢 *Sniper Bot V26.1 ACTIVO*\n"
        f"Modo: Multi-Coin Scanner\n"
        f"Timeframe: `{TIMEFRAME}`\n"
        f"Score mínimo: `{SCORE_THRESHOLD}/100`\n"
        f"Top N: `{SCAN_TOP_N}`\n"
        f"Riesgo/trade: `{MAX_RISK_PCT}%`"
    )
    await asyncio.gather(scanner_loop(), trading_loop())


if __name__ == "__main__":
    asyncio.run(main())
