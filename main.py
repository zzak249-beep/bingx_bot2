"""
MLP Tactical Bridge Bot - BingX Trading Bot
Estrategia: Triple Confirmación (Tendencial + WaveTrend + ADX)
"""

import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY", "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL        = os.getenv("SYMBOL", "BTC-USDT")          # Par a operar
TIMEFRAME     = os.getenv("TIMEFRAME", "1h")             # Temporalidad
TRADE_AMOUNT  = float(os.getenv("TRADE_AMOUNT", "10"))   # USDT por operación
LEVERAGE      = int(os.getenv("LEVERAGE", "5"))          # Apalancamiento
MAX_RISK_PCT  = float(os.getenv("MAX_RISK_PCT", "2"))    # % max riesgo por trade
MIN_SIGNAL    = int(os.getenv("MIN_SIGNAL", "2"))        # Mínimo puntos (2 o 3)
USE_LIVE      = os.getenv("USE_LIVE", "false").lower() == "true"

BINGX_BASE = "https://open-api.bingx.com"

INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h",
    "6h": "6h", "12h": "12h", "1d": "1d", "1w": "1w"
}


# ─── BINGX API ─────────────────────────────────────────────────────────────────
def bingx_sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(BINGX_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()

def bingx_get(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = bingx_sign(params)
    headers = {"X-BX-APIKEY": BINGX_API_KEY}
    r = requests.get(BINGX_BASE + path, params=params, headers=headers, timeout=10)
    return r.json()

def bingx_post(path: str, params: dict) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = bingx_sign(params)
    headers = {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}
    r = requests.post(BINGX_BASE + path, json=params, headers=headers, timeout=10)
    return r.json()

def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    path = "/openApi/swap/v3/quote/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = bingx_get(path, params)
    if data.get("code") != 0:
        logger.error(f"Klines error: {data}")
        return pd.DataFrame()
    rows = data["data"]
    df = pd.DataFrame(rows, columns=["open_time","open","high","low","close","volume","close_time","_"])
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col])
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df.sort_values("close_time").reset_index(drop=True)

def get_position(symbol: str) -> dict | None:
    data = bingx_get("/openApi/swap/v2/user/positions", {"symbol": symbol})
    positions = data.get("data", {}).get("positions", [])
    for p in positions:
        if float(p.get("positionAmt", 0)) != 0:
            return p
    return None

def get_balance() -> float:
    data = bingx_get("/openApi/swap/v2/user/balance")
    return float(data.get("data", {}).get("balance", {}).get("availableMargin", 0))

def set_leverage(symbol: str, lev: int):
    bingx_post("/openApi/swap/v2/trade/leverage", {
        "symbol": symbol, "side": "LONG", "leverage": lev
    })
    bingx_post("/openApi/swap/v2/trade/leverage", {
        "symbol": symbol, "side": "SHORT", "leverage": lev
    })

def place_order(symbol: str, side: str, qty: float, sl: float, tp: float) -> dict:
    """side: LONG o SHORT"""
    action = "BUY" if side == "LONG" else "SELL"
    pos_side = side
    params = {
        "symbol": symbol,
        "side": action,
        "positionSide": pos_side,
        "type": "MARKET",
        "quantity": round(qty, 4),
    }
    result = bingx_post("/openApi/swap/v2/trade/order", params)
    logger.info(f"Order result: {result}")

    # SL y TP
    sl_side = "SELL" if side == "LONG" else "BUY"
    bingx_post("/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "STOP_MARKET", "stopPrice": round(sl, 4), "quantity": round(qty, 4),
        "workingType": "MARK_PRICE"
    })
    bingx_post("/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": pos_side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": round(tp, 4), "quantity": round(qty, 4),
        "workingType": "MARK_PRICE"
    })
    return result

def close_position(symbol: str, position: dict):
    amt = abs(float(position["positionAmt"]))
    pos_side = position["positionSide"]
    close_side = "SELL" if pos_side == "LONG" else "BUY"
    return bingx_post("/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": close_side, "positionSide": pos_side,
        "type": "MARKET", "quantity": round(amt, 4), "reduceOnly": True
    })


# ─── INDICADORES ───────────────────────────────────────────────────────────────
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_tendencial(df: pd.DataFrame, length: int = 55) -> pd.Series:
    """EMA 55 como línea tendencial principal"""
    return calc_ema(df["close"], length)

