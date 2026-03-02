"""
╔══════════════════════════════════════════════════════════════════╗
║              SATY ELITE v19 — CLEAN TREND FOLLOWER              ║
║         BingX Perpetual Futures · 24/7 · Riesgo Controlado      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  FILOSOFÍA v19 (reescritura completa desde cero):               ║
║                                                                  ║
║  MENOS es MÁS. 5 señales independientes > 25 colineales.        ║
║                                                                  ║
║  SEÑALES (5 independientes, cada una mide algo distinto):       ║
║  1. Supertrend (10,3) — ¿Hay tendencia real?                    ║
║  2. EMA 8/48 — ¿Está la estructura alineada?                    ║
║  3. RSI(14) zona 40-62 — ¿No está sobrecomprado/vendido?        ║
║  4. ADX > 22 con DI correcto — ¿La tendencia tiene fuerza?      ║
║  5. Volumen > media 20 barras — ¿Hay dinero detrás?             ║
║                                                                  ║
║  GESTIÓN DE RIESGO:                                             ║
║  · Leverage: 3× (NO 12×)                                        ║
║  · Riesgo: 1% del capital por trade (kelly conservador)         ║
║  · SL: 2× ATR (estructura, no ruido)                            ║
║  · TP1: 1.5× ATR → mover SL a BE                               ║
║  · TP2: 3× ATR (R:R = 1.5)                                     ║
║  · Sin DCA — si la posición pierde, cierra                      ║
║  · Max 3 trades simultáneos                                      ║
║  · Cooldown 45min tras cierre                                    ║
║                                                                  ║
║  FILTROS MACRO:                                                  ║
║  · BTC tendencia (1h EMA)                                       ║
║  · Spread < 0.3%                                                 ║
║  · Volumen 24h > $5M                                            ║
║  · Circuit breaker: -5% drawdown diario                         ║
║                                                                  ║
║  TIMEFRAME: 15m (señal) + 1h (HTF bias) + 4h (macro)           ║
║                                                                  ║
║  VARIABLES OBLIGATORIAS:                                         ║
║      BINGX_API_KEY  BINGX_API_SECRET                            ║
║      TELEGRAM_BOT_TOKEN  TELEGRAM_CHAT_ID                       ║
║                                                                  ║
║  VARIABLES OPCIONALES:                                           ║
║      RISK_PCT       def:1.0   % del capital por trade           ║
║      MAX_TRADES     def:3     trades simultáneos máximo         ║
║      LEVERAGE       def:3     apalancamiento (máx 5)            ║
║      MIN_SCORE      def:4     señales mínimas de 5              ║
║      TIMEFRAME      def:15m                                      ║
║      HTF1           def:1h                                       ║
║      HTF2           def:4h                                       ║
║      POLL_SECS      def:60                                       ║
║      COOLDOWN_MIN   def:45                                       ║
║      DAILY_DD_PCT   def:5.0   circuit breaker diario            ║
║      MIN_VOLUME     def:5000000                                  ║
║      TOP_N          def:100   universo de pares                  ║
║      BLACKLIST      def:""    separado por comas                 ║
║      DRY_RUN        def:false modo simulación sin órdenes reales ║
╚══════════════════════════════════════════════════════════════════╝

ADVERTENCIA: El trading con futuros conlleva riesgo de pérdida total
del capital. Este bot no garantiza ganancias. Úsalo bajo tu propio
riesgo y solo con dinero que puedas permitirte perder.
"""

import os
import time
import logging
import csv
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import ccxt
import pandas as pd
import numpy as np

# ══════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("saty_v19")


# ══════════════════════════════════════════════════════════
# CONFIGURACIÓN — Variables de entorno
# ══════════════════════════════════════════════════════════
API_KEY    = os.environ.get("BINGX_API_KEY",    "")
API_SECRET = os.environ.get("BINGX_API_SECRET", "")
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID",   "")

TF         = os.environ.get("TIMEFRAME",  "15m")
HTF1       = os.environ.get("HTF1",       "1h")
HTF2       = os.environ.get("HTF2",       "4h")
POLL_SECS  = int(os.environ.get("POLL_SECS", "60"))

# Capital y riesgo
RISK_PCT       = float(os.environ.get("RISK_PCT",    "1.0"))   # % del balance por trade
MAX_TRADES     = int(os.environ.get("MAX_TRADES",    "3"))
LEVERAGE       = min(int(os.environ.get("LEVERAGE",  "3")), 5) # Máximo 5× forzado
MIN_SCORE      = int(os.environ.get("MIN_SCORE",     "4"))     # 4 de 5 señales

# Filtros
MIN_VOLUME     = float(os.environ.get("MIN_VOLUME",  "5000000"))
TOP_N          = int(os.environ.get("TOP_N",         "100"))
COOLDOWN_MIN   = int(os.environ.get("COOLDOWN_MIN",  "45"))
DAILY_DD_PCT   = float(os.environ.get("DAILY_DD_PCT","5.0"))
MAX_SPREAD_PCT = float(os.environ.get("MAX_SPREAD",  "0.3"))
DRY_RUN        = os.environ.get("DRY_RUN", "false").lower() == "true"

_bl = os.environ.get("BLACKLIST", "")
BLACKLIST: List[str] = [s.strip() for s in _bl.split(",") if s.strip()]

# Parámetros de indicadores (fijos, probados)
ATR_LEN       = 14
ADX_LEN       = 14
RSI_LEN       = 14
VOL_PERIOD    = 20
ST_PERIOD     = 10
ST_MULT       = 3.0
EMA_FAST      = 8
EMA_SLOW      = 48
EMA_TREND     = 200

# Niveles de salida
SL_ATR_MULT   = 2.0    # SL = 2 ATR (estructura, no ruido de 5m)
TP1_ATR_MULT  = 1.5    # TP1 = 1.5 ATR → mover SL a BE
TP2_ATR_MULT  = 3.0    # TP2 = 3 ATR (R:R = 1.5)
TRAIL_ATR_MULT= 1.0    # Trailing tras TP1

# RSI zonas
RSI_LONG_MAX  = 62.0   # Long solo si RSI < 62 (no sobrecomprado)
RSI_LONG_MIN  = 40.0   # Long solo si RSI > 40 (algo de momentum)
RSI_SHORT_MIN = 38.0   # Short solo si RSI > 38
RSI_SHORT_MAX = 60.0   # Short solo si RSI < 60

ADX_MIN       = 22     # Tendencia mínima
ADX_DI_MIN    = 3.0    # DI+ debe superar DI- por al menos 3 puntos

CSV_PATH  = "/tmp/saty_v19_trades.csv"
STAT_PATH = "/tmp/saty_v19_stats.json"


