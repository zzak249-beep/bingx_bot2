"""
╔══════════════════════════════════════════════════════════════════════════╗
║  SAIYAN ELITE BOT v6.0 — COMPETITIVE EDITION                            ║
║  "Inspired by studying 3Commas, Freqtrade, Gunbot & Pionex internals"   ║
║                                                                          ║
║  ESTRATEGIAS INTEGRADAS:                                                 ║
║  1. Dwell Blocks Breakout  — consolidación + breakout ATR                ║
║  2. UTBot ATR Trailing     — EMA cross ATR trailing stop                 ║
║  3. BB + RSI               — Bollinger Bands oversold/overbought         ║
║  4. EMA Trend Follow       — cruce EMA rápida/lenta con volumen          ║
║  5. Regime-Adaptive        — detecta tendencia vs rango, elige estrategia║
║                                                                          ║
║  AUTO-MEJORA (aprende de errores):                                       ║
║  • Registra causa de cada pérdida (SL tipo, hora, volatilidad, régimen)  ║
║  • Ajusta pesos de estrategias según rendimiento reciente                ║
║  • Sube SL dinámicamente si las últimas N operaciones son pérdidas       ║
║  • Detecta drawdown por estrategia y la pausa si supera umbral           ║
║  • Volatility sizing — ajusta tamaño según ATR actual vs histórico       ║
║  • Patrón de horas malas — bloquea automáticamente horas con pérdidas    ║
║                                                                          ║
║  VARIABLES OBLIGATORIAS:                                                 ║
║    BINGX_API_KEY  BINGX_API_SECRET                                       ║
║    TELEGRAM_BOT_TOKEN  TELEGRAM_CHAT_ID  WEBHOOK_SECRET                  ║
║                                                                          ║
║  VARIABLES OPCIONALES (todas tienen defaults):                           ║
║    FIXED_USDT=20  LEVERAGE=5  MAX_OPEN_TRADES=5                          ║
║    MAX_DRAWDOWN=15  DAILY_LOSS_LIMIT=8                                   ║
║    TP1_PCT=1.0  TP2_PCT=1.8  TP3_PCT=3.0  SL_PCT=0.8                    ║
║    TRAILING_PCT=0.5  TRAILING_ACTIVATE=1.0                               ║
║    MIN_STRATEGY_SCORE=0.4   (win rate mín para que estrategia opere)     ║
║    LEARNING_WINDOW=20       (operaciones para calcular rendimiento)       ║
║    AUTO_PAUSE_DD_PCT=25     (DD por estrategia para pausarla)             ║
║    DRY_RUN=false                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, time, logging, csv, threading, json, math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
from collections import deque, defaultdict
from statistics import mean, stdev

import requests
import ccxt
import numpy as np
from flask import Flask, request, jsonify, Response

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()])
log = logging.getLogger("saiyan_elite")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
API_KEY           = os.environ.get("BINGX_API_KEY",       "")
API_SECRET        = os.environ.get("BINGX_API_SECRET",    "")
TG_TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TG_CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID",    "")
WEBHOOK_SECRET    = os.environ.get("WEBHOOK_SECRET",      "saiyan2024")

FIXED_USDT        = float(os.environ.get("FIXED_USDT",           "20.0"))
LEVERAGE          = int  (os.environ.get("LEVERAGE",              "5"))
MAX_OPEN_TRADES   = int  (os.environ.get("MAX_OPEN_TRADES",       "5"))
CB_DD             = float(os.environ.get("MAX_DRAWDOWN",          "15.0"))
DAILY_LOSS_PCT    = float(os.environ.get("DAILY_LOSS_LIMIT",      "8.0"))
TP1_PCT           = float(os.environ.get("TP1_PCT",               "1.0"))
TP2_PCT           = float(os.environ.get("TP2_PCT",               "1.8"))
TP3_PCT           = float(os.environ.get("TP3_PCT",               "3.0"))
SL_PCT            = float(os.environ.get("SL_PCT",                "0.8"))
TRAILING_PCT      = float(os.environ.get("TRAILING_PCT",          "0.5"))
TRAILING_ACTIVATE = float(os.environ.get("TRAILING_ACTIVATE",     "1.0"))
HEARTBEAT_MIN     = int  (os.environ.get("HEARTBEAT_MIN",         "60"))
COOLDOWN_MIN      = int  (os.environ.get("COOLDOWN_MIN",          "5"))
ANTI_SPIKE_PCT    = float(os.environ.get("ANTI_SPIKE_PCT",        "3.0"))
DRY_RUN           = os.environ.get("DRY_RUN", "false").lower() == "true"
PORT              = int  (os.environ.get("PORT", "8080"))

# Auto-mejora
MIN_STRATEGY_SCORE = float(os.environ.get("MIN_STRATEGY_SCORE", "0.35"))
LEARNING_WINDOW    = int  (os.environ.get("LEARNING_WINDOW",     "20"))
AUTO_PAUSE_DD_PCT  = float(os.environ.get("AUTO_PAUSE_DD_PCT",   "25.0"))
BAD_HOUR_THRESHOLD = int  (os.environ.get("BAD_HOUR_THRESHOLD",  "3"))   # N pérdidas en 1h para bloquearla

STATE_PATH = "/tmp/saiyan_elite_state.json"
CSV_PATH   = "/tmp/saiyan_elite_trades.csv"
BRAIN_PATH = "/tmp/saiyan_elite_brain.json"  # memoria adaptativa
_lock      = threading.Lock()

# Nombres de estrategias
STRAT_DWELL    = "dwell_blocks"
STRAT_UTBOT    = "utbot"
STRAT_BBRSI    = "bb_rsi"
STRAT_EMA      = "ema_trend"
STRAT_WEBHOOK  = "webhook"   # señales externas sin estrategia específica
ALL_STRATEGIES = [STRAT_DWELL, STRAT_UTBOT, STRAT_BBRSI, STRAT_EMA, STRAT_WEBHOOK]

# ─────────────────────────────────────────────────────────────────────────────
# BRAIN — Memoria Adaptativa (NÚCLEO AUTO-MEJORA)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class StrategyBrain:
    """Registra rendimiento por estrategia y aprende."""
    name:         str
    trades:       List[dict]   = field(default_factory=list)  # últimas N operaciones
    total_pnl:    float        = 0.0
    wins:         int          = 0
    losses:       int          = 0
    paused_until: float        = 0.0   # timestamp hasta cuando está pausada
    pause_reason: str          = ""
    weight:       float        = 1.0   # multiplicador de confianza (0.1–2.0)

    def wr(self) -> float:
        t = self.wins + self.losses
        return self.wins / t if t else 0.5

    def pf(self) -> float:
        gross_w = sum(t["pnl"] for t in self.trades if t["pnl"] > 0)
        gross_l = sum(abs(t["pnl"]) for t in self.trades if t["pnl"] < 0)
        return gross_w / gross_l if gross_l else 1.0

    def recent_wr(self, n: int = None) -> float:
        n = n or LEARNING_WINDOW
        recent = self.trades[-n:] if len(self.trades) >= n else self.trades
        if not recent: return 0.5
        return sum(1 for t in recent if t["pnl"] > 0) / len(recent)

    def recent_dd(self) -> float:
        """Drawdown acumulado en las últimas N operaciones."""
        peak = 0.0; dd = 0.0; eq = 0.0
        for t in self.trades[-LEARNING_WINDOW:]:
            eq += t["pnl"]
            if eq > peak: peak = eq
            if peak > 0:
                cur_dd = (peak - eq) / peak * 100
                if cur_dd > dd: dd = cur_dd
        return dd

    def is_active(self) -> bool:
        if self.paused_until > time.time():
            return False
        if len(self.trades) >= 5 and self.recent_wr() < MIN_STRATEGY_SCORE:
            return False
        return True

    def add_trade(self, pnl: float, meta: dict):
        if pnl > 0: self.wins += 1
        else:        self.losses += 1
        self.total_pnl += pnl
        record = {"pnl": pnl, "ts": time.time(), **meta}
        self.trades.append(record)
        if len(self.trades) > 200: self.trades = self.trades[-200:]
        self._update_weight()

    def _update_weight(self):
        """Ajusta weight según rendimiento reciente."""
        wr = self.recent_wr()
        pf = self.pf()
        # Weight: función de WR y PF
        w = (wr * 0.6 + min(pf / 3.0, 1.0) * 0.4) * 2.0  # 0 → 2
        self.weight = max(0.1, min(2.0, w))

    def dynamic_sl_adj(self) -> float:
        """
        Si últimas 3 operaciones son pérdidas, reduce SL en 20%.
        Si últimas 3 son ganancias, puede ampliar un poco.
        """
        recent = self.trades[-3:]
        if len(recent) < 3: return 1.0
        all_loss = all(t["pnl"] < 0 for t in recent)
        all_win  = all(t["pnl"] > 0 for t in recent)
        if all_loss: return 0.75   # SL más ajustado
        if all_win:  return 1.15   # SL un poco más holgado
        return 1.0

    def check_auto_pause(self):
        """Pausa la estrategia si su DD reciente supera el umbral."""
        dd = self.recent_dd()
        if dd >= AUTO_PAUSE_DD_PCT:
            self.paused_until = time.time() + 4 * 3600  # pausa 4h
            self.pause_reason = f"DD reciente {dd:.1f}% >= {AUTO_PAUSE_DD_PCT}%"
            return True
        return False


@dataclass
class AdaptiveBrain:
    """Cerebro central de auto-mejora."""
    strategies:    Dict[str, StrategyBrain]  = field(default_factory=dict)
    bad_hours:     Dict[int, int]            = field(default_factory=dict)  # hora UTC → n pérdidas
    blocked_hours: List[int]                 = field(default_factory=list)
    total_errors:  int                       = 0
    error_log:     List[dict]                = field(default_factory=list)
    last_report:   float                     = field(default_factory=time.time)

    def __post_init__(self):
        for s in ALL_STRATEGIES:
            if s not in self.strategies:
                self.strategies[s] = StrategyBrain(name=s)

    def get(self, strat: str) -> StrategyBrain:
        if strat not in self.strategies:
            self.strategies[strat] = StrategyBrain(name=strat)
        return self.strategies[strat]

    def record_result(self, strat: str, pnl: float, meta: dict):
        sb = self.get(strat)
        sb.add_trade(pnl, meta)
        sb.check_auto_pause()

        # Registrar hora mala
        hour = datetime.now(timezone.utc).hour
        if pnl < 0:
            self.bad_hours[hour] = self.bad_hours.get(hour, 0) + 1
            if self.bad_hours[hour] >= BAD_HOUR_THRESHOLD and hour not in self.blocked_hours:
                self.blocked_hours.append(hour)
                log.info(f"Brain: hora {hour}h UTC bloqueada ({self.bad_hours[hour]} pérdidas)")
                tg_brain_notify(f"🧠 Auto-aprendizaje: hora <b>{hour}:xx UTC</b> bloqueada "
                                f"({self.bad_hours[hour]} pérdidas consecutivas)")

    def is_hour_ok(self) -> bool:
        hour = datetime.now(timezone.utc).hour
        return hour not in self.blocked_hours

    def best_strategy(self) -> str:
        active = [(s, sb) for s, sb in self.strategies.items() if sb.is_active()]
        if not active: return STRAT_WEBHOOK
        return max(active, key=lambda x: x[1].weight * x[1].recent_wr())[0]

    def size_multiplier(self, strat: str) -> float:
        """Ajusta tamaño de posición basado en confianza de la estrategia."""
        sb = self.get(strat)
        if not sb.is_active(): return 0.0
        return max(0.5, min(1.5, sb.weight))

    def dynamic_sl_for(self, strat: str) -> float:
        return self.get(strat).dynamic_sl_adj()

    def log_error(self, error_type: str, detail: str, strat: str = ""):
        self.total_errors += 1
        self.error_log.append({
            "ts": now(), "type": error_type, "detail": detail[:200], "strat": strat
        })
        if len(self.error_log) > 100: self.error_log = self.error_log[-100:]

    def to_dict(self) -> dict:
        return {
            "strategies": {
                k: {
                    "name": v.name, "wins": v.wins, "losses": v.losses,
                    "total_pnl": v.total_pnl, "weight": v.weight,
                    "paused_until": v.paused_until, "pause_reason": v.pause_reason,
                    "trades": v.trades[-50:]
                } for k, v in self.strategies.items()
            },
            "bad_hours":     self.bad_hours,
            "blocked_hours": self.blocked_hours,
            "total_errors":  self.total_errors,
            "error_log":     self.error_log[-20:],
        }

    def load_dict(self, d: dict):
        for k, v in d.get("strategies", {}).items():
            sb = StrategyBrain(name=k)
            sb.wins = v.get("wins", 0); sb.losses = v.get("losses", 0)
            sb.total_pnl = v.get("total_pnl", 0.0); sb.weight = v.get("weight", 1.0)
            sb.paused_until = v.get("paused_until", 0.0)
            sb.pause_reason = v.get("pause_reason", "")
            sb.trades = v.get("trades", [])
            self.strategies[k] = sb
        self.bad_hours     = {int(k): v for k, v in d.get("bad_hours", {}).items()}
        self.blocked_hours = d.get("blocked_hours", [])
        self.total_errors  = d.get("total_errors", 0)
        self.error_log     = d.get("error_log", [])


brain = AdaptiveBrain()

def tg_brain_notify(msg: str):
    """Notificación de auto-aprendizaje (se llama sin lock)."""
    threading.Thread(target=lambda: _tg_raw(msg), daemon=True).start()

def save_brain():
    try:
        with open(BRAIN_PATH, "w") as f: json.dump(brain.to_dict(), f)
    except Exception as e: log.warning(f"save_brain: {e}")

def load_brain():
    try:
        if os.path.exists(BRAIN_PATH):
            with open(BRAIN_PATH) as f: brain.load_dict(json.load(f))
            log.info("Brain cargado OK")
    except Exception as e: log.warning(f"load_brain: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    symbol:        str
    side:          str
    entry_price:   float
    contracts:     float
    tp1:           float
    tp2:           float
    tp3:           float
    sl:            float
    entry_time:    str
    strategy:      str   = STRAT_WEBHOOK
    sl_pct_used:   float = 0.0       # SL real usado (tras ajuste dinámico)
    score:         int   = 0
    tp1_hit:       bool  = False
    tp2_hit:       bool  = False
    sl_at_be:      bool  = False
    trailing_on:   bool  = False
    trailing_high: float = 0.0
    dry_run:       bool  = False
    # Dwell Blocks extras
    dwell_high:    float = 0.0
    dwell_low:     float = 0.0
    rr_ratio:      float = 2.0

@dataclass
class State:
    trades:           Dict[str, Trade] = field(default_factory=dict)
    closed_history:   List[dict]       = field(default_factory=list)
    cooldowns:        Dict[str, float] = field(default_factory=dict)
    wins:             int   = 0
    losses:           int   = 0
    gross_profit:     float = 0.0
    gross_loss:       float = 0.0
    peak_equity:      float = 0.0
    total_pnl:        float = 0.0
    daily_pnl:        float = 0.0
    daily_reset_ts:   float = field(default_factory=time.time)
    start_time:       float = field(default_factory=time.time)
    total_trades:     int   = 0
    paused:           bool  = False
    max_dd_real:      float = 0.0
    best_trade:       float = 0.0
    worst_trade:      float = 0.0
    tg_offset:        int   = 0

    def n(self): return len(self.trades)
    def wr(self):
        t = self.wins + self.losses; return self.wins/t*100 if t else 0.0
    def pf(self): return self.gross_profit/self.gross_loss if self.gross_loss else 0.0
    def avg_win(self): return self.gross_profit/self.wins if self.wins else 0.0
    def avg_loss(self): return self.gross_loss/self.losses if self.losses else 0.0
    def expectancy(self):
        wr=self.wr()/100; return wr*self.avg_win()-(1-wr)*self.avg_loss()
    def cb(self):
        if self.peak_equity<=0: return False
        return self.total_pnl<0 and abs(self.total_pnl)/self.peak_equity*100>=CB_DD
    def daily_hit(self):
        if self.peak_equity<=0: return False
        return self.daily_pnl<0 and abs(self.daily_pnl)/self.peak_equity*100>=DAILY_LOSS_PCT
    def in_cooldown(self, symbol):
        return (time.time()-self.cooldowns.get(symbol,0))<COOLDOWN_MIN*60
    def reset_daily(self):
        if time.time()-self.daily_reset_ts>86400:
            self.daily_pnl=0.0; self.daily_reset_ts=time.time()
    def record_close(self, pnl, symbol, strategy=STRAT_WEBHOOK):
        self.total_trades+=1
        if pnl>=0: self.wins+=1; self.gross_profit+=pnl; self.best_trade=max(self.best_trade,pnl)
        else: self.losses+=1; self.gross_loss+=abs(pnl); self.worst_trade=min(self.worst_trade,pnl)
        self.total_pnl+=pnl; self.daily_pnl+=pnl; self.cooldowns[symbol]=time.time()
        if self.peak_equity>0:
            dd=abs(self.total_pnl)/self.peak_equity*100
            if self.total_pnl<0 and dd>self.max_dd_real: self.max_dd_real=dd
        cur=self.peak_equity+self.total_pnl
        if cur>self.peak_equity: self.peak_equity=cur
    def uptime(self):
        s=int(time.time()-self.start_time); h,m=divmod(s//60,60); d,h=divmod(h,24)
        return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
    def to_persist(self):
        return {"wins":self.wins,"losses":self.losses,"gross_profit":self.gross_profit,
                "gross_loss":self.gross_loss,"total_pnl":self.total_pnl,
                "peak_equity":self.peak_equity,"total_trades":self.total_trades,
                "best_trade":self.best_trade,"worst_trade":self.worst_trade,
                "max_dd_real":self.max_dd_real,"closed_history":self.closed_history[-100:],
                "cooldowns":self.cooldowns}
    def load_persist(self, d):
        for k in ("wins","losses","gross_profit","gross_loss","total_pnl","peak_equity",
                  "total_trades","best_trade","worst_trade","max_dd_real"):
            if k in d: setattr(self,k,d[k])
        self.closed_history=d.get("closed_history",[]); self.cooldowns=d.get("cooldowns",{})

st = State()

def save_state():
    try:
        with open(STATE_PATH,"w") as f: json.dump(st.to_persist(),f)
    except Exception as e: log.warning(f"save_state: {e}")
def load_state():
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f: st.load_persist(json.load(f))
            log.info(f"Estado restaurado: {st.total_trades} trades")
    except Exception as e: log.warning(f"load_state: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE
# ─────────────────────────────────────────────────────────────────────────────
_ex = None; _ex_lock = threading.Lock()
def ex():
    global _ex
    with _ex_lock:
        if _ex is None:
            _ex = ccxt.bingx({"apiKey":API_KEY,"secret":API_SECRET,
                "options":{"defaultType":"swap","defaultMarginMode":"cross"},
                "enableRateLimit":True})
            _ex.load_markets(); log.info("BingX conectado OK")
        return _ex

def ex_call(fn, *args, retries=3, **kwargs):
    for attempt in range(retries):
        try: return fn(*args, **kwargs)
        except ccxt.NetworkError as e:
            wait=2**attempt; log.warning(f"Network({attempt+1}): {e} {wait}s"); time.sleep(wait)
        except ccxt.RateLimitExceeded: log.warning("RateLimit 15s"); time.sleep(15)
        except ccxt.AuthenticationError as e: log.error(f"Auth: {e}"); raise
        except Exception as e:
            if attempt==retries-1: raise
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed {retries}")

def sym(raw):
    r=raw.upper().strip()
    for s in (".P","PERP","-PERP","_PERP"):
        if r.endswith(s): r=r[:-len(s)]
    if ":" in r: return r
    if "/" in r:
        b,q=r.split("/",1); q2=q.split(":")[0]; return f"{b}/{q2}:{q2}"
    if r.endswith("USDT"): return f"{r[:-4]}/USDT:USDT"
    return f"{r}/USDT:USDT"

def price(symbol): return float(ex_call(ex().fetch_ticker,symbol)["last"])
def price_validated(symbol):
    t=ex_call(ex().fetch_ticker,symbol); last=float(t["last"])
    bid=float(t.get("bid") or last); ask=float(t.get("ask") or last); mid=(bid+ask)/2
    if mid>0 and abs(last-mid)/mid*100>ANTI_SPIKE_PCT:
        raise ValueError(f"Anti-spike {last:.6g} vs {mid:.6g}")
    return last

def balance():
    b=ex_call(ex().fetch_balance); usdt=b.get("USDT",{})
    free=float(usdt.get("free",0) or 0)
    if free==0:
        for item in b.get("info",{}).get("data",{}).get("balance",[]):
            if item.get("asset")=="USDT": free=float(item.get("availableMargin",0) or 0); break
    return free

def get_position(symbol):
    try:
        for p in ex_call(ex().fetch_positions,[symbol]):
            qty=abs(float(p.get("contracts") or p.get("info",{}).get("positionAmt",0) or 0))
            if qty>0: return p
    except Exception as e: log.warning(f"get_pos: {e}")
    return None

def set_lev(symbol):
    try: ex_call(ex().set_leverage,LEVERAGE,symbol,{"marginMode":"cross"}); log.info(f"  Lev {LEVERAGE}x OK")
    except Exception as e: log.warning(f"  set_lev: {e}")

def cancel_all_safe(symbol):
    try: ex_call(ex().cancel_all_orders,symbol); return
    except Exception: pass
    try:
        for o in ex_call(ex().fetch_open_orders,symbol):
            try: ex_call(ex().cancel_order,o["id"],symbol)
            except Exception as e2: log.warning(f"cancel {o['id']}: {e2}")
    except Exception as e: log.warning(f"cancel_all: {e}")

def place_tp(e,symbol,cs,qty,tp_price):
    try:
        tp=float(e.price_to_precision(symbol,tp_price))
        q=float(e.amount_to_precision(symbol,qty))
        if q*tp<1: return False
        ex_call(e.create_order,symbol,"limit",cs,q,tp,{"reduceOnly":True})
        log.info(f"  TP @ {tp:.6g} qty={q} OK"); return True
    except Exception as err: log.warning(f"  place_tp: {err}"); return False

def place_sl(e,symbol,cs,qty,stop_price):
    try:
        sp=float(e.price_to_precision(symbol,stop_price))
        q=float(e.amount_to_precision(symbol,qty))
        params={"reduceOnly":True,"stopPrice":sp}
        for otype in ["stop_market","stop"]:
            try:
                ex_call(e.create_order,symbol,otype,cs,q,None,params)
                log.info(f"  SL {otype} @ {sp:.6g} OK"); return True
            except Exception as te: log.warning(f"  SL {otype}: {te}")
        return False
    except Exception as err: log.warning(f"  place_sl: {err}"); return False

def update_sl(t,new_sl):
    if t.dry_run: return
    try:
        cancel_all_safe(t.symbol)
        place_sl(ex(),t.symbol,"sell" if t.side=="long" else "buy",t.contracts,new_sl)
    except Exception as e: log.warning(f"update_sl: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# INDICADORES TÉCNICOS (calculados en tiempo real desde OHLCV)
# ─────────────────────────────────────────────────────────────────────────────
_ohlcv_cache: Dict[str, Tuple[float, np.ndarray]] = {}  # symbol → (ts, array)
_ohlcv_lock = threading.Lock()
OHLCV_TTL = 60  # segundos

def get_ohlcv(symbol: str, timeframe="15m", limit=100) -> Optional[np.ndarray]:
    now_ts = time.time()
    with _ohlcv_lock:
        cached = _ohlcv_cache.get(symbol)
        if cached and now_ts - cached[0] < OHLCV_TTL:
            return cached[1]
    try:
        data = ex_call(ex().fetch_ohlcv, symbol, timeframe, limit=limit)
        if not data or len(data) < 20: return None
        arr = np.array(data, dtype=float)
        with _ohlcv_lock: _ohlcv_cache[symbol] = (now_ts, arr)
        return arr
    except Exception as e: log.warning(f"ohlcv({symbol}): {e}"); return None

def calc_atr(h, l, c, period=14):
    trs = []
    for i in range(1, len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    trs = np.array(trs)
    if len(trs) < period: return float(np.mean(trs)) if len(trs) else 0.0
    atr = float(np.mean(trs[:period]))
    for tr in trs[period:]: atr = (atr*(period-1)+tr)/period
    return atr

def calc_ema(closes, period):
    if len(closes) < period: return float(closes[-1])
    k = 2/(period+1); ema = float(np.mean(closes[:period]))
    for c in closes[period:]: ema = c*k + ema*(1-k)
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period+1: return 50.0
    d = np.diff(closes)
    g = np.where(d>0,d,0); l = np.where(d<0,-d,0)
    ag = float(np.mean(g[:period])); al = float(np.mean(l[:period]))
    for i in range(period, len(d)):
        ag = (ag*(period-1)+g[i])/period; al = (al*(period-1)+l[i])/period
    return 100.0 if al==0 else 100-100/(1+ag/al)

def calc_bb(closes, period=20, std_mult=2.0):
    if len(closes) < period: return closes[-1], closes[-1], closes[-1]
    recent = closes[-period:]
    mid = float(np.mean(recent)); sd = float(np.std(recent))
    return mid - std_mult*sd, mid, mid + std_mult*sd  # lower, mid, upper

def calc_adx(h, l, c, period=14):
    """ADX para detectar fuerza de tendencia."""
    if len(c) < period+2: return 25.0
    dm_plus = []; dm_minus = []; tr_list = []
    for i in range(1, len(c)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        tr_list.append(tr)
        up = h[i]-h[i-1]; dn = l[i-1]-l[i]
        dm_plus.append(up if up>dn and up>0 else 0)
        dm_minus.append(dn if dn>up and dn>0 else 0)
    def smooth(arr, p):
        s = sum(arr[:p])
        result = [s]
        for v in arr[p:]: s = s - s/p + v; result.append(s)
        return result
    atr_s = smooth(tr_list, period); dmp = smooth(dm_plus, period); dmm = smooth(dm_minus, period)
    dx_list = []
    for i in range(len(atr_s)):
        if atr_s[i]==0: continue
        pdi = 100*dmp[i]/atr_s[i]; mdi = 100*dmm[i]/atr_s[i]
        if pdi+mdi==0: continue
        dx_list.append(100*abs(pdi-mdi)/(pdi+mdi))
    if not dx_list: return 25.0
    return float(np.mean(dx_list[-period:])) if len(dx_list)>=period else float(np.mean(dx_list))

# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 1 — DWELL BLOCKS BREAKOUT
# Basada en el Pine Script proporcionado
# ─────────────────────────────────────────────────────────────────────────────
def strategy_dwell_blocks(symbol: str, side_hint: str = None) -> Optional[dict]:
    """
    Detecta bloques de consolidación (dwell) y señala breakouts.
    Retorna señal con: side, sl, tp, dwell_high, dwell_low, rr_ratio
    o None si no hay señal.
    """
    arr = get_ohlcv(symbol, "15m", 60)
    if arr is None: return None

    closes = arr[:,4]; highs = arr[:,2]; lows = arr[:,3]
    cons_length = 20
    atr_mult    = 1.5
    atr_length  = 14
    rr_ratio    = 2.0
    risk_pct    = SL_PCT / 100

    atr = calc_atr(highs, lows, closes, atr_length)
    if atr == 0: return None

    # Lookback sobre las últimas cons_length velas
    range_high = float(np.max(highs[-cons_length-1:-1]))  # shifted [1]
    range_low  = float(np.min(lows[-cons_length-1:-1]))
    range_width = range_high - range_low

    is_consolidation = range_width < atr_mult * atr
    if not is_consolidation:
        return None

    current_close = float(closes[-1])
    prev_close    = float(closes[-2])

    # Long breakout: close cruza por encima de range_high[1]
    # (prev_close <= range_high y current_close > range_high)
    if prev_close <= range_high < current_close:
        sl_price  = current_close * (1 - risk_pct)
        tp_price  = current_close * (1 + risk_pct * rr_ratio)
        return {
            "side": "long", "sl": sl_price, "tp": tp_price,
            "dwell_high": range_high, "dwell_low": range_low,
            "rr_ratio": rr_ratio, "strategy": STRAT_DWELL,
            "atr": atr, "range_width": range_width
        }

    # Short breakout: close cruza por debajo de range_low[1]
    if prev_close >= range_low > current_close:
        sl_price  = current_close * (1 + risk_pct)
        tp_price  = current_close * (1 - risk_pct * rr_ratio)
        return {
            "side": "short", "sl": sl_price, "tp": tp_price,
            "dwell_high": range_high, "dwell_low": range_low,
            "rr_ratio": rr_ratio, "strategy": STRAT_DWELL,
            "atr": atr, "range_width": range_width
        }

    return None

# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 2 — UTBot (ATR Trailing Stop + EMA cross)
# ─────────────────────────────────────────────────────────────────────────────
def strategy_utbot(symbol: str) -> Optional[dict]:
    arr = get_ohlcv(symbol, "15m", 80)
    if arr is None: return None
    closes = arr[:,4]; highs = arr[:,2]; lows = arr[:,3]
    atr = calc_atr(highs, lows, closes, 14)
    key_value = 2.0  # configurable, equivale al "Key Value" del UTBot

    # ATR Trailing Stop (simplificado)
    atr_stop = float(closes[-1]) - key_value * atr
    atr_stop_short = float(closes[-1]) + key_value * atr

    ema_fast = calc_ema(closes, 20)
    ema_slow = calc_ema(closes, 50)

    # Long: EMA fast cruza sobre EMA slow Y precio sobre ATR stop
    if ema_fast > ema_slow and float(closes[-1]) > atr_stop and float(closes[-2]) <= calc_ema(closes[:-1], 50):
        sl = atr_stop
        tp = float(closes[-1]) + (float(closes[-1]) - sl) * 2
        return {"side":"long","sl":sl,"tp":tp,"strategy":STRAT_UTBOT,"atr":atr}
    # Short: inverso
    if ema_fast < ema_slow and float(closes[-1]) < atr_stop_short:
        sl = atr_stop_short
        tp = float(closes[-1]) - (sl - float(closes[-1])) * 2
        return {"side":"short","sl":sl,"tp":tp,"strategy":STRAT_UTBOT,"atr":atr}
    return None

# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 3 — BB + RSI (oversold/overbought reversal)
# ─────────────────────────────────────────────────────────────────────────────
def strategy_bbrsi(symbol: str) -> Optional[dict]:
    arr = get_ohlcv(symbol, "15m", 60)
    if arr is None: return None
    closes = arr[:,4]; highs = arr[:,2]; lows = arr[:,3]
    rsi = calc_rsi(closes, 14)
    bb_low, bb_mid, bb_high = calc_bb(closes, 20, 2.0)
    atr = calc_atr(highs, lows, closes, 14)
    cur = float(closes[-1])

    # Long: precio toca BB inferior Y RSI < 30
    if cur <= bb_low and rsi < 30:
        sl = cur - 1.5*atr
        tp = bb_mid + (bb_mid - bb_low) * 0.5
        return {"side":"long","sl":sl,"tp":tp,"strategy":STRAT_BBRSI,"rsi":rsi,"atr":atr}
    # Short: precio toca BB superior Y RSI > 70
    if cur >= bb_high and rsi > 70:
        sl = cur + 1.5*atr
        tp = bb_mid - (bb_high - bb_mid) * 0.5
        return {"side":"short","sl":sl,"tp":tp,"strategy":STRAT_BBRSI,"rsi":rsi,"atr":atr}
    return None

# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 4 — EMA Trend Follow + Volumen
# ─────────────────────────────────────────────────────────────────────────────
def strategy_ema_trend(symbol: str) -> Optional[dict]:
    arr = get_ohlcv(symbol, "15m", 80)
    if arr is None: return None
    closes = arr[:,4]; highs = arr[:,2]; lows = arr[:,3]; vols = arr[:,5]
    ema9  = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema9_prev  = calc_ema(closes[:-1], 9)
    ema21_prev = calc_ema(closes[:-1], 21)
    atr = calc_atr(highs, lows, closes, 14)
    adx = calc_adx(highs, lows, closes, 14)
    vol_ratio = float(vols[-1]) / float(np.mean(vols[-20:-1])) if float(np.mean(vols[-20:-1]))>0 else 1.0

    # Solo operar si ADX > 20 (tendencia fuerte) y volumen > 1.1x media
    if adx < 20 or vol_ratio < 1.1: return None

    cur = float(closes[-1])
    if ema9_prev <= ema21_prev and ema9 > ema21:  # cruce alcista
        sl = cur - atr * 1.5
        tp = cur + atr * 3.0
        return {"side":"long","sl":sl,"tp":tp,"strategy":STRAT_EMA,"adx":adx,"vol_ratio":vol_ratio,"atr":atr}
    if ema9_prev >= ema21_prev and ema9 < ema21:  # cruce bajista
        sl = cur + atr * 1.5
        tp = cur - atr * 3.0
        return {"side":"short","sl":sl,"tp":tp,"strategy":STRAT_EMA,"adx":adx,"vol_ratio":vol_ratio,"atr":atr}
    return None

# ─────────────────────────────────────────────────────────────────────────────
# SCANNER DE SEÑALES (hilo autónomo)
# ─────────────────────────────────────────────────────────────────────────────
SCAN_SYMBOLS = os.environ.get("SCAN_SYMBOLS", "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT").split(",")
SCAN_ENABLED = os.environ.get("SCAN_ENABLED", "true").lower() == "true"
SCAN_INTERVAL_SEC = int(os.environ.get("SCAN_INTERVAL_SEC", "300"))  # cada 5min

def _scanner_worker():
    """Escanea símbolos automáticamente con las estrategias activas."""
    log.info(f"Scanner iniciado: {SCAN_SYMBOLS} cada {SCAN_INTERVAL_SEC}s")
    time.sleep(120)  # esperar startup
    while True:
        try:
            if not SCAN_ENABLED or st.paused or st.cb() or st.daily_hit():
                time.sleep(SCAN_INTERVAL_SEC); continue
            if not brain.is_hour_ok():
                time.sleep(60); continue

            for raw_sym in SCAN_SYMBOLS:
                raw_sym = raw_sym.strip()
                if not raw_sym: continue
                symbol = sym(raw_sym)
                with _lock:
                    if symbol in st.trades: continue
                    if st.in_cooldown(symbol): continue
                    if st.n() >= MAX_OPEN_TRADES: break

                # Probar cada estrategia activa según su weight
                strategies_to_try = [
                    (STRAT_DWELL, strategy_dwell_blocks),
                    (STRAT_BBRSI, strategy_bbrsi),
                    (STRAT_EMA,   strategy_ema_trend),
                    (STRAT_UTBOT, strategy_utbot),
                ]
                for strat_name, strat_fn in strategies_to_try:
                    if not brain.get(strat_name).is_active(): continue
                    try:
                        signal = strat_fn(symbol)
                        if signal:
                            log.info(f"[SCAN] {symbol} señal {strat_name}: {signal['side']}")
                            open_trade_from_signal(symbol, signal)
                            time.sleep(2)
                            break
                    except Exception as e:
                        log.warning(f"Scanner {strat_name}/{symbol}: {e}")

        except Exception as e:
            log.warning(f"Scanner main: {e}")
        time.sleep(SCAN_INTERVAL_SEC)

# ─────────────────────────────────────────────────────────────────────────────
# CORE LOGIC — OPEN TRADE
# ─────────────────────────────────────────────────────────────────────────────
def open_trade_from_signal(raw_symbol: str, signal: dict) -> dict:
    """Abre un trade desde una señal de estrategia interna."""
    side     = signal.get("side", "long")
    strategy = signal.get("strategy", STRAT_WEBHOOK)
    return open_trade(raw_symbol, side, strategy=strategy, signal_meta=signal)

def open_trade(raw_symbol: str, side: str,
               strategy: str = STRAT_WEBHOOK,
               signal_meta: dict = None) -> dict:
    with _lock:
        symbol = sym(raw_symbol)
        log.info(f"[OPEN] {symbol} {side.upper()} strat={strategy}")

        if st.paused:         return {"result":"paused"}
        if st.n()>=MAX_OPEN_TRADES:
            msg_blocked(f"Max {MAX_OPEN_TRADES}",side,symbol); return {"result":"blocked_max_trades"}
        if symbol in st.trades: return {"result":"already_open"}
        if st.cb():
            msg_blocked(f"Circuit Breaker {CB_DD}%",side,symbol); return {"result":"blocked_cb"}
        if st.daily_hit():
            msg_blocked(f"Daily limit {DAILY_LOSS_PCT}%",side,symbol); return {"result":"blocked_daily"}
        if st.in_cooldown(symbol): return {"result":"cooldown"}
        if not brain.is_hour_ok():
            return {"result":"blocked_bad_hour"}
        if not brain.get(strategy).is_active():
            return {"result":f"strategy_{strategy}_paused",
                    "reason": brain.get(strategy).pause_reason}

        try:
            e = ex()
            if symbol not in e.markets: ex_call(e.load_markets)
            if symbol not in e.markets: raise ValueError(f"Simbolo no encontrado: {symbol}")

            set_lev(symbol)
            px  = price_validated(symbol)
            bal = balance()

            # Sizing dinámico por brain
            size_mult = brain.size_multiplier(strategy)
            usdt_size = FIXED_USDT * size_mult
            notl      = usdt_size * LEVERAGE
            qty       = float(e.amount_to_precision(symbol, notl/px))
            if qty*px < 5: raise ValueError(f"Notional muy pequeno: ${qty*px:.2f}")

            order_side = "buy" if side=="long" else "sell"

            # SL dinámico — ajuste por brain
            sl_adj   = brain.dynamic_sl_for(strategy)
            sl_pct_n = SL_PCT * sl_adj / 100  # ajustado

            # Calcular niveles desde señal o por defecto
            if DRY_RUN: entry_p = px
            else:
                order   = ex_call(e.create_order,symbol,"market",order_side,qty,params={"reduceOnly":False})
                entry_p = float(order.get("average") or order.get("price") or px)
                if entry_p==0: entry_p=px
                log.info(f"  Fill @ {entry_p:.6g}")

            mult       = 1 if side=="long" else -1
            meta       = signal_meta or {}

            # Si la señal provee SL/TP específicos (Dwell Blocks, UTBot, etc.)
            if meta.get("sl") and meta.get("tp"):
                sl  = float(e.price_to_precision(symbol, meta["sl"]))
                # Convertir TP único a tres niveles
                tp_dist = abs(meta["tp"] - entry_p)
                tp1 = float(e.price_to_precision(symbol, entry_p + mult*tp_dist*0.40))
                tp2 = float(e.price_to_precision(symbol, entry_p + mult*tp_dist*0.70))
                tp3 = float(e.price_to_precision(symbol, entry_p + mult*tp_dist*1.00))
            else:
                sl  = float(e.price_to_precision(symbol, entry_p*(1-mult*sl_pct_n)))
                tp1 = float(e.price_to_precision(symbol, entry_p*(1+mult*TP1_PCT/100)))
                tp2 = float(e.price_to_precision(symbol, entry_p*(1+mult*TP2_PCT/100)))
                tp3 = float(e.price_to_precision(symbol, entry_p*(1+mult*TP3_PCT/100)))

            close_side = "sell" if side=="long" else "buy"
            if not DRY_RUN:
                place_tp(e,symbol,close_side,qty*0.50,tp1)
                place_tp(e,symbol,close_side,qty*0.30,tp2)
                place_tp(e,symbol,close_side,qty*0.20,tp3)
                place_sl(e,symbol,close_side,qty,sl)

            t = Trade(symbol=symbol,side=side,entry_price=entry_p,
                      contracts=qty,tp1=tp1,tp2=tp2,tp3=tp3,sl=sl,
                      entry_time=now(),strategy=strategy,
                      sl_pct_used=sl_pct_n*100,trailing_high=entry_p,
                      dry_run=DRY_RUN,
                      dwell_high=meta.get("dwell_high",0.0),
                      dwell_low=meta.get("dwell_low",0.0),
                      rr_ratio=meta.get("rr_ratio",2.0))
            st.trades[symbol]=t
            csv_log("OPEN",t)
            msg_open(t,bal,meta)
            log.info(f"[OPEN] {symbol} {side.upper()} OK strat={strategy} size_mult={size_mult:.2f}")
            return {"result":"opened","symbol":symbol,"side":side,"entry":entry_p,
                    "qty":qty,"strategy":strategy,"size_mult":size_mult,"dry_run":DRY_RUN}

        except Exception as err:
            log.error(f"open_trade {symbol}: {err}")
            brain.log_error("open_trade_error", str(err), strategy)
            msg_error(f"open_trade {symbol}: {err}")
            return {"result":"error","detail":str(err)}


def close_trade(raw_symbol: str, reason: str) -> dict:
    with _lock:
        symbol = sym(raw_symbol)
        if symbol not in st.trades: return {"result":"not_found"}
        t = st.trades[symbol]
        try:
            e = ex()
            cancel_all_safe(symbol)
            exit_p = price(symbol); pnl = 0.0

            if t.dry_run:
                pnl=((exit_p-t.entry_price) if t.side=="long" else (t.entry_price-exit_p))*t.contracts
            else:
                pos=get_position(symbol)
                if pos:
                    qty_pos=abs(float(pos.get("contracts") or pos.get("info",{}).get("positionAmt",0) or 0))
                    if qty_pos>0:
                        csid="sell" if t.side=="long" else "buy"
                        ord_=ex_call(e.create_order,symbol,"market",csid,qty_pos,params={"reduceOnly":True})
                        exit_p=float(ord_.get("average") or ord_.get("price") or exit_p)
                        if exit_p==0: exit_p=price(symbol)
                        pnl=((exit_p-t.entry_price) if t.side=="long" else (t.entry_price-exit_p))*qty_pos
                    else:
                        pnl=((exit_p-t.entry_price) if t.side=="long" else (t.entry_price-exit_p))*t.contracts
                else:
                    pnl=((exit_p-t.entry_price) if t.side=="long" else (t.entry_price-exit_p))*t.contracts

            dur = _dur(t.entry_time)
            st.closed_history.append({
                "symbol":t.symbol,"side":t.side,"entry":t.entry_price,"exit":exit_p,
                "pnl":round(pnl,4),"reason":reason,"duration":dur,"ts":now(),
                "strategy":t.strategy,"dry_run":t.dry_run
            })
            if len(st.closed_history)>100: st.closed_history=st.closed_history[-100:]

            st.record_close(pnl, symbol, t.strategy)

            # BRAIN: registrar resultado
            hour = datetime.now(timezone.utc).hour
            brain.record_result(t.strategy, pnl, {
                "symbol": symbol, "side": t.side,
                "duration_min": int((time.time()-
                    datetime.strptime(t.entry_time,"%Y-%m-%d %H:%M UTC")
                    .replace(tzinfo=timezone.utc).timestamp())/60) if t.entry_time else 0,
                "hour_utc": hour,
                "sl_adj": t.sl_pct_used,
                "reason": reason
            })

            csv_log("CLOSE",t,exit_p,pnl)
            msg_close(t,exit_p,pnl,reason)
            del st.trades[symbol]
            save_state(); save_brain()

            # Notificar si estrategia fue pausada tras esta operación
            sb = brain.get(t.strategy)
            if not sb.is_active() and sb.paused_until > time.time():
                tg(f"🧠 <b>Auto-aprendizaje</b>: estrategia <code>{t.strategy}</code> "
                   f"pausada 4h\n📉 Motivo: {sb.pause_reason}\n{now()}")

            return {"result":"closed","pnl":round(pnl,4)}
        except Exception as err:
            log.error(f"close_trade {symbol}: {err}")
            brain.log_error("close_trade_error", str(err), t.strategy)
            msg_error(f"close_trade {symbol}: {err}")
            return {"result":"error","detail":str(err)}


def handle_tp(raw_symbol: str, tp_label: str) -> dict:
    with _lock:
        symbol = sym(raw_symbol)
        if symbol not in st.trades: return {"result":"not_found"}
        t = st.trades[symbol]
        try:
            e=ex(); pos=get_position(symbol)
            rem=str(round(abs(float(pos.get("contracts") or
                pos.get("info",{}).get("positionAmt",0) or 0)),4)) if pos else "~"

            if tp_label=="TP1" and not t.tp1_hit:
                t.tp1_hit=True
                pnl_est=abs(t.tp1-t.entry_price)*t.contracts*0.50
                if not t.dry_run:
                    try:
                        be=float(e.price_to_precision(symbol,t.entry_price))
                        csid="sell" if t.side=="long" else "buy"
                        cancel_all_safe(symbol); rem_qty=t.contracts*0.50
                        place_tp(e,symbol,csid,rem_qty*0.60,t.tp2)
                        place_tp(e,symbol,csid,rem_qty*0.40,t.tp3)
                        place_sl(e,symbol,csid,rem_qty,be)
                        t.sl=be; t.sl_at_be=True; t.trailing_on=True
                        t.trailing_high=price(symbol)
                    except Exception as be_err: log.warning(f"  BE: {be_err}")
                else: t.sl_at_be=True; t.trailing_on=True
                msg_tp(t,"TP1",pnl_est,rem)

            elif tp_label=="TP2" and not t.tp2_hit:
                t.tp2_hit=True
                pnl_est=abs(t.tp2-t.entry_price)*t.contracts*0.30
                msg_tp(t,"TP2",pnl_est,rem)

            elif tp_label=="TP3":
                pnl_est=abs(t.tp3-t.entry_price)*t.contracts*0.20
                msg_tp(t,"TP3",pnl_est,"0")
                st.record_close(pnl_est,symbol,t.strategy)
                brain.record_result(t.strategy, pnl_est, {"symbol":symbol,"reason":"TP3"})
                csv_log("CLOSE",t,t.tp3,pnl_est)
                if symbol in st.trades: del st.trades[symbol]
                save_state(); save_brain()

            return {"result":f"{tp_label}_handled"}
        except Exception as err:
            log.error(f"handle_tp {symbol} {tp_label}: {err}")
            return {"result":"error","detail":str(err)}

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────
_tg_queue=deque(maxlen=50); _tg_q_lock=threading.Lock()
def _tg_raw(msg: str, silent=False):
    if not(TG_TOKEN and TG_CHAT_ID): return
    try:
        r=requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id":TG_CHAT_ID,"text":msg[:4096],"parse_mode":"HTML","disable_notification":silent},
            timeout=15)
        if not r.ok: log.warning(f"TG {r.status_code}"); return
    except Exception as e: log.warning(f"TG: {e}")

def tg(msg, silent=False):
    if not(TG_TOKEN and TG_CHAT_ID): return
    try: _tg_raw(msg, silent)
    except Exception as e:
        log.warning(f"TG: {e}")
        with _tg_q_lock: _tg_queue.append(msg)

def _tg_retry_worker():
    while True:
        time.sleep(30)
        with _tg_q_lock: pending=list(_tg_queue); _tg_queue.clear()
        for m in pending:
            try: _tg_raw(m)
            except Exception: pass

def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
def _bar(v,mx,w=10): f=int(min(v/mx,1.0)*w) if mx>0 else 0; return "█"*f+"░"*(w-f)
def _dur(ts):
    try:
        dt=datetime.strptime(ts,"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        s=int((datetime.now(timezone.utc)-dt).total_seconds()); h,r=divmod(s,3600)
        return f"{h}h {r//60}m" if h else f"{r//60}m"
    except Exception: return "?"

def _strat_emoji(strat):
    return {"dwell_blocks":"🧱","utbot":"🤖","bb_rsi":"🎯","ema_trend":"📈","webhook":"📡"}.get(strat,"⚡")

# ─────────────────────────────────────────────────────────────────────────────
# MENSAJES ENRIQUECIDOS
# ─────────────────────────────────────────────────────────────────────────────
def msg_start(bal):
    strats_status = ""
    for s in ALL_STRATEGIES:
        sb=brain.get(s); icon="✅" if sb.is_active() else "⏸"
        strats_status += f"  {icon} {_strat_emoji(s)} {s}: WR={sb.wr()*100:.0f}% W={sb.weight:.2f}\n"
    tg(
        f"<b>🔥 SAIYAN ELITE v6.0 — ONLINE</b>\n"
        f"{'🔸 DRY-RUN ACTIVO\n' if DRY_RUN else ''}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${bal:.2f} USDT</b>\n"
        f"⚙️ ${FIXED_USDT:.0f}/trade x{LEVERAGE} | max {MAX_OPEN_TRADES} pos\n"
        f"🎯 TP1+{TP1_PCT}% TP2+{TP2_PCT}% TP3+{TP3_PCT}% SL-{SL_PCT}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Auto-Mejora Activa:</b>\n"
        f"  Score mínimo: {MIN_STRATEGY_SCORE*100:.0f}% | Ventana: {LEARNING_WINDOW} ops\n"
        f"  DD pausa: {AUTO_PAUSE_DD_PCT}% | Horas bloq: {brain.blocked_hours or 'ninguna'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Estrategias:</b>\n{strats_status}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Scanner: {'✅ '+str(SCAN_SYMBOLS) if SCAN_ENABLED else '❌ OFF'}\n"
        f"📲 /status /brain /pos /strats /pause /resume /help\n{now()}"
    )

def msg_open(t, bal, meta=None):
    icon="▲ LONG" if t.side=="long" else "▼ SHORT"
    dry=" [DRY]" if t.dry_run else ""
    sl_info=f"SL-{t.sl_pct_used:.2f}% (adj)" if t.sl_pct_used!=SL_PCT else f"SL-{SL_PCT}%"
    dwell_info=""
    if t.dwell_high and t.dwell_low:
        dwell_info=f"🧱 Dwell: {t.dwell_low:.6g} – {t.dwell_high:.6g}\n"
    tg(
        f"{_strat_emoji(t.strategy)} <b>{icon}{dry}</b> — <code>{t.symbol}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Entrada: <code>{t.entry_price:.6g}</code> | Strat: <b>{t.strategy}</b>\n"
        f"🟡 TP1 50%: <code>{t.tp1:.6g}</code>\n"
        f"🟠 TP2 30%: <code>{t.tp2:.6g}</code>\n"
        f"🟢 TP3 20%: <code>{t.tp3:.6g}</code>\n"
        f"🛑 SL: <code>{t.sl:.6g}</code>  {sl_info}\n"
        f"{dwell_info}"
        f"📦 {t.contracts} contratos | R:R {t.rr_ratio:.1f}\n"
        f"🧠 Brain weight: {brain.get(t.strategy).weight:.2f}\n"
        f"📊 {st.wins}W/{st.losses}L WR:{st.wr():.1f}% | {st.n()}/{MAX_OPEN_TRADES}\n"
        f"💰 Bal: ${bal:.2f}\n{now()}"
    )

def msg_tp(t, label, pnl_est, rem):
    extra="🛡 SL→BE + Trailing ON\n" if label=="TP1" else ""
    tg(f"🏆 <b>{label} HIT</b> — <code>{t.symbol}</code>\n"
       f"~${pnl_est:+.2f} | Restante: {rem}\n{extra}"
       f"Hoy: ${st.daily_pnl:+.2f} | Total: ${st.total_pnl:+.2f}\n{now()}")

def msg_trailing_update(t, new_sl, gain_pct):
    tg(f"〽️ TRAILING <code>{t.symbol}</code> SL→<code>{new_sl:.6g}</code> +{gain_pct:.2f}%\n{now()}", silent=True)

def msg_close(t, exit_p, pnl, reason):
    e="✅" if pnl>=0 else "❌"
    pct=(exit_p-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
    sb=brain.get(t.strategy)
    tg(
        f"{e} <b>CERRADO [{t.strategy}]</b> — {reason}\n"
        f"<code>{t.symbol}</code> {t.side.upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{t.entry_price:.6g}</code>→<code>{exit_p:.6g}</code> ({pct:+.2f}%)\n"
        f"PnL: <b>${pnl:+.2f}</b>  ⏱{_dur(t.entry_time)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 {t.strategy} W={sb.weight:.2f} WR={sb.wr()*100:.0f}%\n"
        f"📊 {st.wins}W/{st.losses}L WR:{st.wr():.1f}% PF:{st.pf():.2f}\n"
        f"💹 Hoy: ${st.daily_pnl:+.2f} | Total: ${st.total_pnl:+.2f}\n{now()}"
    )

def msg_blocked(reason, action, symbol):
    tg(f"⛔ <b>BLOQUEADO</b> — {reason}\n{action} {symbol}\n{now()}")
def msg_error(txt):
    tg(f"🔥 <b>ERROR:</b> <code>{txt[:400]}</code>\n{now()}")

def msg_status():
    try: bal=balance()
    except Exception: bal=0.0
    db=_bar(abs(st.daily_pnl),st.peak_equity*DAILY_LOSS_PCT/100 if st.peak_equity>0 else 1)
    cb=_bar(abs(st.total_pnl) if st.total_pnl<0 else 0,st.peak_equity*CB_DD/100 if st.peak_equity>0 else 1)
    tg(
        f"📊 <b>STATUS — SAIYAN ELITE v6.0</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'⏸ PAUSA\n' if st.paused else ''}"
        f"{'🚨 CIRCUIT BREAKER\n' if st.cb() else ''}"
        f"{'🚨 LIMITE DIARIO\n' if st.daily_hit() else ''}"
        f"💰 ${bal:.2f} USDT | {st.n()}/{MAX_OPEN_TRADES} pos\n"
        f"⏱ Uptime: {st.uptime()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 {st.wins}W/{st.losses}L WR:{st.wr():.1f}% PF:{st.pf():.2f}\n"
        f"💡 E:${st.expectancy():.2f}/trade\n"
        f"🏆 Best: ${st.best_trade:+.2f} | Worst: ${st.worst_trade:+.2f}\n"
        f"💹 Hoy: ${st.daily_pnl:+.2f} [{db}]\n"
        f"🛡 DD: [{cb}] Max:{st.max_dd_real:.1f}%\n"
        f"💼 Total: ${st.total_pnl:+.2f}\n"
        f"🧠 Horas bloq: {brain.blocked_hours or 'ninguna'}\n{now()}"
    )

def msg_brain_report():
    lines = ["🧠 <b>BRAIN REPORT — Auto-Aprendizaje</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for s in ALL_STRATEGIES:
        sb = brain.get(s)
        active = "✅" if sb.is_active() else f"⏸ {sb.pause_reason[:30]}"
        lines.append(
            f"{_strat_emoji(s)} <b>{s}</b> {active}\n"
            f"  WR:{sb.wr()*100:.0f}% ({sb.wins}W/{sb.losses}L) | PF:{sb.pf():.2f}\n"
            f"  Weight:{sb.weight:.2f} | Recent WR:{sb.recent_wr()*100:.0f}% | DD:{sb.recent_dd():.1f}%\n"
            f"  Total PnL: ${sb.total_pnl:+.2f}"
        )
    lines.append(f"\n⏰ Horas bloq: {brain.blocked_hours or 'ninguna'}")
    lines.append(f"🔢 Errores: {brain.total_errors}")
    lines.append(f"🏆 Mejor estrategia ahora: <b>{brain.best_strategy()}</b>")
    tg("\n".join(lines))

def msg_positions():
    if not st.trades: tg("📦 <b>Sin posiciones abiertas</b>"); return
    lines=[f"📦 <b>POSICIONES ({st.n()})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for sym_,t in st.trades.items():
        try:
            px=price(sym_); gain=(px-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
            icon="🟢" if gain>=0 else "🔴"
            lines.append(
                f"{icon} <code>{sym_}</code> {t.side.upper()} [{t.strategy}]\n"
                f"   {t.entry_price:.6g}→{px:.6g} ({gain:+.2f}%) SL:{t.sl:.6g} ⏱{_dur(t.entry_time)}"
            )
        except Exception: lines.append(f"<code>{sym_}</code> {t.side.upper()}")
    tg("\n".join(lines))

def msg_strats():
    lines=["📊 <b>ESTRATEGIAS STATUS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for s in ALL_STRATEGIES:
        sb=brain.get(s); active="✅ Activa" if sb.is_active() else "⏸ Pausada"
        lines.append(f"{_strat_emoji(s)} <b>{s}</b>: {active}\n"
                     f"  WR:{sb.recent_wr()*100:.0f}% | Weight:{sb.weight:.2f} | PnL:${sb.total_pnl:+.2f}")
    tg("\n".join(lines))

def msg_heartbeat():
    try:
        bal=balance()
        open_lines=""
        for sym_,t in list(st.trades.items()):
            try:
                px=price(sym_); gain=(px-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
                open_lines+=f"  {'🟢' if gain>=0 else '🔴'} <code>{sym_}</code> {t.side.upper()} {gain:+.2f}% [{t.strategy}]\n"
            except Exception: open_lines+=f"  <code>{sym_}</code>\n"
        if not open_lines: open_lines="  (sin posiciones)\n"
        best = brain.best_strategy()
        db=_bar(abs(st.daily_pnl),st.peak_equity*DAILY_LOSS_PCT/100 if st.peak_equity>0 else 1)
        tg(
            f"💓 <b>HEARTBEAT</b> · {now()}\n"
            f"💰 ${bal:.2f} | {st.n()}/{MAX_OPEN_TRADES} pos\n"
            f"{open_lines}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {st.wins}W/{st.losses}L WR:{st.wr():.1f}% PF:{st.pf():.2f}\n"
            f"💹 Hoy: ${st.daily_pnl:+.2f} [{db}]\n"
            f"🧠 Mejor strat: {best} | Horas bloq: {brain.blocked_hours or 'ninguna'}\n"
            f"⏱ {st.uptime()}",
            silent=True
        )
    except Exception as e: log.warning(f"heartbeat: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────────────────
def csv_log(action, t, exit_p=0.0, pnl=0.0):
    try:
        exists=os.path.exists(CSV_PATH)
        with open(CSV_PATH,"a",newline="") as f:
            w=csv.writer(f)
            if not exists:
                w.writerow(["ts","action","symbol","side","entry","exit","pnl","qty",
                            "strategy","trailing","sl_at_be","sl_pct","dry_run"])
            w.writerow([now(),action,t.symbol,t.side,t.entry_price,
                        exit_p or t.entry_price,round(pnl,4),t.contracts,
                        t.strategy,t.trailing_on,t.sl_at_be,t.sl_pct_used,t.dry_run])
    except Exception as e: log.warning(f"CSV: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# WORKERS
# ─────────────────────────────────────────────────────────────────────────────
def _trailing_worker():
    log.info("Trailing worker iniciado")
    while True:
        time.sleep(15)
        with _lock: symbols=list(st.trades.keys())
        for symbol in symbols:
            try:
                with _lock:
                    if symbol not in st.trades: continue
                    t=st.trades[symbol]
                px=price(symbol)
                gain_pct=(px-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
                with _lock:
                    if symbol not in st.trades: continue
                    t=st.trades[symbol]
                    if not t.trailing_on and gain_pct>=TRAILING_ACTIVATE:
                        t.trailing_on=True; t.trailing_high=px
                    if not t.trailing_on: continue
                    if t.side=="long":
                        if px>t.trailing_high: t.trailing_high=px
                        new_sl=t.trailing_high*(1-TRAILING_PCT/100)
                        if new_sl>t.sl:
                            t.sl=new_sl; msg_trailing_update(t,new_sl,gain_pct); update_sl(t,new_sl)
                    else:
                        if t.trailing_high==0 or px<t.trailing_high: t.trailing_high=px
                        new_sl=t.trailing_high*(1+TRAILING_PCT/100)
                        if new_sl<t.sl:
                            t.sl=new_sl; msg_trailing_update(t,new_sl,gain_pct); update_sl(t,new_sl)
            except Exception as e: log.warning(f"Trailing [{symbol}]: {e}")

def _heartbeat_worker():
    time.sleep(90)
    while True: msg_heartbeat(); time.sleep(HEARTBEAT_MIN*60)

def _daily_worker():
    while True:
        nu=datetime.now(timezone.utc)
        tomorrow=(nu+timedelta(days=1)).replace(hour=0,minute=0,second=5,microsecond=0)
        time.sleep((tomorrow-nu).total_seconds())
        tg(f"📉 <b>RESUMEN DIARIO</b>\n"
           f"PnL: ${st.daily_pnl:+.2f} | {st.wins}W/{st.losses}L\n"
           f"Total: ${st.total_pnl:+.2f} | MaxDD: {st.max_dd_real:.1f}%\n{now()}")
        with _lock: st.daily_pnl=0.0; st.daily_reset_ts=time.time()
        save_state(); save_brain()

def _autosave_worker():
    while True: time.sleep(300); save_state(); save_brain()

def _tg_commands_worker():
    if not(TG_TOKEN and TG_CHAT_ID): return
    log.info("Telegram polling iniciado")
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"timeout":30,"offset":st.tg_offset,"allowed_updates":["message"]},timeout=40)
            if not r.ok: time.sleep(5); continue
            for upd in r.json().get("result",[]):
                st.tg_offset=upd["update_id"]+1
                m=upd.get("message",{}); cid=str(m.get("chat",{}).get("id","")); txt=m.get("text","").strip().lower()
                if cid!=str(TG_CHAT_ID): continue
                if txt in("/status","/s"):       msg_status()
                elif txt in("/brain","/b"):      msg_brain_report()
                elif txt in("/pos","/p"):        msg_positions()
                elif txt in("/strats","/st"):    msg_strats()
                elif txt=="/pause":
                    with _lock: st.paused=True
                    tg("⏸ Bot en PAUSA. /resume para reanudar.")
                elif txt=="/resume":
                    with _lock: st.paused=False
                    tg("▶️ Bot REANUDADO.")
                elif txt.startswith("/close "):
                    raw=txt.split("/close ",1)[1].strip().upper()
                    tg(f"Cerrando {raw}...")
                    res=close_trade(raw,"MANUAL")
                    tg(f"{'✅' if res.get('result')=='closed' else '❌'} PnL: ${res.get('pnl',0):+.2f}")
                elif txt.startswith("/scan "):
                    # Escanea un símbolo específico inmediatamente
                    raw=txt.split("/scan ",1)[1].strip().upper()
                    tg(f"🔍 Escaneando {raw}...")
                    results=[]
                    for sname,sfn in [(STRAT_DWELL,strategy_dwell_blocks),
                                      (STRAT_BBRSI,strategy_bbrsi),
                                      (STRAT_EMA,strategy_ema_trend),
                                      (STRAT_UTBOT,strategy_utbot)]:
                        try:
                            sig=sfn(sym(raw))
                            if sig: results.append(f"  ✅ {sname}: {sig['side'].upper()}")
                            else: results.append(f"  ⬜ {sname}: sin señal")
                        except Exception as se: results.append(f"  ❌ {sname}: error")
                    tg(f"📊 <b>Scan {raw}:</b>\n"+"\n".join(results)+f"\n{now()}")
                elif txt=="/unblock_hours":
                    with _lock: brain.blocked_hours.clear(); brain.bad_hours.clear()
                    tg("🧠 Horas bloqueadas liberadas.")
                elif txt=="/help":
                    tg(
                        "<b>Comandos SAIYAN ELITE v6.0:</b>\n"
                        "/status — estado\n/brain — reporte auto-aprendizaje\n"
                        "/pos — posiciones\n/strats — estrategias\n"
                        "/scan SYMBOL — escanear símbolo\n"
                        "/pause /resume — pausar/reanudar\n"
                        "/close SYMBOL — cierre manual\n"
                        "/unblock_hours — liberar horas bloqueadas\n"
                        "/help — esta ayuda\n\n"
                        "<b>Webhook:</b>\n"
                        f'<code>{{"secret":"{WEBHOOK_SECRET}","action":"long entry","symbol":"BTCUSDT"}}</code>\n'
                        "<b>Acciones:</b> long entry|short entry|buy|sell|tp1|tp2|tp3|close|stop loss"
                    )
        except requests.exceptions.Timeout: pass
        except Exception as e: log.warning(f"tg_cmd: {e}"); time.sleep(10)

# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK PARSER
# ─────────────────────────────────────────────────────────────────────────────
_ACTION_MAP={
    "long entry":"long_entry","long_entry":"long_entry","buy":"long_entry","long":"long_entry",
    "openlong":"long_entry","enter_long":"long_entry","bullish":"long_entry",
    "short entry":"short_entry","short_entry":"short_entry","sell":"short_entry","short":"short_entry",
    "openshort":"short_entry","enter_short":"short_entry","bearish":"short_entry",
    "long exit":"close_long","long_exit":"close_long",
    "short exit":"close_short","short_exit":"close_short",
    "exit":"close","close":"close","close_trade":"close",
    "stop loss":"stop_loss","stop_loss":"stop_loss","stoploss":"stop_loss","sl":"stop_loss","stop":"stop_loss",
    "tp1":"tp1","tp1 hit":"tp1","take profit 1":"tp1",
    "tp2":"tp2","tp2 hit":"tp2","take profit 2":"tp2",
    "tp3":"tp3","tp3 hit":"tp3","take profit 3":"tp3","take profit":"tp3",
    # Dwell blocks desde TradingView
    "dwell long":"long_entry","dwell short":"short_entry",
    "breakout long":"long_entry","breakout short":"short_entry",
}
def parse_action(raw):
    clean=raw.strip().lower()
    if clean in _ACTION_MAP: return _ACTION_MAP[clean]
    for k,v in _ACTION_MAP.items():
        if k in clean: return v
    return None

# ─────────────────────────────────────────────────────────────────────────────
# FLASK
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/",methods=["GET"])
def health():
    return jsonify({
        "status":"alive","bot":"SAIYAN ELITE v6.0","dry_run":DRY_RUN,
        "paused":st.paused,"uptime":st.uptime(),"open_trades":st.n(),
        "total_trades":st.total_trades,"wins":st.wins,"losses":st.losses,
        "win_rate":round(st.wr(),1),"profit_factor":round(st.pf(),2),
        "expectancy":round(st.expectancy(),2),"total_pnl":round(st.total_pnl,2),
        "daily_pnl":round(st.daily_pnl,2),"circuit_breaker":st.cb(),
        "best_strategy":brain.best_strategy(),"blocked_hours":brain.blocked_hours,
        "time":now()
    })

@app.route("/brain",methods=["GET"])
def brain_ep():
    return jsonify(brain.to_dict())

@app.route("/positions",methods=["GET"])
def positions_ep():
    result={}
    for sym_,t in st.trades.items():
        try: px=price(sym_); u=(px-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
        except Exception: px,u=0.0,0.0
        result[sym_]={**t.__dict__,"current_price":px,"unrealized_pct":round(u,2)}
    return jsonify(result)

@app.route("/scan/<raw_sym>",methods=["GET"])
def scan_ep(raw_sym):
    symbol=sym(raw_sym.upper())
    results={}
    for sname,sfn in [(STRAT_DWELL,strategy_dwell_blocks),(STRAT_BBRSI,strategy_bbrsi),
                      (STRAT_EMA,strategy_ema_trend),(STRAT_UTBOT,strategy_utbot)]:
        try: results[sname]=sfn(symbol) or "no_signal"
        except Exception as e: results[sname]=f"error: {e}"
    return jsonify({"symbol":symbol,"signals":results,"time":now()})

@app.route("/history",methods=["GET"])
def history_ep():
    return jsonify({"trades":st.closed_history[-20:]})

@app.route("/dashboard",methods=["GET"])
def dashboard():
    try: bal=balance()
    except Exception: bal=0.0
    color="#00ff88" if st.total_pnl>=0 else "#ff4444"
    rows=""
    for t in reversed(st.closed_history[-10:]):
        pc="#00ff88" if t["pnl"]>=0 else "#ff4444"
        rows+=(f"<tr><td>{t['ts']}</td><td>{t['symbol']}</td><td>{t['side'].upper()}</td>"
               f"<td style='color:{pc}'>${t['pnl']:+.2f}</td><td>{t['reason']}</td>"
               f"<td>{t.get('strategy','?')}</td><td>{t['duration']}</td></tr>")
    open_rows=""
    for sym_,t in st.trades.items():
        try: px=price(sym_); g=(px-t.entry_price)/t.entry_price*100*(1 if t.side=="long" else -1)
        except Exception: px,g=0.0,0.0
        gc="#00ff88" if g>=0 else "#ff4444"
        open_rows+=(f"<tr><td>{sym_}</td><td>{t.side.upper()}</td>"
                    f"<td>{t.entry_price:.6g}</td><td>{px:.6g}</td>"
                    f"<td style='color:{gc}'>{g:+.2f}%</td>"
                    f"<td>{t.strategy}</td><td>{_dur(t.entry_time)}</td></tr>")
    strat_rows=""
    for s in ALL_STRATEGIES:
        sb=brain.get(s); color_s="#00ff88" if sb.is_active() else "#ff8800"
        strat_rows+=(f"<tr><td>{s}</td>"
                     f"<td style='color:{color_s}'>{'Activa' if sb.is_active() else 'Pausada'}</td>"
                     f"<td>{sb.recent_wr()*100:.0f}%</td><td>{sb.pf():.2f}</td>"
                     f"<td>{sb.weight:.2f}</td><td>${sb.total_pnl:+.2f}</td></tr>")
    html=f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30"><title>SAIYAN ELITE v6.0</title>
<style>
body{{background:#0a0a0a;color:#e0e0e0;font-family:monospace;margin:20px}}
h1{{color:#ff6600}} h2{{color:#ff9900;margin-top:30px}}
.card{{background:#141414;border:1px solid #333;border-radius:8px;padding:15px;
       display:inline-block;margin:8px;min-width:130px;text-align:center}}
.big{{font-size:1.7em;font-weight:bold}}
.sub{{color:#888;font-size:.8em}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th{{background:#1e1e1e;padding:8px;text-align:left;color:#ff9900}}
td{{padding:6px 8px;border-bottom:1px solid #1e1e1e}}
tr:hover{{background:#141414}}
.badge{{background:#333;padding:2px 6px;border-radius:4px;font-size:.8em}}
</style></head><body>
{'<div style="background:#ff8800;color:#000;padding:10px;text-align:center;font-weight:bold">⏸ BOT EN PAUSA</div>' if st.paused else ""}
{'<div style="background:#3366ff;color:#fff;padding:8px;text-align:center">🔸 DRY-RUN ACTIVO</div>' if DRY_RUN else ""}
<h1>🔥 SAIYAN ELITE v6.0 — Multi-Estrategia + Auto-Mejora</h1>
<div class="sub">Auto-refresh 30s · {now()}</div>
<div>
<div class="card"><div class="sub">Balance</div><div class="big">${bal:.2f}</div></div>
<div class="card"><div class="sub">PnL Total</div><div class="big" style="color:{color}">${st.total_pnl:+.2f}</div></div>
<div class="card"><div class="sub">Hoy</div><div class="big" style="color:{'#00ff88' if st.daily_pnl>=0 else '#ff4444'}">${st.daily_pnl:+.2f}</div></div>
<div class="card"><div class="sub">Win Rate</div><div class="big">{st.wr():.1f}%</div><div class="sub">{st.wins}W/{st.losses}L</div></div>
<div class="card"><div class="sub">Profit Factor</div><div class="big">{st.pf():.2f}</div></div>
<div class="card"><div class="sub">Expectancy</div><div class="big" style="color:{'#00ff88' if st.expectancy()>=0 else '#ff4444'}">${st.expectancy():.2f}</div></div>
<div class="card"><div class="sub">Max DD</div><div class="big" style="color:#ff4444">{st.max_dd_real:.1f}%</div></div>
<div class="card"><div class="sub">Uptime</div><div class="big" style="font-size:1em">{st.uptime()}</div></div>
</div>
<h2>🧠 Estrategias (Auto-Mejora)</h2>
<table><tr><th>Estrategia</th><th>Estado</th><th>WR Reciente</th><th>PF</th><th>Weight</th><th>PnL</th></tr>
{strat_rows}</table>
<p style="color:#888">Horas bloqueadas: {brain.blocked_hours or 'ninguna'} | Errores: {brain.total_errors}</p>
<h2>📦 Posiciones ({st.n()}/{MAX_OPEN_TRADES})</h2>
<table><tr><th>Símbolo</th><th>Lado</th><th>Entrada</th><th>Precio</th><th>PnL%</th><th>Estrategia</th><th>Tiempo</th></tr>
{open_rows or "<tr><td colspan='7' style='color:#666;text-align:center'>Sin posiciones</td></tr>"}
</table>
<h2>📜 Últimas 10 operaciones</h2>
<table><tr><th>Fecha</th><th>Símbolo</th><th>Lado</th><th>PnL</th><th>Razón</th><th>Estrategia</th><th>Duración</th></tr>
{rows or "<tr><td colspan='7' style='color:#666;text-align:center'>Sin historial</td></tr>"}
</table>
<h2>🔌 Webhook TradingView</h2>
<div style="background:#0d0d0d;padding:12px;border-radius:6px;color:#0f0">
{{"secret": "{WEBHOOK_SECRET}", "action": "long entry", "symbol": "{{{{ticker}}}}"}}
</div>
<p style="color:#888">Estrategias Pine: dwell long | breakout long | breakout short</p>
</body></html>"""
    return Response(html, mimetype="text/html")

