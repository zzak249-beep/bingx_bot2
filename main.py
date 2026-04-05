#!/usr/bin/env python3
"""
BOT LONGS v5.0 — Estrategia VWAP Breakout + Retest + EMA25
Basado en la estrategia de Whale Analytics:
  - VWAP institucional como nivel clave
  - Setup: Ruptura del VWAP + Retesteo = entrada de alta probabilidad
  - EMA25 para gestionar salidas
  - 1H para confirmar tendencia antes de entrar en 5M
  - No operar si VWAP está plano (mercado lateral)
  - Regla del 1% en gestión de riesgo

MEJORAS vs v4.0:
  NEW-1  Estrategia VWAP Breakout + Retest (señal principal)
  NEW-2  EMA25 como salida dinámica (cierra cuando precio cruza EMA25 a la baja)
  NEW-3  Detección VWAP plano: no operar en rangos
  NEW-4  Confirmación 1H alcista antes de entrar en 5M
  NEW-5  Score system simplificado y centrado en el setup VWAP
  NEW-6  Modo agresivo/conservador según volatilidad del mercado
  FIX-01 Circuit breaker: reset correcto sin bucle infinito
  FIX-02 LTV protection automática
  FIX-03 set_leverage sin BOTH (error 109400)
  FIX-04 Detección automática hedge/oneway
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re, json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from collections import defaultdict

# ============================================================================
# CONFIG
# ============================================================================

def clean(key, default, typ='str'):
    v = os.getenv(key, str(default)).strip().strip('"').strip("'")
    if typ in ('int', 'float'):
        v = v.replace(',', '.')
        m = re.match(r'^-?\d+\.?\d*', v)
        v = m.group(0) if m else str(default)
    if typ == 'int':   return int(float(v))
    if typ == 'float': return float(v)
    if typ == 'bool':  return v.lower() == 'true'
    return v

API_KEY    = os.getenv('BINGX_API_KEY',    '').strip().strip('"').strip("'")
API_SECRET = os.getenv('BINGX_API_SECRET', '').strip().strip('"').strip("'")
TG_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN', '')
TG_CHAT    = os.getenv('TELEGRAM_CHAT_ID',   '')

# ── Capital ────────────────────────────────────────────────────────────────
AUTO       = clean('AUTO_TRADING_ENABLED', 'true', 'bool')
POS_SIZE   = clean('MAX_POSITION_SIZE',    '10',   'float')  # USDT por trade
MIN_TRADE  = clean('MIN_TRADE_USDT',       '10',   'float')
_lev       = clean('LEVERAGE',             '2',    'int')
LEVERAGE   = min(_lev, 3)
MAX_TRADES = clean('MAX_OPEN_TRADES',      '3',    'int')

# ── TP/SL ──────────────────────────────────────────────────────────────────
TP_MIN     = clean('TAKE_PROFIT_PCT',      '4.0',  'float')
SL_MAX     = clean('STOP_LOSS_PCT',        '2.0',  'float')
ATR_TP_M   = clean('ATR_TP_MULT',          '2.5',  'float')
ATR_SL_M   = clean('ATR_SL_MULT',          '1.1',  'float')
USE_EMA25_EXIT = clean('EMA25_EXIT',       'true', 'bool')  # NEW-2

# ── Filtros ────────────────────────────────────────────────────────────────
MIN_VOL    = clean('MIN_VOLUME_24H',       '500000','float')
MAX_SYMS   = clean('MAX_SYMBOLS',          '60',   'int')
MIN_SCORE  = clean('MIN_SCORE',            '55',   'float')
BTC_BLOCK  = clean('BTC_BEAR_BLOCK_PCT',   '2.0',  'float')

# ── VWAP params (NEW) ──────────────────────────────────────────────────────
VWAP_FLAT_PCT    = clean('VWAP_FLAT_PCT',     '0.15', 'float') # VWAP plano si rango < 0.15%
VWAP_BREAK_PCT   = clean('VWAP_BREAK_PCT',    '0.10', 'float') # ruptura > 0.10% sobre VWAP
VWAP_RETEST_PCT  = clean('VWAP_RETEST_PCT',   '0.25', 'float') # retest: vuelve a <0.25% del VWAP
VWAP_CANDLES     = clean('VWAP_CANDLES',      '50',   'int')   # velas para calcular VWAP

# ── Circuit breaker ────────────────────────────────────────────────────────
CB_USDT    = clean('CIRCUIT_BREAKER_USDT', '3.0',  'float')
CB_HOURS   = clean('CB_PAUSE_HOURS',       '2',    'int')
MAX_STREAK = clean('MAX_LOSING_STREAK',    '4',    'int')

# ── Cooldowns ─────────────────────────────────────────────────────────────
CD_TP      = clean('COOLDOWN_TP_MIN',      '5',    'int')
CD_SL      = clean('COOLDOWN_SL_MIN',      '60',   'int')

# ── Misc ───────────────────────────────────────────────────────────────────
INTERVAL   = clean('CHECK_INTERVAL',       '120',  'int')
LTV_WARN   = clean('LTV_WARNING_PCT',      '80',   'float')
SKIP_HOURS = {2, 3}
BASE_URL   = "https://open-api.bingx.com"
FEE        = 0.0002
TP_MIN_FEE = round((2 * FEE * LEVERAGE + 0.003) * 100, 3)

EXCLUDE = {
    'DOW','SP500','GOLD','SILVER','XAU','OIL','BRENT','EUR','GBP','JPY',
    'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN','MSTR',
    'WHEAT','CORN','SUGAR','PAXG','XAUT',
}

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ============================================================================
# API
# ============================================================================

def api(method, endpoint, params=None, retries=3):
    params = params or {}
    for attempt in range(retries + 1):
        try:
            p   = {**{k: str(v) for k, v in params.items()},
                   'timestamp': str(int(time.time() * 1000))}
            qs  = urlencode(sorted(p.items()))
            sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
            url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
            hdr = {'X-BX-APIKEY': API_KEY,
                   'Content-Type': 'application/x-www-form-urlencoded'}
            r   = getattr(requests, method.lower())(url, headers=hdr, timeout=15)
            return r.json()
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                log.error(f"API {endpoint}: {e}")
                return {}

def pub(path, params=None):
    try:
        return requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=10).json()
    except:
        return {}

# ============================================================================
# INDICADORES
# ============================================================================

def ema(prices, n):
    if not prices: return 0
    if len(prices) < n: return sum(prices) / len(prices)
    k, e = 2 / (n + 1), prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(prices, n=14):
    if len(prices) < n + 1: return 50.0
    g = [max(prices[i] - prices[i-1], 0) for i in range(1, len(prices))]
    l = [max(prices[i-1] - prices[i], 0) for i in range(1, len(prices))]
    ag, al = sum(g[-n:]) / n, sum(l[-n:]) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

def atr_calc(h, l, c, n=14):
    if len(c) < 2: return 0
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
           for i in range(1, min(len(c), n+1))]
    return sum(trs) / len(trs) if trs else 0

def calc_vwap(closes, highs, lows, volumes, n=None):
    """VWAP = Σ(típico × volumen) / Σvolumen"""
    n = n or len(closes)
    c = closes[-n:]; h = highs[-n:]; l = lows[-n:]; v = volumes[-n:]
    typical = [(h[i] + l[i] + c[i]) / 3 for i in range(len(c))]
    tp_vol  = sum(typical[i] * v[i] for i in range(len(c)))
    vol_sum = sum(v)
    return tp_vol / vol_sum if vol_sum > 0 else c[-1]

def vwap_slope(closes, highs, lows, volumes, n=20):
    """Pendiente del VWAP en las últimas n velas — detecta si está plano."""
    if len(closes) < n * 2:
        return 0.0
    vwap_now  = calc_vwap(closes, highs, lows, volumes, n)
    vwap_prev = calc_vwap(closes[:-5], highs[:-5], lows[:-5], volumes[:-5], n)
    return (vwap_now - vwap_prev) / vwap_prev * 100 if vwap_prev > 0 else 0.0

def detect_vwap_setup(closes, highs, lows, volumes, opens):
    """
    NEW-1: Detecta el setup VWAP Breakout + Retest
    
    Condiciones:
    1. VWAP NO está plano (hay tendencia)
    2. Hace N velas hubo una ruptura alcista del VWAP
    3. El precio retestó el VWAP (bajó a tocarlo o casi)
    4. Ahora el precio está rebotando por encima del VWAP
    
    Retorna: (setup_detected, vwap_value, setup_quality 0-100)
    """
    if len(closes) < VWAP_CANDLES + 10:
        return False, 0, 0

    vwap_val = calc_vwap(closes, highs, lows, volumes, VWAP_CANDLES)
    price    = closes[-1]

    # 1. Verificar que el VWAP NO está plano (NEW-3)
    slope = vwap_slope(closes, highs, lows, volumes, 20)
    if abs(slope) < VWAP_FLAT_PCT:
        return False, vwap_val, 0  # VWAP plano = no operar

    # El VWAP debe tener pendiente alcista para longs
    if slope < 0:
        return False, vwap_val, 0

    # 2. Precio actual por encima del VWAP (confirmación alcista)
    pct_above = (price - vwap_val) / vwap_val * 100
    if pct_above < 0:
        return False, vwap_val, 0

    # 3. Buscar patrón: ruptura + retest en las últimas 15 velas
    window = min(15, len(closes) - 5)
    broke_above  = False
    retested     = False
    now_bouncing = False

    for i in range(-window, -1):
        c_i = closes[i]
        l_i = lows[i]
        h_i = highs[i]
        o_i = opens[i] if opens else c_i

        # Ruptura: vela que cerró claramente por encima del VWAP
        if not broke_above:
            if c_i > vwap_val * (1 + VWAP_BREAK_PCT / 100):
                broke_above = True
            continue

        # Retest: después de romper, volvió cerca del VWAP
        if broke_above and not retested:
            touch_pct = abs(l_i - vwap_val) / vwap_val * 100
            if touch_pct < VWAP_RETEST_PCT:
                retested = True
            continue

        # Rebote: tras retest, vela verde cerrando por encima
        if broke_above and retested:
            if c_i > o_i and c_i > vwap_val:
                now_bouncing = True
                break

    if not (broke_above and retested and now_bouncing):
        return False, vwap_val, 0

    # Calidad del setup (0-100)
    quality = 60
    if slope > 0.3:    quality += 15   # VWAP con buena pendiente
    if pct_above < 0.5: quality += 15  # Recién rebotó (no se fue lejos)
    if slope > 0.6:    quality += 10   # Tendencia fuerte

    return True, vwap_val, min(quality, 100)

# ============================================================================
# APRENDIZAJE
# ============================================================================

class Learning:
    def __init__(self):
        self.history   = []
        self.sym_stats = defaultdict(lambda: {'w': 0, 'l': 0, 'pnl': 0.0})
        self.opt_score = MIN_SCORE
        self.blacklist = set()
        self.streak    = 0
        self.last10    = []

    def record(self, symbol, score, pnl, win):
        rec = {'ts': datetime.now().isoformat(), 'sym': symbol,
               'score': score, 'pnl': pnl, 'win': win}
        self.history.append(rec)
        self.last10.append(rec)
        if len(self.last10) > 10: self.last10.pop(0)
        s = self.sym_stats[symbol]
        if win: s['w'] += 1; self.streak = 0
        else:   s['l'] += 1; self.streak += 1
        s['pnl'] += pnl
        self._adjust()

    def _adjust(self):
        if len(self.history) < 10: return
        wr = sum(1 for t in self.last10 if t['win']) / len(self.last10)
        if wr < 0.4:
            self.opt_score = min(self.opt_score + 3, 85)
            log.warning(f"  [LEARN] WR bajo {wr:.0%} → score mín {self.opt_score}")
        elif wr > 0.65:
            self.opt_score = max(self.opt_score - 2, MIN_SCORE)
        for sym, s in self.sym_stats.items():
            tot = s['w'] + s['l']
            if tot >= 4 and s['w']/tot < 0.25 and s['pnl'] < -1.5:
                self.blacklist.add(sym)

    def ok(self, sym, score):
        if sym in self.blacklist:   return False, "blacklist"
        if score < self.opt_score:  return False, f"score {score:.0f}<{self.opt_score:.0f}"
        if self.streak >= MAX_STREAK: return False, f"streak -{self.streak}"
        return True, "ok"

    def save(self, fp='/tmp/bot_learn.json'):
        try:
            json.dump({'history': self.history[-100:],
                       'sym_stats': dict(self.sym_stats),
                       'opt_score': self.opt_score,
                       'blacklist': list(self.blacklist)},
                      open(fp, 'w'), indent=2)
        except: pass

    def load(self, fp='/tmp/bot_learn.json'):
        try:
            if os.path.exists(fp):
                d = json.load(open(fp))
                self.history   = d.get('history', [])
                self.sym_stats = defaultdict(
                    lambda: {'w':0,'l':0,'pnl':0.0}, d.get('sym_stats', {}))
                self.opt_score = d.get('opt_score', MIN_SCORE)
                self.blacklist = set(d.get('blacklist', []))
                log.info(f"  [LEARN] {len(self.history)} trades cargados")
        except: pass

# ============================================================================
# BOT PRINCIPAL v5.0
# ============================================================================

class LongBot:
    _opening = False

    def __init__(self):
        log.info("=" * 72)
        log.info("  BOT LONGS v5.0 — VWAP Breakout + Retest + EMA25")
        log.info(f"  Capital: ${POS_SIZE}x{LEVERAGE} | TP≥{TP_MIN}% SL≤{SL_MAX}%")
        log.info(f"  Score mín: {MIN_SCORE} | Símbolos: {MAX_SYMS} | Max: {MAX_TRADES} trades")
        log.info(f"  VWAP flat threshold: {VWAP_FLAT_PCT}% | Break: {VWAP_BREAK_PCT}%")
        log.info(f"  EMA25 exit: {'ON' if USE_EMA25_EXIT else 'OFF'}")
        log.info(f"  Circuit breaker: -${CB_USDT}/día")
        log.info("=" * 72)

        self.symbols       = []
        self.trades        = {}
        self._contracts    = {}
        self._cooldowns    = {}
        self._last_report  = datetime.now() - timedelta(hours=3)
        self._btc_1h       = 0.0
        self._btc_ok       = True
        self._mode         = 'hedge'
        self._daily_pnl    = 0.0
        self._daily_date   = datetime.utcnow().date()
        self._cb_active    = False
        self._cb_until     = None
        self.learn         = Learning()
        self.learn.load()
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0,'fees':0.0}

        if not self._connect():
            log.error("❌ Sin conexión BingX")
            sys.exit(1)

        self._detect_mode()
        self._load_contracts()
        self._refresh_symbols()
        self._recover()

        self._tg(
            f"<b>🤖 Bot LONGS v5.0 — VWAP Strategy</b>\n"
            f"Capital: ${POS_SIZE}x{LEVERAGE} | TP≥{TP_MIN}% SL≤{SL_MAX}%\n"
            f"Símbolos: {len(self.symbols)} | Max: {MAX_TRADES} trades\n"
            f"Setup: VWAP Breakout + Retest + EMA25\n"
            f"Circuit breaker: -${CB_USDT}/día\n"
            f"Posiciones recuperadas: {len(self.trades)}"
        )

    # ════════════════════════════════════════════════════════════════
    # SETUP
    # ════════════════════════════════════════════════════════════════

    def _connect(self) -> bool:
        global AUTO
        if not AUTO: return True
        if not API_KEY or not API_SECRET:
            log.error("❌ API keys no configuradas")
            AUTO = False; return False
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') == 0:
            b  = d.get('data', {})
            eq = b.get('equity', b.get('balance', '?'))
            log.info(f"✅ BingX conectado | ${eq} USDT")
            return True
        log.error(f"❌ [{d.get('code')}]: {d.get('msg')}")
        AUTO = False; return False

    def _detect_mode(self):
        try:
            d = api('GET', '/openApi/swap/v2/user/positions', {'symbol': 'BTC-USDT'})
            for p in (d.get('data') or []):
                side = str(p.get('positionSide', '')).upper()
                if side in ('LONG', 'SHORT'):
                    self._mode = 'hedge'
                    log.info("  Modo: HEDGE"); return
                if side == 'BOTH':
                    self._mode = 'oneway'
                    log.info("  Modo: ONE-WAY"); return
        except: pass
        log.info("  Modo: HEDGE (default)")

    def _load_contracts(self):
        d = pub('/openApi/swap/v2/quote/contracts')
        if d.get('code') == 0:
            for c in d.get('data', []):
                s = c.get('symbol', '')
                if s:
                    self._contracts[s] = {
                        'step':  float(c.get('tradeMinQuantity', 1)),
                        'prec':  int(c.get('quantityPrecision', 2)),
                        'ctval': float(c.get('contractSize', 1)),
                    }
            log.info(f"  Contratos: {len(self._contracts)}")

    def _refresh_symbols(self):
        d = pub('/openApi/swap/v2/quote/ticker')
        if d.get('code') != 0:
            self.symbols = self.symbols or ['BTC-USDT','ETH-USDT','SOL-USDT']
            return
        items = []
        for t in d.get('data', []):
            sym = t.get('symbol', '')
            if not sym.endswith('-USDT'): continue
            base = sym.replace('-USDT','').upper()
            if any(ex in base for ex in EXCLUDE): continue
            try:
                price    = float(t.get('lastPrice', 0))
                vol_usdt = float(t.get('volume', 0)) * price
                if vol_usdt >= MIN_VOL and price > 0:
                    items.append({'sym': sym, 'vol': vol_usdt})
            except: continue
        items.sort(key=lambda x: x['vol'], reverse=True)
        self.symbols = [x['sym'] for x in items[:MAX_SYMS]]
        log.info(f"  Símbolos: {len(self.symbols)} (vol>${MIN_VOL/1e6:.1f}M)")

    def _recover(self):
        if not AUTO: return
        d = api('GET', '/openApi/swap/v2/user/positions', {})
        n = 0
        for p in (d.get('data') or []):
            try:
                amt  = float(p.get('positionAmt', 0) or 0)
                side = str(p.get('positionSide', '')).upper()
                is_long = (side == 'LONG' and abs(amt) > 0) or (side == 'BOTH' and amt > 0)
                if not is_long: continue
                sym = p.get('symbol', '')
                if not sym or sym in self.trades: continue
                entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                if entry <= 0: continue
                self.trades[sym] = {
                    'entry': entry, 'qty': abs(amt), 'usdt': POS_SIZE,
                    'tp': entry * (1 + TP_MIN/100),
                    'sl': entry * (1 - SL_MAX/100),
                    'tp_pct': TP_MIN, 'sl_pct': SL_MAX,
                    'highest': entry, 'opened': datetime.now(),
                    'score': 0, 'pos_side': side,
                    'ema25': entry,
                }
                n += 1
                log.info(f"  ♻️  {sym} @ ${entry:.6f}")
            except: continue
        log.info(f"  Recuperadas: {n} posiciones")

    # ════════════════════════════════════════════════════════════════
    # MERCADO
    # ════════════════════════════════════════════════════════════════

    def _klines(self, symbol, interval='5m', limit=120):
        d = pub('/openApi/swap/v3/quote/klines',
                {'symbol': symbol, 'interval': interval, 'limit': limit})
        if d.get('code') == 0 and d.get('data'):
            kl = d['data']
            return ([float(k['close'])  for k in kl],
                    [float(k['high'])   for k in kl],
                    [float(k['low'])    for k in kl],
                    [float(k['volume']) for k in kl],
                    [float(k['open'])   for k in kl])
        return None, None, None, None, None

    def _ticker(self, sym):
        d = pub('/openApi/swap/v2/quote/ticker', {'symbol': sym})
        if d.get('code') == 0 and d.get('data'):
            t = d['data']
            return {'price':  float(t.get('lastPrice', 0)),
                    'change': float(t.get('priceChangePercent', 0))}
        return None

    def _update_btc(self):
        c, *_ = self._klines('BTC-USDT', '1h', 4)
        if c and len(c) >= 2:
            self._btc_1h = (c[-1] - c[-2]) / c[-2] * 100
            self._btc_ok = self._btc_1h >= -BTC_BLOCK
        else:
            self._btc_ok = True

    def _check_ltv(self):
        if not AUTO: return
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') != 0: return
        try:
            b      = d.get('data', {})
            equity = float(b.get('equity', 0) or b.get('balance', 0))
            margin = float(b.get('usedMargin', b.get('initialMargin', 0)) or 0)
            if equity <= 0: return
            ltv = margin / equity * 100
            if ltv >= LTV_WARN:
                log.warning(f"  ⚠️  LTV {ltv:.0f}% — cerrando posiciones")
                self._tg(f"<b>⚠️ LTV ALTO {ltv:.0f}%</b>\nCerrando todas las posiciones")
                for sym in list(self.trades.keys()):
                    tk = self._ticker(sym)
                    if tk: self.close_trade(sym, tk['price'], "LTV EMERGENCIA")
        except: pass

    # ════════════════════════════════════════════════════════════════
    # ANÁLISIS v5.0 — VWAP STRATEGY
    # ════════════════════════════════════════════════════════════════

    def analyze(self, symbol):
        if symbol in self.trades: return None
        if not self._cd_ok(symbol): return None
        if datetime.utcnow().hour in SKIP_HOURS: return None
        if not self._btc_ok: return None
        if self._cb_active: return None

        # ── Datos 5M (señal) ────────────────────────────────────
        c5, h5, l5, v5, o5 = self._klines(symbol, '5m', 120)
        if not c5 or len(c5) < 60: return None

        # ── Datos 1H (contexto NEW-4) ────────────────────────────
        c1h, h1h, l1h, v1h, o1h = self._klines(symbol, '1h', 50)

        tk = self._ticker(symbol)
        if not tk or tk['price'] <= 0: return None

        price     = tk['price']
        change_24 = tk['change']

        # ── VWAP Setup (NEW-1) ───────────────────────────────────
        vwap_setup, vwap_val, vwap_quality = detect_vwap_setup(c5, h5, l5, v5, o5)

        # ── Indicadores complementarios ──────────────────────────
        e25   = ema(c5, 25)   # EMA25 — salida profesional
        e9    = ema(c5, 9)
        e21   = ema(c5, 21)
        rsi_v = rsi(c5, 14)
        atr_v = atr_calc(h5, l5, c5, 14)
        atr_pct = atr_v / price * 100 if price > 0 else 0

        vol_avg = sum(v5[-6:-1]) / 5 if len(v5) >= 6 else 1
        vol_ratio = v5[-1] / vol_avg if vol_avg > 0 else 1

        # Contexto 1H (NEW-4)
        trend_1h = 0
        rsi_1h   = 50.0
        vwap_1h  = 0.0
        if c1h and len(c1h) >= 25:
            e9_1h  = ema(c1h, 9)
            e21_1h = ema(c1h, 21)
            rsi_1h = rsi(c1h, 14)
            vwap_1h= calc_vwap(c1h, h1h, l1h, v1h, 30)
            if e9_1h > e21_1h and c1h[-1] > vwap_1h:
                trend_1h = 1
            elif e9_1h < e21_1h:
                trend_1h = -1

        # ── FILTROS OBLIGATORIOS ─────────────────────────────────

        # 1. Tendencia 1H NO bajista fuerte (NEW-4)
        if trend_1h == -1 and rsi_v > 50:
            return None

        # 2. Volatilidad mínima
        if atr_pct < 0.15:
            return None

        # 3. RSI no sobrecomprado
        rsi_limit = 72 if trend_1h == 1 else 65
        if rsi_v > rsi_limit:
            return None

        # 4. Sin pumps extremos
        if change_24 > 15.0:
            return None

        # 5. Precio sobre EMA25 (tendencia intacta)
        if price < e25 * 0.995:
            return None

        # ── SCORING v5 ────────────────────────────────────────────
        score   = 0
        reasons = []

        # VWAP Setup (0-50) — señal principal NEW-1
        if vwap_setup:
            score += vwap_quality // 2  # 0-50 puntos
            reasons.append(f"VWAP_Setup({vwap_quality:.0f}%)")
        else:
            # Sin setup VWAP, requerir más confirmaciones
            score -= 20
            reasons.append("NoVWAP(-20)")

        # Precio sobre VWAP y EMA25 (0-15)
        if price > vwap_val and price > e25:
            score += 15; reasons.append("PriceOK(15)")
        elif price > vwap_val:
            score += 8;  reasons.append("OverVWAP(8)")

        # Contexto 1H NEW-4 (0-20)
        if trend_1h == 1:
            score += 20; reasons.append("1H↑(20)")
        elif trend_1h == -1:
            score -= 10; reasons.append("1H↓(-10)")

        # EMA alineación 5M (0-15)
        if e9 > e21 > e25:
            score += 15; reasons.append("EMA↑(15)")
        elif e9 > e21:
            score += 8;  reasons.append("EMA~(8)")

        # RSI (0-20)
        if rsi_v < 30:
            score += 20; reasons.append(f"RSI{rsi_v:.0f}(20)")
        elif rsi_v < 40:
            score += 14; reasons.append(f"RSI{rsi_v:.0f}(14)")
        elif rsi_v < 50:
            score += 7;  reasons.append(f"RSI{rsi_v:.0f}(7)")

        # Volumen en la ruptura (0-12)
        if vol_ratio >= 2.0:
            score += 12; reasons.append(f"Vol{vol_ratio:.1f}x(12)")
        elif vol_ratio >= 1.4:
            score += 7;  reasons.append(f"Vol{vol_ratio:.1f}x(7)")

        # BTC alcista (0-8)
        if self._btc_1h > 1.0:
            score += 8; reasons.append(f"BTC+{self._btc_1h:.1f}%(8)")
        elif self._btc_1h > 0.3:
            score += 4; reasons.append(f"BTC+{self._btc_1h:.1f}%(4)")

        # Caída 24h = oportunidad rebote (0-10)
        if change_24 < -5:
            score += 10; reasons.append(f"Drop{change_24:.0f}%(10)")
        elif change_24 < -2:
            score += 5;  reasons.append(f"Drop{change_24:.0f}%(5)")

        # RSI 1H sobrevendido = doble oportunidad (10)
        if rsi_1h < 40:
            score += 10; reasons.append(f"RSI1H{rsi_1h:.0f}(10)")

        # ATR suficiente (0-8)
        if atr_pct > 1.5:
            score += 8; reasons.append(f"ATR{atr_pct:.1f}%(8)")
        elif atr_pct > 0.6:
            score += 4; reasons.append(f"ATR{atr_pct:.1f}%(4)")

        # ── TP/SL dinámicos basados en ATR ──────────────────────
        sl_dyn = max(SL_MAX, atr_pct * ATR_SL_M)
        sl_dyn = min(sl_dyn, SL_MAX * 2.0)
        tp_dyn = max(TP_MIN, sl_dyn * 2.2, TP_MIN_FEE, atr_pct * ATR_TP_M)

        # ── Aprendizaje ──────────────────────────────────────────
        ok, reason = self.learn.ok(symbol, score)
        if not ok: return None

        if score >= self.learn.opt_score:
            return {
                'price': price, 'change': change_24,
                'score': score, 'score_min': self.learn.opt_score,
                'rsi': rsi_v, 'rsi_1h': rsi_1h,
                'vol': vol_ratio, 'atr_pct': atr_pct,
                'tp_pct': round(tp_dyn, 2),
                'sl_pct': round(sl_dyn, 2),
                'rr': round(tp_dyn / sl_dyn, 2),
                'vwap': vwap_val, 'vwap_setup': vwap_setup,
                'vwap_quality': vwap_quality,
                'ema25': e25, 'trend_1h': trend_1h,
                'reasons': ' | '.join(reasons),
            }
        return None

    # ════════════════════════════════════════════════════════════════
    # GESTIÓN POSICIONES
    # ════════════════════════════════════════════════════════════════

    def _set_lev(self, symbol):
        """FIX-03: solo LONG/SHORT."""
        for side in ('LONG', 'SHORT'):
            try:
                api('POST', '/openApi/swap/v2/trade/leverage',
                    {'symbol': symbol, 'side': side, 'leverage': str(LEVERAGE)})
                log.info(f"  ⚙️  {symbol} {side} {LEVERAGE}x ✅")
            except Exception as e:
                log.debug(f"  lev {side}: {e}")

    def _calc_qty(self, symbol, price):
        notional = max(POS_SIZE * LEVERAGE, MIN_TRADE)
        info     = self._contracts.get(symbol, {'step':1,'prec':2,'ctval':1})
        step     = max(float(info.get('step',1)), 1e-6)
        prec     = int(info.get('prec', 2))
        ctval    = max(float(info.get('ctval',1)), 1e-9)
        ppc      = price * ctval
        if ppc <= 0: return None, 0
        qty = math.ceil((notional/ppc)/step) * step
        qty = round(qty, prec)
        val = qty * ppc
        for _ in range(200):
            if val >= MIN_TRADE: break
            qty += step; qty = round(qty, prec); val = qty * ppc
        return (qty, round(val,4)) if val >= MIN_TRADE else (None, 0)

    def _order(self, sym, side, qty, otype='MARKET',
               price=None, stop_price=None, reduce=False):
        params = {'symbol': sym, 'side': side.upper(),
                  'type': otype, 'quantity': str(qty)}
        if self._mode == 'hedge':
            params['positionSide'] = 'LONG' if side.upper()=='BUY' else 'SHORT'
        if price:
            params['price'] = str(round(price, 8)); params['timeInForce'] = 'GTC'
        if stop_price:
            params['stopPrice'] = str(round(stop_price, 8))
        if reduce and self._mode != 'hedge':
            params['reduceOnly'] = 'true'
        return api('POST', '/openApi/swap/v2/trade/order', params)

    def _wait_fill(self, sym, oid, timeout=35):
        for _ in range(timeout):
            d = api('GET', '/openApi/swap/v2/trade/order',
                    {'symbol': sym, 'orderId': str(oid)})
            if d.get('code') == 0:
                o  = d.get('data', {}).get('order', {})
                st = o.get('status', '')
                if st == 'FILLED':
                    return float(o.get('executedQty',0)), float(o.get('avgPrice',0))
                if st in ('CANCELED','EXPIRED','REJECTED'):
                    return None, None
            time.sleep(1)
        return None, None

    def _confirm_pos(self, sym, timeout=15):
        for _ in range(timeout):
            d = api('GET', '/openApi/swap/v2/user/positions', {'symbol': sym})
            for p in (d.get('data') or []):
                amt  = float(p.get('positionAmt',0) or 0)
                side = str(p.get('positionSide','')).upper()
                if (side=='LONG' and abs(amt)>0) or (side=='BOTH' and amt>0):
                    return abs(amt), float(p.get('avgPrice') or p.get('entryPrice') or 0)
            time.sleep(1)
        return None, None

    def _cancel_open(self, sym):
        d = api('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': sym})
        for o in (d.get('data',{}).get('orders') or []):
            oid = o.get('orderId')
            if oid:
                api('DELETE', '/openApi/swap/v2/trade/order',
                    {'symbol': sym, 'orderId': str(oid)})

    def _place_tp_sl(self, sym, qty, tp, sl):
        tp_ok = sl_ok = False
        d = self._order(sym, 'SELL', qty, 'TAKE_PROFIT_MARKET',
                        stop_price=tp, reduce=True)
        tp_ok = d.get('code') == 0
        log.info(f"  {'✅' if tp_ok else '❌'} TP @ ${tp:.6f}")
        time.sleep(0.3)
        d = self._order(sym, 'SELL', qty, 'STOP_MARKET',
                        stop_price=sl, reduce=True)
        sl_ok = d.get('code') == 0
        if not sl_ok:
            d = self._order(sym, 'SELL', qty, 'STOP',
                            price=sl*0.999, stop_price=sl, reduce=True)
            sl_ok = d.get('code') == 0
        log.info(f"  {'✅' if sl_ok else '❌'} SL @ ${sl:.6f}")
        return tp_ok, sl_ok

    def open_trade(self, sym, sig):
        if not AUTO or sym in self.trades: return False
        if LongBot._opening or len(self.trades) >= MAX_TRADES: return False
        LongBot._opening = True
        try:
            return self._open(sym, sig)
        finally:
            LongBot._opening = False

    def _open(self, sym, sig):
        price = sig['price']
        log.info(f"\n  🎯 LONG {sym} | Score:{sig['score']:.0f}/{sig['score_min']:.0f} "
                 f"| RR:{sig['rr']:.2f}:1 | VWAP:{sig['vwap_setup']}")
        log.info(f"  {sig['reasons']}")

        self._set_lev(sym)
        time.sleep(0.2)

        qty, notional = self._calc_qty(sym, price)
        if not qty: return False

        limit_p = round(price * (1 - 0.08/100), 8)
        d = self._order(sym, 'BUY', qty, 'LIMIT', price=limit_p)
        if d.get('code') != 0:
            log.error(f"  ❌ LIMIT: {d.get('msg')}")
            return False

        oid = d.get('data', {}).get('orderId')
        filled_qty, fill_price = self._wait_fill(sym, oid, 30)

        if not filled_qty:
            log.warning("  ⚠️  LIMIT sin fill → MARKET")
            self._cancel_open(sym)
            time.sleep(0.5)
            d = self._order(sym, 'BUY', qty, 'MARKET')
            if d.get('code') != 0:
                log.error(f"  ❌ MARKET: {d.get('msg')}")
                return False
            filled_qty, fill_price = self._confirm_pos(sym, 12)
            if not filled_qty: return False

        tp = fill_price * (1 + sig['tp_pct']/100)
        sl = fill_price * (1 - sig['sl_pct']/100)
        tp_ok, sl_ok = self._place_tp_sl(sym, filled_qty, tp, sl)

        if not sl_ok:
            time.sleep(2); _, sl_ok = self._place_tp_sl(sym, filled_qty, tp, sl)
        if not sl_ok:
            log.error("  ❌ SL crítico — cerrando")
            self._order(sym, 'SELL', filled_qty, 'MARKET', reduce=True)
            return False

        self.trades[sym] = {
            'entry': fill_price, 'qty': filled_qty, 'usdt': POS_SIZE,
            'tp': tp, 'sl': sl,
            'tp_pct': sig['tp_pct'], 'sl_pct': sig['sl_pct'],
            'highest': fill_price, 'opened': datetime.now(),
            'score': sig['score'], 'ema25': sig['ema25'],
            'vwap': sig['vwap'],
        }
        self.stats['exec']  += 1
        self.stats['fees']  += notional * FEE

        setup_txt = "📐 VWAP Breakout+Retest ✅" if sig['vwap_setup'] else "📊 Sin setup VWAP"
        self._tg(
            f"<b>🟢 LONG ABIERTO</b> — <b>{sym}</b>\n"
            f"Score: {sig['score']:.0f}/{sig['score_min']:.0f} | RR: {sig['rr']:.2f}:1\n"
            f"{setup_txt}\n"
            f"Entrada: ${fill_price:.6f}\n"
            f"VWAP: ${sig['vwap']:.6f} | EMA25: ${sig['ema25']:.6f}\n"
            f"{'✅' if tp_ok else '❌'} TP: ${tp:.6f} (+{sig['tp_pct']:.2f}%)\n"
            f"{'✅' if sl_ok else '❌'} SL: ${sl:.6f} (-{sig['sl_pct']:.2f}%)\n"
            f"1H: {'🟢' if sig['trend_1h']==1 else '⚪' if sig['trend_1h']==0 else '🔴'} | "
            f"BTC: {self._btc_1h:+.2f}%"
        )
        return True

    def close_trade(self, sym, exit_price, reason):
        if sym not in self.trades: return False
        t = self.trades[sym]
        self._order(sym, 'SELL', t['qty'], 'MARKET', reduce=True)

        chg   = (exit_price - t['entry']) / t['entry']
        gross = t['usdt'] * LEVERAGE * chg
        fees  = t['usdt'] * LEVERAGE * FEE * 2
        net   = gross - fees
        win   = net > 0

        self.stats['closed'] += 1
        self.stats['pnl']    += net
        self.stats['fees']   += fees
        self._daily_pnl      += net
        if win: self.stats['wins']   += 1
        else:   self.stats['losses'] += 1

        self.learn.record(sym, t['score'], net, win)

        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        mins  = int((datetime.now() - t['opened']).total_seconds() / 60)
        emoji = "✅" if win else "❌"
        pct   = net / t['usdt'] * 100

        log.info(f"  {emoji} {reason} | ${net:+.4f} ({pct:+.1f}%) | {mins}min | WR:{wr:.0f}%")
        self._set_cd(sym, 'TP' if 'PROFIT' in reason else 'SL')
        self._tg(
            f"<b>{emoji} LONG CERRADO — {reason}</b>\n"
            f"<b>{sym}</b> | {mins}min\n"
            f"${t['entry']:.6f} → ${exit_price:.6f}\n"
            f"PnL: ${net:+.4f} ({pct:+.1f}%)\n"
            f"<b>Total: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}%</b>"
        )
        if self.stats['closed'] % 5 == 0: self.learn.save()
        del self.trades[sym]
        return True

    # ════════════════════════════════════════════════════════════════
    # MONITOR
    # ════════════════════════════════════════════════════════════════

    async def monitor(self):
        for sym in list(self.trades.keys()):
            try:
                t  = self.trades[sym]
                tk = self._ticker(sym)
                if not tk: continue
                cur = tk['price']
                pct = (cur - t['entry']) / t['entry'] * 100

                # Actualizar EMA25 dinámicamente
                c5, h5, l5, v5, o5 = self._klines(sym, '5m', 30)
                if c5:
                    t['ema25'] = ema(c5, 25)

                # NEW-2: Salida por EMA25
                if USE_EMA25_EXIT and pct > 0.5:
                    if cur < t['ema25'] and c5 and c5[-1] < t['ema25']:
                        self.close_trade(sym, cur, "EMA25 CRUCE")
                        continue

                # Trailing stop
                if cur > t['highest']:
                    t['highest'] = cur
                    if pct >= 2.5:
                        locked = t['entry'] + (cur - t['entry']) * 0.55
                        if locked > t['sl']:
                            t['sl'] = locked
                            log.info(f"  📈 Trail {sym}: SL→${locked:.6f}")

                if cur >= t['tp']:
                    self.close_trade(sym, cur, "TAKE PROFIT")
                elif cur <= t['sl']:
                    self.close_trade(sym, cur, "STOP LOSS")

            except Exception as e:
                log.debug(f"monitor {sym}: {e}")

    # ════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ════════════════════════════════════════════════════════════════

    def _cd_ok(self, sym):
        ts = self._cooldowns.get(sym)
        if not ts: return True
        resume, _ = ts if isinstance(ts, tuple) else (ts, 'TP')
        if time.time() >= resume:
            del self._cooldowns[sym]; return True
        return False

    def _set_cd(self, sym, reason='TP'):
        mins = CD_TP if reason == 'TP' else CD_SL
        self._cooldowns[sym] = (time.time() + mins*60, reason)

    def _daily_reset(self):
        today = datetime.utcnow().date()
        if today != self._daily_date:
            self._daily_pnl  = 0.0
            self._daily_date = today
            self._cb_active  = False   # FIX-01: reset al nuevo día
            self._cb_until   = None
            self.learn.streak= 0
            log.info("📅 Nuevo día")

    def _circuit_check(self) -> bool:
        """FIX-01: no se reactiva en bucle."""
        self._daily_reset()
        if self._cb_active:
            if self._cb_until and datetime.utcnow() > self._cb_until:
                self._cb_active = False
                self._daily_pnl = 0.0   # ← reset para no re-activar
                log.info("  🔓 Circuit breaker OFF")
                self._tg("<b>🔓 Circuit breaker OFF</b> — trading reanudado")
            return self._cb_active
        if self._daily_pnl < -CB_USDT:
            self._cb_active = True
            self._cb_until  = datetime.utcnow() + timedelta(hours=CB_HOURS)
            log.warning(f"  🔒 CIRCUIT BREAKER | ${self._daily_pnl:.3f}")
            self._tg(
                f"<b>🔒 CIRCUIT BREAKER</b>\n"
                f"Pérdida: ${self._daily_pnl:.3f} | Umbral: -${CB_USDT}\n"
                f"Pausa {CB_HOURS}h → {self._cb_until.strftime('%H:%M')} UTC"
            )
        return self._cb_active

    def _report(self):
        if datetime.now() - self._last_report < timedelta(hours=2): return
        self._last_report = datetime.now()
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        pos   = ""
        for sym, t in self.trades.items():
            tk  = self._ticker(sym)
            cur = tk['price'] if tk else t['entry']
            pct = (cur - t['entry']) / t['entry'] * 100
            pos += f"  📌 {sym}: {pct:+.2f}% | EMA25:${t['ema25']:.4f}\n"
        self._tg(
            f"<b>📊 Reporte LONGS v5.0</b>\n"
            f"PnL: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}% | {total} trades\n"
            f"Día: ${self._daily_pnl:+.4f} (límite -${CB_USDT})\n"
            f"Fees: ${self.stats['fees']:.4f}\n"
            f"Abiertos: {len(self.trades)}/{MAX_TRADES} | BTC: {self._btc_1h:+.2f}%\n"
            f"Circuit: {'🔒' if self._cb_active else '🔓'} | "
            f"Score mín: {self.learn.opt_score:.0f}\n"
            + (pos if pos else "  Sin posiciones\n")
        )

    def _tg(self, msg):
        try:
            if TG_TOKEN and TG_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                    timeout=6)
        except: pass

    # ════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL
    # ════════════════════════════════════════════════════════════════

    async def run(self):
        log.info("\n🚀 Bot LONGS v5.0 — VWAP Strategy arrancado\n")
        iteration       = 0
        last_sym_refr   = 0
        last_ltv_check  = 0

        while True:
            try:
                iteration += 1
                self._daily_reset()

                if time.time() - last_sym_refr > 600:
                    self._refresh_symbols()
                    last_sym_refr = time.time()

                if time.time() - last_ltv_check > 300:
                    self._check_ltv()
                    last_ltv_check = time.time()

                self._update_btc()

                if self._circuit_check():
                    log.warning("  🔒 Circuit breaker activo")
                    await asyncio.sleep(INTERVAL)
                    continue

                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0

                log.info(f"\n{'='*72}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"Abiertos:{len(self.trades)}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.4f} | WR:{wr:.0f}%")
                log.info(f"  BTC:{self._btc_1h:+.2f}% {'🟢' if self._btc_ok else '🔴'} | "
                         f"Score mín:{self.learn.opt_score:.0f} | "
                         f"Día:${self._daily_pnl:+.4f}")
                log.info(f"{'='*72}\n")

                await self.monitor()
                self._report()

                if len(self.trades) < MAX_TRADES:
                    found = 0
                    log.info(f"  Escaneando {len(self.symbols)} símbolos...")
                    for i, sym in enumerate(self.symbols):
                        if len(self.trades) >= MAX_TRADES: break
                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            setup_icon = "📐" if sig['vwap_setup'] else "📊"
                            log.info(
                                f"  💡 {setup_icon} {sym} | "
                                f"Score:{sig['score']:.0f} | "
                                f"RSI:{sig['rsi']:.0f} | RR:{sig['rr']:.2f}:1 | "
                                f"VWAP quality:{sig['vwap_quality']:.0f}"
                            )
                            if self.open_trade(sym, sig):
                                await asyncio.sleep(3)
                        if (i+1) % 15 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)}")
                        await asyncio.sleep(0.12)
                    log.info(f"  ✅ Scan: {found} señales")
                else:
                    log.info("  ⏸️  Max trades — monitoreando")

                log.info(f"\n  ⏭️  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)

            except KeyboardInterrupt:
                log.info("⏹️  Detenido")
                break
            except Exception as e:
                log.error(f"❌ Error #{iteration}: {e}", exc_info=True)
                await asyncio.sleep(20)

        self.learn.save()

# ============================================================================
# ENTRY POINT
# ============================================================================

async def main():
    bot = LongBot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Bot terminado")
