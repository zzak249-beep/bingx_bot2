#!/usr/bin/env python3
"""
BOT LONGS RENTABLE v3.0 — Señales reales + Filtros equilibrados
FIXES vs v2.0:
  FIX-1  MIN_SCORE bajado a 65 (era 95 — imposible de alcanzar)
  FIX-2  Filtro BTC suavizado: bloquea si cae >1.5% (era >0.5% alcista obligatorio)
  FIX-3  EMA filter flexible: permite entradas en pull-backs
  FIX-4  MAX_SYMBOLS aumentado a 50 (era 30)
  FIX-5  MAX_TRADES aumentado a 3 (era 1)
  FIX-6  Score system rebalanceado para ser alcanzable
  FIX-7  set_leverage: solo LONG/SHORT (BOTH causaba error 109400)
  FIX-8  Análisis de 1h + 5m para contexto mayor
  FIX-9  Modo señales mejorado: muestra candidatos aunque no abra trade
  FIX-10 Cooldown reducido: 3min TP / 30min SL (era 5/60)
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re, json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from collections import defaultdict

def clean(key, default, typ='str'):
    v = os.getenv(key, str(default)).strip().strip('"').strip("'").strip()
    if typ in ('int', 'float'):
        v = v.replace(',', '.')
        m = re.match(r'^-?\d+\.?\d*', v)
        v = m.group(0) if m else str(default)
    if typ == 'int':   return int(float(v))
    if typ == 'float': return float(v)
    if typ == 'bool':  return v.lower() == 'true'
    return v

BINGX_API_KEY    = os.getenv('BINGX_API_KEY',    '').strip().strip('"').strip("'")
BINGX_API_SECRET = os.getenv('BINGX_API_SECRET', '').strip().strip('"').strip("'")
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT    = os.getenv('TELEGRAM_CHAT_ID',   '')

# ============================================================================
# CONFIGURACIÓN v3.0 — EQUILIBRADA PARA GENERAR SEÑALES
# ============================================================================

AUTO_TRADING  = clean('AUTO_TRADING_ENABLED',  'true',  'bool')
POSITION_SIZE = clean('MAX_POSITION_SIZE',      '10',   'float')
MIN_TRADE     = clean('MIN_TRADE_USDT',         '10',   'float')

# TP/SL con RR 2:1
TP_PCT        = clean('TAKE_PROFIT_PCT',         '5.0', 'float')
SL_PCT        = clean('STOP_LOSS_PCT',           '2.5', 'float')
TRAILING      = clean('TRAILING_STOP_ENABLED', 'false', 'bool')
TRAILING_START= clean('TRAILING_START_PCT',     '3.0',  'float')
TRAILING_LOCK = clean('TRAILING_LOCK_PCT',      '60',   'float')

# Leverage conservador
_lev_env   = clean('LEVERAGE', '2', 'int')
LEVERAGE   = min(_lev_env, 3)

# Control de operaciones — FIX-4, FIX-5
INTERVAL      = clean('CHECK_INTERVAL',          '120', 'int')
MIN_VOLUME    = clean('MIN_VOLUME_24H',       '500000', 'float')  # Bajado para más opciones
MAX_SYMBOLS   = clean('MAX_SYMBOLS_TO_ANALYZE',  '50',  'int')   # FIX-4: era 30
MIN_SCORE     = clean('MIN_SCORE',               '65',  'float') # FIX-1: era 95
MAX_TRADES    = clean('MAX_OPEN_TRADES',          '3',  'int')   # FIX-5: era 1

USE_LIMIT_ORDERS = True
LIMIT_OFFSET_PCT = 0.08

# FIX-2: Filtro BTC suavizado
BTC_BEAR_BLOCK_PCT = clean('BTC_BEAR_BLOCK_PCT', '1.5',  'float')  # Bloquea si BTC cae >1.5%
BTC_MIN_TREND_PCT  = clean('BTC_MIN_TREND_PCT',  '-0.5', 'float')  # Permite hasta -0.5%

# Circuit breakers
MAX_LOSS_PCT         = clean('MAX_LOSS_PCT',           '4.0',  'float')
CIRCUIT_BREAKER_USDT = clean('CIRCUIT_BREAKER_USDT',   '2.0',  'float')
MAX_LOSING_STREAK    = clean('MAX_LOSING_STREAK',        '4',  'int')

# FIX-10: Cooldowns reducidos
COOLDOWN_MIN_TP  = clean('COOLDOWN_AFTER_TP_MIN',   '3',   'int')
COOLDOWN_MIN_SL  = clean('COOLDOWN_AFTER_SL_MIN',  '30',   'int')

REGIME_FILTER = clean('REGIME_FILTER',  'true', 'bool')
LEARNING_ENABLED = clean('LEARNING_ENABLED', 'true', 'bool')

# Horas a evitar (UTC)
SKIP_HOURS_UTC = {2, 3}  # Solo 2 horas de bajo volumen (antes era 4)

MIN_TRADES_LEARN  = 10
SCORE_ADJUST_STEP = 2
FORCE_MIN_USDT    = max(MIN_TRADE, 10.0)
BASE_URL          = "https://open-api.bingx.com"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ============================================================================
# COMISIONES
# ============================================================================

COMISION_MAKER  = 0.0002
COMISION_ACTUAL = COMISION_MAKER
TP_MIN_RENTABLE = round((2 * COMISION_ACTUAL * LEVERAGE + 0.003) * 100, 3)
log.info(f"TP mínimo rentable: {TP_MIN_RENTABLE}%")

# ============================================================================
# API
# ============================================================================

def bingx_request(method, endpoint, params, retries=3):
    for attempt in range(retries + 1):
        try:
            p = dict(params)
            p['timestamp'] = int(time.time() * 1000)
            qs  = urlencode(sorted(p.items()))
            sig = hmac.new(BINGX_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
            url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
            hdr = {'X-BX-APIKEY': BINGX_API_KEY, 'Content-Type': 'application/x-www-form-urlencoded'}
            if method == 'GET':
                r = requests.get(url, headers=hdr, timeout=15)
            elif method == 'POST':
                r = requests.post(url, headers=hdr, timeout=15)
            else:
                r = requests.delete(url, headers=hdr, timeout=15)
            return r
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                raise

# ============================================================================
# INDICADORES
# ============================================================================

def calc_ema(prices, period):
    if not prices or len(prices) < 2:
        return prices[0] if prices else 0
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0
    trs = []
    for i in range(1, min(len(closes), period + 1)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0

def vol_spike(volumes):
    if len(volumes) < 5:
        return 1.0
    avg = sum(volumes[:-1]) / len(volumes[:-1])
    return volumes[-1] / avg if avg > 0 else 1.0

# ============================================================================
# SISTEMA DE APRENDIZAJE
# ============================================================================

class TradeLearningSystem:
    def __init__(self):
        self.trades_history   = []
        self.symbol_stats     = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0})
        self.score_performance= defaultdict(lambda: {'wins': 0, 'losses': 0})
        self.optimal_score    = MIN_SCORE
        self.blacklist        = set()
        self.losing_streak    = 0
        self.last_trades      = []

    def record_trade(self, symbol, entry_data, exit_data, pnl, win):
        record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'score': entry_data.get('score', 0),
            'rsi': entry_data.get('rsi', 0),
            'entry_price': entry_data.get('price', 0),
            'pnl': pnl, 'win': win,
        }
        self.trades_history.append(record)
        self.last_trades.append(record)
        if len(self.last_trades) > 10:
            self.last_trades.pop(0)

        s = self.symbol_stats[symbol]
        if win:
            s['wins'] += 1
            self.losing_streak = 0
        else:
            s['losses'] += 1
            self.losing_streak += 1
        s['total_pnl'] += pnl
        self._auto_adjust()

    def _auto_adjust(self):
        if len(self.trades_history) < MIN_TRADES_LEARN:
            return
        recent_wins = sum(1 for t in self.last_trades if t['win'])
        recent_wr   = recent_wins / len(self.last_trades) if self.last_trades else 0
        if recent_wr < 0.4 and len(self.last_trades) >= 10:
            self.optimal_score = min(self.optimal_score + SCORE_ADJUST_STEP, 90)
            log.warning(f"  [LEARN] WR bajo ({recent_wr:.1%}) → Score: {self.optimal_score}")
        elif recent_wr > 0.65 and len(self.last_trades) >= 10:
            self.optimal_score = max(self.optimal_score - SCORE_ADJUST_STEP, MIN_SCORE)
            log.info(f"  [LEARN] WR bueno ({recent_wr:.1%}) → Score: {self.optimal_score}")
        for symbol, stats in self.symbol_stats.items():
            total = stats['wins'] + stats['losses']
            if total >= 4 and stats['wins'] / total < 0.25 and stats['total_pnl'] < -1.0:
                self.blacklist.add(symbol)

    def should_trade(self, symbol, score):
        if symbol in self.blacklist:
            return False, "Blacklist"
        if score < self.optimal_score:
            return False, f"Score {score:.0f} < {self.optimal_score:.0f}"
        if self.losing_streak >= MAX_LOSING_STREAK:
            return False, f"Racha -{self.losing_streak}"
        return True, "OK"

    def save_to_file(self, fp='/tmp/trade_history.json'):
        try:
            data = {
                'trades': self.trades_history[-100:],
                'symbol_stats': dict(self.symbol_stats),
                'optimal_score': self.optimal_score,
                'blacklist': list(self.blacklist),
            }
            with open(fp, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.debug(f"[LEARN] save error: {e}")

    def load_from_file(self, fp='/tmp/trade_history.json'):
        try:
            if os.path.exists(fp):
                with open(fp) as f:
                    data = json.load(f)
                self.trades_history = data.get('trades', [])
                self.symbol_stats   = defaultdict(
                    lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0},
                    data.get('symbol_stats', {})
                )
                self.optimal_score = data.get('optimal_score', MIN_SCORE)
                self.blacklist     = set(data.get('blacklist', []))
                log.info(f"  [LEARN] {len(self.trades_history)} trades cargados")
        except Exception as e:
            log.debug(f"[LEARN] load error: {e}")

# ============================================================================
# BOT PRINCIPAL v3.0
# ============================================================================

class OptimizedLongBot:

    _abriendo = False

    def __init__(self):
        log.info("=" * 80)
        log.info("  BOT LONGS v3.0 — Señales reales + Filtros equilibrados")
        log.info("=" * 80)
        log.info(f"  Modo:        {'AUTO' if AUTO_TRADING else 'SEÑALES'}")
        log.info(f"  Capital:     ${POSITION_SIZE} x{LEVERAGE} = ${POSITION_SIZE*LEVERAGE:.0f} notional")
        log.info(f"  TP/SL:       {TP_PCT}% / {SL_PCT}% (RR {TP_PCT/SL_PCT:.2f}:1)")
        log.info(f"  Score mín:   {MIN_SCORE} (FIX-1: era 95)")
        log.info(f"  Símbolos:    {MAX_SYMBOLS} (FIX-4: era 30)")
        log.info(f"  Max trades:  {MAX_TRADES} (FIX-5: era 1)")
        log.info(f"  BTC bloquea: caída > -{BTC_BEAR_BLOCK_PCT}% (FIX-2: era +0.3% obligatorio)")
        log.info(f"  Aprendizaje: {'ON' if LEARNING_ENABLED else 'OFF'}")
        log.info("=" * 80)

        self.symbols       = []
        self.open_trades   = {}
        self._contracts    = {}
        self._cooldowns    = {}
        self._last_report  = datetime.now()
        self._btc_1h       = 0.0
        self._btc_ok       = True
        self._daily_pnl    = 0.0
        self._daily_reset  = datetime.utcnow().date()
        self._circuit_open = False
        self._circuit_until= None

        self.learning = TradeLearningSystem() if LEARNING_ENABLED else None
        if self.learning:
            self.learning.load_from_file()

        self.stats = {'exec': 0, 'closed': 0, 'wins': 0, 'losses': 0,
                      'pnl': 0.0, 'fees_paid': 0.0}

        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._recover_positions()

        self._tg(
            f"<b>🤖 Bot LONGS v3.0</b>\n"
            f"Capital: ${POSITION_SIZE}x{LEVERAGE} | TP:{TP_PCT}% SL:{SL_PCT}%\n"
            f"Score mín:{MIN_SCORE} | Símbolos:{len(self.symbols)} | Max:{MAX_TRADES} trades\n"
            f"BTC bloquea si cae >{BTC_BEAR_BLOCK_PCT}%\n"
            f"Posiciones recuperadas: {len(self.open_trades)}"
        )

    # ========================================================================
    # SETUP
    # ========================================================================

    def _verify(self):
        global AUTO_TRADING
        if not AUTO_TRADING:
            return
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            AUTO_TRADING = False
            log.error("❌ Credenciales faltantes")
            return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                b = d.get('data', {})
                equity = b.get('equity', b.get('balance', '?'))
                log.info(f"✅ BingX conectado | Balance: ${equity} USDT")
            else:
                log.error(f"❌ BingX [{d.get('code')}]: {d.get('msg')}")
                AUTO_TRADING = False
        except Exception as e:
            log.error(f"❌ Error API: {e}")
            AUTO_TRADING = False

    def _load_contracts(self):
        try:
            r = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/contracts", timeout=15)
            d = r.json()
            if d.get('code') == 0:
                for c in d.get('data', []):
                    sym = c.get('symbol', '')
                    if sym:
                        self._contracts[sym] = {
                            'step':  float(c.get('tradeMinQuantity', 1)),
                            'prec':  int(c.get('quantityPrecision', 2)),
                            'ctval': float(c.get('contractSize', 1)),
                        }
                log.info(f"📋 Contratos: {len(self._contracts)}")
        except Exception as e:
            log.warning(f"⚠️  Contratos: {e}")

    def _get_symbols(self):
        EXCLUDE = [
            'DOW','JONES','SP500','SPX','SPY','QQQ','NASDAQ','RUSSELL',
            'DAX','FTSE','CAC','NIKKEI','HANG','BOVESPA','IBEX',
            'GOLD','SILVER','XAU','XAG','PAXG','XAUT',
            'OIL','BRENT','WTI','CRUDE','GAS','NATURAL',
            'PLATINUM','PALLADIUM','COPPER','NICKEL','ZINC',
            'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN','MSTR',
            'EUR','GBP','JPY','CHF','AUD','CAD','NZD',
            'WHEAT','CORN','SUGAR','COFFEE','COTTON',
        ]
        try:
            r = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker", timeout=15)
            d = r.json()
            if d.get('code') == 0:
                candidates = []
                for t in d.get('data', []):
                    sym = t.get('symbol', '')
                    if not sym.endswith('-USDT'):
                        continue
                    base = sym.replace('-USDT', '').upper()
                    if any(kw in base for kw in EXCLUDE):
                        continue
                    try:
                        price    = float(t.get('lastPrice', 0))
                        vol_usdt = float(t.get('volume', 0)) * price
                        if vol_usdt >= MIN_VOLUME and price > 0:
                            candidates.append({'symbol': sym, 'volume': vol_usdt})
                    except:
                        continue
                candidates.sort(key=lambda x: x['volume'], reverse=True)
                self.symbols = [c['symbol'] for c in candidates[:MAX_SYMBOLS]]
                log.info(f"🎯 Símbolos: {len(self.symbols)} (vol>${MIN_VOLUME/1e6:.1f}M)")
                return
        except Exception as e:
            log.warning(f"⚠️  Símbolos: {e}")
        self.symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT']

    def _recover_positions(self):
        if not AUTO_TRADING:
            return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0:
                return
            recovered = 0
            for p in d.get('data', []):
                amt  = float(p.get('positionAmt', 0) or 0)
                side = str(p.get('positionSide', '')).upper()
                is_long = (side == 'LONG' and abs(amt) > 0) or (side == 'BOTH' and amt > 0)
                if not is_long:
                    continue
                sym = p.get('symbol', '')
                if not sym or sym in self.open_trades:
                    continue
                entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                if entry <= 0:
                    tk = self._ticker(sym)
                    entry = tk['price'] if tk else 0
                if entry <= 0:
                    continue
                self.open_trades[sym] = {
                    'entry': entry, 'qty_c': abs(amt),
                    'usdt_qty': POSITION_SIZE,
                    'tp': entry * (1 + TP_PCT / 100),
                    'sl': entry * (1 - SL_PCT / 100),
                    'tp_pct': TP_PCT, 'sl_pct': SL_PCT,
                    'highest': entry, 'order_id': 'RECOVERED',
                    'opened_at': datetime.now(), 'score': 0, 'entry_data': {},
                }
                recovered += 1
                log.info(f"  ♻️  {sym} @ ${entry:.6f}")
            log.info(f"✅ Recuperadas {recovered} posiciones LONG")
        except Exception as e:
            log.error(f"❌ Recover: {e}")

    # ========================================================================
    # DATOS DE MERCADO
    # ========================================================================

    def _klines(self, symbol, interval='5m', limit=80):
        try:
            r = requests.get(
                f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol': symbol, 'interval': interval, 'limit': limit},
                timeout=10
            )
            d = r.json()
            if d.get('code') == 0 and d.get('data'):
                klines  = d['data']
                closes  = [float(k['close'])  for k in klines]
                highs   = [float(k['high'])   for k in klines]
                lows    = [float(k['low'])    for k in klines]
                volumes = [float(k['volume']) for k in klines]
                opens   = [float(k['open'])   for k in klines]
                return closes, highs, lows, volumes, opens
        except:
            pass
        return None, None, None, None, None

    def _ticker(self, symbol):
        try:
            r = requests.get(
                f"{BASE_URL}/openApi/swap/v2/quote/ticker",
                params={'symbol': symbol}, timeout=8
            )
            d = r.json()
            if d.get('code') == 0 and d.get('data'):
                t = d['data']
                return {
                    'price':  float(t.get('lastPrice', 0)),
                    'change': float(t.get('priceChangePercent', 0)),
                }
        except:
            pass
        return None

    def _update_btc_trend(self):
        try:
            closes, *_ = self._klines('BTC-USDT', '1h', 4)
            if closes and len(closes) >= 2:
                self._btc_1h = (closes[-1] - closes[-2]) / closes[-2] * 100
                # FIX-2: solo bloquear si cae fuerte
                self._btc_ok = self._btc_1h >= -BTC_BEAR_BLOCK_PCT
            else:
                self._btc_ok = True
        except:
            self._btc_ok = True

    # ========================================================================
    # ANÁLISIS v3.0 — FILTROS EQUILIBRADOS
    # ========================================================================

    def analyze(self, symbol):
        """
        FIX-3: EMA filter flexible
        FIX-6: Score system alcanzable
        FIX-8: Contexto 1h + señal 5m
        """
        if symbol in self.open_trades:
            return None
        if not self._cooldown_ok(symbol):
            return None
        if not self._hora_ok():
            return None

        # FIX-2: BTC filter suavizado
        if not self._btc_ok:
            return None

        if self._check_circuit_breaker():
            return None

        # Velas 5m para señal
        closes5, highs5, lows5, volumes5, opens5 = self._klines(symbol, '5m', 80)
        if not closes5 or len(closes5) < 30:
            return None

        # Velas 1h para contexto (FIX-8)
        closes1h, highs1h, lows1h, *_ = self._klines(symbol, '1h', 30)

        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0:
            return None

        price     = ticker['price']
        change_24h= ticker['change']

        # ── Indicadores 5m ──────────────────────────────────────
        ema9  = calc_ema(closes5, 9)
        ema21 = calc_ema(closes5, 21)
        ema50 = calc_ema(closes5, min(50, len(closes5)))
        rsi   = calc_rsi(closes5, 14)
        vol_m = vol_spike(volumes5)
        atr   = calc_atr(highs5, lows5, closes5, 14)
        atr_pct = (atr / price * 100) if price > 0 else 0

        # Contexto de precio
        min_20   = min(closes5[-20:]) if len(closes5) >= 20 else price
        max_20   = max(closes5[-20:]) if len(closes5) >= 20 else price
        near_low = price <= min_20 * 1.02
        rng_pct  = (max_20 - min_20) / min_20 * 100 if min_20 > 0 else 0

        # Momentum
        momentum_5 = (closes5[-1] - closes5[-6]) / closes5[-6] * 100 if len(closes5) >= 6 else 0
        momentum_15= (closes5[-1] - closes5[-16]) / closes5[-16] * 100 if len(closes5) >= 16 else 0

        # Velas verdes
        green = 0
        if opens5 and len(opens5) >= 5:
            green = sum(1 for i in range(-5, 0) if closes5[i] > opens5[i])

        # Contexto 1h (FIX-8)
        trend_1h = 0
        if closes1h and len(closes1h) >= 10:
            ema9_1h  = calc_ema(closes1h, 9)
            ema21_1h = calc_ema(closes1h, 21)
            if ema9_1h > ema21_1h:
                trend_1h = 1   # alcista en 1h
            elif ema9_1h < ema21_1h:
                trend_1h = -1  # bajista en 1h

        # ── FILTROS OBLIGATORIOS (FIX-3: menos estrictos) ───────

        # 1. ATR mínimo
        if atr_pct < 0.20:
            return None

        # 2. RSI no sobrecomprado
        rsi_limit = 70 if trend_1h == 1 else 65
        if rsi > rsi_limit:
            return None

        # 3. FIX-3: EMA filter flexible
        ema_alcista    = ema9 > ema21 > ema50
        ema_recuperando= ema9 > ema21 and ema50 > 0  # pull-back con EMA9 > EMA21
        ema_oversold   = rsi < 35 and near_low        # muy sobrevendido = excepción

        if not (ema_alcista or ema_recuperando or ema_oversold):
            return None

        # 4. Cambio 24h no extremo
        if change_24h > 12.0:
            return None

        # ── SCORING (FIX-6: rebalanceado, alcanzable) ───────────

        score   = 0
        reasons = []

        # EMA (25 pts max)
        if ema_alcista:
            gap = abs(ema9 - ema21) / ema21 * 100
            pts = min(25, 15 + int(gap * 4))
            score += pts
            reasons.append(f"EMA↑({pts})")
        elif ema_recuperando:
            score += 12
            reasons.append("EMA~(12)")

        # RSI (35 pts max) — peso mayor, señal más fiable
        if rsi < 25:
            score += 35; reasons.append(f"RSI{rsi:.0f}(35)")
        elif rsi < 30:
            score += 28; reasons.append(f"RSI{rsi:.0f}(28)")
        elif rsi < 35:
            score += 20; reasons.append(f"RSI{rsi:.0f}(20)")
        elif rsi < 40:
            score += 14; reasons.append(f"RSI{rsi:.0f}(14)")
        elif rsi < 50:
            score += 8;  reasons.append(f"RSI{rsi:.0f}(8)")

        # Volumen (15 pts max)
        if vol_m >= 2.5 and momentum_5 > 0.2:
            pts = min(15, int(vol_m * 5))
            score += pts; reasons.append(f"Vol{vol_m:.1f}x({pts})")
        elif vol_m >= 1.5:
            score += 8;   reasons.append(f"Vol{vol_m:.1f}x(8)")

        # Cerca de mínimos (12 pts)
        if near_low:
            score += 12; reasons.append("NearLow(12)")

        # Momentum (10 pts max)
        if 0.3 < momentum_5 < 5.0:
            score += 10; reasons.append("Mom+(10)")
        elif momentum_5 > 0:
            score += 5;  reasons.append("Mom+(5)")

        # Caída 24h = oportunidad de rebote (12 pts max)
        if change_24h < -8.0:
            score += 12; reasons.append(f"Drop{change_24h:.1f}%(12)")
        elif change_24h < -5.0:
            score += 8;  reasons.append(f"Drop{change_24h:.1f}%(8)")
        elif change_24h < -2.0:
            score += 4;  reasons.append(f"Drop{change_24h:.1f}%(4)")

        # Velas verdes (8 pts max)
        if green >= 4:
            score += 8; reasons.append("Green4(8)")
        elif green >= 3:
            score += 5; reasons.append("Green3(5)")
        elif green >= 2:
            score += 2; reasons.append("Green2(2)")

        # ATR (8 pts max)
        if atr_pct > 2.0:
            score += 8; reasons.append(f"ATR{atr_pct:.1f}%(8)")
        elif atr_pct > 1.0:
            score += 5; reasons.append(f"ATR{atr_pct:.1f}%(5)")

        # Contexto 1h (FIX-8) (10 pts bonus)
        if trend_1h == 1:
            score += 10; reasons.append(f"1hBull(10)")
        elif trend_1h == -1:
            score -= 5;  reasons.append("1hBear(-5)")

        # BTC bonus (8 pts max)
        if self._btc_1h > 1.0:
            score += 8; reasons.append(f"BTC+{self._btc_1h:.1f}%(8)")
        elif self._btc_1h > 0.3:
            score += 4; reasons.append(f"BTC+{self._btc_1h:.1f}%(4)")

        # Rango suficiente para TP (8 pts)
        if rng_pct > TP_PCT * 1.5:
            score += 8; reasons.append(f"Rng{rng_pct:.1f}%(8)")
        elif rng_pct > TP_PCT:
            score += 4; reasons.append(f"Rng{rng_pct:.1f}%(4)")

        # ── TP/SL dinámicos ─────────────────────────────────────
        sl_dyn = max(SL_PCT, atr_pct * 1.2)
        sl_dyn = min(sl_dyn, SL_PCT * 1.8)
        tp_dyn = max(TP_PCT, sl_dyn * 2.0, TP_MIN_RENTABLE)

        # ── Aprendizaje ──────────────────────────────────────────
        score_min = self.learning.optimal_score if self.learning else MIN_SCORE
        if self.learning:
            can, reason_str = self.learning.should_trade(symbol, score)
            if not can:
                return None

        # ── Decisión ─────────────────────────────────────────────
        if score >= score_min:
            return {
                'price': price, 'change': change_24h,
                'score': score, 'score_min': score_min,
                'reasons': ' | '.join(reasons),
                'rsi': rsi, 'vol': vol_m,
                'tp_pct': round(tp_dyn, 2),
                'sl_pct': round(sl_dyn, 2),
                'atr_pct': round(atr_pct, 2),
                'rr': round(tp_dyn / sl_dyn, 2),
                'ema_alcista': ema_alcista,
                'trend_1h': trend_1h,
            }
        return None

    # ========================================================================
    # GESTIÓN DE POSICIONES
    # ========================================================================

    def _set_leverage(self, symbol):
        """FIX-7: solo LONG/SHORT — BOTH causa error 109400 en hedge mode."""
        for side in ('LONG', 'SHORT'):
            try:
                bingx_request('POST', '/openApi/swap/v2/trade/leverage', {
                    'symbol': symbol, 'side': side, 'leverage': str(LEVERAGE),
                })
                log.info(f"  ⚙️  Leverage {symbol} {side} → {LEVERAGE}x")
            except Exception as e:
                log.debug(f"  leverage {side}: {e}")

    def _qty_contratos(self, symbol, price, usdt_amount=None):
        if usdt_amount is None:
            usdt_amount = POSITION_SIZE
        notional = max(usdt_amount * LEVERAGE, FORCE_MIN_USDT * LEVERAGE, MIN_TRADE)
        info     = self._contracts.get(symbol, {'step': 1.0, 'prec': 2, 'ctval': 1.0})
        step     = max(info.get('step', 1.0), 0.0001)
        prec     = info.get('prec', 2)
        ctval    = max(info.get('ctval', 1.0), 1e-9)
        ppc      = price * ctval
        if ppc <= 0:
            return None, 0
        qty = math.ceil((notional / ppc) / step) * step
        qty = round(qty, prec)
        val = qty * ppc
        attempts = 0
        while val < max(MIN_TRADE, FORCE_MIN_USDT) and attempts < 100:
            qty += step; qty = round(qty, prec); val = qty * ppc; attempts += 1
        if val < max(MIN_TRADE, FORCE_MIN_USDT):
            return None, 0
        log.info(f"  📊 {symbol}: {qty}cts × ${ppc:.6f} = ${val:.2f}")
        return qty, round(val, 4)

    def _place_limit_long(self, symbol, qty, price):
        limit_price = round(price * (1 - LIMIT_OFFSET_PCT / 100), 8)
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': 'BUY', 'positionSide': 'LONG',
                'type': 'LIMIT', 'price': str(limit_price),
                'quantity': str(qty), 'timeInForce': 'GTC',
            }).json()
            if d.get('code') == 0:
                oid = d.get('data', {}).get('orderId', 'OK')
                log.info(f"  ✅ LIMIT BUY @ ${limit_price:.6f}")
                return oid, qty
            else:
                log.error(f"  ❌ LIMIT [{d.get('code')}]: {d.get('msg')}")
        except Exception as e:
            log.error(f"  ❌ LIMIT error: {e}")
        return None, None

    def _wait_fill(self, symbol, order_id, timeout=30):
        for _ in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/trade/order', {
                    'symbol': symbol, 'orderId': str(order_id)
                }).json()
                if d.get('code') == 0:
                    order  = d.get('data', {}).get('order', {})
                    status = order.get('status', '')
                    if status == 'FILLED':
                        return float(order.get('executedQty', 0)), float(order.get('avgPrice', 0))
                    if status in ('CANCELED', 'EXPIRED', 'REJECTED'):
                        return None, None
            except:
                pass
            time.sleep(1)
        return None, None

    def _confirm_position(self, symbol, timeout=15):
        for _ in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                                  {'symbol': symbol}).json()
                if d.get('code') == 0:
                    for p in d.get('data', []):
                        amt  = float(p.get('positionAmt', 0) or 0)
                        side = str(p.get('positionSide', '')).upper()
                        if (side == 'LONG' and abs(amt) > 0) or (side == 'BOTH' and amt > 0):
                            return abs(amt), float(p.get('avgPrice') or p.get('entryPrice') or 0)
            except:
                pass
            time.sleep(1)
        return None, None

    def _cancel_orders(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/trade/openOrders',
                              {'symbol': symbol}).json()
            if d.get('code') == 0:
                for o in d.get('data', {}).get('orders', []):
                    oid = o.get('orderId')
                    if oid:
                        bingx_request('DELETE', '/openApi/swap/v2/trade/order',
                                      {'symbol': symbol, 'orderId': str(oid)})
        except:
            pass

    def _place_tp_sl(self, symbol, qty, tp_price, sl_price):
        tp_ok = sl_ok = False
        # TP
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': 'SELL', 'positionSide': 'LONG',
                'type': 'TAKE_PROFIT_MARKET', 'quantity': str(qty),
                'stopPrice': str(round(tp_price, 8)),
            }).json()
            tp_ok = d.get('code') == 0
            log.info(f"  {'✅' if tp_ok else '❌'} TP @ ${tp_price:.6f}")
        except Exception as e:
            log.error(f"  ❌ TP: {e}")
        time.sleep(0.3)
        # SL
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': 'SELL', 'positionSide': 'LONG',
                'type': 'STOP_MARKET', 'quantity': str(qty),
                'stopPrice': str(round(sl_price, 8)),
            }).json()
            sl_ok = d.get('code') == 0
            log.info(f"  {'✅' if sl_ok else '❌'} SL @ ${sl_price:.6f}")
        except Exception as e:
            log.error(f"  ❌ SL: {e}")
        return tp_ok, sl_ok

    def open_trade(self, symbol, signal):
        if not AUTO_TRADING or symbol in self.open_trades:
            return False
        if OptimizedLongBot._abriendo or len(self.open_trades) >= MAX_TRADES:
            return False
        OptimizedLongBot._abriendo = True
        try:
            return self._open_trade_inner(symbol, signal)
        finally:
            OptimizedLongBot._abriendo = False

    def _open_trade_inner(self, symbol, sig):
        price = sig['price']
        log.info(f"\n  🎯 LONG {symbol} | Score:{sig['score']:.0f}/{sig['score_min']:.0f} "
                 f"| RSI:{sig['rsi']:.0f} | RR:{sig['rr']:.2f}:1")
        log.info(f"  {sig['reasons']}")

        self._set_leverage(symbol)
        time.sleep(0.2)

        qty, notional = self._qty_contratos(symbol, price, POSITION_SIZE)
        if not qty:
            return False

        order_id, _ = self._place_limit_long(symbol, qty, price)
        if not order_id:
            return False

        filled_qty, fill_price = self._wait_fill(symbol, order_id, timeout=30)
        if not filled_qty:
            log.warning("  ⚠️  LIMIT no ejecutada → MARKET")
            self._cancel_orders(symbol)
            time.sleep(0.5)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': 'BUY', 'positionSide': 'LONG',
                'type': 'MARKET', 'quantity': str(qty),
            }).json()
            if d.get('code') != 0:
                log.error(f"  ❌ MARKET: {d.get('msg')}")
                return False
            filled_qty, fill_price = self._confirm_position(symbol, timeout=15)
            if not filled_qty:
                return False

        tp_price = fill_price * (1 + sig['tp_pct'] / 100)
        sl_price = fill_price * (1 - sig['sl_pct'] / 100)
        tp_ok, sl_ok = self._place_tp_sl(symbol, filled_qty, tp_price, sl_price)

        if not sl_ok:
            time.sleep(2)
            _, sl_ok = self._place_tp_sl(symbol, filled_qty, tp_price, sl_price)

        if not sl_ok:
            log.error("  ❌ SL crítico — cerrando")
            self._close_market(symbol, filled_qty)
            return False

        self.open_trades[symbol] = {
            'entry': fill_price, 'qty_c': filled_qty, 'usdt_qty': POSITION_SIZE,
            'tp': tp_price, 'sl': sl_price,
            'tp_pct': sig['tp_pct'], 'sl_pct': sig['sl_pct'],
            'highest': fill_price, 'order_id': order_id,
            'opened_at': datetime.now(), 'score': sig['score'], 'entry_data': sig,
        }
        self.stats['exec'] += 1
        self.stats['fees_paid'] += notional * COMISION_ACTUAL

        self._tg(
            f"<b>🟢 LONG ABIERTO</b> — <b>{symbol}</b>\n"
            f"Score: {sig['score']:.0f} | RSI: {sig['rsi']:.0f} | RR: {sig['rr']:.2f}:1\n"
            f"Entrada: ${fill_price:.6f}\n"
            f"{'✅' if tp_ok else '❌'} TP: ${tp_price:.6f} (+{sig['tp_pct']:.2f}%)\n"
            f"{'✅' if sl_ok else '❌'} SL: ${sl_price:.6f} (-{sig['sl_pct']:.2f}%)\n"
            f"Capital: ${POSITION_SIZE}x{LEVERAGE} | PnL día: ${self._daily_pnl:+.3f}"
        )
        return True

    def _close_market(self, symbol, qty):
        try:
            bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': 'SELL', 'positionSide': 'LONG',
                'type': 'MARKET', 'quantity': str(qty),
            })
            return True
        except:
            return False

    def close_trade(self, symbol, exit_price, reason):
        if symbol not in self.open_trades:
            return False
        t = self.open_trades[symbol]
        self._close_market(symbol, t['qty_c'])

        change      = (exit_price - t['entry']) / t['entry']
        gross_pnl   = t['usdt_qty'] * LEVERAGE * change
        fees        = t['usdt_qty'] * LEVERAGE * COMISION_ACTUAL * 2
        net_pnl     = gross_pnl - fees
        pnl_pct     = (net_pnl / t['usdt_qty']) * 100
        win         = net_pnl > 0

        self.stats['closed']    += 1
        self.stats['pnl']       += net_pnl
        self.stats['fees_paid'] += fees
        self._daily_pnl         += net_pnl
        if win: self.stats['wins'] += 1
        else:   self.stats['losses'] += 1

        if self.learning:
            self.learning.record_trade(symbol, t['entry_data'],
                                       {'price': exit_price}, net_pnl, win)

        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        mins  = int((datetime.now() - t['opened_at']).total_seconds() / 60)
        emoji = "✅" if win else "❌"

        log.info(f"  {emoji} {reason} | ${net_pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min")

        self._set_cooldown(symbol, 'TP' if 'PROFIT' in reason else 'SL')
        self._tg(
            f"<b>{emoji} LONG CERRADO — {reason}</b>\n"
            f"<b>{symbol}</b>\n"
            f"PnL: ${net_pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min\n"
            f"${t['entry']:.6f} → ${exit_price:.6f}\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR: {wr:.1f}%</b>"
        )

        if self.learning and self.stats['closed'] % 5 == 0:
            self.learning.save_to_file()

        del self.open_trades[symbol]
        return True

    # ========================================================================
    # UTILIDADES
    # ========================================================================

    def _cooldown_ok(self, symbol):
        ts = self._cooldowns.get(symbol)
        if not ts:
            return True
        resume_ts, _ = ts if isinstance(ts, tuple) else (ts + COOLDOWN_MIN_TP * 60, 'TP')
        if time.time() >= resume_ts:
            del self._cooldowns[symbol]
            return True
        return False

    def _set_cooldown(self, symbol, reason='TP'):
        mins = COOLDOWN_MIN_TP if reason == 'TP' else COOLDOWN_MIN_SL
        self._cooldowns[symbol] = (time.time() + mins * 60, reason)

    def _hora_ok(self):
        return int(datetime.utcnow().hour) not in SKIP_HOURS_UTC

    def _reset_daily(self):
        today = datetime.utcnow().date()
        if today != self._daily_reset:
            self._daily_pnl    = 0.0
            self._daily_reset  = today
            self._circuit_open = False
            self._circuit_until= None
            if self.learning:
                self.learning.losing_streak = 0
            log.info("📅 Nuevo día")

    def _check_circuit_breaker(self):
        self._reset_daily()
        if self._circuit_open:
            if self._circuit_until and datetime.utcnow() > self._circuit_until:
                self._circuit_open = False
                self._tg("<b>🔓 Circuit breaker OFF</b>")
            return self._circuit_open
        if self._daily_pnl < -CIRCUIT_BREAKER_USDT:
            self._circuit_open  = True
            self._circuit_until = datetime.utcnow() + timedelta(hours=2)
            log.warning(f"  🔒 CIRCUIT BREAKER | día: ${self._daily_pnl:.3f}")
            self._tg(
                f"<b>🔒 CIRCUIT BREAKER ACTIVADO</b>\n"
                f"Pérdida día: ${self._daily_pnl:.3f} USDT\n"
                f"Pausado 2h"
            )
        return self._circuit_open

    # ========================================================================
    # MONITOREO
    # ========================================================================

    async def monitor_trades(self):
        for sym in list(self.open_trades.keys()):
            try:
                t  = self.open_trades[sym]
                tk = self._ticker(sym)
                if not tk:
                    continue
                cur     = tk['price']
                pnl_pct = (cur - t['entry']) / t['entry'] * 100

                if TRAILING and cur > t['highest']:
                    t['highest'] = cur
                    if pnl_pct >= TRAILING_START:
                        new_sl = t['entry'] + (cur - t['entry']) * (TRAILING_LOCK / 100)
                        if new_sl > t['sl']:
                            t['sl'] = new_sl

                if cur >= t['tp']:
                    self.close_trade(sym, cur, "TAKE PROFIT")
                elif cur <= t['sl']:
                    self.close_trade(sym, cur, "STOP LOSS")
                elif pnl_pct * LEVERAGE < -MAX_LOSS_PCT:
                    self.close_trade(sym, cur, "STOP EMERGENCIA")
            except Exception as e:
                log.debug(f"Monitor {sym}: {e}")

    def _reporte_horario(self):
        if datetime.now() - self._last_report < timedelta(hours=1):
            return
        self._last_report = datetime.now()
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        pos_txt = ""
        for sym, t in self.open_trades.items():
            tk  = self._ticker(sym)
            cur = tk['price'] if tk else t['entry']
            pos_txt += f"  {sym}: {(cur-t['entry'])/t['entry']*100:+.2f}%\n"
        self._tg(
            f"<b>📊 Reporte LONGS v3.0</b>\n"
            f"PnL: ${self.stats['pnl']:+.3f} | WR: {wr:.1f}% | {total} trades\n"
            f"Día: ${self._daily_pnl:+.3f} | Fees: ${self.stats['fees_paid']:.2f}\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES} | BTC: {self._btc_1h:+.2f}%\n"
            f"Circuit: {'🔒' if self._circuit_open else '🔓'}\n"
            + (pos_txt if pos_txt else "  Sin posiciones\n")
        )

    def _tg(self, msg):
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                    timeout=6
                )
        except:
            pass

    # ========================================================================
    # LOOP PRINCIPAL
    # ========================================================================

    async def run(self):
        log.info("\n🚀 Bot LONGS v3.0 iniciado\n")
        iteration          = 0
        last_symbol_refresh= 0

        while True:
            try:
                iteration += 1
                self._reset_daily()

                if time.time() - last_symbol_refresh > 600:
                    self._get_symbols()
                    last_symbol_refresh = time.time()

                self._update_btc_trend()

                if self._check_circuit_breaker():
                    log.warning("  🔒 Circuit breaker — esperando")
                    await asyncio.sleep(INTERVAL)
                    continue

                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0
                score_actual = self.learning.optimal_score if self.learning else MIN_SCORE
                btc_status   = "🟢" if self._btc_ok else "🔴"

                log.info(f"\n{'='*80}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"Abiertos:{len(self.open_trades)}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                log.info(f"  BTC:{self._btc_1h:+.2f}%{btc_status} | "
                         f"Score mín:{score_actual:.0f} | "
                         f"Símbolos:{len(self.symbols)}")
                log.info(f"{'='*80}\n")

                await self.monitor_trades()
                self._reporte_horario()

                if len(self.open_trades) < MAX_TRADES:
                    signals_found = 0
                    log.info(f"  Escaneando {len(self.symbols)} símbolos...")
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES:
                            break
                        sig = self.analyze(sym)
                        if sig:
                            signals_found += 1
                            log.info(
                                f"  💡 {sym} | Score:{sig['score']:.0f}/{sig['score_min']:.0f} "
                                f"| RSI:{sig['rsi']:.0f} | {sig['reasons']}"
                            )
                            if self.open_trade(sym, sig):
                                await asyncio.sleep(3)
                        if (i + 1) % 10 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)}")
                        await asyncio.sleep(0.15)
                    log.info(f"  ✅ Scan completo: {signals_found} señales")
                else:
                    log.info(f"  ⏸️  Max trades — monitoreando")

                log.info(f"\n  ⏭️  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)

            except KeyboardInterrupt:
                log.info("⏹️  Detenido")
                break
            except Exception as e:
                log.error(f"❌ Error #{iteration}: {e}")
                await asyncio.sleep(20)

        if self.learning:
            self.learning.save_to_file()

# ============================================================================
# ENTRY POINT
# ============================================================================

async def main():
    try:
        bot = OptimizedLongBot()
        await bot.run()
    except Exception as e:
        log.error(f"❌ Fatal: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Bot terminado")