@app.route("/webhook",methods=["POST"])
def webhook():
    try:
        data=request.get_json(force=True,silent=True) or {}
        log.info(f"Webhook: {data}")
        incoming=str(data.get("secret",data.get("passphrase",data.get("key",""))))
        if incoming!=WEBHOOK_SECRET:
            log.warning(f"No autorizado: '{incoming}'"); return jsonify({"error":"unauthorized"}),401
        action_raw=str(data.get("action",data.get("signal",data.get("order","")))).strip()
        symbol_raw=str(data.get("symbol",data.get("ticker",data.get("pair","")))).strip()
        if not action_raw: return jsonify({"error":"falta action"}),400
        if not symbol_raw: return jsonify({"error":"falta symbol"}),400
        st.reset_daily()
        action=parse_action(action_raw)
        if action is None:
            tg(f"⚠️ Acción no reconocida: <code>{action_raw}</code>\n{now()}")
            return jsonify({"error":f"unknown: {action_raw}"}),400
        log.info(f"  action='{action}' symbol='{symbol_raw}'")
        # Detectar si viene estrategia en el payload
        strat=data.get("strategy", data.get("source", STRAT_WEBHOOK))
        if action=="long_entry":        res=open_trade(symbol_raw,"long",strategy=strat)
        elif action=="short_entry":     res=open_trade(symbol_raw,"short",strategy=strat)
        elif action=="close_long":      res=close_trade(symbol_raw,"LONG EXIT")
        elif action=="close_short":     res=close_trade(symbol_raw,"SHORT EXIT")
        elif action=="close":           res=close_trade(symbol_raw,"EXIT SIGNAL")
        elif action=="stop_loss":       res=close_trade(symbol_raw,"STOP LOSS")
        elif action=="tp1":             res=handle_tp(symbol_raw,"TP1")
        elif action=="tp2":             res=handle_tp(symbol_raw,"TP2")
        elif action=="tp3":             res=handle_tp(symbol_raw,"TP3")
        else: return jsonify({"error":f"sin handler: {action}"}),400
        return jsonify(res),200
    except Exception as e:
        log.exception(f"Webhook crash: {e}")
        msg_error(f"Webhook: {e}")
        return jsonify({"error":str(e)}),500

