#!/usr/bin/env python3
"""
BOT FLOOP Pro — Python translation of FLOOP Pro (Pine Script -> BingX)
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re
from datetime import datetime, timedelta
from urllib.parse import urlencode

# ============================================================================
# CONFIGURACION
# ============================================================================

def clean(key, default, typ='str'):
    v = os.getenv(key, str(default))
    v = v.strip().strip('"').strip("'").strip()
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

AUTO_TRADING     = clean('AUTO_TRADING_ENABLED',  'true',  'bool')
POSITION_SIZE    = clean('MAX_POSITION_SIZE',       '7',   'float')
MIN_TRADE        = clean('MIN_TRADE_USDT',          '5',   'float')
LEVERAGE         = clean('LEVERAGE',                '3',   'int')
MAX_TRADES       = clean('MAX_OPEN_TRADES',         '3',   'int')
INTERVAL         = clean('CHECK_INTERVAL',         '120',  'int')
MIN_VOLUME       = clean('MIN_VOLUME_24H',      '500000',  'float')
MAX_SYMBOLS      = clean('MAX_SYMBOLS_TO_ANALYZE',  '60',  'int')
ENABLE_LONGS     = clean('ENABLE_LONGS',          'true',  'bool')
ENABLE_SHORTS    = clean('ENABLE_SHORTS',         'true',  'bool')
USE_LIMIT_ORDERS = clean('USE_LIMIT_ORDERS',      'true',  'bool')
TRAILING         = clean('TRAILING_STOP_ENABLED', 'true',  'bool')
BTC_FILTER_PCT   = clean('BTC_FILTER_PCT',         '2.0',  'float')

# FLOOP Core
SENSITIVITY      = clean('FLOOP_SENSITIVITY',       '6',   'int')
ATR_LEN          = clean('FLOOP_ATR_LENGTH',        '14',  'int')
ATR_MULT         = clean('FLOOP_ATR_MULT',          '0.8', 'float')
EMA_FAST         = clean('FLOOP_EMA_FAST',          '60',  'int')
EMA_SLOW         = clean('FLOOP_EMA_SLOW',         '200',  'int')
EMA_FILTER_ON    = clean('FLOOP_EMA_FILTER',       'true', 'bool')
HTF_INTERVAL     = clean('FLOOP_HTF_TF',           '1h',   'str')
ADX_FILTER_ON    = clean('FLOOP_ADX_FILTER',       'true', 'bool')
ADX_LEN          = clean('FLOOP_ADX_LENGTH',        '14',  'int')
ADX_THRESH       = clean('FLOOP_ADX_THRESH',        '20',  'float')
CHOP_FILTER_ON   = clean('FLOOP_CHOP_FILTER',      'true', 'bool')
CHOP_LEN         = clean('FLOOP_CHOP_LENGTH',       '14',  'int')
CHOP_THRESH      = clean('FLOOP_CHOP_THRESH',      '61.8', 'float')
COOLDOWN_BARS    = clean('FLOOP_COOLDOWN_BARS',      '5',   'int')
TP_MULT          = clean('TP_ATR_MULT',             '3.0', 'float')
SL_MULT          = clean('SL_ATR_MULT',             '2.2', 'float')
TP_MIN_PCT       = clean('TP_MIN_PCT',              '1.2', 'float')
TP_MAX_PCT       = clean('TP_MAX_PCT',              '6.0', 'float')
SL_MIN_PCT       = clean('SL_MIN_PCT',              '0.8', 'float')
SL_MAX_PCT       = clean('SL_MAX_PCT',              '3.0', 'float')
MIN_SCORE        = clean('MIN_SCORE',                '8',   'int')

SKIP_HOURS_UTC   = {0, 1}
LIMIT_OFFSET_PCT = 0.05
BASE_URL         = "https://open-api.bingx.com"
COMISION_MAKER   = 0.0002
COMISION_TAKER   = 0.0005
COMISION_ACTUAL  = COMISION_MAKER if USE_LIMIT_ORDERS else COMISION_TAKER

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

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
            hdr = {'X-BX-APIKEY': BINGX_API_KEY, 'Content-Type': 'application/x-www-form-urlencoded'}
            r = requests.get(url, headers=hdr, timeout=12) if method == 'GET' \
                else requests.post(url, headers=hdr, timeout=12)
            return r
        except Exception as e:
            if attempt < retries: time.sleep(1.5)
            else: raise

# ============================================================================
# INDICADORES FLOOP PRO
# ============================================================================

def calc_ema(prices, period):
    if not prices: return 0.0
    n = len(prices); period = min(period, n)
    k = 2.0 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]: e = p * k + e * (1 - k)
    return e

def calc_rma(values, period):
    if not values: return 0.0
    period = min(period, len(values))
    alpha  = 1.0 / period
    result = sum(values[:period]) / period
    for v in values[period:]: result = alpha * v + (1 - alpha) * result
    return result

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2: return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return calc_rma(trs, period) if trs else 0.0

def calc_atr_series(highs, lows, closes, period=14):
    if len(closes) < 2: return [0.0]
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    result, out, alpha = trs[0], [], 1.0 / period
    for i, tr in enumerate(trs):
        result = sum(trs[:i+1])/(i+1) if i < period else alpha*tr + (1-alpha)*result
        out.append(result)
    return out

def calc_range_filter(closes, highs, lows, sensitivity=6, atr_len=14, atr_mult=0.8):
    """
    FLOOP Core Range Filter — traduccion directa de Pine:
      rng  = ATR x atr_mult x (sensitivity / 8.0)
      filt = trailing: sube si close > filt+rng, baja si close < filt-rng
      trend: 1 si filt subiendo, -1 si bajando
      sig: cambio de trend
    """
    n = len(closes)
    if n < atr_len + 2: return [closes[-1]]*n, [0]*n, [0]*n

    atr_vals = calc_atr_series(highs, lows, closes, atr_len)
    atr_full = [atr_vals[0]] + atr_vals

    filt_s, trend_s, sig_s = [0.0]*n, [0]*n, [0]*n
    filt_s[0] = closes[0]

    for i in range(1, n):
        atr_i = atr_full[i] if i < len(atr_full) else atr_full[-1]
        rng   = atr_i * atr_mult * (sensitivity / 8.0)
        pf    = filt_s[i-1]
        if   closes[i] > pf + rng: filt_s[i] = closes[i] - rng
        elif closes[i] < pf - rng: filt_s[i] = closes[i] + rng
        else:                       filt_s[i] = pf

        pt = trend_s[i-1]
        if   filt_s[i] > filt_s[i-1]: trend_s[i] = 1
        elif filt_s[i] < filt_s[i-1]: trend_s[i] = -1
        else:                           trend_s[i] = pt
        sig_s[i] = trend_s[i] if trend_s[i] != pt else 0

    return filt_s, trend_s, sig_s

def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 2: return 0.0, 0.0, 0.0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up, down = highs[i]-highs[i-1], lows[i-1]-lows[i]
        plus_dm.append(up   if up > down and up > 0   else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    rma_tr = calc_rma(trs, period)
    if rma_tr == 0: return 0.0, 0.0, 0.0
    di_p  = 100 * calc_rma(plus_dm, period)  / rma_tr
    di_m  = 100 * calc_rma(minus_dm, period) / rma_tr
    denom = di_p + di_m
    if denom == 0: return 0.0, di_p, di_m
    dx_s = []
    for i in range(len(trs)):
        rt   = calc_rma(trs[:i+1], period)
        rp   = calc_rma(plus_dm[:i+1], period)
        rm   = calc_rma(minus_dm[:i+1], period)
        d_p  = 100*rp/rt if rt else 0
        d_m  = 100*rm/rt if rt else 0
        den  = d_p + d_m
        dx_s.append(abs(d_p - d_m) / den * 100 if den else 0)
    return calc_rma(dx_s, period), di_p, di_m

def calc_choppiness(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 2: return 50.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, n)]
    atr_sum = sum(trs[-period:])
    rng     = max(highs[-period:]) - min(lows[-period:])
    if rng <= 0 or atr_sum <= 0: return 50.0
    return 100 * math.log10(atr_sum / rng) / math.log10(period)

def calc_momentum_roc(closes):
    n = len(closes)
    roc5  = (closes[-1]-closes[-6])  / closes[-6]  * 100 if n > 6  else 0.0
    roc10 = (closes[-1]-closes[-11]) / closes[-11] * 100 if n > 11 else 0.0
    roc20 = (closes[-1]-closes[-21]) / closes[-21] * 100 if n > 21 else 0.0
    return roc5, roc10, roc20, roc5>0 and roc10>0 and roc20>0, roc5<0 and roc10<0 and roc20<0

def calc_atr_rank(highs, lows, closes, period=14, lookback=60):
    n = len(closes)
    if n < 2: return 50.0, 0.0
    atr_now  = calc_atr(highs[-lookback:], lows[-lookback:], closes[-lookback:], period)
    atr_norm = atr_now / closes[-1] * 100 if closes[-1] > 0 else 0.0
    count = sum(1 for k in range(min(lookback, n))
                if calc_atr(highs[max(0,n-k-period-2):n-k],
                             lows[max(0,n-k-period-2):n-k],
                             closes[max(0,n-k-period-2):n-k], period) <= atr_now)
    return round(count / min(lookback, n) * 100), atr_norm

def calc_tp_sl(price, direction, atr, tp_mult, sl_mult, tp_min, tp_max, sl_min, sl_max):
    atr_pct = (atr / price * 100) if price > 0 else 1.0
    tp_pct  = max(tp_min, min(tp_max, atr_pct * tp_mult))
    sl_pct  = max(sl_min, min(sl_max, atr_pct * sl_mult))
    if tp_pct < sl_pct * 1.3: tp_pct = sl_pct * 1.3
    if direction == 'LONG':
        return price*(1+tp_pct/100), price*(1-sl_pct/100), round(tp_pct,3), round(sl_pct,3)
    return price*(1-tp_pct/100), price*(1+sl_pct/100), round(tp_pct,3), round(sl_pct,3)

# ============================================================================
# BOT FLOOP PRO
# ============================================================================

class FloopBot:

    def __init__(self):
        dirs = (['LONGS'] if ENABLE_LONGS else []) + (['SHORTS'] if ENABLE_SHORTS else [])
        log.info("=" * 65)
        log.info("  BOT FLOOP Pro — Range Filter ML (Pine -> Python)")
        log.info("=" * 65)
        log.info(f"  Modo:        {'AUTO' if AUTO_TRADING else 'SENALES SOLO'}")
        log.info(f"  Capital:     ${POSITION_SIZE} USDT x{LEVERAGE}")
        log.info(f"  Score min:   {MIN_SCORE}/14  (8=MED, 11=HIGH)")
        log.info(f"  Sensitivity: {SENSITIVITY}  ATR:{ATR_LEN}x{ATR_MULT}")
        log.info(f"  EMA:         {EMA_FAST}/{EMA_SLOW}  Filter={'ON' if EMA_FILTER_ON else 'OFF'}")
        log.info(f"  ADX:         {'ON' if ADX_FILTER_ON else 'OFF'} >={ADX_THRESH}  "
                 f"Chop:{'ON' if CHOP_FILTER_ON else 'OFF'} <={CHOP_THRESH}")
        log.info(f"  TP:          {TP_MULT}xATR  SL:{SL_MULT}xATR")
        log.info(f"  Dirs:        {' + '.join(dirs)}")
        log.info("=" * 65)

        self.symbols      = []
        self.open_trades  = {}
        self._contracts   = {}
        self._cooldowns   = {}
        self._rf_state    = {}   # {symbol: {tf: bars_since_signal}}
        self._last_report = datetime.now()
        self._btc_1h      = 0.0
        self._btc_4h      = 0.0
        self._balance     = 0.0
        self.stats        = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0}

        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._reconciliar_posiciones()
        self._tg(
            f"<b>FLOOP Pro iniciado</b>\n"
            f"Range Filter ML | Score >= {MIN_SCORE}/14\n"
            f"Sensitivity:{SENSITIVITY} | EMA:{EMA_FAST}/{EMA_SLOW}\n"
            f"TP:{TP_MULT}xATR | SL:{SL_MULT}xATR\n"
            f"Capital: ${POSITION_SIZE} x{LEVERAGE} | Balance: ${self._balance:.2f}\n"
            f"Dirs: {' + '.join(dirs)}"
        )

    # ---------------------------------------------------------------- setup

    def _extraer_balance(self, d):
        try:
            data = d.get('data', {})
            if isinstance(data, list): data = data[0] if data else {}
            bal = data.get('balance', None)
            if isinstance(bal, dict):
                for k in ['equity','balance','availableMargin','availableBalance']:
                    v = bal.get(k)
                    if v is not None:
                        try: return float(str(v) or 0)
                        except: continue
            for k in ['equity','balance','availableMargin','availableBalance','walletBalance']:
                v = data.get(k)
                if v is not None and not isinstance(v, dict):
                    try: return float(str(v) or 0)
                    except: continue
            def buscar(obj, depth=0):
                if depth > 3: return None
                if isinstance(obj, (int, float)): return float(obj)
                if isinstance(obj, str):
                    try: return float(obj)
                    except: return None
                if isinstance(obj, dict):
                    for k in ['equity','balance','availableMargin','availableBalance']:
                        if k in obj:
                            r = buscar(obj[k], depth+1)
                            if r is not None and r > 0: return r
                if isinstance(obj, list) and obj: return buscar(obj[0], depth+1)
                return None
            return buscar(data) or 0.0
        except Exception as e:
            log.error(f"  Error balance: {e}"); return 0.0

    def _verify(self):
        global AUTO_TRADING
        if not AUTO_TRADING: return
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            log.error("  API keys vacias"); AUTO_TRADING = False; return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                self._balance = self._extraer_balance(d)
                log.info(f"BingX OK | Balance: ${self._balance:.2f} USDT")
            else:
                log.error(f"BingX error [{d.get('code')}]: {d.get('msg')}"); AUTO_TRADING = False
        except Exception as e:
            log.error(f"Error API: {e}"); AUTO_TRADING = False

    def _update_balance(self):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0: self._balance = self._extraer_balance(d)
        except: pass
        return self._balance

    def _balance_suficiente(self):
        bal = self._update_balance()
        needed = POSITION_SIZE / LEVERAGE
        if bal < needed:
            log.warning(f"  Balance ${bal:.2f} < margen ${needed:.2f} -- skip"); return False
        return True

    def _set_leverage(self, symbol, direction):
        try: bingx_request('POST', '/openApi/swap/v2/trade/leverage',
                           {'symbol':symbol,'side':direction,'leverage':str(LEVERAGE)})
        except: pass

    def _load_contracts(self):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/contracts", timeout=15).json()
            if d.get('code') == 0:
                for c in d.get('data', []):
                    self._contracts[c.get('symbol','')] = {
                        'step': float(c.get('tradeMinQuantity', 1)),
                        'prec': int(c.get('quantityPrecision', 2)),
                        'ctval': float(c.get('contractSize', 1)),
                    }
                log.info(f"Contratos: {len(self._contracts)}")
        except Exception as e: log.warning(f"Error contratos: {e}")

    def _get_symbols(self):
        NO = ['DOW','JONES','SP500','SPX','SPY','QQQ','NASDAQ','RUSSELL','DAX','FTSE',
              'CAC','NIKKEI','HANG','BOVESPA','IBEX','US30','NAS100','US500','DJI','INDEX',
              'GOLD','SILVER','XAU','XAG','PAXG','XAUT','OIL','BRENT','WTI','CRUDE',
              'GAS','GASOLINE','PLATINUM','PALLADIUM','COPPER','NICKEL','ZINC','IRON',
              'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN','MSTR',
              'EUR','GBP','JPY','CHF','AUD','CAD','NZD',
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
        except Exception as e: log.warning(f"Error simbolos: {e}")
        self.symbols = ['BTC-USDT','ETH-USDT','SOL-USDT','BNB-USDT','XRP-USDT']

    def _reconciliar_posiciones(self):
        if not AUTO_TRADING: return
        log.info("  Reconciliando posiciones...")
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            recuperadas = 0
            for p in (d.get('data') or []):
                try: amt = float(p.get('positionAmt', 0) or 0)
                except: continue
                if abs(amt) == 0: continue
                sym = p.get('symbol', '')
                if not sym: continue
                try: lev = int(float(p.get('leverage', 0) or 0))
                except: lev = 0
                if lev != 0 and lev != LEVERAGE: continue
                try: entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                except: entry = 0
                if entry <= 0:
                    tk = self._ticker(sym); entry = tk['price'] if tk else 0
                if entry <= 0: continue
                direction = 'LONG' if amt > 0 else 'SHORT'
                qty_c = abs(amt)
                tp_p  = entry*(1+2.0/100) if direction=='LONG' else entry*(1-2.0/100)
                sl_p  = entry*(1-1.0/100) if direction=='LONG' else entry*(1+1.0/100)
                tp_ok = self._cond_order(sym, direction, qty_c, tp_p, 'TAKE_PROFIT_MARKET')
                time.sleep(0.3)
                sl_ok = self._cond_order(sym, direction, qty_c, sl_p, 'STOP_MARKET')
                self.open_trades[sym] = {
                    'direction':direction,'entry':entry,'qty_c':qty_c,'usdt_qty':POSITION_SIZE,
                    'tp':tp_p,'sl':sl_p,'tp_pct':2.0,'sl_pct':1.0,
                    'highest':entry,'lowest':entry,'order_id':'RECONCILIADO',
                    'tp_ok':tp_ok,'sl_ok':sl_ok,'opened_at':datetime.now(),'score':0,
                }
                recuperadas += 1
                log.info(f"  {'Long' if direction=='LONG' else 'Short'} {sym} reconciliado")
            log.info(f"  Reconciliacion: {recuperadas} posiciones")
        except Exception as e: log.error(f"  Error reconciliacion: {e}")

    # ---------------------------------------------------------------- datos

    def _klines(self, symbol, interval='15m', limit=150):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol':symbol,'interval':interval,'limit':limit}, timeout=12).json()
            if d.get('code') == 0 and d.get('data'):
                k = d['data']
                return ([float(x['close']) for x in k], [float(x['high']) for x in k],
                        [float(x['low'])   for x in k], [float(x['volume']) for x in k],
                        [float(x['open'])  for x in k])
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
            c1h, *_ = self._klines('BTC-USDT', '1h', 3)
            if c1h and len(c1h) >= 2: self._btc_1h = (c1h[-1]-c1h[-2])/c1h[-2]*100
            c4h, *_ = self._klines('BTC-USDT', '4h', 3)
            if c4h and len(c4h) >= 2: self._btc_4h = (c4h[-1]-c4h[-2])/c4h[-2]*100
        except: pass

    # ---------------------------------------------------------------- sizing

    def _qty_contratos(self, symbol, price, usdt_amount=None):
        if usdt_amount is None: usdt_amount = POSITION_SIZE
        info  = self._contracts.get(symbol, {'step':1.0,'prec':2,'ctval':1.0})
        step  = max(info['step'], 0.0001)
        prec  = info['prec']
        ppc   = price * info.get('ctval', 1.0) if info.get('ctval', 1.0) != 1.0 else price
        if ppc <= 0: return None, 0
        qty = round(math.ceil(usdt_amount / ppc / step) * step, prec)
        val = qty * ppc
        i = 0
        while val < MIN_TRADE and i < 500: qty += step; qty = round(qty, prec); val = qty*ppc; i+=1
        if val > usdt_amount * 1.3:
            qty = round(math.floor((usdt_amount*1.3/ppc)/step)*step, prec); val = qty*ppc
        log.info(f"    qty: {qty} x ${ppc:.6f} = ${val:.2f} USDT")
        return qty, round(val, 4)

    def _cooldown_trade_ok(self, symbol):
        ts = self._cooldowns.get(symbol)
        return not (ts and (time.time()-ts) < 15*60)

    def _hora_ok(self):
        return datetime.utcnow().hour not in SKIP_HOURS_UTC

    # ---------------------------------------------------------------- ANALISIS FLOOP

    def _floop_tf(self, symbol, interval, bars_since_prev=999):
        """
        Calcula todos los componentes FLOOP para un timeframe.
        Retorna dict completo o None si datos insuficientes.
        """
        closes, highs, lows, vols, opens = self._klines(symbol, interval, 150)
        if not closes or len(closes) < 40: return None

        # Range Filter
        filt_s, trend_s, sig_s = calc_range_filter(closes, highs, lows, SENSITIVITY, ATR_LEN, ATR_MULT)
        rf_trend = trend_s[-1]
        rf_sig   = sig_s[-1]   # 1=new long, -1=new short, 0=none

        # ATR
        atr_val  = calc_atr(highs, lows, closes, ATR_LEN)
        atr_norm = atr_val / closes[-1] * 100 if closes[-1] > 0 else 0.0
        atr_rank, _ = calc_atr_rank(highs, lows, closes, ATR_LEN, 60)

        # Momentum ROC (Pine: roc5/10/20)
        roc5, roc10, roc20, mom_bull, mom_bear = calc_momentum_roc(closes)
        mom_aligned = (rf_trend==1 and mom_bull) or (rf_trend==-1 and mom_bear)
        mom_partial = (rf_trend==1 and roc5>0) or (rf_trend==-1 and roc5<0)

        # EMA (Pine: ema_fast/slow, slope, cross, price position)
        ema_f = calc_ema(closes, EMA_FAST)
        ema_s = calc_ema(closes, EMA_SLOW)
        ema_f_prev = calc_ema(closes[:-1], EMA_FAST) if len(closes) > EMA_FAST else ema_f

        ema_cross_bull  = ema_f > ema_s
        ema_price_above = closes[-1] > ema_f
        ema_slope_up    = ema_f > ema_f_prev
        ema_all_bull    = ema_cross_bull and ema_price_above and ema_slope_up

        ema_cross_bear  = ema_f < ema_s
        ema_price_below = closes[-1] < ema_f
        ema_slope_down  = ema_f < ema_f_prev
        ema_all_bear    = ema_cross_bear and ema_price_below and ema_slope_down

        ema_cond1 = ema_cross_bull if rf_trend==1 else ema_cross_bear
        ema_cond2 = ema_price_above if rf_trend==1 else ema_price_below
        ema_fully_aligned = ema_all_bull if rf_trend==1 else ema_all_bear

        # score_ema = min(ema_cond1 + ema_cond2 + mom_aligned + mom_partial, 4)
        score_ema = min((1 if ema_cond1 else 0) + (1 if ema_cond2 else 0) +
                        (1 if mom_aligned else 0) + (1 if mom_partial else 0), 4)

        # ADX
        adx_val, _, _ = calc_adx(highs, lows, closes, ADX_LEN)
        adx_trending  = adx_val >= ADX_THRESH

        # Choppiness Index
        chop_idx   = calc_choppiness(highs, lows, closes, CHOP_LEN)
        chop_clear = chop_idx <= CHOP_THRESH

        # Cooldown de barras (reemplaza `bars_since_signal` de Pine)
        bars_since = bars_since_prev + 1
        if rf_sig != 0: bars_since = 0
        cooldown_clear = bars_since >= COOLDOWN_BARS

        # Chop Gate + Penalty
        chop_gate    = (not ADX_FILTER_ON or adx_trending) and \
                       (not CHOP_FILTER_ON or chop_clear)   and cooldown_clear
        chop_penalty = ((-1 if ADX_FILTER_ON  and not adx_trending else 0) +
                        (-1 if CHOP_FILTER_ON and not chop_clear    else 0))

        # Volatility score (0-2)
        score_vol = min((1 if atr_rank < 80 else 0) + (1 if atr_norm < 1.5 else 0), 2)

        # Sensitivity cross-check (S:12 = 2pt, S:16 = 1pt)
        _, ts12, _ = calc_range_filter(closes, highs, lows, 12, ATR_LEN, ATR_MULT)
        _, ts16, _ = calc_range_filter(closes, highs, lows, 16, ATR_LEN, ATR_MULT)
        score_sens = (2 if ts12[-1]==rf_trend else 0) + (1 if ts16[-1]==rf_trend else 0)

        # EMA gate
        ema_gate = ema_fully_aligned if EMA_FILTER_ON else True

        # Senales finales (como Pine: long_sig = long_sig_raw and ema_gate and chop_gate)
        long_sig  = (rf_sig == 1)  and ema_gate and chop_gate
        short_sig = (rf_sig == -1) and ema_gate and chop_gate

        return {
            'rf_trend':rf_trend, 'rf_sig':rf_sig,
            'long_sig':long_sig, 'short_sig':short_sig,
            'ema_fully_aligned':ema_fully_aligned,
            'chop_gate':chop_gate, 'chop_penalty':chop_penalty,
            'score_ema':score_ema, 'score_vol':score_vol, 'score_sens':score_sens,
            'adx':adx_val, 'adx_trending':adx_trending,
            'chop_idx':chop_idx,
            'atr_val':atr_val, 'atr_norm':atr_norm, 'atr_rank':atr_rank,
            'roc5':roc5, 'bars_since':bars_since,
            'closes':closes, 'highs':highs, 'lows':lows,
        }

    def analyze(self, symbol):
        """
        FLOOP Pro scoring completo (0-14):
          HTF Agreement   : 1 pt
          MTF Confluence  : 4 pts (5m/15m/1h/4h)
          Sensitivity     : 3 pts (S:12=2, S:16=1)
          EMA + Momentum  : 4 pts
          Volatility      : 2 pts
          Chop Penalty    : -2 max
        Entrada si score >= MIN_SCORE Y senal activa en 15m.
        """
        if symbol in self.open_trades: return None
        if not self._cooldown_trade_ok(symbol): return None
        if not self._hora_ok(): return None

        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0: return None
        price = ticker['price']

        rf_state = self._rf_state.get(symbol, {})

        # Timeframe principal: 15m
        bs_15m = rf_state.get('15m', 999)
        main   = self._floop_tf(symbol, '15m', bs_15m)
        if not main: return None

        rf_state['15m'] = main['bars_since']
        self._rf_state[symbol] = rf_state

        if not main['long_sig'] and not main['short_sig']: return None

        # HTF
        bs_htf = rf_state.get(HTF_INTERVAL, 999)
        htf    = self._floop_tf(symbol, HTF_INTERVAL, bs_htf)
        rf_state[HTF_INTERVAL] = htf['bars_since'] if htf else 999
        self._rf_state[symbol] = rf_state

        htf_trend = htf['rf_trend'] if htf else 0
        score_htf = 1 if (main['rf_trend']==1 and htf_trend==1) or \
                         (main['rf_trend']==-1 and htf_trend==-1) else 0

        # MTF: 5m, 1h, 4h (+ 15m propio = siempre coincide = +1)
        mtf_trends = {}
        score_mtf  = 1  # 15m siempre coincide consigo mismo
        for tf_interval in ['5m', '1h', '4h']:
            bs = rf_state.get(tf_interval, 999)
            tf = self._floop_tf(symbol, tf_interval, bs)
            if tf:
                rf_state[tf_interval] = tf['bars_since']
                mtf_trends[tf_interval] = tf['rf_trend']
                if tf['rf_trend'] == main['rf_trend']: score_mtf += 1
        score_mtf = min(score_mtf, 4)
        self._rf_state[symbol] = rf_state

        # Score total (0-14, igual que FLOOP Pine)
        score = max(0, min(14,
            score_htf + score_mtf + main['score_sens'] +
            main['score_ema'] + main['score_vol'] + main['chop_penalty']))

        str_label = "HIGH" if score>=11 else "MED" if score>=8 else "LOW" if score>=6 else "WEAK"

        if score < MIN_SCORE: return None

        # Direccion
        direction = None
        if main['long_sig']  and ENABLE_LONGS  and self._btc_1h > -BTC_FILTER_PCT: direction = 'LONG'
        elif main['short_sig'] and ENABLE_SHORTS and self._btc_1h < BTC_FILTER_PCT: direction = 'SHORT'
        if not direction: return None

        # TP / SL
        atr = main['atr_val']
        tp_price, sl_price, tp_pct, sl_pct = calc_tp_sl(
            price, direction, atr,
            TP_MULT, SL_MULT, TP_MIN_PCT, TP_MAX_PCT, SL_MIN_PCT, SL_MAX_PCT)

        mtf_str = ' '.join([f"{k}:{'up' if v==1 else 'dn'}" for k,v in mtf_trends.items()])

        return {
            'signal':direction, 'price':price, 'score':score, 'str_label':str_label,
            'tp_price':tp_price, 'sl_price':sl_price, 'tp_pct':tp_pct, 'sl_pct':sl_pct,
            'atr_val':atr, 'atr_pct':round(main['atr_norm'],2),
            'adx':round(main['adx'],1), 'chop':round(main['chop_idx'],1),
            'roc5':round(main['roc5'],2),
            'score_ema':main['score_ema'], 'score_mtf':score_mtf, 'score_htf':score_htf,
            'score_vol':main['score_vol'], 'score_sens':main['score_sens'],
            'chop_penalty':main['chop_penalty'],
            'mtf_str':mtf_str, 'htf_trend':htf_trend,
            'ema_ok':main['ema_fully_aligned'],
        }

    # ---------------------------------------------------------------- ordenes

    def _place_entry(self, symbol, direction, usdt_qty, price):
        qty_c, val = self._qty_contratos(symbol, price, usdt_qty)
        if not qty_c: return None, None
        side = 'BUY' if direction=='LONG' else 'SELL'
        log.info(f"  Abriendo {direction} {symbol}: {qty_c} cts = ${val:.2f}")
        if USE_LIMIT_ORDERS:
            offset = (1-LIMIT_OFFSET_PCT/100) if direction=='LONG' else (1+LIMIT_OFFSET_PCT/100)
            lp = round(price*offset, 8)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':side,'positionSide':direction,
                'type':'LIMIT','price':str(lp),'quantity':str(qty_c),'timeInForce':'GTC',
            }).json()
            if d.get('code') == 0:
                log.info(f"  LIMITE OK @ ${lp:.6f}")
                return d.get('data',{}).get('orderId','OK'), qty_c
            if 'margin' in str(d.get('msg','')).lower(): return None, None
            log.warning(f"  Limite fallo -- fallback mercado")
        d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
            'symbol':symbol,'side':side,'positionSide':direction,'type':'MARKET','quantity':str(qty_c),
        }).json()
        if d.get('code') == 0: return d.get('data',{}).get('orderId','OK'), qty_c
        log.error(f"  Entrada fallida: {d.get('msg')}"); return None, None

    def _cond_order(self, symbol, direction, qty_c, stop_price, otype):
        if not qty_c or qty_c <= 0: return False
        try:
            is_tp = "TAKE" in otype; lbl = "TP" if is_tp else "SL"
            close_side = 'SELL' if direction=='LONG' else 'BUY'
            params = ({'symbol':symbol,'side':close_side,'positionSide':direction,
                       'type':'TAKE_PROFIT','quantity':str(qty_c),
                       'price':str(round(stop_price,8)),'stopPrice':str(round(stop_price,8)),'timeInForce':'GTC'}
                      if is_tp else
                      {'symbol':symbol,'side':close_side,'positionSide':direction,
                       'type':'STOP_MARKET','quantity':str(qty_c),'stopPrice':str(round(stop_price,8))})
            d  = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json()
            ok = d.get('code') == 0
            if ok: log.info(f"  {lbl} OK @ ${stop_price:.6f}")
            elif is_tp:
                p2 = {'symbol':symbol,'side':close_side,'positionSide':direction,
                      'type':'TAKE_PROFIT_MARKET','quantity':str(qty_c),'stopPrice':str(round(stop_price,8))}
                d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', p2).json()
                ok = d2.get('code') == 0
                if ok: log.info(f"  TP OK fallback")
                else:  log.error(f"  TP FALLO: {d2.get('msg')}")
            else: log.error(f"  {lbl} FALLO: {d.get('msg')}")
            return ok
        except Exception as e: log.error(f"  {otype}: {e}"); return False

    def _close_position(self, symbol, direction, t):
        qty_c = t.get('qty_c', 0)
        close_side = 'SELL' if direction=='LONG' else 'BUY'
        params = ({'symbol':symbol,'side':close_side,'positionSide':direction,
                   'type':'MARKET','quantity':str(qty_c),'reduceOnly':'true'} if qty_c
                  else {'symbol':symbol,'side':close_side,'positionSide':direction,
                        'type':'MARKET','quoteOrderQty':str(round(t.get('usdt_qty',POSITION_SIZE),2)),'reduceOnly':'true'})
        return bingx_request('POST', '/openApi/swap/v2/trade/order', params).json().get('code') == 0

    def _tiene_posicion(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {'symbol':symbol}).json()
            if d.get('code') == 0:
                for p in (d.get('data') or []):
                    amt = float(p.get('positionAmt',0) or 0)
                    if abs(amt) > 0: return True, 'LONG' if amt>0 else 'SHORT'
        except: pass
        return False, None

    def _esperar_posicion(self, symbol, direction, timeout=45):
        log.info(f"  Esperando confirmacion {direction} {symbol}...")
        for i in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions', {'symbol':symbol}).json()
                if d.get('code') == 0:
                    for p in (d.get('data') or []):
                        try: amt = float(p.get('positionAmt',0) or 0)
                        except: continue
                        ps  = str(p.get('positionSide','')).upper()
                        ok  = (amt>0 or ps=='LONG') if direction=='LONG' else (amt<0 or ps=='SHORT')
                        if ok and abs(amt)>0:
                            entry_real = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                            log.info(f"  OK: qty={abs(amt):.4f} entry=${entry_real:.6f} ({i+1}s)")
                            return abs(amt), entry_real
            except: pass
            time.sleep(1)
        log.warning(f"  Timeout {timeout}s"); return None, None

    def _cancelar_ordenes(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol':symbol}).json()
            if d.get('code') == 0:
                for o in (d.get('data',{}).get('orders') or []):
                    oid = o.get('orderId','')
                    if oid: bingx_request('DELETE', '/openApi/swap/v2/trade/order',
                                          {'symbol':symbol,'orderId':str(oid)})
        except: pass

    # ---------------------------------------------------------------- lifecycle

    def open_trade(self, symbol, sig):
        if not AUTO_TRADING:
            log.info(f"  [SENAL] {sig['signal']} {symbol} {sig['str_label']} {sig['score']}/14")
            return False
        if symbol in self.open_trades: return False
        if not self._balance_suficiente(): return False
        tiene, dir_bx = self._tiene_posicion(symbol)
        if tiene: log.info(f"  {symbol} ya tiene {dir_bx} -- skip"); return False

        direction = sig['signal']
        price     = sig['price']
        usdt_qty  = round(max(POSITION_SIZE, MIN_TRADE), 2)
        tp_price, sl_price, tp_pct, sl_pct = sig['tp_price'], sig['sl_price'], sig['tp_pct'], sig['sl_pct']
        emoji = "Long" if direction=='LONG' else "Short"

        self._set_leverage(symbol, direction)
        log.info(f"\n  > {direction} {symbol} [FLOOP {sig['str_label']} {sig['score']}/14]")
        log.info(f"  EMA:{'OK' if sig['ema_ok'] else 'NO'} ADX:{sig['adx']} CI:{sig['chop']} ROC5:{sig['roc5']:+.2f}%")
        log.info(f"  HTF={sig['score_htf']}/1 MTF={sig['score_mtf']}/4 SENS={sig['score_sens']}/3 "
                 f"EMA={sig['score_ema']}/4 VOL={sig['score_vol']}/2 CHOP={sig['chop_penalty']}")
        log.info(f"  ATR:{sig['atr_pct']:.2f}% TP:{tp_pct:.2f}% SL:{sl_pct:.2f}% RR:{tp_pct/sl_pct:.1f}:1")

        oid, qty_c = self._place_entry(symbol, direction, usdt_qty, price)
        if not oid: return False

        qty_real, entry_real = self._esperar_posicion(symbol, direction, timeout=45)
        if qty_real is None:
            self._cancelar_ordenes(symbol); time.sleep(0.5)
            side = 'BUY' if direction=='LONG' else 'SELL'
            d_mkt = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':side,'positionSide':direction,'type':'MARKET','quantity':str(qty_c),
            }).json()
            if d_mkt.get('code') == 0:
                qty_real, entry_real = self._esperar_posicion(symbol, direction, timeout=20)
            if qty_real is None:
                self._tg(f"AVISO {direction} {symbol} SIN TP/SL -- fijar manual")
                self.open_trades[symbol] = {
                    'direction':direction,'entry':price,'qty_c':qty_c,'usdt_qty':usdt_qty,
                    'tp':tp_price,'sl':sl_price,'tp_pct':tp_pct,'sl_pct':sl_pct,
                    'highest':price,'lowest':price,'order_id':oid,'tp_ok':False,'sl_ok':False,
                    'opened_at':datetime.now(),'score':sig['score'],
                }
                return True

        if entry_real and entry_real > 0:
            tp_price, sl_price, tp_pct, sl_pct = calc_tp_sl(
                entry_real, direction, sig['atr_val'],
                TP_MULT, SL_MULT, TP_MIN_PCT, TP_MAX_PCT, SL_MIN_PCT, SL_MAX_PCT)

        qty_final   = qty_real if qty_real else qty_c
        entry_final = entry_real if (entry_real and entry_real > 0) else price

        tp_ok = self._cond_order(symbol, direction, qty_final, tp_price, 'TAKE_PROFIT_MARKET')
        time.sleep(0.3)
        sl_ok = self._cond_order(symbol, direction, qty_final, sl_price, 'STOP_MARKET')
        for delay in [3, 5]:
            if tp_ok and sl_ok: break
            time.sleep(delay)
            if not tp_ok: tp_ok = self._cond_order(symbol, direction, qty_final, tp_price, 'TAKE_PROFIT_MARKET')
            if not sl_ok: sl_ok = self._cond_order(symbol, direction, qty_final, sl_price, 'STOP_MARKET')

        self.open_trades[symbol] = {
            'direction':direction,'entry':entry_final,'qty_c':qty_final,'usdt_qty':usdt_qty,
            'tp':tp_price,'sl':sl_price,'tp_pct':tp_pct,'sl_pct':sl_pct,
            'highest':entry_final,'lowest':entry_final,
            'order_id':oid,'tp_ok':tp_ok,'sl_ok':sl_ok,
            'opened_at':datetime.now(),'score':sig['score'],
        }
        self.stats['exec'] += 1

        self._tg(
            f"<b>{'LONG' if direction=='LONG' else 'SHORT'} ABIERTO -- FLOOP {sig['str_label']}</b>\n"
            f"<b>{symbol}</b> | Score: {sig['score']}/14\n"
            f"Entrada: ${entry_final:.6f}\n"
            f"{'OK' if tp_ok else 'FIJAR MANUAL'} TP: ${tp_price:.6f} (+{tp_pct:.2f}%)\n"
            f"{'OK' if sl_ok else 'FIJAR MANUAL'} SL: ${sl_price:.6f} (-{sl_pct:.2f}%)\n"
            f"RR: {tp_pct/sl_pct:.1f}:1 | ATR: {sig['atr_pct']:.2f}%\n"
            f"EMA:{'OK' if sig['ema_ok'] else 'NO'} ADX:{sig['adx']} CI:{sig['chop']}\n"
            f"HTF={sig['score_htf']} MTF={sig['score_mtf']} EMA={sig['score_ema']} "
            f"SENS={sig['score_sens']} VOL={sig['score_vol']} CHOP={sig['chop_penalty']}\n"
            f"{sig['mtf_str']}\n"
            f"Capital: ${usdt_qty} x{LEVERAGE} | Balance: ${self._balance:.2f}"
        )
        return True

    def close_trade(self, symbol, cur_price, reason):
        if symbol not in self.open_trades: return False
        t = self.open_trades[symbol]; direction = t['direction']
        self._close_position(symbol, direction, t)
        cambio  = (cur_price-t['entry'])/t['entry'] if direction=='LONG' else (t['entry']-cur_price)/t['entry']
        pnl     = (t['usdt_qty']*LEVERAGE*cambio) - (t['usdt_qty']*LEVERAGE*COMISION_ACTUAL*2)
        pnl_pct = (pnl / t['usdt_qty']) * 100
        self.stats['closed'] += 1; self.stats['pnl'] += pnl
        if pnl > 0: self.stats['wins'] += 1
        else:        self.stats['losses'] += 1
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        mins  = int((datetime.now()-t['opened_at']).total_seconds()/60)
        emoji = "OK" if pnl > 0 else "MAL"
        log.info(f"  [{emoji}] {reason} {symbol} PnL:${pnl:+.3f}({pnl_pct:+.1f}%) {mins}min")
        self._tg(
            f"<b>{'OK' if pnl>0 else 'MAL'} {direction} CERRADO -- {reason}</b>\n<b>{symbol}</b>\n"
            f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ${t['entry']:.6f} -> Exit: ${cur_price:.6f} | {mins} min\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}% ({self.stats['wins']}W/{self.stats['losses']}L)</b>"
        )
        self._cooldowns[symbol] = time.time(); del self.open_trades[symbol]; return True

    # ---------------------------------------------------------------- monitor

    async def _sync_bingx(self):
        if not self.open_trades or not AUTO_TRADING: return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            pos = {p.get('symbol'): float(p.get('positionAmt',0) or 0)
                   for p in (d.get('data') or []) if abs(float(p.get('positionAmt',0) or 0)) > 0}
            for sym in list(self.open_trades.keys()):
                if sym not in pos:
                    t = self.open_trades[sym]; dir = t['direction']
                    tk = self._ticker(sym); cur = tk['price'] if tk else t['entry']
                    cambio = (cur-t['entry'])/t['entry'] if dir=='LONG' else (t['entry']-cur)/t['entry']
                    pnl    = (t['usdt_qty']*LEVERAGE*cambio)-(t['usdt_qty']*LEVERAGE*COMISION_ACTUAL*2)
                    pnl_pct = (pnl/t['usdt_qty'])*100
                    self.stats['closed'] += 1; self.stats['pnl'] += pnl
                    if pnl>=0: self.stats['wins']+=1
                    else: self.stats['losses']+=1
                    total = self.stats['wins']+self.stats['losses']
                    wr = self.stats['wins']/total*100 if total else 0
                    mins = int((datetime.now()-t['opened_at']).total_seconds()/60)
                    self._tg(f"<b>{'OK' if pnl>=0 else 'MAL'} {dir} cerrado BingX</b>\n<b>{sym}</b>\n"
                             f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min\n"
                             f"Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                    self._cooldowns[sym] = time.time(); del self.open_trades[sym]
        except Exception as e: log.debug(f"sync: {e}")

    async def monitor_trades(self):
        await self._sync_bingx()
        for sym in list(self.open_trades.keys()):
            try:
                t = self.open_trades[sym]; tk = self._ticker(sym)
                if not tk: continue
                cur = tk['price']; dir = t['direction']
                if dir == 'LONG':
                    pnl_pct = (cur-t['entry'])/t['entry']*100
                    if TRAILING and cur > t['highest']:
                        t['highest'] = cur
                        if pnl_pct >= 0.8:
                            new_sl = t['entry'] + (cur-t['entry'])*0.65
                            if new_sl > t['sl']: t['sl'] = new_sl; log.info(f"  Trailing SL {sym}: ${new_sl:.6f}")
                    hit_tp = cur >= t['tp']; hit_sl = cur <= t['sl']
                else:
                    pnl_pct = (t['entry']-cur)/t['entry']*100
                    if TRAILING and cur < t['lowest']:
                        t['lowest'] = cur
                        if pnl_pct >= 0.8:
                            new_sl = t['entry'] - (t['entry']-cur)*0.65
                            if new_sl < t['sl']: t['sl'] = new_sl; log.info(f"  Trailing SL {sym}: ${new_sl:.6f}")
                    hit_tp = cur <= t['tp']; hit_sl = cur >= t['sl']
                if abs(pnl_pct) > 0.3:
                    log.info(f"  {sym} {dir}: {pnl_pct:+.2f}% | TP:${t['tp']:.6f} SL:${t['sl']:.6f}")
                if hit_tp: self.close_trade(sym, cur, "TAKE PROFIT")
                elif hit_sl: self.close_trade(sym, cur, "STOP LOSS")
            except Exception as e: log.debug(f"Monitor {sym}: {e}")

    def _reporte_horario(self):
        if datetime.now() - self._last_report < timedelta(hours=1): return
        self._last_report = datetime.now()
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        pos_txt = ""
        for sym, t in self.open_trades.items():
            tk = self._ticker(sym)
            if tk:
                cur = tk['price']; dir = t['direction']
                pnl_pct = (cur-t['entry'])/t['entry']*100 if dir=='LONG' else (t['entry']-cur)/t['entry']*100
                pos_txt += f"  {sym} {dir}: {pnl_pct:+.2f}%\n"
        self._tg(
            f"<b>Reporte horario -- FLOOP Pro</b>\n"
            f"PnL: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%\n"
            f"({self.stats['wins']}W/{self.stats['losses']}L | {self.stats['closed']} trades)\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES}\n"
            f"Balance: ${self._balance:.2f} USDT\n"
            f"BTC 1h:{self._btc_1h:+.2f}% 4h:{self._btc_4h:+.2f}%\n"
            + (pos_txt or "  sin posiciones\n")
        )

    def _tg(self, msg):
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id':TELEGRAM_CHAT,'text':msg,'parse_mode':'HTML'}, timeout=6)
        except: pass

    # ---------------------------------------------------------------- loop

    async def run(self):
        log.info("\n> Bot FLOOP Pro arrancado\n")
        iteration, last_refresh = 0, 0
        while True:
            try:
                iteration += 1
                if time.time() - last_refresh > 600:
                    self._get_symbols(); last_refresh = time.time()
                self._update_btc_trend(); self._update_balance()
                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0
                hora_st = "BAJA" if not self._hora_ok() else "OK"
                log.info(f"\n{'='*65}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"Abiertos:{len(self.open_trades)}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                log.info(f"  Balance:${self._balance:.2f} | "
                         f"BTC 1h:{self._btc_1h:+.2f}% 4h:{self._btc_4h:+.2f}% | {hora_st}")
                log.info(f"{'='*65}\n")
                await self.monitor_trades(); self._reporte_horario()
                if len(self.open_trades) < MAX_TRADES:
                    found = 0
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES: break
                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            log.info(f"  * {sig['signal']} {sym} {sig['str_label']} {sig['score']}/14 | "
                                     f"EMA:{'OK' if sig['ema_ok'] else 'NO'} ADX:{sig['adx']} ROC5:{sig['roc5']:+.1f}%")
                            self.open_trade(sym, sig)
                        await asyncio.sleep(0.25)
                        if (i+1) % 20 == 0: log.info(f"  ...{i+1}/{len(self.symbols)} analizados")
                    log.info(f"\n  {len(self.symbols)} pares | {found} senales FLOOP")
                else:
                    log.info(f"  Max ({MAX_TRADES}) trades abiertos")
                log.info(f"\n  Proximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)
            except KeyboardInterrupt: log.info("Detenido"); break
            except Exception as e:
                log.error(f"Error loop #{iteration}: {e}"); await asyncio.sleep(20)

async def main():
    try: await FloopBot().run()
    except Exception as e: log.error(f"Error fatal: {e}")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: log.info("Terminado")