# ══════════════════════════════════════════════════════════
# CACHÉ OHLCV
# ══════════════════════════════════════════════════════════
_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
CACHE_TTL = 50  # segundos

def fetch_df(ex: ccxt.Exchange, symbol: str, tf: str, limit: int = 300) -> pd.DataFrame:
    key = f"{symbol}|{tf}"
    now = time.time()
    if key in _cache:
        ts, df = _cache[key]
        if now - ts < CACHE_TTL:
            return df
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df  = pd.DataFrame(raw, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    _cache[key] = (now, df)
    return df

def clear_cache():
    _cache.clear()


# ══════════════════════════════════════════════════════════
# ESTADO DEL BOT
# ══════════════════════════════════════════════════════════
@dataclass
class Trade:
    symbol:      str   = ""
    base:        str   = ""
    side:        str   = ""      # "long" | "short"
    entry_price: float = 0.0
    sl_price:    float = 0.0
    tp1_price:   float = 0.0
    tp2_price:   float = 0.0
    contracts:   float = 0.0
    risk_usdt:   float = 0.0     # cuánto USDT arriesgo (1% del balance)
    entry_score: int   = 0
    entry_time:  str   = ""
    atr_entry:   float = 0.0
    rsi_entry:   float = 0.0
    adx_entry:   float = 0.0
    sl_at_be:    bool  = False   # SL movido a break-even
    tp1_hit:     bool  = False
    trail_high:  float = 0.0
    trail_low:   float = 0.0
    bar_count:   int   = 0


@dataclass
class Stats:
    wins:          int   = 0
    losses:        int   = 0
    gross_profit:  float = 0.0
    gross_loss:    float = 0.0
    total_pnl:     float = 0.0
    daily_pnl:     float = 0.0
    daily_reset:   float = 0.0
    peak_balance:  float = 0.0
    consec_losses: int   = 0
    last_hb:       float = 0.0

    def win_rate(self) -> float:
        t = self.wins + self.losses
        return (self.wins / t * 100) if t else 0.0

    def profit_factor(self) -> float:
        return (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else 0.0

    def max_dd_pct(self, balance: float) -> float:
        if self.peak_balance <= 0: return 0.0
        return (self.peak_balance - balance) / self.peak_balance * 100

    def daily_limit_hit(self, balance: float) -> bool:
        if self.peak_balance <= 0: return False
        dd = abs(self.daily_pnl) / self.peak_balance * 100
        return self.daily_pnl < 0 and dd >= DAILY_DD_PCT

    def reset_daily(self):
        if time.time() - self.daily_reset > 86400:
            self.daily_pnl   = 0.0
            self.daily_reset = time.time()

    def save(self):
        try:
            with open(STAT_PATH, "w") as f:
                json.dump({
                    "wins": self.wins, "losses": self.losses,
                    "gross_profit": self.gross_profit,
                    "gross_loss": self.gross_loss,
                    "total_pnl": self.total_pnl,
                    "peak_balance": self.peak_balance,
                }, f)
        except Exception:
            pass

    def load(self):
        try:
            if os.path.exists(STAT_PATH):
                with open(STAT_PATH) as f:
                    d = json.load(f)
                self.wins         = d.get("wins", 0)
                self.losses       = d.get("losses", 0)
                self.gross_profit = d.get("gross_profit", 0.0)
                self.gross_loss   = d.get("gross_loss", 0.0)
                self.total_pnl    = d.get("total_pnl", 0.0)
                self.peak_balance = d.get("peak_balance", 0.0)
        except Exception:
            pass


class BotState:
    def __init__(self):
        self.trades:    Dict[str, Trade] = {}
        self.cooldowns: Dict[str, float] = {}
        self.stats = Stats()
        self.btc_bull: bool  = True
        self.btc_bear: bool  = False
        self.btc_rsi:  float = 50.0
        self.stats.load()

    def open_count(self) -> int:
        return len(self.trades)

    def bases_open(self) -> Dict[str, str]:
        return {t.base: t.side for t in self.trades.values()}

    def in_cooldown(self, symbol: str) -> bool:
        return time.time() - self.cooldowns.get(symbol, 0) < COOLDOWN_MIN * 60

    def set_cooldown(self, symbol: str):
        self.cooldowns[symbol] = time.time()

    def size_bar(self, score: int, mx: int = 5) -> str:
        return "█" * score + "░" * (mx - score)


state = BotState()


# ══════════════════════════════════════════════════════════
# CSV LOG
# ══════════════════════════════════════════════════════════
def log_csv(action: str, t: Trade, price: float, pnl: float = 0.0):
    try:
        exists = os.path.exists(CSV_PATH)
        with open(CSV_PATH, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["ts", "action", "symbol", "side", "score",
                            "entry", "exit", "sl", "tp1", "tp2",
                            "contracts", "risk_usdt", "pnl", "bars",
                            "rsi_entry", "adx_entry"])
            w.writerow([
                utcnow(), action, t.symbol, t.side, t.entry_score,
                t.entry_price, price, t.sl_price, t.tp1_price, t.tp2_price,
                t.contracts, t.risk_usdt, round(pnl, 4), t.bar_count,
                round(t.rsi_entry, 1), round(t.adx_entry, 1)
            ])
    except Exception as e:
        log.warning(f"CSV: {e}")


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def score_bar(score: int, mx: int = 5) -> str:
    return "█" * score + "░" * (mx - score)


# ══════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════
def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.warning(f"TG: {e}")


def tg_startup(balance: float, n_symbols: int):
    mode = "🔵 DRY-RUN (sin órdenes reales)" if DRY_RUN else "🟢 LIVE"
    tg(
        f"<b>🚀 SATY ELITE v19 — CLEAN TREND FOLLOWER</b>\n"
        f"══════════════════════════════\n"
        f"⚙️ Modo: {mode}\n"
        f"⏱ {TF} · {HTF1} · {HTF2} | Leverage: {LEVERAGE}×\n"
        f"🌍 Universo: {n_symbols} pares | Vol≥${MIN_VOLUME/1e6:.0f}M\n"
        f"🎯 Score min: {MIN_SCORE}/5 | Max trades: {MAX_TRADES}\n"
        f"💰 Balance: ${balance:.2f} | Riesgo: {RISK_PCT}% por trade\n"
        f"🛡 Circuit breaker: -{DAILY_DD_PCT}% diario\n"
        f"📏 SL: {SL_ATR_MULT}× ATR | TP1: {TP1_ATR_MULT}× | TP2: {TP2_ATR_MULT}×\n"
        f"⏳ Cooldown: {COOLDOWN_MIN}min | Spread máx: {MAX_SPREAD_PCT}%\n"
        f"══════════════════════════════\n"
        f"📊 5 SEÑALES INDEPENDIENTES:\n"
        f"  1. Supertrend({ST_PERIOD},{ST_MULT}) — tendencia\n"
        f"  2. EMA {EMA_FAST}/{EMA_SLOW} — estructura\n"
        f"  3. RSI({RSI_LEN}) zona sana — momentum\n"
        f"  4. ADX({ADX_LEN}) > {ADX_MIN} — fuerza\n"
        f"  5. Volumen > media {VOL_PERIOD} — confirmación\n"
        f"══════════════════════════════\n"
        f"⏰ {utcnow()}"
    )


def tg_signal(t: Trade, score: int, signals: dict):
    e = "🟢" if t.side == "long" else "🔴"
    sl_dist = abs(t.entry_price - t.sl_price)
    rr = abs(t.tp2_price - t.entry_price) / max(sl_dist, 1e-9)
    tg(
        f"{e} <b>{'LONG' if t.side=='long' else 'SHORT'}</b> — {t.symbol}\n"
        f"══════════════════════════════\n"
        f"🎯 Score: {score}/5  {score_bar(score)}\n"
        f"💵 Entrada: <code>{t.entry_price:.6g}</code>\n"
        f"🟡 TP1:    <code>{t.tp1_price:.6g}</code>\n"
        f"🟢 TP2:    <code>{t.tp2_price:.6g}</code>  R:R 1:{rr:.1f}\n"
        f"🛑 SL:     <code>{t.sl_price:.6g}</code>\n"
        f"══════════════════════════════\n"
        f"📊 Señales activas:\n"
        f"  {'✅' if signals.get('st') else '❌'} Supertrend\n"
        f"  {'✅' if signals.get('ema') else '❌'} EMA estructura\n"
        f"  {'✅' if signals.get('rsi') else '❌'} RSI zona sana ({t.rsi_entry:.1f})\n"
        f"  {'✅' if signals.get('adx') else '❌'} ADX fuerza ({t.adx_entry:.1f})\n"
        f"  {'✅' if signals.get('vol') else '❌'} Volumen\n"
        f"══════════════════════════════\n"
        f"⚖️ Riesgo: ${t.risk_usdt:.2f} ({RISK_PCT}% balance)\n"
        f"📦 Contratos: {t.contracts:.4f} | ATR: {t.atr_entry:.5f}\n"
        f"₿ BTC: {'🟢BULL' if state.btc_bull else '🔴BEAR' if state.btc_bear else '⚪NEUTRAL'} "
        f"RSI:{state.btc_rsi:.0f}\n"
        f"📊 {state.open_count()}/{MAX_TRADES} trades abiertos\n"
        f"{'🔵 DRY-RUN' if DRY_RUN else ''}\n"
        f"⏰ {utcnow()}"
    )


def tg_tp1(t: Trade, price: float):
    tg(
        f"🟡 <b>TP1 + BREAK-EVEN</b> — {t.symbol}\n"
        f"💵 Precio: <code>{price:.6g}</code>\n"
        f"🛑 SL movido a entrada: <code>{t.entry_price:.6g}</code>\n"
        f"🎯 Siguiente objetivo: TP2 <code>{t.tp2_price:.6g}</code>\n"
        f"⏰ {utcnow()}"
    )


def tg_close(t: Trade, price: float, pnl: float, reason: str):
    e = "✅" if pnl > 0 else "❌"
    pct = (pnl / t.risk_usdt * 100) if t.risk_usdt > 0 else 0
    tg(
        f"{e} <b>CERRADO</b> — {t.symbol}\n"
        f"📋 {t.side.upper()} · {t.entry_score}/5 · {reason}\n"
        f"💵 <code>{t.entry_price:.6g}</code> → <code>{price:.6g}</code>\n"
        f"{'💰' if pnl > 0 else '💸'} PnL: ${pnl:+.3f} ({pct:+.1f}% del riesgo)\n"
        f"📊 Barras: {t.bar_count}\n"
        f"══════════════════════════════\n"
        f"📈 Total: {state.stats.wins}W/{state.stats.losses}L "
        f"WR:{state.stats.win_rate():.1f}% "
        f"PF:{state.stats.profit_factor():.2f}\n"
        f"💹 Hoy: ${state.stats.daily_pnl:+.2f} | "
        f"Total: ${state.stats.total_pnl:+.2f}\n"
        f"⏰ {utcnow()}"
    )


def tg_circuit_breaker(reason: str):
    tg(
        f"⛔ <b>CIRCUIT BREAKER</b> — {reason}\n"
        f"PnL hoy: ${state.stats.daily_pnl:+.2f}\n"
        f"El bot pausa hasta el siguiente día UTC.\n"
        f"⏰ {utcnow()}"
    )


def tg_heartbeat(balance: float):
    open_lines = "\n".join(
        f"  {'🟢' if t.side=='long' else '🔴'} {sym} "
        f"E:{t.entry_price:.5g} "
        f"{'🛡BE' if t.sl_at_be else ''} "
        f"{'TP1✓' if t.tp1_hit else ''}"
        for sym, t in state.trades.items()
    ) or "  (ninguna)"
    tg(
        f"💓 <b>HEARTBEAT</b> — {utcnow()}\n"
        f"💰 Balance: ${balance:.2f}\n"
        f"📊 {state.open_count()}/{MAX_TRADES} trades\n"
        f"{open_lines}\n"
        f"══════════════════════════════\n"
        f"📈 {state.stats.wins}W/{state.stats.losses}L | "
        f"WR:{state.stats.win_rate():.1f}% | "
        f"PF:{state.stats.profit_factor():.2f}\n"
        f"💹 Hoy: ${state.stats.daily_pnl:+.2f} | "
        f"Total: ${state.stats.total_pnl:+.2f}\n"
        f"₿ BTC: {'🟢' if state.btc_bull else '🔴' if state.btc_bear else '⚪'} "
        f"RSI:{state.btc_rsi:.0f}\n"
        f"{'🔵 DRY-RUN' if DRY_RUN else ''}"
    )


def tg_error(msg: str):
    tg(f"🔥 <b>ERROR:</b> <code>{msg[:300]}</code>\n⏰ {utcnow()}")


# ══════════════════════════════════════════════════════════
# INDICADORES — Solo los necesarios, implementación limpia
# ══════════════════════════════════════════════════════════

def calc_atr(df: pd.DataFrame, n: int = ATR_LEN) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()],
        axis=1
    ).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def calc_rsi(s: pd.Series, n: int = RSI_LEN) -> pd.Series:
    d  = s.diff()
    g  = d.clip(lower=0).ewm(span=n, adjust=False).mean()
    lo = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
    return 100 - (100 / (1 + g / lo.replace(0, np.nan)))