def calc_wavetrend(df: pd.DataFrame, ch_len: int = 10, avg_len: int = 21,
                   ob1: float = 60, os1: float = -60) -> pd.DataFrame:
    """WaveTrend (LazyBear) - portado a Python"""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = calc_ema(ap, ch_len)
    d   = calc_ema(abs(ap - esa), ch_len)
    ci  = (ap - esa) / (0.015 * d)
    tci = calc_ema(ci, avg_len)
    wt2 = tci.rolling(4).mean()
    wt1 = tci

    result = pd.DataFrame({
        "wt1": wt1,
        "wt2": wt2,
        "cross_up":   (wt1.shift(1) < wt2.shift(1)) & (wt1 >= wt2) & (wt1 < os1),
        "cross_down": (wt1.shift(1) > wt2.shift(1)) & (wt1 <= wt2) & (wt1 > ob1),
        "oversold":   wt1 < os1,
        "overbought": wt1 > ob1,
    })
    return result

def calc_adx(df: pd.DataFrame, period: int = 14, key_level: float = 23) -> pd.DataFrame:
    """ADX / DMI"""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        abs(high - close.shift(1)),
        abs(low  - close.shift(1))
    ], axis=1).max(axis=1)

    dm_plus  = np.where((high - high.shift(1)) > (low.shift(1) - low),
                        np.maximum(high - high.shift(1), 0), 0)
    dm_minus = np.where((low.shift(1) - low) > (high - high.shift(1)),
                        np.maximum(low.shift(1) - low, 0), 0)

    atr  = pd.Series(tr).ewm(span=period, adjust=False).mean()
    pdi  = 100 * pd.Series(dm_plus).ewm(span=period, adjust=False).mean()  / atr
    mdi  = 100 * pd.Series(dm_minus).ewm(span=period, adjust=False).mean() / atr
    dx   = 100 * abs(pdi - mdi) / (pdi + mdi).replace(0, np.nan)
    adx  = dx.ewm(span=period, adjust=False).mean()

    return pd.DataFrame({
        "adx":      adx.values,
        "pdi":      pdi.values,
        "mdi":      mdi.values,
        "adx_fall": (adx < adx.shift(1)).values,
        "bull_dir": (pdi > mdi).values,
        "bear_dir": (mdi > pdi).values,
    }, index=df.index)


# ─── SEÑAL PRINCIPAL ───────────────────────────────────────────────────────────
class Signal:
    def __init__(self, direction: str, points: int, price: float,
                 sl: float, tp: float, reason: str):
        self.direction = direction   # LONG / SHORT
        self.points    = points      # 1-3
        self.price     = price
        self.sl        = sl
        self.tp        = tp
        self.reason    = reason

def analyze(df: pd.DataFrame) -> Signal | None:
    if len(df) < 60:
        return None

    ema    = calc_tendencial(df)
    wt     = calc_wavetrend(df)
    adx_df = calc_adx(df)

    i = -2  # última vela cerrada
    close   = df["close"].iloc[i]
    ema_val = ema.iloc[i]

    # Punto 1 – Tendencial
    trend_bull = close > ema_val
    trend_bear = close < ema_val
    zone_pct   = 0.005  # 0.5% zona alrededor de EMA
    in_zone    = abs(close - ema_val) / ema_val < zone_pct

    # Punto 2 – WaveTrend
    wt_cross_up   = bool(wt["cross_up"].iloc[i])
    wt_cross_down = bool(wt["cross_down"].iloc[i])
    wt_oversold   = bool(wt["oversold"].iloc[i])
    wt_overbought = bool(wt["overbought"].iloc[i])

    # Punto 3 – ADX/Direccionalidad
    adx_fall  = bool(adx_df["adx_fall"].iloc[i])
    bull_dir  = bool(adx_df["bull_dir"].iloc[i])
    bear_dir  = bool(adx_df["bear_dir"].iloc[i])
    adx_val   = float(adx_df["adx"].iloc[i])

    # Calcular SL/TP dinámico
    atr = df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()
    atr_pct = atr / close

    sl_dist = max(atr_pct * 1.5, 0.01)   # min 1%
    tp_dist = sl_dist * 1.8               # R:R mínimo 1.8

    # ── LONG ──
    if trend_bull or in_zone:
        pts = 0
        reasons = []
        if in_zone or (close > ema_val * 0.995):
            pts += 1; reasons.append("Tendencial✓")
        if wt_cross_up or wt_oversold:
            pts += 1; reasons.append("WT-Oversold✓")
        if adx_fall and bull_dir:
            pts += 1; reasons.append("ADX-Bull✓")

        if pts >= MIN_SIGNAL and trend_bull:
            sl = close * (1 - sl_dist)
            tp = close * (1 + tp_dist)
            return Signal("LONG", pts, close, sl, tp, " | ".join(reasons))

    # ── SHORT ──
    if trend_bear or in_zone:
        pts = 0
        reasons = []
        if in_zone or (close < ema_val * 1.005):
            pts += 1; reasons.append("Tendencial✓")
        if wt_cross_down or wt_overbought:
            pts += 1; reasons.append("WT-Overbought✓")
        if adx_fall and bear_dir:
            pts += 1; reasons.append("ADX-Bear✓")

        if pts >= MIN_SIGNAL and trend_bear:
            sl = close * (1 + sl_dist)
            tp = close * (1 - tp_dist)
            return Signal("SHORT", pts, close, sl, tp, " | ".join(reasons))

    return None