@app.route("/test",methods=["GET","POST"])
def test_ep():
    if request.method=="POST":
        data=request.get_json(force=True,silent=True) or {}
        ar=str(data.get("action",""))
        return jsonify({"action_raw":ar,"action_parsed":parse_action(ar),
                        "symbol_parsed":sym(data.get("symbol","BTCUSDT")),
                        "secret_ok":data.get("secret","")==WEBHOOK_SECRET})
    return jsonify({"example":{"secret":WEBHOOK_SECRET,"action":"long entry","symbol":"BTCUSDT"}})

@app.route("/test_telegram",methods=["GET"])
def test_tg():
    try: tg(f"🧪 Test Telegram OK — SAIYAN ELITE v6.0\n{now()}"); return jsonify({"result":"ok"})
    except Exception as e: return jsonify({"result":"error","detail":str(e)}),500

@app.route("/test_exchange",methods=["GET"])
def test_ex():
    try: bal=balance(); return jsonify({"result":"ok","balance_usdt":bal})
    except Exception as e: return jsonify({"result":"error","detail":str(e)}),500

# ─────────────────────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────────────────────
def startup():
    load_state(); load_brain()
    log.info("━"*65)
    log.info("  SAIYAN ELITE BOT v6.0 — Multi-Estrategia + Auto-Mejora")
    log.info("━"*65)
    log.info(f"  DRY-RUN: {'YES' if DRY_RUN else 'NO'} | Scan: {'ON' if SCAN_ENABLED else 'OFF'}")
    log.info(f"  Símbolos: {SCAN_SYMBOLS}")
    log.info("━"*65)
    if not(API_KEY and API_SECRET): log.warning("No API keys")
    if not(TG_TOKEN and TG_CHAT_ID): log.warning("No Telegram")
    for attempt in range(10):
        try:
            bal=balance()
            if st.peak_equity==0: st.peak_equity=bal
            st.daily_reset_ts=time.time()
            log.info(f"Balance: ${bal:.2f} | Trades: {st.total_trades}")
            msg_start(bal); break
        except Exception as e:
            wait=min(2**attempt,60)
            log.warning(f"Startup {attempt+1}/10: {e} — retry {wait}s"); time.sleep(wait)
    else:
        log.error("No conecta BingX")
        tg(f"❌ SAIYAN ELITE v6.0 ERROR\nNo conecta BingX\n{now()}")

threading.Thread(target=startup,              daemon=True,name="startup").start()
threading.Thread(target=_trailing_worker,     daemon=True,name="trailing").start()
threading.Thread(target=_heartbeat_worker,    daemon=True,name="heartbeat").start()
threading.Thread(target=_daily_worker,        daemon=True,name="daily").start()
threading.Thread(target=_autosave_worker,     daemon=True,name="autosave").start()
threading.Thread(target=_tg_retry_worker,     daemon=True,name="tg_retry").start()
threading.Thread(target=_tg_commands_worker,  daemon=True,name="tg_cmd").start()
threading.Thread(target=_scanner_worker,      daemon=True,name="scanner").start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=PORT,debug=False)