def calc_adx(df: pd.DataFrame, n: int = ADX_LEN) -> Tuple[pd.Series, pd.Series, pd.Series]:
    h, l   = df["high"], df["low"]
    up, dn = h.diff(), -l.diff()
    pdm    = up.where((up > dn) & (up > 0), 0.0)
    mdm    = dn.where((dn > up) & (dn > 0), 0.0)
    atr_s  = calc_atr(df, n)
    dip    = 100 * pdm.ewm(span=n, adjust=False).mean() / atr_s
    dim    = 100 * mdm.ewm(span=n, adjust=False).mean() / atr_s
    dx     = 100 * (dip - dim).abs() / (dip + dim).replace(0, np.nan)
    adx    = dx.ewm(span=n, adjust=False).mean()
    return dip, dim, adx


def calc_supertrend(df: pd.DataFrame,
                    period: int = ST_PERIOD,
                    multiplier: float = ST_MULT) -> Tuple[pd.Series, pd.Series]:
    """
    Supertrend clásico.
    Retorna (supertrend_line, direction): direction=+1 alcista, -1 bajista
    """
    h, l, c = df["high"], df["low"], df["close"]
    hl2  = (h + l) / 2.0
    atr  = calc_atr(df, period)

    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    upper = basic_upper.values.copy()
    lower = basic_lower.values.copy()
    c_arr = c.values.copy()

    for i in range(1, len(df)):
        upper[i] = (
            basic_upper.iloc[i]
            if basic_upper.iloc[i] < upper[i-1] or c_arr[i-1] > upper[i-1]
            else upper[i-1]
        )
        lower[i] = (
            basic_lower.iloc[i]
            if basic_lower.iloc[i] > lower[i-1] or c_arr[i-1] < lower[i-1]
            else lower[i-1]
        )

    direction = np.ones(len(df))
    supertrend = lower.copy()
    direction[0] = 1.0

    for i in range(1, len(df)):
        if direction[i-1] == -1:
            direction[i] = 1.0 if c_arr[i] > upper[i-1] else -1.0
        else:
            direction[i] = -1.0 if c_arr[i] < lower[i-1] else 1.0
        supertrend[i] = lower[i] if direction[i] == 1 else upper[i]

    idx = df.index
    return pd.Series(supertrend, index=idx), pd.Series(direction, index=idx)


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula todos los indicadores necesarios.
    Solo 5 familias de señales, sin redundancias.
    """
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    # EMAs
    df["ema_fast"]  = c.ewm(span=EMA_FAST,  adjust=False).mean()
    df["ema_slow"]  = c.ewm(span=EMA_SLOW,  adjust=False).mean()
    df["ema_trend"] = c.ewm(span=EMA_TREND, adjust=False).mean()

    # ATR
    df["atr"] = calc_atr(df)

    # RSI
    df["rsi"] = calc_rsi(c)

    # ADX
    dip, dim, adx = calc_adx(df)
    df["dip"] = dip
    df["dim"] = dim
    df["adx"] = adx

    # Supertrend
    st_line, st_dir = calc_supertrend(df)
    df["st_line"] = st_line
    df["st_dir"]  = st_dir  # +1 = bull, -1 = bear

    # Volumen
    df["vol_ma"]    = v.rolling(VOL_PERIOD).mean()
    df["vol_ratio"] = v / df["vol_ma"].replace(0, np.nan)

    # HTF bias (simplificado, para uso en la función principal)
    df["htf_bull"] = (c > df["ema_slow"]) & (df["ema_fast"] > df["ema_slow"])
    df["htf_bear"] = (c < df["ema_slow"]) & (df["ema_fast"] < df["ema_slow"])

    return df


def htf_bias(df: pd.DataFrame) -> Tuple[bool, bool]:
    """Determina la tendencia del timeframe superior."""
    df  = compute(df)
    row = df.iloc[-2]  # Vela cerrada más reciente
    bull = bool(row["close"] > row["ema_slow"] and row["ema_fast"] > row["ema_slow"])
    bear = bool(row["close"] < row["ema_slow"] and row["ema_fast"] < row["ema_slow"])
    return bull, bear


# ══════════════════════════════════════════════════════════
# SCORE — 5 señales independientes
# ══════════════════════════════════════════════════════════
def score_signals(row: pd.Series,
                  htf1_bull: bool, htf1_bear: bool,
                  htf2_bull: bool, htf2_bear: bool
                  ) -> Tuple[int, int, dict, dict]:
    """
    Calcula score LONG y SHORT (0-5).
    Cada señal mide algo fundamentalmente distinto:
    1. Supertrend  — ¿tendencia real?
    2. EMA struct  — ¿estructura alineada con HTF?
    3. RSI zona    — ¿momentum sano, no extremo?
    4. ADX fuerza  — ¿la tendencia tiene potencia?
    5. Volumen     — ¿hay dinero detrás del movimiento?

    Retorna (long_score, short_score, long_signals_dict, short_signals_dict)
    """
    rsi = float(row["rsi"])
    adx = float(row["adx"])
    dip = float(row["dip"])
    dim = float(row["dim"])

    # ── LONG ──────────────────────────────────────────────
    # 1. Supertrend alcista
    l_st  = bool(row["st_dir"] == 1.0)
    # 2. EMA estructura + HTF alineado
    l_ema = bool(row["ema_fast"] > row["ema_slow"] and (htf1_bull or htf2_bull))
    # 3. RSI en zona sana para long (no sobrecomprado, tiene momentum)
    l_rsi = bool(RSI_LONG_MIN <= rsi <= RSI_LONG_MAX)
    # 4. ADX con DI+ liderando
    l_adx = bool(adx >= ADX_MIN and dip > dim + ADX_DI_MIN)
    # 5. Volumen por encima de la media
    l_vol = bool(float(row["vol_ratio"]) >= 1.1)

    # ── SHORT ─────────────────────────────────────────────
    # 1. Supertrend bajista
    s_st  = bool(row["st_dir"] == -1.0)
    # 2. EMA estructura + HTF alineado
    s_ema = bool(row["ema_fast"] < row["ema_slow"] and (htf1_bear or htf2_bear))
    # 3. RSI en zona sana para short
    s_rsi = bool(RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX)
    # 4. ADX con DI- liderando
    s_adx = bool(adx >= ADX_MIN and dim > dip + ADX_DI_MIN)
    # 5. Volumen
    s_vol = bool(float(row["vol_ratio"]) >= 1.1)

    long_signals  = {"st": l_st, "ema": l_ema, "rsi": l_rsi, "adx": l_adx, "vol": l_vol}
    short_signals = {"st": s_st, "ema": s_ema, "rsi": s_rsi, "adx": s_adx, "vol": s_vol}

    long_score  = sum(long_signals.values())
    short_score = sum(short_signals.values())

    return long_score, short_score, long_signals, short_signals


# ══════════════════════════════════════════════════════════
# EXCHANGE HELPERS
# ══════════════════════════════════════════════════════════
def build_exchange() -> ccxt.Exchange:
    ex = ccxt.bingx({
        "apiKey":    API_KEY,
        "secret":    API_SECRET,
        "options":   {"defaultType": "swap"},
        "enableRateLimit": True,
    })
    ex.load_markets()
    return ex


def get_balance(ex: ccxt.Exchange) -> float:
    return float(ex.fetch_balance()["USDT"]["free"])


def get_last_price(ex: ccxt.Exchange, symbol: str) -> float:
    return float(ex.fetch_ticker(symbol)["last"])


def get_spread_pct(ex: ccxt.Exchange, symbol: str) -> float:
    try:
        ob  = ex.fetch_order_book(symbol, limit=1)
        bid = ob["bids"][0][0] if ob["bids"] else 0
        ask = ob["asks"][0][0] if ob["asks"] else 0
        mid = (bid + ask) / 2
        return ((ask - bid) / mid * 100) if mid > 0 else 999.0
    except Exception:
        return 0.0


def get_position(ex: ccxt.Exchange, symbol: str) -> Optional[dict]:
    try:
        for p in ex.fetch_positions([symbol]):
            if abs(float(p.get("contracts", 0) or 0)) > 0:
                return p
    except Exception:
        pass
    return None


def get_all_positions(ex: ccxt.Exchange) -> Dict[str, dict]:
    result: Dict[str, dict] = {}
    try:
        for p in ex.fetch_positions():
            if abs(float(p.get("contracts", 0) or 0)) > 0:
                result[p["symbol"]] = p
    except Exception as e:
        log.warning(f"fetch_positions: {e}")
    return result


def get_min_amount(ex: ccxt.Exchange, symbol: str) -> float:
    try:
        mkt = ex.markets.get(symbol, {})
        return float(mkt.get("limits", {}).get("amount", {}).get("min", 0) or 0)
    except Exception:
        return 0.0


def get_symbols(ex: ccxt.Exchange) -> List[str]:
    candidates = []
    for sym, mkt in ex.markets.items():
        if not (mkt.get("swap") and mkt.get("quote") == "USDT"
                and mkt.get("active", True)):
            continue
        if sym in BLACKLIST:
            continue
        candidates.append(sym)

    try:
        tickers = ex.fetch_tickers(candidates)
    except Exception as e:
        log.warning(f"fetch_tickers: {e}")
        return candidates[:TOP_N]

    ranked = []
    for sym in candidates:
        tk  = tickers.get(sym, {})
        vol = float(tk.get("quoteVolume", 0) or 0)
        if vol >= MIN_VOLUME:
            ranked.append((sym, vol))

    ranked.sort(key=lambda x: -x[1])
    result = [s for s, _ in ranked[:TOP_N]]
    log.info(f"Universo: {len(result)} pares (vol≥${MIN_VOLUME/1e6:.0f}M)")
    return result


# ══════════════════════════════════════════════════════════
# CÁLCULO DE TAMAÑO DE POSICIÓN — Kelly conservador (1% riesgo)
# ══════════════════════════════════════════════════════════
def calc_position_size(balance: float, price: float,
                       atr: float, symbol: str,
                       ex: ccxt.Exchange) -> Tuple[float, float]:
    """
    Tamaño basado en riesgo fijo del 1% del balance.
    SL = SL_ATR_MULT × ATR
    risk_usdt = balance × RISK_PCT / 100
    contracts = risk_usdt / (SL_ATR_MULT × ATR)
    Verificar que el notional no exceda el margen disponible.
    """
    risk_usdt = balance * RISK_PCT / 100.0
    sl_dist   = SL_ATR_MULT * atr
    if sl_dist <= 0 or price <= 0:
        return 0.0, 0.0

    contracts = risk_usdt / sl_dist

    # Verificar límite de margen: contratos × precio / leverage ≤ balance × 0.3
    notional = contracts * price
    margin   = notional / LEVERAGE
    max_margin = balance * 0.30  # Nunca más del 30% del balance en margen por trade

    if margin > max_margin:
        contracts = (max_margin * LEVERAGE) / price
        risk_usdt = contracts * sl_dist

    # Aplicar mínimo del exchange
    min_amt = get_min_amount(ex, symbol)
    if min_amt > 0 and contracts < min_amt:
        contracts = min_amt

    contracts = float(ex.amount_to_precision(symbol, contracts))
    return contracts, risk_usdt


# ══════════════════════════════════════════════════════════
# ABRIR POSICIÓN
# ══════════════════════════════════════════════════════════
def open_trade(ex: ccxt.Exchange,
               symbol: str,
               side: str,       # "long" | "short"
               score: int,
               row: pd.Series,
               signals: dict,
               balance: float) -> Optional[Trade]:
    try:
        # ── Validaciones previas ──
        spread = get_spread_pct(ex, symbol)
        if spread > MAX_SPREAD_PCT:
            log.info(f"[{symbol}] spread {spread:.3f}% > {MAX_SPREAD_PCT}% — skip")
            return None

        price = get_last_price(ex, symbol)
        atr   = float(row["atr"])
        rsi   = float(row["rsi"])
        adx   = float(row["adx"])

        if atr <= 0 or price <= 0:
            return None

        # Calcular tamaño
        contracts, risk_usdt = calc_position_size(balance, price, atr, symbol, ex)
        if contracts <= 0:
            log.warning(f"[{symbol}] size = 0, skip")
            return None

        # Calcular SL, TP1, TP2
        if side == "long":
            sl_price  = price - SL_ATR_MULT  * atr
            tp1_price = price + TP1_ATR_MULT * atr
            tp2_price = price + TP2_ATR_MULT * atr
        else:
            sl_price  = price + SL_ATR_MULT  * atr
            tp1_price = price - TP1_ATR_MULT * atr
            tp2_price = price - TP2_ATR_MULT * atr

        sl_price  = float(ex.price_to_precision(symbol, sl_price))
        tp1_price = float(ex.price_to_precision(symbol, tp1_price))
        tp2_price = float(ex.price_to_precision(symbol, tp2_price))

        base      = symbol.split("/")[0]
        order_side = "buy" if side == "long" else "sell"
        close_side = "sell" if side == "long" else "buy"

        log.info(
            f"[OPEN] {symbol} {side.upper()} score={score}/5 "
            f"contracts={contracts} ${risk_usdt:.2f} riesgo "
            f"SL={sl_price:.6g} TP2={tp2_price:.6g} "
            f"{'DRY-RUN' if DRY_RUN else 'LIVE'}"
        )

        if not DRY_RUN:
            # Establecer leverage
            try:
                ex.set_leverage(LEVERAGE, symbol)
            except Exception as lv_err:
                log.warning(f"[{symbol}] set_leverage: {lv_err}")

            # Orden de entrada
            order = ex.create_order(symbol, "market", order_side, contracts)
            entry_price = float(order.get("average") or price)

            # Recalcular niveles con el precio real de entrada
            if side == "long":
                sl_price  = float(ex.price_to_precision(symbol, entry_price - SL_ATR_MULT  * atr))
                tp1_price = float(ex.price_to_precision(symbol, entry_price + TP1_ATR_MULT * atr))
                tp2_price = float(ex.price_to_precision(symbol, entry_price + TP2_ATR_MULT * atr))
            else:
                sl_price  = float(ex.price_to_precision(symbol, entry_price + SL_ATR_MULT  * atr))
                tp1_price = float(ex.price_to_precision(symbol, entry_price - TP1_ATR_MULT * atr))
                tp2_price = float(ex.price_to_precision(symbol, entry_price - TP2_ATR_MULT * atr))

            # TP2 con límite (mitad de contratos)
            half = float(ex.amount_to_precision(symbol, contracts * 0.5))
            try:
                ex.create_order(symbol, "limit", close_side, half, tp2_price,
                                params={"reduceOnly": True})
            except Exception as e:
                log.warning(f"[{symbol}] TP2 limit: {e}")

            # SL stop-market
            try:
                ex.create_order(symbol, "stop_market", close_side, contracts, None,
                                params={"stopPrice": sl_price, "reduceOnly": True})
            except Exception as e:
                log.warning(f"[{symbol}] SL stop: {e}")

        else:
            entry_price = price  # DRY-RUN: usar precio actual

        t = Trade(
            symbol=symbol,
            base=base,
            side=side,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            contracts=contracts,
            risk_usdt=risk_usdt,
            entry_score=score,
            entry_time=utcnow(),
            atr_entry=atr,
            rsi_entry=rsi,
            adx_entry=adx,
        )
        if side == "long":
            t.trail_high = entry_price
        else:
            t.trail_low = entry_price

        log_csv("OPEN", t, entry_price)
        tg_signal(t, score, signals)
        return t

    except Exception as e:
        log.error(f"[{symbol}] open_trade: {e}")
        tg_error(f"open {symbol}: {str(e)[:150]}")
        return None


# ══════════════════════════════════════════════════════════
# CERRAR POSICIÓN
# ══════════════════════════════════════════════════════════
def close_trade(ex: ccxt.Exchange,
                symbol: str,
                reason: str,
                price: float):
    if symbol not in state.trades:
        return
    t = state.trades[symbol]

    if not DRY_RUN:
        try:
            ex.cancel_all_orders(symbol)
        except Exception as e:
            log.warning(f"[{symbol}] cancel: {e}")

        pos = get_position(ex, symbol)
        if pos:
            qty        = abs(float(pos.get("contracts", 0)))
            close_side = "sell" if t.side == "long" else "buy"
            try:
                ex.create_order(symbol, "market", close_side, qty,
                                params={"reduceOnly": True})
            except Exception as e:
                log.error(f"[{symbol}] close market: {e}")
                tg_error(f"close {symbol}: {e}")
                return

    # Calcular PnL
    if t.side == "long":
        pnl = (price - t.entry_price) * t.contracts
    else:
        pnl = (t.entry_price - price) * t.contracts

    # Actualizar stats
    if pnl > 0:
        state.stats.wins         += 1
        state.stats.gross_profit += pnl
        state.stats.consec_losses = 0
    else:
        state.stats.losses         += 1
        state.stats.gross_loss     += abs(pnl)
        state.stats.consec_losses  += 1

    state.stats.total_pnl += pnl
    state.stats.daily_pnl += pnl
    state.stats.save()
    state.set_cooldown(symbol)

    log_csv("CLOSE", t, price, pnl)
    tg_close(t, price, pnl, reason)
    del state.trades[symbol]

    log.info(
        f"[CLOSE] {symbol} {reason} pnl=${pnl:+.3f} "
        f"{'DRY-RUN' if DRY_RUN else 'LIVE'}"
    )


# ══════════════════════════════════════════════════════════
# MOVER SL A BREAK-EVEN
# ══════════════════════════════════════════════════════════
def move_be(ex: ccxt.Exchange, symbol: str):
    if symbol not in state.trades:
        return
    t = state.trades[symbol]
    if t.sl_at_be:
        return

    if not DRY_RUN:
        try:
            ex.cancel_all_orders(symbol)
        except Exception as e:
            log.warning(f"[{symbol}] cancel for BE: {e}")

        be        = float(ex.price_to_precision(symbol, t.entry_price))
        close_side = "sell" if t.side == "long" else "buy"
        try:
            ex.create_order(symbol, "stop_market", close_side, t.contracts, None,
                            params={"stopPrice": be, "reduceOnly": True})
        except Exception as e:
            log.warning(f"[{symbol}] BE order: {e}")
            return

    t.sl_price  = t.entry_price
    t.sl_at_be  = True
    tg_tp1(t, t.tp1_price)
    log.info(f"[{symbol}] SL → BE @ {t.entry_price:.6g}")


# ══════════════════════════════════════════════════════════
# GESTIONAR TRADE ABIERTO
# ══════════════════════════════════════════════════════════
def manage_trade(ex: ccxt.Exchange,
                 symbol: str,
                 live_price: float,
                 atr: float,
                 live_pos: Optional[dict]):
    if symbol not in state.trades:
        return
    t = state.trades[symbol]
    t.bar_count += 1

    # ── Posición cerrada externamente (SL o TP ejecutado por el exchange) ──
    if not DRY_RUN and live_pos is None:
        # La posición ya no existe → fue cerrada por SL o TP
        if t.side == "long":
            pnl = (live_price - t.entry_price) * t.contracts
        else:
            pnl = (t.entry_price - live_price) * t.contracts

        reason = "TP2 ✅" if pnl > 0 else "SL 🛑"
        if pnl > 0:
            state.stats.wins         += 1
            state.stats.gross_profit += pnl
            state.stats.consec_losses = 0
        else:
            state.stats.losses        += 1
            state.stats.gross_loss    += abs(pnl)
            state.stats.consec_losses += 1

        state.stats.total_pnl += pnl
        state.stats.daily_pnl += pnl
        state.stats.save()
        state.set_cooldown(symbol)
        log_csv("CLOSE_EXT", t, live_price, pnl)
        tg_close(t, live_price, pnl, reason)
        del state.trades[symbol]
        return

    # ── Verificar SL manual (para DRY-RUN y como fallback) ──
    sl_hit = (
        (t.side == "long"  and live_price <= t.sl_price) or
        (t.side == "short" and live_price >= t.sl_price)
    )
    if sl_hit:
        close_trade(ex, symbol, "SL 🛑", live_price)
        return

    # ── TP1: mover SL a BE ──
    if not t.tp1_hit:
        tp1_hit = (
            (t.side == "long"  and live_price >= t.tp1_price) or
            (t.side == "short" and live_price <= t.tp1_price)
        )
        if tp1_hit:
            t.tp1_hit = True
            move_be(ex, symbol)

    # ── TP2: cerrar si alcanzado (DRY-RUN / fallback) ──
    if t.tp1_hit:
        tp2_hit = (
            (t.side == "long"  and live_price >= t.tp2_price) or
            (t.side == "short" and live_price <= t.tp2_price)
        )
        if tp2_hit:
            close_trade(ex, symbol, "TP2 ✅", live_price)
            return

    # ── Trailing stop tras TP1 ──
    if t.tp1_hit and symbol in state.trades:
        atr_t = atr if atr > 0 else t.atr_entry
        if t.side == "long":
            t.trail_high = max(t.trail_high, live_price)
            trail_sl = t.trail_high - TRAIL_ATR_MULT * atr_t
            if live_price <= trail_sl and trail_sl > t.sl_price:
                close_trade(ex, symbol, "TRAILING STOP 📉", live_price)
                return
        else:
            if t.trail_low == 0.0:
                t.trail_low = live_price
            t.trail_low = min(t.trail_low, live_price)
            trail_sl = t.trail_low + TRAIL_ATR_MULT * atr_t
            if live_price >= trail_sl and trail_sl < t.sl_price:
                close_trade(ex, symbol, "TRAILING STOP 📈", live_price)
                return


# ══════════════════════════════════════════════════════════
# BTC BIAS
# ══════════════════════════════════════════════════════════
def update_btc_bias(ex: ccxt.Exchange):
    try:
        df  = fetch_df(ex, "BTC/USDT:USDT", "1h", limit=250)
        df  = compute(df)
        row = df.iloc[-2]
        state.btc_bull = bool(row["ema_fast"] > row["ema_slow"]
                              and row["close"] > row["ema_slow"])
        state.btc_bear = bool(row["ema_fast"] < row["ema_slow"]
                              and row["close"] < row["ema_slow"])
        state.btc_rsi  = float(row["rsi"])
        log.info(
            f"BTC bias: {'BULL' if state.btc_bull else 'BEAR' if state.btc_bear else 'NEUTRAL'} "
            f"RSI:{state.btc_rsi:.1f} "
            f"ST:{'▲' if row['st_dir']==1 else '▼'}"
        )
    except Exception as e:
        log.warning(f"BTC bias: {e}")


# ══════════════════════════════════════════════════════════
# SCAN DE UN SÍMBOLO
# ══════════════════════════════════════════════════════════
def scan_symbol(ex: ccxt.Exchange, symbol: str) -> Optional[dict]:
    try:
        df   = fetch_df(ex, symbol, TF,   300)
        df1  = fetch_df(ex, symbol, HTF1, 200)
        df2  = fetch_df(ex, symbol, HTF2, 150)

        df = compute(df)
        row = df.iloc[-2]  # Vela cerrada (no la vela en curso)

        # Validar que los indicadores están disponibles
        for col in ["adx", "rsi", "atr", "st_dir", "vol_ratio"]:
            val = row.get(col)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return None

        htf1_bull, htf1_bear = htf_bias(df1)
        htf2_bull, htf2_bear = htf_bias(df2)

        long_score, short_score, long_sigs, short_sigs = score_signals(
            row, htf1_bull, htf1_bear, htf2_bull, htf2_bear
        )

        return {
            "symbol":      symbol,
            "base":        symbol.split("/")[0],
            "long_score":  long_score,
            "short_score": short_score,
            "long_sigs":   long_sigs,
            "short_sigs":  short_sigs,
            "row":         row,
            "atr":         float(row["atr"]),
            "live_price":  float(row["close"]),
            "rsi":         float(row["rsi"]),
            "adx":         float(row["adx"]),
        }
    except Exception as e:
        log.debug(f"[{symbol}] scan: {e}")
        return None


# ══════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════
def main():
    log.info("=" * 65)
    log.info("  SATY ELITE v19 — CLEAN TREND FOLLOWER")
    log.info(f"  Modo: {'DRY-RUN (sin órdenes reales)' if DRY_RUN else 'LIVE'}")
    log.info(f"  Leverage: {LEVERAGE}× | Riesgo: {RISK_PCT}% por trade")
    log.info(f"  Score mínimo: {MIN_SCORE}/5 | Max trades: {MAX_TRADES}")
    log.info("=" * 65)

    if DRY_RUN:
        log.info("🔵 DRY-RUN activo — no se ejecutarán órdenes reales")

    if not (API_KEY and API_SECRET):
        if not DRY_RUN:
            log.warning("Sin claves API y DRY_RUN=false — revisa las variables de entorno")
        log.info("Ejecutando en modo DRY-RUN sin claves API...")

    # Conectar al exchange
    ex = None
    for attempt in range(10):
        try:
            ex = build_exchange()
            log.info("Exchange conectado ✓")
            break
        except Exception as e:
            wait = min(2 ** attempt, 120)
            log.warning(f"Conexión {attempt+1}/10: {e} — retry {wait}s")
            time.sleep(wait)

    if ex is None:
        raise RuntimeError("No se pudo conectar al exchange tras 10 intentos")

    # Balance inicial
    balance = 0.0
    for i in range(5):
        try:
            balance = get_balance(ex)
            break
        except Exception as e:
            log.warning(f"get_balance {i+1}/5: {e}")
            time.sleep(5)

    state.stats.peak_balance = max(state.stats.peak_balance, balance)
    state.stats.daily_reset  = time.time()
    log.info(f"Balance: ${balance:.2f} USDT")

    # Cargar universo de pares
    symbols: List[str] = []
    while not symbols:
        try:
            ex.load_markets()
            symbols = get_symbols(ex)
        except Exception as e:
            log.error(f"get_symbols: {e} — reintento 60s")
            time.sleep(60)

    # Actualizar bias BTC
    update_btc_bias(ex)

    # Mensaje de inicio
    tg_startup(balance, len(symbols))

    scan_count    = 0
    HB_INTERVAL   = 3600       # Heartbeat cada 1h
    REFRESH_EVERY = max(1, 3600 // max(POLL_SECS, 1))  # Refrescar universo cada 1h
    BTC_REFRESH   = max(1, 900  // max(POLL_SECS, 1))   # BTC bias cada 15min

    while True:
        ts_start = time.time()
        try:
            scan_count += 1
            state.stats.reset_daily()
            clear_cache()

            # Actualizar balance periódicamente
            if scan_count % 5 == 0:
                try:
                    balance = get_balance(ex)
                    state.stats.peak_balance = max(state.stats.peak_balance, balance)
                except Exception:
                    pass

            log.info(
                f"━━━ SCAN #{scan_count} {datetime.now(timezone.utc):%H:%M:%S} "
                f"| {state.open_count()}/{MAX_TRADES} trades "
                f"| balance: ${balance:.2f} ━━━"
            )

            # Refrescar universo y BTC bias
            if scan_count % REFRESH_EVERY == 0:
                try:
                    ex.load_markets()
                    symbols = get_symbols(ex)
                except Exception as e:
                    log.warning(f"Refresh: {e}")

            if scan_count % BTC_REFRESH == 0:
                update_btc_bias(ex)

            # Heartbeat
            if time.time() - state.stats.last_hb > HB_INTERVAL:
                try:
                    tg_heartbeat(balance)
                    state.stats.last_hb = time.time()
                except Exception:
                    pass

            # ── CIRCUIT BREAKER ──
            if state.stats.daily_limit_hit(balance):
                log.warning(f"⛔ Circuit breaker: pérdida diaria ≥ {DAILY_DD_PCT}%")
                tg_circuit_breaker(
                    f"Pérdida diaria ${state.stats.daily_pnl:.2f} "
                    f"≥ {DAILY_DD_PCT}% del balance"
                )
                time.sleep(POLL_SECS)
                continue

            # ── Obtener posiciones reales del exchange ──
            live_positions = {} if DRY_RUN else get_all_positions(ex)

            # ── Gestionar trades abiertos ──
            for sym in list(state.trades.keys()):
                try:
                    lp    = live_positions.get(sym)
                    price = (float(lp["markPrice"]) if lp
                             else get_last_price(ex, sym))
                    res   = scan_symbol(ex, sym)
                    atr   = res["atr"] if res else state.trades[sym].atr_entry
                    manage_trade(ex, sym, price, atr, lp)
                except Exception as e:
                    log.warning(f"[{sym}] manage: {e}")

            # ── Buscar nuevas entradas ──
            if state.open_count() < MAX_TRADES:
                bases_open = state.bases_open()
                to_scan = [
                    s for s in symbols
                    if s not in state.trades
                    and not state.in_cooldown(s)
                    and s.split("/")[0] not in bases_open
                ]

                log.info(f"Escaneando {len(to_scan)} pares...")

                with ThreadPoolExecutor(max_workers=8) as pool:
                    futures = {pool.submit(scan_symbol, ex, s): s for s in to_scan}
                    results = [f.result() for f in as_completed(futures)
                               if f.result() is not None]

                # Filtrar señales válidas
                candidates = []
                for res in results:
                    base       = res["base"]
                    long_score = res["long_score"]
                    short_score = res["short_score"]

                    if base in bases_open:
                        continue

                    can_long  = long_score  >= MIN_SCORE
                    can_short = short_score >= MIN_SCORE

                    # ── Filtro BTC macro ──
                    # Si BTC está claramente bajista, no abrimos longs
                    # Si BTC está claramente alcista, no abrimos shorts
                    if state.btc_bear and state.btc_rsi < 45:
                        can_long = False
                    if state.btc_bull and state.btc_rsi > 55:
                        can_short = False

                    # ── Filtro RSI extremo de BTC ──
                    if state.btc_rsi > 72:
                        can_short = False   # No shorts en rally extremo de BTC
                    if state.btc_rsi < 28:
                        can_long  = False   # No longs en crash extremo de BTC

                    best_side  = None
                    best_score = 0

                    if can_long and long_score > best_score:
                        best_score = long_score
                        best_side  = "long"

                    if can_short and short_score > best_score:
                        best_score = short_score
                        best_side  = "short"

                    if best_side:
                        candidates.append({
                            "symbol":   res["symbol"],
                            "base":     base,
                            "side":     best_side,
                            "score":    best_score,
                            "row":      res["row"],
                            "signals":  (res["long_sigs"] if best_side == "long"
                                         else res["short_sigs"]),
                            "atr":      res["atr"],
                        })

                # Ordenar por score descendente
                candidates.sort(key=lambda x: x["score"], reverse=True)

                for sig in candidates:
                    if state.open_count() >= MAX_TRADES:
                        break
                    sym  = sig["symbol"]
                    base = sig["base"]
                    if sym  in state.trades:        continue
                    if base in state.bases_open():  continue
                    if state.in_cooldown(sym):       continue

                    t = open_trade(
                        ex       = ex,
                        symbol   = sym,
                        side     = sig["side"],
                        score    = sig["score"],
                        row      = sig["row"],
                        signals  = sig["signals"],
                        balance  = balance,
                    )
                    if t:
                        state.trades[sym] = t

            else:
                log.info(f"Máximo de trades alcanzado ({MAX_TRADES})")

            elapsed = time.time() - ts_start
            log.info(
                f"✓ {elapsed:.1f}s | {state.stats.wins}W/{state.stats.losses}L "
                f"| hoy: ${state.stats.daily_pnl:+.2f} "
                f"| total: ${state.stats.total_pnl:+.2f}"
            )

        except ccxt.NetworkError as e:
            log.warning(f"Network: {e} — 15s")
            time.sleep(15)
        except ccxt.ExchangeError as e:
            log.error(f"Exchange error: {e}")
            tg_error(str(e)[:200])
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
            tg("🛑 <b>Bot detenido.</b>")
            break
        except Exception as e:
            log.exception(f"Error inesperado: {e}")
            tg_error(str(e)[:200])

        # Esperar hasta el siguiente ciclo
        elapsed = time.time() - ts_start
        sleep_time = max(0, POLL_SECS - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


# ══════════════════════════════════════════════════════════
# ENTRY POINT — con reinicio automático
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    while True:
        try:
            main()
        except KeyboardInterrupt:
            log.info("Detenido por el usuario.")
            break
        except Exception as e:
            log.exception(f"CRASH: {e}")
            try:
                tg_error(f"💥 CRASH — reiniciando en 30s:\n{e}")
            except Exception:
                pass
            log.info("Reiniciando en 30 segundos...")
            time.sleep(30)