# ─── TELEGRAM NOTIFICACIONES ───────────────────────────────────────────────────
async def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info(f"[TELEGRAM] {msg}")
        return
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


# ─── LOOP PRINCIPAL ────────────────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        self.last_signal_time = None
        self.current_position = None

    def run_cycle(self):
        logger.info(f"[CYCLE] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {SYMBOL} {TIMEFRAME}")

        df = get_klines(SYMBOL, INTERVAL_MAP.get(TIMEFRAME, "1h"), 200)
        if df.empty:
            logger.warning("No data received")
            return

        # Revisar posición activa
        pos = None
        if USE_LIVE:
            pos = get_position(SYMBOL)

        if pos:
            logger.info(f"Position active: {pos['positionSide']} | PnL: {pos.get('unrealizedProfit', '?')}")
            return

        signal = analyze(df)
        if not signal:
            logger.info("No signal")
            return

        logger.info(f"SIGNAL {signal.points}/3 {signal.direction} @ {signal.price:.4f} | {signal.reason}")

        import asyncio
        msg = (
            f"🎯 <b>SEÑAL {signal.points}/3 — {signal.direction}</b>\n"
            f"📊 Par: <code>{SYMBOL}</code> | TF: {TIMEFRAME}\n"
            f"💰 Precio: <code>{signal.price:.4f}</code>\n"
            f"🛑 SL: <code>{signal.sl:.4f}</code>\n"
            f"✅ TP: <code>{signal.tp:.4f}</code>\n"
            f"📋 Confirmaciones: {signal.reason}\n"
            f"{'🔴 MODO REAL' if USE_LIVE else '🟡 MODO DEMO'}"
        )
        asyncio.run(send_telegram(msg))

        if USE_LIVE and signal.points >= MIN_SIGNAL:
            balance = get_balance()
            qty = (TRADE_AMOUNT * LEVERAGE) / signal.price
            set_leverage(SYMBOL, LEVERAGE)
            result = place_order(SYMBOL, signal.direction, qty, signal.sl, signal.tp)

            result_msg = (
                f"{'✅' if result.get('code') == 0 else '❌'} Orden ejecutada\n"
                f"ID: {result.get('data', {}).get('order', {}).get('orderId', 'N/A')}"
            )
            asyncio.run(send_telegram(result_msg))
            logger.info(f"Order: {result}")


def main():
    bot = TradingBot()
    import asyncio

    # Verificar conexión
    if USE_LIVE:
        bal = get_balance()
        logger.info(f"Balance disponible: {bal} USDT")
        asyncio.run(send_telegram(
            f"🤖 <b>Bot iniciado</b>\n"
            f"📊 {SYMBOL} | {TIMEFRAME}\n"
            f"💵 Balance: {bal:.2f} USDT\n"
            f"⚡ Apalancamiento: {LEVERAGE}x\n"
            f"🎯 Señal mínima: {MIN_SIGNAL}/3\n"
            f"🔴 MODO REAL ACTIVO"
        ))
    else:
        asyncio.run(send_telegram(
            f"🤖 <b>Bot iniciado (DEMO)</b>\n"
            f"📊 {SYMBOL} | {TIMEFRAME}\n"
            f"🟡 Para modo real: USE_LIVE=true"
        ))

    # Calcular intervalo de espera según temporalidad
    interval_seconds = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
        "1d": 86400
    }.get(TIMEFRAME, 3600)

    wait_time = max(60, interval_seconds // 4)  # Revisar 4 veces por vela

    while True:
        try:
            bot.run_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            import asyncio
            asyncio.run(send_telegram(f"⚠️ Error en ciclo: {str(e)[:200]}"))
        time.sleep(wait_time)


if __name__ == "__main__":
    main()
