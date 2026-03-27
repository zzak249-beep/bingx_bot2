#!/usr/bin/env python3
"""
BOT LONGS PROFESIONAL v1.1 — FIX mínimo 10 USDT
════════════════════════════════════════════════════════════════
FIXES aplicados vs v1.0:
  ▸ FIX 1: MAX_LOSS_PCT limpia el '%' antes de parsear (era "8%" → crash)
  ▸ FIX 2: FORCE_MIN_USDT subido a 10.0 por defecto (era 8.0)
  ▸ FIX 3: _qty_contratos — bucle while aumentado a 500 iteraciones
            y validación doble al final con assert
  ▸ FIX 4: _qty_contratos — cuando ctval <= 0 o price <= 0 devuelve
            None, 0 en lugar de dividir por cero silenciosamente
  ▸ FIX 5: _place_long_entry — usdt_qty forzado a max(usdt_qty,
            FORCE_MIN_USDT, MIN_TRADE) ANTES de calcular qty_c, y
            el fallback quoteOrderQty usa directamente ese valor
            en lugar de qty_c*ppc (que podía ser ~$0 con ctval raro)
  ▸ FIX 6: open_trade — usdt_qty siempre = max(POSITION_SIZE,
            FORCE_MIN_USDT, MIN_TRADE) sin posibilidad de bajar
  ▸ FIX 7: clean() para MAX_LOSS_PCT quita '%' y caracteres no numéricos
════════════════════════════════════════════════════════════════
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re
from datetime import datetime, timedelta
from urllib.parse import urlencode

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

def clean(key, default, typ='str'):
    v = os.getenv(key, str(default)).strip().strip('"').strip("'").strip()
    # FIX 7: quitar cualquier símbolo no numérico antes de parsear números
    if typ in ('int', 'float'):
        v = v.replace(',', '.').replace('%', '')   # <-- FIX: elimina el '%'
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

AUTO_TRADING  = clean('AUTO_TRADING_ENABLED',  'true',  'bool')
POSITION_SIZE = clean('MAX_POSITION_SIZE',      '10',   'float')
MIN_TRADE     = clean('MIN_TRADE_USDT',         '10',   'float')   # FIX 2: era '8'
LEVERAGE      = clean('LEVERAGE',               '3',    'int')
TP_PCT        = clean('TAKE_PROFIT_PCT',        '2.5',  'float')
SL_PCT        = clean('STOP_LOSS_PCT',          '1.5',  'float')
MAX_TRADES    = clean('MAX_OPEN_TRADES',        '2',    'int')
INTERVAL      = clean('CHECK_INTERVAL',         '60',   'int')
MIN_VOLUME    = clean('MIN_VOLUME_24H',      '500000',  'float')
MAX_SYMBOLS   = clean('MAX_SYMBOLS_TO_ANALYZE', '50',   'int')
MIN_SCORE     = clean('MIN_SCORE',              '82',   'float')
TRAILING      = clean('TRAILING_STOP_ENABLED', 'true',  'bool')
TRAILING_START= clean('TRAILING_START_PCT',    '1.0',   'float')
TRAILING_LOCK = clean('TRAILING_LOCK_PCT',      '60',   'float')
USE_LIMIT_ORDERS   = clean('USE_LIMIT_ORDERS',      'true', 'bool')
BTC_BEAR_BLOCK_PCT = clean('BTC_BEAR_BLOCK_PCT',    '1.5',  'float')
MAX_LOSS_PCT       = clean('MAX_LOSS_PCT',           '5.0',  'float')   # FIX 1+7
SL_LIMIT_OFFSET    = clean('SL_LIMIT_OFFSET_PCT',   '0.05', 'float') / 100
FORCE_MIN_USDT     = max(clean('FORCE_MIN_USDT',    '10.0', 'float'), 10.0)  # FIX 2: nunca < 10
COOLDOWN_MIN_TP    = clean('COOLDOWN_AFTER_TP_MIN',  '15',   'int')
COOLDOWN_MIN_SL    = clean('COOLDOWN_AFTER_SL_MIN',  '45',   'int')

MAE_PERIOD    = clean('MAE_PERIOD',     '20',  'int')
MAE_PCT       = clean('MAE_PCT',        '2.0', 'float')
PATTERN_SCORE = clean('PATTERN_SCORE', 'true', 'bool')
REGIME_FILTER = clean('REGIME_FILTER', 'true', 'bool')

LIMIT_OFFSET_PCT = 0.05
SKIP_HOURS_UTC   = {0, 1}
BASE_URL         = "https://open-api.bingx.com"

# FIX: POSITION_SIZE y MIN_TRADE nunca pueden bajar de FORCE_MIN_USDT
POSITION_SIZE = max(POSITION_SIZE, FORCE_MIN_USDT)
MIN_TRADE     = max(MIN_TRADE,     FORCE_MIN_USDT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

COMISION_MAKER  = 0.0002
COMISION_TAKER  = 0.0005
COMISION_ACTUAL = COMISION_MAKER if USE_LIMIT_ORDERS else COMISION_TAKER
TP_MIN_RENTABLE = round((COMISION_ACTUAL / LEVERAGE + 0.002) * 100, 3)

log.info(f"[CONFIG] FORCE_MIN_USDT={FORCE_MIN_USDT} | POSITION_SIZE={POSITION_SIZE} | MIN_TRADE={MIN_TRADE} | MAX_LOSS_PCT={MAX_LOSS_PCT}")

# ============================================================================
# API BINGX
# ============================================================================

def bingx_request(method, endpoint, params, retries=2):
    for attempt in range(retries + 1):
        try:
            p = dict(params)
            p['timestamp'] = int(time.time() * 1000)
            qs  = urlencode(sorted(p.items()))
            sig = hmac.new(BINGX_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
            url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
            hdr = {'X-BX-APIKEY': BINGX_API_KEY,
                   'Content-Type': 'application/x-www-form-urlencoded'}
            r = requests.get(url, headers=hdr, timeout=12) if method == 'GET' \
                else requests.post(url, headers=hdr, timeout=12)
            return r
        except Exception as e:
            if attempt < retries:
                log.warning(f"  retry {attempt+1}: {e}"); time.sleep(1.5)
            else:
                raise

# ============================================================================
# INDICADORES
# ============================================================================

def calc_ema(prices, period):
    if not prices: return 0
    if len(prices) < period: return sum(prices) / len(prices)
    k, e = 2 / (period + 1), prices[0]
    for p in prices[1:]: e = p * k + e * (1 - k)
    return e

def calc_sma(prices, period):
    if len(prices) < period: return sum(prices) / len(prices)
    return sum(prices[-period:]) / period

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains  = [max(0,  prices[i] - prices[i-1]) for i in range(1, len(prices))]
    losses = [max(0, prices[i-1] - prices[i])  for i in range(1, len(prices))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100.0
    return 100 - (100 / (1 + ag / al))

def calc_macd(prices):
    if len(prices) < 26: return 0, 0, 0
    ml = calc_ema(prices, 12) - calc_ema(prices, 26)
    return ml, ml * 0.9, ml * 0.1

def calc_bollinger(prices, period=20):
    if len(prices) < period:
        m = sum(prices) / len(prices); return m, m, m
    w = prices[-period:]
    mid = sum(w) / period
    std = (sum((p - mid)**2 for p in w) / period) ** 0.5
    return mid + 2*std, mid, mid - 2*std

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2: return 0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, min(len(closes), period+1))]
    return sum(trs) / len(trs) if trs else 0

def vol_spike(volumes):
    if len(volumes) < 5: return 1.0
    avg = sum(volumes[:-1]) / len(volumes[:-1])
    return (volumes[-1] / avg) if avg > 0 else 1.0

# ============================================================================
# MAE
# ============================================================================

def calc_sma_val(prices, period):
    if len(prices) < period: return sum(prices) / len(prices)
    return sum(prices[-period:]) / period

def mae_long_score(prices, period=20, pct=2.0):
    if len(prices) < period:
        ma = sum(prices) / len(prices)
    else:
        ma = calc_sma_val(prices, period)

    factor = pct / 100.0
    upper  = ma * (1 + factor)
    lower  = ma * (1 - factor)
    price  = prices[-1]

    band_width = upper - lower
    pos = (price - lower) / band_width if band_width > 0 else 0.5

    if len(prices) >= period + 5:
        ma_old       = calc_sma_val(prices[:-5], period)
        ma_slope_pct = (ma - ma_old) / ma_old * 100 if ma_old > 0 else 0
    else:
        ma_slope_pct = 0

    is_uptrend   = ma_slope_pct >  0.3
    is_downtrend = ma_slope_pct < -0.5
    is_ranging   = not is_uptrend and not is_downtrend

    score, desc = 0, ""
    if is_ranging:
        regime = "RANGO"
        if pos <= 0.05:   score = 30; desc = f"MAE_BOT_RANGO(30) pos:{pos:.2f}"
        elif pos <= 0.20: score = 20; desc = f"MAE_BAJO_RANGO(20) pos:{pos:.2f}"
        elif pos <= 0.40: score = 8;  desc = f"MAE_MEDIO-(8) pos:{pos:.2f}"
        elif pos >= 0.70: score = -15; desc = f"MAE_ALTO(-15) pos:{pos:.2f}"
        else:             score = 0;   desc = f"MAE_NEUTRAL(0) pos:{pos:.2f}"
    elif is_uptrend:
        regime = "ALCISTA"
        if pos <= 0.30:   score = 25; desc = f"MAE_RETROCESO_ALCISTA(25) pos:{pos:.2f}"
        elif pos <= 0.50: score = 15; desc = f"MAE_MEDIO_ALCISTA(15) pos:{pos:.2f}"
        else:             score = 5;  desc = f"MAE_ALCISTA_OK(5) pos:{pos:.2f}"
    else:
        regime = "BAJISTA"
        if pos < -0.05:   score = -25; desc = f"MAE_IMPULSO_BAJISTA(-25) pos:{pos:.2f}"
        elif pos < 0.10:  score = -12; desc = f"MAE_BAJISTA_FUERTE(-12) pos:{pos:.2f}"
        elif pos > 0.60:  score = 10;  desc = f"MAE_REBOTE_BAJISTA(10) pos:{pos:.2f}"
        else:             score = -5;  desc = f"MAE_BAJISTA(-5) pos:{pos:.2f}"

    return score, desc, regime, pos, upper, ma, lower

# ============================================================================
# PATRONES CHARTISTAS
# ============================================================================

def find_pivots(prices, window=3):
    highs, lows = [], []
    for i in range(window, len(prices) - window):
        if all(prices[i] >= prices[i-j] and prices[i] >= prices[i+j] for j in range(1, window+1)):
            highs.append((i, prices[i]))
        if all(prices[i] <= prices[i-j] and prices[i] <= prices[i+j] for j in range(1, window+1)):
            lows.append((i, prices[i]))
    return highs, lows

def detect_double_bottom(closes, lows_list, tolerance=0.015):
    if len(lows_list) < 2: return False, 0, ""
    l1_idx, l1_val = lows_list[-2]
    l2_idx, l2_val = lows_list[-1]
    diff = abs(l1_val - l2_val) / max(l1_val, l2_val)
    if diff > tolerance: return False, 0, ""
    peak_prices = closes[l1_idx:l2_idx]
    if not peak_prices: return False, 0, ""
    peak = max(peak_prices)
    neck_rise = (peak - min(l1_val, l2_val)) / min(l1_val, l2_val)
    if neck_rise < 0.01: return False, 0, ""
    cur = closes[-1]
    if cur >= peak * 0.995:   return True, 40, "DoubleBottom_NECK(40)"
    if cur <= l2_val * 1.015: return True, 32, "DoubleBottom_BOT(32)"
    return False, 0, ""

def detect_inv_head_shoulders(closes, lows_list, tolerance=0.02):
    if len(lows_list) < 3: return False, 0, ""
    ls_idx, ls_val = lows_list[-3]
    h_idx,  h_val  = lows_list[-2]
    rs_idx, rs_val = lows_list[-1]
    if not (h_val < ls_val and h_val < rs_val): return False, 0, ""
    shoulder_diff = abs(ls_val - rs_val) / max(ls_val, rs_val)
    if shoulder_diff > tolerance: return False, 0, ""
    cur = closes[-1]
    if cur >= rs_val * 1.005: return True, 38, "InvH&S_BREAK(38)"
    if cur <= rs_val * 1.01:  return True, 28, "InvH&S_SHOULDER(28)"
    return False, 0, ""

def detect_falling_wedge(closes, highs_list, lows_list, min_points=3):
    if len(highs_list) < min_points or len(lows_list) < min_points:
        return False, 0, ""
    def slope(points):
        if len(points) < 2: return 0
        x1, y1 = points[0]; x2, y2 = points[-1]
        return (y2 - y1) / (x2 - x1) if x2 != x1 else 0
    sh   = slope(highs_list[-min_points:])
    sl_s = slope(lows_list[-min_points:])
    if sh >= 0 or sl_s >= 0: return False, 0, ""
    if not (sl_s < sh * 0.7): return False, 0, ""
    cur = closes[-1]
    last_low  = lows_list[-1][1]
    last_high = highs_list[-1][1]
    rng = last_high - last_low
    if rng > 0 and (cur - last_low) / rng <= 0.25:
        return True, 30, "FallingWedge_BOT(30)"
    return False, 0, ""

def detect_bullish_flag(closes, volumes, lows_list):
    if len(closes) < 20: return False, 0, ""
    mast_change = (closes[-6] - closes[-12]) / closes[-12] * 100
    if mast_change < 2.5: return False, 0, ""
    flag_prices = closes[-5:]
    flag_range  = (max(flag_prices) - min(flag_prices)) / min(flag_prices) * 100
    if flag_range > 2.0: return False, 0, ""
    if len(volumes) >= 10:
        vol_ok = sum(volumes[-5:]) / 5 < sum(volumes[-10:-5]) / 5
    else:
        vol_ok = True
    return (True, 32, "BullishFlag(32)") if vol_ok else (True, 18, "BullishFlag_noVol(18)")

def detect_resistance_break(closes, highs_list, tolerance=0.008):
    if len(highs_list) < 2 or len(closes) < 5: return False, 0, ""
    recent_highs_vals = [v for _, v in highs_list[-6:]]
    if len(recent_highs_vals) < 2: return False, 0, ""
    resist_level = None
    for high in recent_highs_vals:
        touches = sum(1 for h in recent_highs_vals if abs(h - high) / high < tolerance)
        if touches >= 2:
            resist_level = high; break
    if not resist_level: return False, 0, ""
    cur = closes[-1]
    if cur > resist_level * (1 + tolerance):
        return True, 28, "ResistBreak(28)"
    return False, 0, ""

def scan_bullish_patterns(closes, highs_raw, lows_raw, volumes):
    if not closes or len(closes) < 20: return 0, []
    highs_list, lows_list = find_pivots(closes, window=3)
    patterns, total = [], 0
    for fn in [
        lambda: detect_double_bottom(closes, lows_list),
        lambda: detect_inv_head_shoulders(closes, lows_list),
        lambda: detect_falling_wedge(closes, highs_list, lows_list),
        lambda: detect_bullish_flag(closes, volumes, lows_list),
        lambda: detect_resistance_break(closes, highs_list),
    ]:
        ok, sc, dsc = fn()
        if ok: patterns.append(dsc); total += sc
    return total, patterns

def detect_market_regime(closes, period=20):
    if len(closes) < period + 5: return "UNKNOWN"
    ma_now  = calc_sma_val(closes, period)
    ma_old  = calc_sma_val(closes[:-5], period)
    slope_pct = (ma_now - ma_old) / ma_old * 100 if ma_old > 0 else 0
    deviations = [abs(c - ma_now) / ma_now * 100 for c in closes[-period:]]
    avg_dev = sum(deviations) / len(deviations)
    if slope_pct > 0.6 and avg_dev > 0.8:    return "TREND_UP"
    elif slope_pct < -0.4 and avg_dev > 0.6: return "TREND_DOWN"
    else:                                      return "RANGING"

# ============================================================================
# BOT LONGS
# ============================================================================

class LongBot:

    def __init__(self):
        fee_lbl = f"LÍMITE maker {COMISION_MAKER*100:.2f}%" if USE_LIMIT_ORDERS \
                  else f"MERCADO taker {COMISION_TAKER*100:.2f}%"
        log.info("=" * 70)
        log.info("  BOT LONGS PROFESIONAL v1.1 — FIX mínimo 10 USDT")
        log.info("=" * 70)
        log.info(f"  Modo:           {'AUTO' if AUTO_TRADING else 'SEÑALES'}")
        log.info(f"  Capital:        ${POSITION_SIZE} USDT | Leverage: {LEVERAGE}x")
        log.info(f"  TP/SL:          {TP_PCT}% / {SL_PCT}%")
        log.info(f"  FORCE_MIN_USDT: ${FORCE_MIN_USDT} USDT  ← mínimo garantizado")
        log.info(f"  MIN_TRADE_USDT: ${MIN_TRADE} USDT")
        log.info(f"  MAX_LOSS_PCT:   {MAX_LOSS_PCT}%")
        log.info(f"  Órdenes:        {fee_lbl}")
        log.info("=" * 70)

        self.symbols      = []
        self.open_trades  = {}
        self._contracts   = {}
        self._cooldowns   = {}
        self._last_report = datetime.now()
        self._btc_1h      = 0.0
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0}

        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._tg(
            f"<b>🟢 Bot LONGS v1.1 iniciado</b>\n"
            f"FIX: mínimo ${FORCE_MIN_USDT} USDT garantizado\n"
            f"TP:{TP_PCT}% SL:{SL_PCT}% LEV:{LEVERAGE}x\n"
            f"Score≥{MIN_SCORE} | Capital: ${POSITION_SIZE}"
        )

    # ---------------------------------------------------------------- setup

    def _verify(self):
        global AUTO_TRADING
        if not AUTO_TRADING: return
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            AUTO_TRADING = False; return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                eq = d.get('data',{}).get('equity', d.get('data',{}).get('balance','?'))
                log.info(f"BingX OK | Balance: ${eq} USDT")
            else:
                log.error(f"BingX [{d.get('code')}]: {d.get('msg')}"); AUTO_TRADING = False
        except Exception as e:
            log.error(f"Error API: {e}"); AUTO_TRADING = False

    def _load_contracts(self):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/contracts", timeout=15).json()
            if d.get('code') == 0:
                for c in d.get('data', []):
                    self._contracts[c.get('symbol','')] = {
                        'step':  float(c.get('tradeMinQuantity', 1)),
                        'prec':  int(c.get('quantityPrecision', 2)),
                        'ctval': float(c.get('contractSize', 1)),
                    }
                log.info(f"Contratos: {len(self._contracts)}")
        except Exception as e:
            log.warning(f"Error contratos: {e}")

    def _get_symbols(self):
        NO = ['DOW','JONES','SP500','SPX','SPY','QQQ','NASDAQ','RUSSELL','DAX','FTSE',
              'CAC','NIKKEI','HANG','BOVESPA','IBEX','US30','NAS100','US500','DJI','INDEX',
              'GOLD','SILVER','XAU','XAG','PAXG','XAUT','OIL','BRENT','WTI','CRUDE',
              'GAS','GASOLINE','NATURAL','PETROL','DIESEL','PLATINUM','PALLADIUM','COPPER',
              'NICKEL','ZINC','IRON','TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA',
              'COIN','MSTR','EUR','GBP','JPY','CHF','AUD','CAD','NZD',
              'WHEAT','CORN','SUGAR','COFFEE','COTTON','LUMBER','SOYBEAN']
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker", timeout=15).json()
            if d.get('code') == 0:
                items, excl = [], []
                for t in d.get('data', []):
                    sym = t.get('symbol','')
                    if not sym.endswith('-USDT'): continue
                    base = sym.replace('-USDT','').upper()
                    if any(kw in base for kw in NO): excl.append(base); continue
                    try:
                        price = float(t.get('lastPrice',0))
                        vol   = float(t.get('volume',0)) * price
                        if vol < MIN_VOLUME or price < 0.000001: continue
                        items.append({'symbol':sym,'vol':vol})
                    except: continue
                items.sort(key=lambda x: x['vol'], reverse=True)
                self.symbols = [x['symbol'] for x in items[:MAX_SYMBOLS]]
                log.info(f"Pares: {len(self.symbols)} | Excluidos: {len(excl)}")
                return
        except Exception as e:
            log.warning(f"Error símbolos: {e}")
        self.symbols = ['BTC-USDT','ETH-USDT','SOL-USDT','BNB-USDT','XRP-USDT']

    # ---------------------------------------------------------------- datos

    def _klines(self, symbol, interval='5m', limit=80):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol':symbol,'interval':interval,'limit':limit}, timeout=10).json()
            if d.get('code') == 0 and d.get('data'):
                k = d['data']
                return ([float(x['close'])  for x in k], [float(x['high'])  for x in k],
                        [float(x['low'])    for x in k], [float(x['volume']) for x in k],
                        [float(x['open'])   for x in k])
        except: pass
        return None, None, None, None, None

    def _ticker(self, symbol):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker",
                             params={'symbol':symbol}, timeout=8).json()
            if d.get('code') == 0 and d.get('data'):
                t = d['data']
                return {'price': float(t.get('lastPrice',0)),
                        'change': float(t.get('priceChangePercent',0))}
        except: pass
        return None

    def _update_btc_trend(self):
        try:
            closes, *_ = self._klines('BTC-USDT', '1h', 3)
            if closes and len(closes) >= 2:
                self._btc_1h = (closes[-1] - closes[-2]) / closes[-2] * 100
        except: pass

    # ---------------------------------------------------------------- FIX: sizing robusto

    def _qty_contratos(self, symbol, price, usdt_amount=None):
        """
        FIX 3+4: cálculo de cantidad con validaciones reforzadas.
        - Nunca devuelve una cantidad cuyo valor sea < FORCE_MIN_USDT
        - Bucle ampliado a 500 iteraciones
        - Protección contra price=0 o ctval=0
        """
        if usdt_amount is None: usdt_amount = POSITION_SIZE
        # FIX: siempre respetar el mínimo absoluto
        usdt_amount = max(usdt_amount, FORCE_MIN_USDT, MIN_TRADE)

        info  = self._contracts.get(symbol, {'step':1.0,'prec':2,'ctval':1.0})
        step  = max(info.get('step', 1.0), 0.0001)
        prec  = info.get('prec', 2)
        ctval = info.get('ctval', 1.0)

        # FIX 4: protección contra valores inválidos
        if price <= 0:
            log.error(f"  [QTY] {symbol}: price={price} inválido"); return None, 0
        if ctval <= 0:
            log.warning(f"  [QTY] {symbol}: ctval={ctval} inválido, usando 1.0"); ctval = 1.0

        ppc = price * ctval if ctval != 1.0 else price
        if ppc <= 0:
            log.error(f"  [QTY] {symbol}: ppc={ppc} inválido"); return None, 0

        # Cantidad inicial
        qty = round(math.ceil(usdt_amount / ppc / step) * step, prec)
        val = qty * ppc
        min_val = max(MIN_TRADE, FORCE_MIN_USDT)

        # FIX 3: bucle ampliado a 500 (era 100)
        i = 0
        while val < min_val and i < 500:
            qty += step
            qty  = round(qty, prec)
            val  = qty * ppc
            i   += 1

        if val < min_val:
            log.error(f"  [QTY] {symbol} no alcanza mínimo tras 500 iters: ${val:.4f} < ${min_val}")
            return None, 0

        # Cap superior: no gastar más del 130% del presupuesto
        if val > usdt_amount * 1.3:
            qty_capped = round(math.floor((usdt_amount * 1.3 / ppc) / step) * step, prec)
            val_capped = qty_capped * ppc
            if val_capped >= min_val:
                qty = qty_capped
                val = val_capped
            # si el cap baja del mínimo, mantenemos qty sin cap

        # FIX: validación final irrefutable
        val_final = qty * ppc
        if val_final < min_val:
            log.error(f"  [QTY] FALLO FINAL {symbol}: ${val_final:.4f} < ${min_val}")
            return None, 0

        log.info(f"  [QTY] {symbol}: {qty} cts × ${ppc:.8f} = ${val_final:.2f} USDT ✅")
        return qty, round(val_final, 4)

    # ---------------------------------------------------------------- cooldown

    def _cooldown_ok(self, symbol):
        ts = self._cooldowns.get(symbol)
        if not ts: return True
        resume_ts, reason = ts if isinstance(ts, tuple) else (ts + COOLDOWN_MIN_TP * 60, 'TP')
        if time.time() >= resume_ts:
            del self._cooldowns[symbol]; return True
        return False

    def _set_cooldown(self, symbol, reason='TP'):
        mins = COOLDOWN_MIN_TP if reason == 'TP' else COOLDOWN_MIN_SL
        self._cooldowns[symbol] = (time.time() + mins * 60, reason)
        log.info(f"  Cooldown {symbol}: {mins}min ({reason})")

    def _hora_ok(self):
        return datetime.utcnow().hour not in SKIP_HOURS_UTC

    # ---------------------------------------------------------------- análisis LONG

    def analyze(self, symbol):
        if symbol in self.open_trades or not self._cooldown_ok(symbol): return None
        if not self._hora_ok(): return None
        if self._btc_1h <= -BTC_BEAR_BLOCK_PCT: return None

        closes, highs, lows, volumes, opens = self._klines(symbol, '5m', 80)
        if not closes or len(closes) < 30: return None
        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0: return None
        price  = ticker['price']
        change = ticker['change']

        ema9  = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        ema50 = calc_ema(closes, min(50, len(closes)))
        rsi   = calc_rsi(closes, 14)
        rsi_r = calc_rsi(closes[-20:], 10)
        ml, sg, hist = calc_macd(closes)
        bb_u, bb_m, bb_l = calc_bollinger(closes, 20)
        atr   = calc_atr(highs, lows, closes, 14)
        vs    = vol_spike(volumes)

        ema_gap  = abs(ema9 - ema21) / ema21 * 100 if ema21 > 0 else 0
        trend_5  = (closes[-1] - closes[-6])  / closes[-6]  * 100 if len(closes) >= 6  else 0
        trend_10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0
        bb_pos   = (price - bb_l) / (bb_u - bb_l) if (bb_u - bb_l) > 0 else 0.5
        near_low     = price <= min(closes[-15:]) * 1.02 if len(closes) >= 15 else False
        green_candles = sum(1 for i in range(-4, 0) if opens and closes[i] > opens[i]) if opens else 0
        atr_pct      = (atr / price * 100) if price > 0 else 0

        rsi_min = min(rsi, rsi_r)

        mae_score, mae_desc, mae_regime, mae_pos, _, _, _ = mae_long_score(closes, MAE_PERIOD, MAE_PCT)
        regime = detect_market_regime(closes)

        pattern_total, pattern_list = 0, []
        if PATTERN_SCORE:
            pattern_total, pattern_list = scan_bullish_patterns(closes, highs, lows, volumes)

        if rsi_min > 45 and not pattern_list: return None
        if vs < 1.2: return None
        if atr_pct < 0.4: return None
        if self._btc_1h > 4.0: return None
        if opens and green_candles < 1: return None

        ema_long_ok = ema9 > ema21 > ema50
        if not ema_long_ok and (not pattern_list or pattern_total < 35): return None
        if REGIME_FILTER and regime == "TREND_DOWN" and not pattern_list: return None

        score_min = MIN_SCORE + (10 if self._btc_1h < -0.5 else 0)
        ss, sr = 0, []

        if ema_long_ok:
            p = min(35, 28 + int(ema_gap * 4)) if ema_gap > 1.5 else min(28, 20 + int(ema_gap * 5))
            ss += p; sr.append(f"EMA_OK({p})")
        else:
            ss -= 15; sr.append("EMA_ROTA(-15)")

        if   rsi_min < 25: ss += 38; sr.append(f"RSI{rsi_min:.0f}(38)")
        elif rsi_min < 30: ss += 28; sr.append(f"RSI{rsi_min:.0f}(28)")
        elif rsi_min < 35: ss += 18; sr.append(f"RSI{rsi_min:.0f}(18)")
        elif rsi_min < 45: ss += 8;  sr.append(f"RSI{rsi_min:.0f}(8)")

        if ml > sg and hist > 0:
            p = 22 if abs(hist) > abs(ml) * 0.35 else 15
            ss += p; sr.append(f"MACD+({p})")
        elif ml < 0 and hist < 0:
            ss -= 15; sr.append("MACD-(-15)")

        if   bb_pos <= 0.05: ss += 25; sr.append("BB_bot(25)")
        elif bb_pos <= 0.15: ss += 17; sr.append("BB_low(17)")
        elif bb_pos <= 0.30: ss += 8;  sr.append("BB_mid-(8)")
        elif bb_pos >= 0.60: ss -= 12; sr.append("BB_high(-12)")

        if vs >= 2.0 and trend_5 > 0.3:
            p = min(18, int(vs*8)); ss += p; sr.append(f"VolCompra{vs:.1f}x({p})")
        elif vs >= 1.5:
            p = min(12, int(vs*6)); ss += p; sr.append(f"Vol{vs:.1f}x({p})")
        elif vs >= 1.2:
            ss += 4; sr.append(f"Vol{vs:.1f}x(4)")

        if trend_5 > 1.5 and trend_10 > 2.5: ss += 20; sr.append("Subida++(20)")
        elif trend_5 > 0.8:                   ss += 12; sr.append("Subida+(12)")
        elif trend_5 < -1.0:                  ss -= 15; sr.append("Bajada(-15)")

        if   change < -6.0: p = min(15, int(abs(change)*2));   ss += p; sr.append(f"24h{change:.1f}%({p})")
        elif change < -3.0: p = min(10, int(abs(change)*1.5)); ss += p; sr.append(f"24h{change:.1f}%({p})")
        elif change > 4.0:  ss -= 12; sr.append(f"24h+{change:.1f}%(-12)")

        if near_low:           ss += 12; sr.append("NearLow(12)")
        if green_candles >= 3: ss += 10; sr.append(f"Verdes{green_candles}(10)")
        elif green_candles >= 2: ss += 5; sr.append(f"Verdes{green_candles}(5)")
        if atr_pct > 1.5:    ss += 8; sr.append(f"ATR{atr_pct:.1f}%(8)")
        elif atr_pct > 0.8:  ss += 4; sr.append(f"ATR{atr_pct:.1f}%(4)")

        if mae_score != 0:
            ss += mae_score; sr.append(mae_desc)

        if regime == "TREND_UP":
            ss += 10; sr.append("RegimeAlcista(+10)")
        elif regime == "RANGING":
            ss += 5;  sr.append("RegimeRango(+5)")
        elif regime == "TREND_DOWN":
            ss -= 10; sr.append("RegimeBajista(-10)")

        if pattern_total > 0:
            ss += pattern_total
            for p_name in pattern_list:
                sr.append(p_name)

        sl_dyn = max(SL_PCT, atr_pct * 0.8) if atr_pct > 0 else SL_PCT
        sl_dyn = round(min(sl_dyn, SL_PCT * 2.0), 3)
        tp_dyn = max(TP_PCT, sl_dyn * 1.7, atr_pct * 2.0, TP_MIN_RENTABLE)
        tp_dyn = round(min(tp_dyn, TP_PCT * 2.5), 3)
        if pattern_total >= 30:
            tp_dyn = max(tp_dyn, sl_dyn * 2.0)

        if ss >= score_min:
            return {
                'price':price,'change':change,'score':ss,'reasons':' | '.join(sr),
                'rsi':rsi_min,'vol':vs,'tp_pct':tp_dyn,'sl_pct':sl_dyn,
                'bb_pos':round(bb_pos*100,1),'atr_pct':round(atr_pct,2),
                'score_min':score_min,'regime':regime,'mae_regime':mae_regime,
                'mae_pos':round(mae_pos*100,1),'patterns':pattern_list,
                'rr':round(tp_dyn/sl_dyn,2),
            }
        return None

    # ---------------------------------------------------------------- FIX: órdenes LONG

    def _place_long_entry(self, symbol, usdt_qty, price):
        """
        FIX 5: entrada LONG con mínimo siempre respetado.
        - usdt_qty forzado antes de calcular qty_c
        - fallback quoteOrderQty usa el usdt real (no qty_c*ppc que podía ser ~$0)
        """
        # FIX: garantizar mínimo ANTES de cualquier cálculo
        usdt_qty = max(usdt_qty, FORCE_MIN_USDT, MIN_TRADE)

        qty_c, qty_val = self._qty_contratos(symbol, price, usdt_qty)
        if not qty_c or qty_c <= 0:
            log.error(f"  ENTRADA ABORTADA {symbol}: qty_c inválido"); return None, None

        # FIX: verificar que el valor calculado sea suficiente
        if qty_val < FORCE_MIN_USDT:
            log.error(f"  ENTRADA ABORTADA {symbol}: valor ${qty_val:.2f} < ${FORCE_MIN_USDT}")
            return None, None

        log.info(f"  Intentando LONG {symbol}: {qty_c} cts = ${qty_val:.2f} USDT")

        # Método 1: LIMIT maker
        if USE_LIMIT_ORDERS:
            limit_price = round(price * (1 - LIMIT_OFFSET_PCT / 100), 8)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':'BUY','positionSide':'LONG',
                'type':'LIMIT','price':str(limit_price),
                'quantity':str(qty_c),'timeInForce':'GTC',
            }).json()
            if d.get('code') == 0:
                log.info(f"  ENTRADA LÍMITE OK {qty_c} cts @ ${limit_price:.8f} (${qty_val:.2f})")
                return d.get('data',{}).get('orderId','OK'), qty_c
            if 'margin' in str(d.get('msg','')).lower():
                log.error(f"  Margen insuficiente — abortando"); return None, None
            log.warning(f"  Límite falló [{d.get('code')}] — fallback MARKET")

        # Método 2: MARKET con quantity
        d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
            'symbol':symbol,'side':'BUY','positionSide':'LONG',
            'type':'MARKET','quantity':str(qty_c),
        }).json()
        if d.get('code') == 0:
            log.info(f"  ENTRADA MARKET OK {qty_c} cts (${qty_val:.2f})")
            return d.get('data',{}).get('orderId','OK'), qty_c

        # Método 3: FIX quoteOrderQty usa usdt_qty directamente (no qty_val que podía ser ~$0)
        usdt_safe = round(max(usdt_qty, FORCE_MIN_USDT), 2)
        log.warning(f"  qty_c falló — fallback quoteOrderQty ${usdt_safe}")
        d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', {
            'symbol':symbol,'side':'BUY','positionSide':'LONG',
            'type':'MARKET','quoteOrderQty':str(usdt_safe),
        }).json()
        if d2.get('code') == 0:
            log.info(f"  ENTRADA quoteOrderQty OK ${usdt_safe}")
            return d2.get('data',{}).get('orderId','OK'), qty_c
        log.error(f"  TODOS los métodos fallaron [{d2.get('code')}]: {d2.get('msg')}")
        return None, None

    def _esperar_posicion(self, symbol, timeout=60):
        log.info(f"  Esperando confirmación LONG {symbol}...")
        for i in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                                  {'symbol': symbol}).json()
                if d.get('code') == 0:
                    for p in (d.get('data') or []):
                        amt = float(p.get('positionAmt', 0) or 0)
                        ps  = str(p.get('positionSide', '')).upper()
                        if amt > 0 or ps == 'LONG':
                            entry_real = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                            qty_real   = abs(amt)
                            if qty_real > 0:
                                log.info(f"  Confirmado: qty={qty_real:.4f} entry=${entry_real:.8f} ({i+1}s)")
                                return qty_real, entry_real
            except: pass
            time.sleep(1)
        log.warning(f"  Timeout {timeout}s — posición no confirmada")
        return None, None

    def _cancelar_ordenes(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/trade/openOrders',
                              {'symbol': symbol}).json()
            if d.get('code') == 0:
                for o in (d.get('data', {}).get('orders') or []):
                    oid = o.get('orderId', '')
                    if oid:
                        bingx_request('DELETE', '/openApi/swap/v2/trade/order',
                                      {'symbol': symbol, 'orderId': str(oid)})
        except: pass

    def _cond_order(self, symbol, qty_c, stop_price, otype):
        if not qty_c or qty_c <= 0: return False
        try:
            is_tp = "TAKE" in otype
            if is_tp:
                params = {
                    'symbol':symbol,'side':'SELL','positionSide':'LONG',
                    'type':'TAKE_PROFIT','quantity':str(qty_c),
                    'price':str(round(stop_price, 8)),
                    'stopPrice':str(round(stop_price, 8)),'timeInForce':'GTC',
                }
                d = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json()
                ok = d.get('code') == 0
                if ok:
                    log.info(f"  TP ✅ límite maker @ ${stop_price:.8f}")
                else:
                    log.warning(f"  TP límite rechazado — fallback TAKE_PROFIT_MARKET")
                    p2 = {'symbol':symbol,'side':'SELL','positionSide':'LONG',
                          'type':'TAKE_PROFIT_MARKET','quantity':str(qty_c),
                          'stopPrice':str(round(stop_price, 8))}
                    d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', p2).json()
                    ok = d2.get('code') == 0
                    if ok: log.info(f"  TP ✅ MARKET fallback")
                    else:  log.error(f"  TP ❌ [{d2.get('code')}]: {d2.get('msg')}")
            else:
                limit_price = round(stop_price * (1 - SL_LIMIT_OFFSET), 8)
                params = {
                    'symbol':symbol,'side':'SELL','positionSide':'LONG',
                    'type':'STOP','quantity':str(qty_c),
                    'price':str(limit_price),
                    'stopPrice':str(round(stop_price, 8)),'timeInForce':'GTC',
                }
                d = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json()
                ok = d.get('code') == 0
                if ok:
                    log.info(f"  SL ✅ límite maker trigger=${stop_price:.8f}")
                else:
                    log.warning(f"  SL límite rechazado — fallback STOP_MARKET")
                    p2 = {'symbol':symbol,'side':'SELL','positionSide':'LONG',
                          'type':'STOP_MARKET','quantity':str(qty_c),
                          'stopPrice':str(round(stop_price, 8))}
                    d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', p2).json()
                    ok = d2.get('code') == 0
                    if ok: log.info(f"  SL ✅ STOP_MARKET fallback")
                    else:  log.error(f"  SL ❌ [{d2.get('code')}]: {d2.get('msg')}")
            return ok
        except Exception as e:
            log.error(f"  {otype} excepción: {e}"); return False

    def _close_long(self, symbol, t):
        qty_c = t.get('qty_c', 0)
        usdt  = t.get('usdt_qty', POSITION_SIZE)
        if qty_c and qty_c > 0:
            cur_price = t.get('entry', 0)
            try:
                tk = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker",
                                  params={'symbol': symbol}, timeout=5).json()
                if tk.get('code') == 0 and tk.get('data'):
                    cur_price = float(tk['data'].get('lastPrice', cur_price))
            except: pass
            if cur_price > 0:
                limit_price = round(cur_price * (1 + 0.0005), 8)
                d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                    'symbol':symbol,'side':'SELL','positionSide':'LONG',
                    'type':'LIMIT','quantity':str(qty_c),
                    'price':str(limit_price),'timeInForce':'IOC','reduceOnly':'true',
                }).json()
                if d.get('code') == 0:
                    log.info(f"  Cierre LONG límite IOC @ ${limit_price:.8f}")
                    return True
                log.warning(f"  Cierre límite rechazado — fallback MARKET")
        params = ({'symbol':symbol,'side':'SELL','positionSide':'LONG',
                   'type':'MARKET','quantity':str(qty_c),'reduceOnly':'true'}
                  if qty_c and qty_c > 0 else
                  {'symbol':symbol,'side':'SELL','positionSide':'LONG',
                   'type':'MARKET','quoteOrderQty':str(round(max(usdt, FORCE_MIN_USDT), 2)),'reduceOnly':'true'})
        ok = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json().get('code') == 0
        if ok: log.info(f"  Cierre LONG MARKET OK")
        return ok

    def _tiene_posicion(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {'symbol':symbol}).json()
            if d.get('code') == 0:
                for p in (d.get('data') or []):
                    amt = float(p.get('positionAmt',0) or 0)
                    if abs(amt) > 0:
                        return True, 'LONG' if amt > 0 else 'SHORT'
        except: pass
        return False, None

    # ---------------------------------------------------------------- FIX: lifecycle

    def open_trade(self, symbol, sig):
        if not AUTO_TRADING:
            log.info(f"  [SEÑAL] LONG {symbol} score:{sig['score']:.0f}"); return False
        if symbol in self.open_trades: return False
        tiene, dir_bx = self._tiene_posicion(symbol)
        if tiene: log.info(f"  {symbol} ya tiene {dir_bx} — skip"); return False

        price = sig['price']

        # FIX 6: usdt_qty siempre garantizado, sin posibilidad de bajar del mínimo
        usdt_qty = round(max(POSITION_SIZE, FORCE_MIN_USDT, MIN_TRADE), 2)
        log.info(f"  [TRADE] usdt_qty={usdt_qty} (POSITION_SIZE={POSITION_SIZE} FORCE_MIN={FORCE_MIN_USDT})")

        # Validación previa
        test_qty, test_val = self._qty_contratos(symbol, price, usdt_qty)
        if not test_qty or test_val < FORCE_MIN_USDT:
            log.warning(f"  {symbol} rechazado: ${test_val:.2f} < ${FORCE_MIN_USDT}"); return False

        tp_price = price * (1 + sig['tp_pct'] / 100)
        sl_price = price * (1 - sig['sl_pct'] / 100)

        log.info(f"\n  ➤ LONG {symbol}")
        log.info(f"  Score:{sig['score']:.0f}/{sig['score_min']:.0f} | RSI:{sig['rsi']:.0f} | RR:{sig['rr']:.2f}")
        log.info(f"  Capital: ${usdt_qty} USDT | Entry:${price:.8f}")
        log.info(f"  TP:${tp_price:.8f} (+{sig['tp_pct']:.2f}%) SL:${sl_price:.8f} (-{sig['sl_pct']:.2f}%)")
        log.info(f"  {sig['reasons']}")

        oid, qty_c = self._place_long_entry(symbol, usdt_qty, price)
        if not oid: log.error(f"  No se pudo abrir {symbol}"); return False

        qty_real, entry_real = self._esperar_posicion(symbol, timeout=60)
        if qty_real is None:
            self._cancelar_ordenes(symbol); time.sleep(0.5)
            d_mkt = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':'BUY','positionSide':'LONG',
                'type':'MARKET','quantity':str(qty_c),
            }).json()
            if d_mkt.get('code') == 0:
                qty_real, entry_real = self._esperar_posicion(symbol, timeout=30)
            if qty_real is None:
                log.error(f"  CRÍTICO: No confirmada posición {symbol}")
                self._tg(f"<b>🚨 CRÍTICO LONG {symbol}</b>\nNo confirmada. Cerrando emergencia.")
                for _ in range(2):
                    try:
                        bingx_request('POST', '/openApi/swap/v2/trade/order', {
                            'symbol':symbol,'side':'SELL','positionSide':'LONG',
                            'type':'MARKET','quantity':str(qty_c),'reduceOnly':'true',
                        }); time.sleep(1)
                    except: pass
                return False

        qty_final   = qty_real if qty_real else qty_c
        entry_final = entry_real if (entry_real and entry_real > 0) else price
        tp_price    = entry_final * (1 + sig['tp_pct'] / 100)
        sl_price    = entry_final * (1 - sig['sl_pct'] / 100)

        tp_ok = self._cond_order(symbol, qty_final, tp_price, 'TAKE_PROFIT_MARKET')
        time.sleep(0.3)
        sl_ok = self._cond_order(symbol, qty_final, sl_price, 'STOP_MARKET')

        for delay in [1, 2, 3, 5, 8, 13]:
            if tp_ok and sl_ok: break
            log.warning(f"  TP:{tp_ok} SL:{sl_ok} — reintentando en {delay}s")
            self._cancelar_ordenes(symbol); time.sleep(delay)
            if not tp_ok: tp_ok = self._cond_order(symbol, qty_final, tp_price, 'TAKE_PROFIT_MARKET')
            if not sl_ok: sl_ok = self._cond_order(symbol, qty_final, sl_price, 'STOP_MARKET')

        if not sl_ok:
            log.error(f"  CRÍTICO: SL fallido {symbol} — cerrando")
            self._tg(f"<b>🚨 CRÍTICO SL FALLIDO — LONG {symbol}</b>")
            time.sleep(1)
            self._close_long(symbol, {'qty_c':qty_final,'usdt_qty':usdt_qty,'entry':entry_final})
            return False

        self.open_trades[symbol] = {
            'entry':entry_final,'qty_c':qty_final,'usdt_qty':usdt_qty,
            'tp':tp_price,'sl':sl_price,'tp_pct':sig['tp_pct'],'sl_pct':sig['sl_pct'],
            'highest':entry_final,'order_id':oid,'tp_ok':tp_ok,'sl_ok':sl_ok,
            'opened_at':datetime.now(),'score':sig['score'],'patterns':sig['patterns'],
        }
        self.stats['exec'] += 1
        pat_str = f"\nPatrones: {', '.join(sig['patterns'])}" if sig['patterns'] else ""
        self._tg(
            f"<b>🟢 LONG ABIERTO</b>\n<b>{symbol}</b> | Score:{sig['score']:.0f}/100\n"
            f"Entrada: ${entry_final:.8f}\n"
            f"{'✅' if tp_ok else '❌'} TP: ${tp_price:.8f} (+{sig['tp_pct']:.2f}%)\n"
            f"{'✅' if sl_ok else '❌'} SL: ${sl_price:.8f} (-{sig['sl_pct']:.2f}%)\n"
            f"RR: {sig['rr']:.2f}:1 | Capital: ${usdt_qty} x{LEVERAGE}\n"
            f"RSI:{sig['rsi']:.0f} BB:{sig['bb_pos']}% ATR:{sig['atr_pct']:.2f}%"
            f"{pat_str}\n{sig['reasons']}"
        )
        return True

    def close_trade(self, symbol, cur_price, reason):
        if symbol not in self.open_trades: return False
        t = self.open_trades[symbol]
        self._close_long(symbol, t)

        cambio  = (cur_price - t['entry']) / t['entry']
        pnl     = (t['usdt_qty'] * LEVERAGE * cambio) - (t['usdt_qty'] * LEVERAGE * COMISION_ACTUAL)
        pnl_pct = (pnl / t['usdt_qty']) * 100

        self.stats['closed'] += 1; self.stats['pnl'] += pnl
        if pnl > 0: self.stats['wins'] += 1
        else:        self.stats['losses'] += 1

        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        mins  = int((datetime.now() - t['opened_at']).total_seconds() / 60)
        emoji = "✅" if pnl > 0 else "❌"
        reason_cd = 'TP' if 'PROFIT' in reason else 'SL'

        log.info(f"  {emoji} {reason} LONG {symbol} PnL:${pnl:+.3f}({pnl_pct:+.1f}%) {mins}min")
        self._tg(
            f"<b>{emoji} LONG CERRADO — {reason}</b>\n<b>{symbol}</b>\n"
            f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ${t['entry']:.8f} → Exit: ${cur_price:.8f} | {mins}min\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%</b>"
        )
        self._set_cooldown(symbol, reason_cd)
        del self.open_trades[symbol]
        return True

    # ---------------------------------------------------------------- monitor

    async def _sync_bingx(self):
        if not self.open_trades or not AUTO_TRADING: return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            pos = {p.get('symbol'): float(p.get('positionAmt',0) or 0)
                   for p in (d.get('data') or [])
                   if abs(float(p.get('positionAmt',0) or 0)) > 0}
            for sym in list(self.open_trades.keys()):
                if sym not in pos:
                    t   = self.open_trades[sym]
                    tk  = self._ticker(sym)
                    cur = tk['price'] if tk else t['entry']
                    cambio  = (cur - t['entry']) / t['entry']
                    pnl     = (t['usdt_qty'] * LEVERAGE * cambio) - (t['usdt_qty'] * LEVERAGE * COMISION_ACTUAL)
                    pnl_pct = (pnl / t['usdt_qty']) * 100
                    self.stats['closed'] += 1; self.stats['pnl'] += pnl
                    if pnl >= 0: self.stats['wins'] += 1
                    else:         self.stats['losses'] += 1
                    total = self.stats['wins'] + self.stats['losses']
                    wr    = self.stats['wins'] / total * 100 if total else 0
                    emoji = "✅" if pnl >= 0 else "❌"
                    self._tg(f"<b>{emoji} LONG cerrado BingX</b>\n<b>{sym}</b>\n"
                             f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%) | WR:{wr:.1f}%")
                    self._set_cooldown(sym, 'TP' if pnl >= 0 else 'SL')
                    del self.open_trades[sym]
        except Exception as e:
            log.debug(f"sync: {e}")

    async def monitor_trades(self):
        await self._sync_bingx()
        for sym in list(self.open_trades.keys()):
            try:
                t   = self.open_trades[sym]
                tk  = self._ticker(sym)
                if not tk: continue
                cur     = tk['price']
                pnl_pct = (cur - t['entry']) / t['entry'] * 100

                if TRAILING and cur > t['highest']:
                    t['highest'] = cur
                    if pnl_pct >= TRAILING_START:
                        new_sl = t['entry'] + (cur - t['entry']) * (TRAILING_LOCK / 100)
                        if new_sl > t['sl']:
                            t['sl'] = new_sl
                            log.info(f"  Trailing LONG {sym}: SL=${new_sl:.8f}")

                pnl_leverage = pnl_pct * LEVERAGE
                if pnl_leverage < -MAX_LOSS_PCT:
                    log.error(f"  EMERGENCIA LONG {sym}: {pnl_leverage:+.1f}%")
                    self._tg(f"<b>🚨 EMERGENCIA LONG {sym}</b>\nPnL: {pnl_leverage:+.1f}%")
                    self.close_trade(sym, cur, "STOP LOSS EMERGENCIA"); continue

                if abs(pnl_pct) > 0.3:
                    log.info(f"  LONG {sym}: {pnl_pct:+.2f}% | cur:${cur:.8f}")

                if cur >= t['tp']:   self.close_trade(sym, cur, "TAKE PROFIT")
                elif cur <= t['sl']: self.close_trade(sym, cur, "STOP LOSS")
            except Exception as e:
                log.debug(f"Monitor LONG {sym}: {e}")

    def _reporte_horario(self):
        if datetime.now() - self._last_report < timedelta(hours=1): return
        self._last_report = datetime.now()
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        pos_txt = "".join(
            f"  {sym}: {((self._ticker(sym) or {'price':t['entry']})['price'] - t['entry'])/t['entry']*100:+.2f}%\n"
            for sym, t in self.open_trades.items()
        )
        self._tg(
            f"<b>📊 Reporte horario LONGS</b>\n"
            f"PnL: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%\n"
            f"({self.stats['wins']}W/{self.stats['losses']}L | {self.stats['closed']} trades)\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES} | BTC 1h:{self._btc_1h:+.2f}%\n"
            + (pos_txt if pos_txt else "  sin posiciones\n")
        )

    def _tg(self, msg):
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id':TELEGRAM_CHAT,'text':msg,'parse_mode':'HTML'}, timeout=6)
        except: pass

    # ---------------------------------------------------------------- loop

    async def run(self):
        log.info("\n▶  Bot LONG v1.1 arrancado\n")
        iteration, last_refresh = 0, 0
        while True:
            try:
                iteration += 1
                if time.time() - last_refresh > 600:
                    self._get_symbols(); last_refresh = time.time()

                self._update_btc_trend()

                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0
                btc_st = "⚠️ BLOQUEADO" if self._btc_1h <= -BTC_BEAR_BLOCK_PCT else "OK"
                hora_st = "🌙 HORA BAJA" if not self._hora_ok() else "☀️"

                log.info(f"\n{'='*70}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"Abiertos:{len(self.open_trades)}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                log.info(f"  BTC 1h:{self._btc_1h:+.2f}% {btc_st} | {hora_st}")
                log.info(f"{'='*70}\n")

                await self.monitor_trades()
                self._reporte_horario()

                if len(self.open_trades) < MAX_TRADES:
                    found = 0
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES: break
                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            pat_str = f" [{','.join(sig['patterns'])}]" if sig['patterns'] else ""
                            log.info(f"  ★ LONG {sym} score:{sig['score']:.0f} RSI:{sig['rsi']:.0f} RR:{sig['rr']:.2f}{pat_str}")
                            self.open_trade(sym, sig)
                        await asyncio.sleep(0.12)
                        if (i+1) % 25 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)} analizados")
                    log.info(f"\n  {len(self.symbols)} pares | {found} señales LONG")
                else:
                    log.info(f"  Max ({MAX_TRADES}) — esperando cierre")

                log.info(f"\n  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)

            except KeyboardInterrupt:
                log.info("Detenido"); break
            except Exception as e:
                log.error(f"Error loop #{iteration}: {e}")
                await asyncio.sleep(20)

async def main():
    try: await LongBot().run()
    except Exception as e: log.error(f"Error fatal: {e}")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: log.info("Terminado")
