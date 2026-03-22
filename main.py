#!/usr/bin/env python3
"""
BOT DUAL STRATEGY v1.0
═══════════════════════════════════════════════════════════════
Combina dos estrategias Pine Script traducidas a Python:

ESTRATEGIA 1 — Trend Magic + EMA + RMI Trend Sniper
  • Trend Magic:  CCI(20) + ATR(5) → soporte/resistencia dinámico
  • EMA(9):       tendencia rápida
  • RMI:          RSI + MFI combinados (señal BUY >66, SELL <30)

ESTRATEGIA 2 — Magical Momentum
  • Worm:         EMA adaptativa con velocidad controlada por StdDev
  • Momentum:     log-normalizado y suavizado
  • Señal:        momentum > 0 acelerando = alcista

ENTRADA LONG:  RMI positive + Momentum alcista + Trend Magic bull
ENTRADA SHORT: RMI negative + Momentum bajista + Trend Magic bear

TODOS LOS FIXES de v4.1 incluidos:
  ✅ qty basada en notional (usdt × leverage)
  ✅ Multi-timeframe 1h confirma, 15m entra
  ✅ TP/SL: 5 reintentos, espera 90s
  ✅ Anti-correlación: máx 2 por dirección
  ✅ Score normalizado 0-100
  ✅ RSI mínimo para SHORT
  ✅ 2× comisión en PnL
  ✅ Reconciliación al arranque
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re
from datetime import datetime, timedelta
from urllib.parse import urlencode

# ============================================================================
# CONFIGURACIÓN — variables de entorno (Railway / .env)
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

AUTO_TRADING     = clean('AUTO_TRADING_ENABLED',   'true',  'bool')
POSITION_SIZE    = clean('MAX_POSITION_SIZE',       '10',   'float')
MIN_TRADE        = clean('MIN_TRADE_USDT',           '5',   'float')
LEVERAGE         = clean('LEVERAGE',                 '5',   'int')
TP_PCT           = clean('TAKE_PROFIT_PCT',          '2.0', 'float')
SL_PCT           = clean('STOP_LOSS_PCT',            '1.0', 'float')
MAX_TRADES       = clean('MAX_OPEN_TRADES',          '3',   'int')
INTERVAL         = clean('CHECK_INTERVAL',          '120',  'int')
MIN_VOLUME       = clean('MIN_VOLUME_24H',       '500000',  'float')
MAX_SYMBOLS      = clean('MAX_SYMBOLS_TO_ANALYZE',   '80',  'int')
MIN_SCORE        = clean('MIN_SCORE',                '65',  'float')
TRAILING         = clean('TRAILING_STOP_ENABLED',  'true',  'bool')
USE_LIMIT_ORDERS = clean('USE_LIMIT_ORDERS',       'true',  'bool')
ENABLE_LONGS     = clean('ENABLE_LONGS',           'true',  'bool')
ENABLE_SHORTS    = clean('ENABLE_SHORTS',          'true',  'bool')
BTC_FILTER_PCT   = clean('BTC_FILTER_PCT',          '2.5',  'float')
MAX_SAME_DIR     = clean('MAX_SAME_DIRECTION',       '2',   'int')
MAX_PER_CYCLE    = clean('MAX_ENTRIES_PER_CYCLE',    '2',   'int')

# Parámetros estrategia 1 (Trend Magic + RMI)
CCI_LEN          = clean('CCI_LENGTH',              '20',   'int')
ATR_LEN          = clean('ATR_LENGTH',               '5',   'int')
ATR_MULT         = clean('ATR_MULTIPLIER',           '1.0', 'float')
EMA_LEN          = clean('EMA_LENGTH',               '9',   'int')
RMI_LEN          = clean('RMI_LENGTH',              '14',   'int')
RMI_POSITIVE     = clean('RMI_POSITIVE_ABOVE',      '66',   'float')
RMI_NEGATIVE     = clean('RMI_NEGATIVE_BELOW',      '30',   'float')

# Parámetros estrategia 2 (Magical Momentum)
MOM_PERIOD       = clean('MOMENTUM_PERIOD',         '50',   'int')
MOM_RESPONSIVE   = clean('MOMENTUM_RESPONSIVENESS', '0.9', 'float')

LIMIT_OFFSET_PCT  = 0.05
SKIP_HOURS_UTC    = {0, 1}
BASE_URL          = "https://open-api.bingx.com"
TPSL_INTENTOS     = 5
ESPERA_POS        = 90

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

COMISION_MAKER  = 0.0002
COMISION_TAKER  = 0.0005
COMISION_ACTUAL = COMISION_MAKER if USE_LIMIT_ORDERS else COMISION_TAKER
TP_MIN          = round((COMISION_ACTUAL * 2 / LEVERAGE + 0.002) * 100, 3)

# ============================================================================
# API BINGX
# ============================================================================

def bingx_request(method, endpoint, params, retries=3):
    for attempt in range(retries + 1):
        try:
            p = dict(params)
            p['timestamp'] = int(time.time() * 1000)
            qs  = urlencode(sorted(p.items()))
            sig = hmac.new(BINGX_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
            url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
            hdr = {'X-BX-APIKEY': BINGX_API_KEY,
                   'Content-Type': 'application/x-www-form-urlencoded'}
            r = requests.get(url, headers=hdr, timeout=15) if method == 'GET' \
                else requests.post(url, headers=hdr, timeout=15)
            return r
        except Exception as e:
            if attempt < retries:
                log.warning(f"  retry {attempt+1}/{retries}: {e}"); time.sleep(2)
            else: raise

# ============================================================================
# INDICADORES — ESTRATEGIA 1: TREND MAGIC + EMA + RMI
# ============================================================================

def calc_ema(prices, period):
    if not prices: return 0.0
    if len(prices) < period: return sum(prices) / len(prices)
    k, e = 2 / (period + 1), prices[0]
    for p in prices[1:]: e = p * k + e * (1 - k)
    return e

def calc_rma(prices, period):
    """RMA (Wilder's smoothing) = ta.rma en Pine Script"""
    if not prices: return 0.0
    if len(prices) < period: return sum(prices) / len(prices)
    alpha = 1 / period
    e = sum(prices[:period]) / period
    for p in prices[period:]: e = alpha * p + (1 - alpha) * e
    return e

def calc_sma(prices, period):
    w = prices[-period:] if len(prices) >= period else prices
    return sum(w) / len(w) if w else 0.0

def calc_atr(highs, lows, closes, period):
    if len(closes) < 2: return 0.0
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i]-lows[i],
                       abs(highs[i]-closes[i-1]),
                       abs(lows[i]-closes[i-1])))
    # SMA del TR (Pine usa ta.sma(ta.tr, len))
    w = trs[-period:] if len(trs) >= period else trs
    return sum(w) / len(w) if w else 0.0

def calc_cci(closes, highs, lows, period):
    """CCI = (precio típico - SMA_tp) / (0.015 × desviación media)"""
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    w  = tp[-period:] if len(tp) >= period else tp
    sma_tp = sum(w) / len(w)
    md = sum(abs(x - sma_tp) for x in w) / len(w)
    return (tp[-1] - sma_tp) / (0.015 * md) if md > 0 else 0.0

def calc_mfi(highs, lows, closes, volumes, period):
    """MFI = Money Flow Index"""
    if len(closes) < period + 1: return 50.0
    hlc3 = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    pos_flow = neg_flow = 0.0
    for i in range(len(hlc3)-period, len(hlc3)):
        mf = hlc3[i] * volumes[i]
        if hlc3[i] > hlc3[i-1]: pos_flow += mf
        elif hlc3[i] < hlc3[i-1]: neg_flow += mf
    if neg_flow == 0: return 100.0
    return 100 - 100 / (1 + pos_flow / neg_flow)

def trend_magic_rmi(closes, highs, lows, volumes):
    """
    Traduce Trend Magic + RMI Trend Sniper de Pine Script a Python.
    Retorna: (trend_magic_bull, trend_magic_bear, rmi_positive, rmi_negative,
              ema9, rsi_mfi_last, x_vals)
    """
    n = len(closes)
    if n < max(CCI_LEN, ATR_LEN, RMI_LEN, EMA_LEN) + 5:
        return False, False, False, False, 0.0, 50.0, []

    # ── Trend Magic ────────────────────────────────────────────────────
    x_vals = [0.0] * n
    swap   = [0.0] * n

    for i in range(1, n):
        sub_c = closes[max(0, i-CCI_LEN+1):i+1]
        sub_h = highs[max(0, i-CCI_LEN+1):i+1]
        sub_l = lows[max(0, i-CCI_LEN+1):i+1]
        cci_now  = calc_cci(sub_c, sub_h, sub_l, min(CCI_LEN, len(sub_c)))
        cci_prev = calc_cci(closes[max(0,i-CCI_LEN):i],
                            highs[max(0,i-CCI_LEN):i],
                            lows[max(0,i-CCI_LEN):i],
                            min(CCI_LEN, i)) if i > 0 else 0.0

        atr_val = calc_atr(highs[max(0,i-ATR_LEN-1):i+1],
                           lows[max(0,i-ATR_LEN-1):i+1],
                           closes[max(0,i-ATR_LEN-1):i+1], ATR_LEN)

        buf_dn = highs[i] + ATR_MULT * atr_val
        buf_up = lows[i]  - ATR_MULT * atr_val

        if cci_now >= 0 and cci_prev < 0:
            buf_up = x_vals[i-1] if x_vals[i-1] != 0 else buf_dn
        if cci_now <= 0 and cci_prev > 0:
            buf_dn = x_vals[i-1] if x_vals[i-1] != 0 else buf_up

        prev_x = x_vals[i-1]
        if cci_now >= 0:
            buf_up = max(buf_up, prev_x) if prev_x != 0 else buf_up
            x_vals[i] = buf_up
        elif cci_now <= 0:
            buf_dn = min(buf_dn, prev_x) if prev_x != 0 else buf_dn
            x_vals[i] = buf_dn
        else:
            x_vals[i] = prev_x

        if x_vals[i] > x_vals[i-1]: swap[i] = 1.0
        elif x_vals[i] < x_vals[i-1]: swap[i] = -1.0
        else: swap[i] = swap[i-1]

    trend_magic_bull = swap[-1] == 1.0
    trend_magic_bear = swap[-1] == -1.0

    # ── EMA 9 ─────────────────────────────────────────────────────────
    ema9 = calc_ema(closes, EMA_LEN)

    # ── RMI (RSI + MFI combinados) ────────────────────────────────────
    changes = [closes[i] - closes[i-1] for i in range(1, n)]
    gains   = [max(c, 0) for c in changes]
    losses  = [max(-c, 0) for c in changes]

    up_rmi   = calc_rma(gains,  RMI_LEN)
    down_rmi = calc_rma(losses, RMI_LEN)
    rsi_val  = 100.0 if down_rmi == 0 else (0.0 if up_rmi == 0
               else 100 - 100 / (1 + up_rmi / down_rmi))
    mfi_val  = calc_mfi(highs, lows, closes, volumes, RMI_LEN)
    rsi_mfi  = (rsi_val + mfi_val) / 2

    # rsi_mfi anterior (para detectar cruce)
    changes_prev = changes[:-1]
    gains_prev   = [max(c, 0) for c in changes_prev]
    losses_prev  = [max(-c, 0) for c in changes_prev]
    up_prev   = calc_rma(gains_prev,  RMI_LEN)
    down_prev = calc_rma(losses_prev, RMI_LEN)
    rsi_prev  = (100.0 if down_prev == 0 else (0.0 if up_prev == 0
                 else 100 - 100 / (1 + up_prev / down_prev)))
    mfi_prev  = calc_mfi(highs, lows, closes[:-1], volumes[:-1], RMI_LEN)
    rsi_mfi_prev = (rsi_prev + mfi_prev) / 2

    ema5_now  = calc_ema(closes,     5)
    ema5_prev = calc_ema(closes[:-1], 5)
    ema5_up   = ema5_now > ema5_prev
    ema5_dn   = ema5_now < ema5_prev

    # p_mom: rsi_mfi[1] < pmom AND rsi_mfi > pmom AND ema5 subiendo
    p_mom = (rsi_mfi_prev < RMI_POSITIVE and
             rsi_mfi      > RMI_POSITIVE and
             rsi_mfi      > RMI_NEGATIVE and
             ema5_up)
    # n_mom: rsi_mfi < nmom AND ema5 bajando
    n_mom = rsi_mfi < RMI_NEGATIVE and ema5_dn

    return (trend_magic_bull, trend_magic_bear,
            p_mom, n_mom,
            ema9, rsi_mfi, x_vals)

# ============================================================================
# INDICADORES — ESTRATEGIA 2: MAGICAL MOMENTUM
# ============================================================================

def magical_momentum(closes):
    """
    Traduce Magical Momentum de Pine Script a Python.
    Retorna: (momentum_now, momentum_prev, acelerando_al_alza, acelerando_a_la_baja)
    """
    n = len(closes)
    period = min(MOM_PERIOD, n)
    if n < period + 5:
        return 0.0, 0.0, False, False

    responsiveness = max(0.00001, MOM_RESPONSIVE)

    # StdDev últimas 50 velas × responsiveness
    w50 = closes[-period:]
    mean50 = sum(w50) / len(w50)
    sd = (sum((x - mean50)**2 for x in w50) / len(w50))**0.5 * responsiveness

    # Calcular worm para toda la serie (necesario para momentum)
    worm = list(closes[:period])
    for i in range(period, n):
        diff  = closes[i] - worm[-1]
        delta = math.copysign(sd, diff) if abs(diff) > sd else diff
        worm.append(worm[-1] + delta)

    def calc_momentum(closes_sub, worm_sub):
        period_s = min(MOM_PERIOD, len(closes_sub))
        ma  = calc_sma(closes_sub, period_s)
        w   = worm_sub[-1]
        if w == 0: return 0.0
        raw = (w - ma) / w

        lo = min(worm_sub[-period_s:]) if len(worm_sub) >= period_s else min(worm_sub)
        hi = max(worm_sub[-period_s:]) if len(worm_sub) >= period_s else max(worm_sub)
        c_lo = min(closes_sub[-period_s:]) if len(closes_sub) >= period_s else min(closes_sub)
        c_hi = max(closes_sub[-period_s:]) if len(closes_sub) >= period_s else max(closes_sub)

        # Usar raw_momentum normalizado
        vals = []
        for j in range(max(0, len(closes_sub)-period_s), len(closes_sub)):
            w_j = worm_sub[j] if j < len(worm_sub) else worm_sub[-1]
            m_j = calc_sma(closes_sub[max(0,j-period_s+1):j+1], period_s)
            vals.append((w_j - m_j) / w_j if w_j != 0 else 0)

        if not vals: return 0.0
        min_m = min(vals); max_m = max(vals)
        span  = max_m - min_m
        if span == 0: return 0.0

        temp = (raw - min_m) / span
        v = 0.5 * 2 * ((temp - 0.5) + (0.5 * 0))  # simplificado (sin recursión completa)
        v = max(-0.9999, min(0.9999, v))
        if v <= -1 or v >= 1: return 0.0
        mom_raw = 0.25 * math.log((1 + v) / (1 - v))
        return mom_raw

    mom_now  = calc_momentum(closes,      worm)
    mom_prev = calc_momentum(closes[:-1], worm[:-1])

    # Suavizar (+ 0.5 * momentum[1])
    mom_now  = mom_now  + 0.5 * mom_prev
    mom_prev = mom_prev + 0.5 * calc_momentum(closes[:-2], worm[:-2]) if n > period+2 else mom_prev

    # trend = abs(momentum) <= abs(momentum[1]) → desacelerando
    # not trend → acelerando
    accel_up = mom_now > 0 and abs(mom_now) > abs(mom_prev)
    accel_dn = mom_now < 0 and abs(mom_now) > abs(mom_prev)

    return mom_now, mom_prev, accel_up, accel_dn

# ============================================================================
# INDICADORES AUXILIARES
# ============================================================================

def calc_atr_pct(highs, lows, closes, period=14):
    atr = calc_atr(highs, lows, closes, period)
    return (atr / closes[-1] * 100) if closes[-1] > 0 else 0.0

def vol_spike(volumes):
    if len(volumes) < 5: return 1.0
    avg = sum(volumes[:-1]) / len(volumes[:-1])
    return (volumes[-1] / avg) if avg > 0 else 1.0

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains  = [max(0,  prices[i] - prices[i-1]) for i in range(1, len(prices))]
    losses = [max(0, prices[i-1] - prices[i])  for i in range(1, len(prices))]
    ag = sum(gains[-period:])  / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100.0
    return 100 - 100 / (1 + ag / al)

def tendencia_1h(closes, highs, lows):
    if not closes or len(closes) < 50: return 'NEUTRAL', 50.0
    ema50 = calc_ema(closes, 50)
    ema20 = calc_ema(closes, 20)
    rsi   = calc_rsi(closes, 14)
    price = closes[-1]
    bull  = price > ema50 and price > ema20 and ema20 > ema50
    bear  = price < ema50 and price < ema20 and ema20 < ema50
    if bull and rsi > 40:  return 'BULL', rsi
    if bear and rsi < 60:  return 'BEAR', rsi
    return 'NEUTRAL', rsi

# ============================================================================
# BOT
# ============================================================================

class DualStrategyBot:

    def __init__(self):
        dirs = []
        if ENABLE_LONGS:  dirs.append("LONGS")
        if ENABLE_SHORTS: dirs.append("SHORTS")
        fee = f"LÍMITE {COMISION_MAKER*100:.2f}%" if USE_LIMIT_ORDERS \
              else f"MERCADO {COMISION_TAKER*100:.2f}%"

        log.info("=" * 65)
        log.info("  BOT DUAL STRATEGY v1.0")
        log.info("  Trend Magic + RMI  ×  Magical Momentum")
        log.info("=" * 65)
        log.info(f"  Modo:    {'AUTO ✅' if AUTO_TRADING else 'SEÑALES ⚠️  (activa AUTO_TRADING_ENABLED=true)'}")
        log.info(f"  Capital: ${POSITION_SIZE} USDT | Leverage: {LEVERAGE}x")
        log.info(f"  TP/SL:   {TP_PCT}% / {SL_PCT}%  RR:{TP_PCT/SL_PCT:.1f}:1  TP_mín:{TP_MIN}%")
        log.info(f"  Score:   ≥{MIN_SCORE}/100")
        log.info(f"  Fee:     {fee}")
        log.info(f"  Dirs:    {' + '.join(dirs)}")
        log.info(f"  Anti-corr: máx {MAX_SAME_DIR}/dir | máx {MAX_PER_CYCLE}/ciclo")
        log.info(f"  CCI:{CCI_LEN} ATR:{ATR_LEN}×{ATR_MULT} EMA:{EMA_LEN} "
                 f"RMI:{RMI_LEN}(+{RMI_POSITIVE}/-{RMI_NEGATIVE})")
        log.info(f"  Momentum period:{MOM_PERIOD} resp:{MOM_RESPONSIVE}")
        log.info("=" * 65)

        self.symbols         = []
        self.open_trades     = {}
        self._contracts      = {}
        self._cooldowns      = {}
        self._cache_1h       = {}
        self._last_report    = datetime.now()
        self._btc_change_1h  = 0.0
        self._btc_trend_1h   = 'NEUTRAL'
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0,
                      'bl_1h':0,'bl_rsi':0,'bl_corr':0}

        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._reconciliar()

        self._tg(
            f"<b>🤖 Dual Strategy Bot v1.0</b>\n"
            f"Trend Magic + RMI  ×  Magical Momentum\n"
            f"Modo: {'AUTO ✅' if AUTO_TRADING else 'SEÑALES ⚠️'}\n"
            f"Capital: ${POSITION_SIZE} ×{LEVERAGE} | TP:{TP_PCT}% SL:{SL_PCT}%\n"
            f"Score ≥{MIN_SCORE}/100 | {fee}"
        )

    # ─────────────────────────────────── SETUP

    def _verify(self):
        global AUTO_TRADING
        if not AUTO_TRADING:
            log.warning("  ⚠️  AUTO_TRADING=false — solo señales. Activa AUTO_TRADING_ENABLED=true")
            return
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            log.error("  ❌ Sin API keys"); AUTO_TRADING = False; return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                eq = d.get('data',{}).get('equity', d.get('data',{}).get('balance','?'))
                log.info(f"  ✅ BingX OK | Balance: ${eq} USDT")
            else:
                log.error(f"  ❌ BingX [{d.get('code')}]: {d.get('msg')}")
                AUTO_TRADING = False
        except Exception as e:
            log.error(f"  ❌ API: {e}"); AUTO_TRADING = False

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
                log.info(f"  Contratos: {len(self._contracts)}")
        except Exception as e:
            log.warning(f"  Contratos error: {e}")

    def _get_symbols(self):
        NO = ['DOW','SP500','SPX','QQQ','NASDAQ','GOLD','SILVER','XAU','XAG',
              'OIL','BRENT','WTI','CRUDE','GAS','PLATINUM','PALLADIUM',
              'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN',
              'EUR','GBP','JPY','CHF','AUD','CAD','NZD',
              'WHEAT','CORN','SUGAR','COFFEE','COTTON']
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker", timeout=15).json()
            if d.get('code') == 0:
                items = []
                for t in d.get('data', []):
                    sym = t.get('symbol','')
                    if not sym.endswith('-USDT'): continue
                    base = sym.replace('-USDT','').upper()
                    if any(kw in base for kw in NO): continue
                    try:
                        price = float(t.get('lastPrice',0))
                        vol   = float(t.get('volume',0)) * price
                        if vol < MIN_VOLUME or price < 0.000001: continue
                        items.append({'symbol':sym,'vol':vol})
                    except: continue
                items.sort(key=lambda x: x['vol'], reverse=True)
                self.symbols = [x['symbol'] for x in items[:MAX_SYMBOLS]]
                log.info(f"  Pares: {len(self.symbols)}")
                return
        except Exception as e:
            log.warning(f"  Símbolos error: {e}")
        self.symbols = ['BTC-USDT','ETH-USDT','SOL-USDT','BNB-USDT','XRP-USDT',
                        'DOGE-USDT','ADA-USDT','AVAX-USDT','LINK-USDT']

    # ─────────────────────────────────── RECONCILIACIÓN

    def _reconciliar(self):
        if not AUTO_TRADING: return
        log.info("  🔍 Reconciliando posiciones...")
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            todas = [p for p in (d.get('data') or [])
                     if abs(float(p.get('positionAmt',0) or 0)) > 0]
            if not todas: log.info("  ✅ Arranque limpio"); return
            rec = 0
            for p in todas:
                sym = p.get('symbol','')
                if not sym: continue
                try: lev = int(float(p.get('leverage',0) or 0))
                except: lev = 0
                if lev != 0 and lev != LEVERAGE:
                    log.info(f"  ⏭ {sym} ignorado (lev {lev}x, manual)"); continue
                try: amt = float(p.get('positionAmt',0) or 0)
                except: continue
                if abs(amt) == 0: continue
                direction = 'LONG' if amt > 0 else 'SHORT'
                try: entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                except: entry = 0
                if entry <= 0:
                    tk = self._ticker(sym)
                    entry = tk['price'] if tk else 0
                if entry <= 0: continue
                qty_c = abs(amt)
                tp_p = entry * (1 + TP_PCT/100) if direction=='LONG' else entry * (1 - TP_PCT/100)
                sl_p = entry * (1 - SL_PCT/100) if direction=='LONG' else entry * (1 + SL_PCT/100)
                tp_ok = self._cond_order(sym, direction, qty_c, tp_p, 'TAKE_PROFIT_MARKET')
                time.sleep(0.4)
                sl_ok = self._cond_order(sym, direction, qty_c, sl_p, 'STOP_MARKET')
                self.open_trades[sym] = {
                    'direction':direction,'entry':entry,'qty_c':qty_c,
                    'usdt_qty':POSITION_SIZE,'tp':tp_p,'sl':sl_p,
                    'tp_pct':TP_PCT,'sl_pct':SL_PCT,'highest':entry,'lowest':entry,
                    'order_id':'RECONCILIADO','tp_ok':tp_ok,'sl_ok':sl_ok,
                    'opened_at':datetime.now(),'score':0,
                }
                rec += 1
                log.info(f"  {'📈' if direction=='LONG' else '📉'} {sym} {direction} "
                         f"entry=${entry:.6f} TP:{'✅' if tp_ok else '❌'} SL:{'✅' if sl_ok else '❌'}")
            log.info(f"  ✅ {rec} recuperadas")
        except Exception as e:
            log.error(f"  Reconciliación error: {e}")

    # ─────────────────────────────────── DATOS

    def _klines(self, symbol, interval='15m', limit=210):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol':symbol,'interval':interval,'limit':limit}, timeout=12).json()
            if d.get('code') == 0 and d.get('data'):
                k = d['data']
                return ([float(x['close'])  for x in k],
                        [float(x['high'])   for x in k],
                        [float(x['low'])    for x in k],
                        [float(x['volume']) for x in k],
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

    def _get_1h(self, symbol):
        now = time.time()
        cached = self._cache_1h.get(symbol)
        if cached and (now - cached[0]) < 600:
            return cached[1]
        closes, highs, lows, *_ = self._klines(symbol, '1h', 60)
        if not closes or len(closes) < 20:
            return 'NEUTRAL', 50.0
        result = tendencia_1h(closes, highs, lows)
        self._cache_1h[symbol] = (now, result)
        return result

    def _update_btc(self):
        try:
            closes, highs, lows, *_ = self._klines('BTC-USDT', '1h', 60)
            if closes and len(closes) >= 2:
                self._btc_change_1h = (closes[-1]-closes[-2])/closes[-2]*100
            if closes and len(closes) >= 50:
                self._btc_trend_1h, _ = tendencia_1h(closes, highs or [], lows or [])
        except: pass

    # ─────────────────────────────────── SIZING (FIX NOTIONAL)

    def _qty(self, symbol, price, usdt=None):
        """qty basada en notional = usdt × leverage (FIX crítico)"""
        if usdt is None: usdt = POSITION_SIZE
        info  = self._contracts.get(symbol, {'step':1.0,'prec':2,'ctval':1.0})
        step  = max(info['step'], 0.0001)
        prec  = info['prec']
        ctval = info.get('ctval', 1.0)
        ppc   = price * ctval if ctval != 1.0 else price
        if ppc <= 0: return None, 0
        notional = usdt * LEVERAGE
        qty = round(math.ceil(notional / ppc / step) * step, prec)
        val = qty * ppc
        margen = val / LEVERAGE
        i = 0
        while margen < MIN_TRADE and i < 500:
            qty += step; qty = round(qty, prec)
            val = qty * ppc; margen = val / LEVERAGE; i += 1
        if margen > usdt * 1.3:
            qty = round(math.floor((usdt * 1.3 * LEVERAGE / ppc) / step) * step, prec)
            val = qty * ppc
            margen = val / LEVERAGE
        log.info(f"    qty:{qty} × ${ppc:.6f} = ${val:.2f} notional (margen:${margen:.2f})")
        return qty, round(val, 4)

    # ─────────────────────────────────── FILTROS

    def _cooldown_ok(self, symbol):
        info = self._cooldowns.get(symbol)
        if not info: return True
        ts, tipo = info
        return (time.time() - ts) >= (30*60 if tipo == 'loss' else 10*60)

    def _hora_ok(self):
        return datetime.utcnow().hour not in SKIP_HOURS_UTC

    def _contar_dir(self):
        l = sum(1 for t in self.open_trades.values() if t['direction']=='LONG')
        s = sum(1 for t in self.open_trades.values() if t['direction']=='SHORT')
        return l, s

    # ─────────────────────────────────── ANÁLISIS DUAL

    def analyze(self, symbol):
        if symbol in self.open_trades: return None
        if not self._cooldown_ok(symbol): return None
        if not self._hora_ok(): return None

        closes, highs, lows, volumes, opens = self._klines(symbol, '15m', 210)
        if not closes or len(closes) < 160: return None

        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0: return None
        price  = ticker['price']
        change = ticker['change']

        # ── ESTRATEGIA 1: Trend Magic + RMI ──────────────────────────────
        (tm_bull, tm_bear,
         rmi_pos, rmi_neg,
         ema9, rsi_mfi, x_vals) = trend_magic_rmi(closes, highs, lows, volumes)

        # ── ESTRATEGIA 2: Magical Momentum ───────────────────────────────
        mom_now, mom_prev, mom_up, mom_dn = magical_momentum(closes)

        # ── FILTRO 1h ─────────────────────────────────────────────────────
        trend_1h, rsi_1h = self._get_1h(symbol)

        # ── Auxiliares ───────────────────────────────────────────────────
        atr_pct = calc_atr_pct(highs, lows, closes, 14)
        vs      = vol_spike(volumes)
        rsi_15  = calc_rsi(closes, 14)

        # ════════════════════════════════════════════════════════════════
        # SCORING LONG (0-100)
        # Distribución: 1h(20) + TM(20) + RMI(25) + Momentum(25) + Extras(10)
        # ════════════════════════════════════════════════════════════════
        ls, lr = 0.0, []
        lb = None   # blocked reason

        if ENABLE_LONGS:
            # ── Filtro 1h ──
            if trend_1h == 'BEAR':
                lb = '1h_BEAR'
                self.stats['bl_1h'] += 1
            elif trend_1h == 'BULL':
                ls += 20; lr.append("1h_BULL(20)")
            else:
                ls += 8;  lr.append("1h_NEUT(8)")

            if lb is None:
                # ── Trend Magic (20 pts) ──
                if tm_bull:
                    ls += 20; lr.append("TM_BULL(20)")
                else:
                    ls -= 10; lr.append("TM_no(-10)")

                # ── RMI (25 pts) ──
                if rmi_pos:
                    ls += 25; lr.append(f"RMI_BUY(25) rmi={rsi_mfi:.0f}")
                elif rsi_mfi > 50:
                    ls += 10; lr.append(f"RMI_ok(10) rmi={rsi_mfi:.0f}")
                elif rsi_mfi < 30:
                    ls -= 5;  lr.append(f"RMI_low(-5)")

                # ── Magical Momentum (25 pts) ──
                if mom_up:
                    ls += 25; lr.append(f"MOM_UP(25) m={mom_now:.4f}")
                elif mom_now > 0:
                    ls += 12; lr.append(f"MOM_pos(12) m={mom_now:.4f}")
                elif mom_now < 0:
                    ls -= 10; lr.append(f"MOM_neg(-10)")

                # ── EMA 9 alcista ──
                if ema9 > price * 0.995:
                    ls += 5; lr.append("EMA9_ok(5)")

                # ── RSI razonable para LONG ──
                if 25 <= rsi_15 <= 55:
                    ls += 5; lr.append(f"RSI_ok({rsi_15:.0f})(5)")
                elif rsi_15 > 75:
                    ls -= 8; lr.append(f"RSI_OB(-8)")

                # ── Volumen ──
                if vs >= 1.8:
                    p = min(5, int(vs*2.5)); ls += p; lr.append(f"Vol{vs:.1f}x({p})")
                elif vs < 1.1:
                    ls -= 5; lr.append("VolBajo(-5)")

        # ════════════════════════════════════════════════════════════════
        # SCORING SHORT (0-100)
        # ════════════════════════════════════════════════════════════════
        ss, sr = 0.0, []
        sb = None

        if ENABLE_SHORTS:
            if trend_1h == 'BULL':
                sb = '1h_BULL'
                self.stats['bl_1h'] += 1
            elif trend_1h == 'BEAR':
                ss += 20; sr.append("1h_BEAR(20)")
            else:
                ss += 8;  sr.append("1h_NEUT(8)")

            if sb is None:
                # ── Trend Magic (20 pts) ──
                if tm_bear:
                    ss += 20; sr.append("TM_BEAR(20)")
                else:
                    ss -= 10; sr.append("TM_no(-10)")

                # ── RMI (25 pts) ──
                if rmi_neg:
                    ss += 25; sr.append(f"RMI_SELL(25) rmi={rsi_mfi:.0f}")
                elif rsi_mfi < 50:
                    ss += 10; sr.append(f"RMI_ok(10) rmi={rsi_mfi:.0f}")
                elif rsi_mfi > 70:
                    ss -= 5;  sr.append(f"RMI_high(-5)")

                # ── Magical Momentum (25 pts) ──
                if mom_dn:
                    ss += 25; sr.append(f"MOM_DN(25) m={mom_now:.4f}")
                elif mom_now < 0:
                    ss += 12; sr.append(f"MOM_neg(12) m={mom_now:.4f}")
                elif mom_now > 0:
                    ss -= 10; sr.append(f"MOM_pos(-10)")

                # ── RSI para SHORT (mínimo 55) ──
                if rsi_15 >= 70:
                    ss += 5; sr.append(f"RSI_OB({rsi_15:.0f})(5)")
                elif rsi_15 >= 55:
                    ss += 3; sr.append(f"RSI_alto({rsi_15:.0f})(3)")
                elif rsi_15 < 40:
                    ss -= 12; sr.append(f"RSI_bajo({rsi_15:.0f})(-12)")
                    self.stats['bl_rsi'] += 1

                # ── Volumen ──
                if vs >= 1.8:
                    p = min(5, int(vs*2.5)); ss += p; sr.append(f"Vol{vs:.1f}x({p})")
                elif vs < 1.1:
                    ss -= 5; sr.append("VolBajo(-5)")

                # ── Sobreextendido 24h ──
                if change > 5.0:
                    ss += 5; sr.append(f"24h+{change:.1f}%(5)")

        # Cap 0-100
        ls = min(100.0, max(0.0, ls))
        ss = min(100.0, max(0.0, ss))

        tp_dyn = max(TP_PCT, TP_MIN, min(TP_PCT*2.5, atr_pct*2.5))

        base = {
            'price':price,'change':change,'rsi':rsi_15,'rsi_1h':rsi_1h,
            'trend_1h':trend_1h,'vol':vs,'tp_pct':tp_dyn,'sl_pct':SL_PCT,
            'ema9':round(ema9,6),'atr_pct':round(atr_pct,2),
            'rsi_mfi':round(rsi_mfi,1),'mom':round(mom_now,5),
            'tm_bull':tm_bull,'tm_bear':tm_bear,'rmi_pos':rmi_pos,'rmi_neg':rmi_neg,
        }

        if ls >= MIN_SCORE and ls > ss and not lb:
            if self._btc_change_1h <= -BTC_FILTER_PCT: return None
            return {**base, 'signal':'LONG','score':ls,'reasons':' | '.join(lr)}

        if ss >= MIN_SCORE and ss > ls and not sb:
            if self._btc_change_1h >= BTC_FILTER_PCT: return None
            return {**base, 'signal':'SHORT','score':ss,'reasons':' | '.join(sr)}

        return None

    # ─────────────────────────────────── ÓRDENES

    def _esperar_pos(self, symbol, direction, timeout=ESPERA_POS):
        log.info(f"  ⏳ Esperando posición {symbol} {direction} (max {timeout}s)...")
        for i in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                                  {'symbol':symbol}).json()
                if d.get('code') == 0:
                    for p in (d.get('data') or []):
                        try: amt = float(p.get('positionAmt',0) or 0)
                        except: amt = 0
                        side = p.get('positionSide','')
                        ok = ((amt > 0) or (side=='LONG'  and abs(amt)>0)) if direction=='LONG' \
                             else ((amt < 0) or (side=='SHORT' and abs(amt)>0))
                        if ok:
                            try: er = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                            except: er = 0
                            log.info(f"  ✅ Posición: qty={abs(amt)} entry=${er:.6f} ({i+1}s)")
                            return abs(amt), (er if er > 0 else None)
            except: pass
            time.sleep(1)
        log.warning(f"  ⏱ Timeout {timeout}s")
        return None, None

    def _cancel_orders(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/trade/openOrders',
                              {'symbol':symbol}).json()
            if d.get('code') == 0:
                for o in (d.get('data',{}).get('orders') or []):
                    oid = o.get('orderId','')
                    if oid:
                        bingx_request('DELETE', '/openApi/swap/v2/trade/order',
                                      {'symbol':symbol,'orderId':str(oid)})
        except: pass

    def _place_entry(self, symbol, direction, usdt_qty, price):
        qty_c, _ = self._qty(symbol, price, usdt_qty)
        side = 'BUY' if direction == 'LONG' else 'SELL'
        if USE_LIMIT_ORDERS and qty_c:
            off = (1 - LIMIT_OFFSET_PCT/100) if direction=='LONG' else (1 + LIMIT_OFFSET_PCT/100)
            lp = round(price * off, 8)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':side,'positionSide':direction,
                'type':'LIMIT','price':str(lp),'quantity':str(qty_c),'timeInForce':'GTC',
            }).json()
            if d.get('code') == 0:
                log.info(f"  LÍMITE OK {qty_c} @ ${lp:.6f}")
                return d.get('data',{}).get('orderId','OK'), qty_c
            log.warning(f"  Límite falló [{d.get('code')}] → MARKET")
        if not qty_c: qty_c, _ = self._qty(symbol, price, usdt_qty)
        if not qty_c: return None, None
        d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
            'symbol':symbol,'side':side,'positionSide':direction,
            'type':'MARKET','quantity':str(qty_c),
        }).json()
        if d.get('code') == 0:
            return d.get('data',{}).get('orderId','OK'), qty_c
        log.error(f"  Entrada fallida [{d.get('code')}]: {d.get('msg')}")
        return None, None

    def _cond_order(self, symbol, direction, qty_c, stop_price, otype):
        if not qty_c or qty_c <= 0: return False
        try:
            is_tp = "TAKE" in otype
            cs = 'SELL' if direction == 'LONG' else 'BUY'
            if is_tp:
                params = {'symbol':symbol,'side':cs,'positionSide':direction,
                          'type':'TAKE_PROFIT','quantity':str(qty_c),
                          'price':str(round(stop_price,8)),
                          'stopPrice':str(round(stop_price,8)),'timeInForce':'GTC'}
            else:
                params = {'symbol':symbol,'side':cs,'positionSide':direction,
                          'type':'STOP_MARKET','quantity':str(qty_c),
                          'stopPrice':str(round(stop_price,8))}
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json()
            ok = d.get('code') == 0
            if ok:
                log.info(f"  {'TP' if is_tp else 'SL'} ✅ @ ${stop_price:.6f}")
            else:
                if is_tp:
                    p2 = {'symbol':symbol,'side':cs,'positionSide':direction,
                          'type':'TAKE_PROFIT_MARKET','quantity':str(qty_c),
                          'stopPrice':str(round(stop_price,8))}
                    d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', p2).json()
                    ok = d2.get('code') == 0
                    if ok: log.info(f"  TP ✅ (fallback) @ ${stop_price:.6f}")
                    else:  log.error(f"  TP ❌ [{d2.get('code')}]: {d2.get('msg')}")
                else:
                    log.error(f"  SL ❌ [{d.get('code')}]: {d.get('msg')}")
            return ok
        except Exception as e:
            log.error(f"  {otype} exc: {e}"); return False

    def _tpsl(self, symbol, direction, qty_c, tp_price, sl_price):
        """5 reintentos con delays crecientes"""
        tp_ok = sl_ok = False
        for delay in [0, 3, 5, 8, 12]:
            if tp_ok and sl_ok: break
            if delay: time.sleep(delay)
            if not tp_ok: tp_ok = self._cond_order(symbol,direction,qty_c,tp_price,'TAKE_PROFIT_MARKET')
            if not sl_ok: sl_ok = self._cond_order(symbol,direction,qty_c,sl_price,'STOP_MARKET')
        if not tp_ok or not sl_ok:
            self._tg(f"⚠️ {direction} {symbol} — "
                     f"{'❌TP' if not tp_ok else '✅TP'} "
                     f"{'❌SL' if not sl_ok else '✅SL'} — FIJAR MANUAL")
        return tp_ok, sl_ok

    def _close_pos(self, symbol, direction, t):
        qty_c = t.get('qty_c', 0)
        cs = 'SELL' if direction == 'LONG' else 'BUY'
        if qty_c and qty_c > 0:
            p = {'symbol':symbol,'side':cs,'positionSide':direction,
                 'type':'MARKET','quantity':str(qty_c),'reduceOnly':'true'}
        else:
            p = {'symbol':symbol,'side':cs,'positionSide':direction,
                 'type':'MARKET','quoteOrderQty':str(round(t.get('usdt_qty',POSITION_SIZE),2)),
                 'reduceOnly':'true'}
        return bingx_request('POST', '/openApi/swap/v2/trade/order', p).json().get('code') == 0

    def _tiene_pos(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                              {'symbol':symbol}).json()
            if d.get('code') == 0:
                for p in (d.get('data') or []):
                    amt = float(p.get('positionAmt',0) or 0)
                    if abs(amt) > 0:
                        return True, 'LONG' if amt>0 else 'SHORT'
        except: pass
        return False, None

    # ─────────────────────────────────── LIFECYCLE

    def open_trade(self, symbol, sig):
        direction = sig['signal']
        if not AUTO_TRADING:
            tm  = '🟢TM' if (direction=='LONG' and sig['tm_bull']) or (direction=='SHORT' and sig['tm_bear']) else '🔴TM'
            rmi = '🟢RMI' if (direction=='LONG' and sig['rmi_pos']) or (direction=='SHORT' and sig['rmi_neg']) else '⚪RMI'
            mom = '🟢MOM' if sig['mom'] > 0 else '🔴MOM'
            log.info(f"  [SEÑAL] {direction} {symbol} {sig['score']:.0f}/100 "
                     f"{tm} {rmi} {mom} 1h:{sig['trend_1h']}")
            return False

        if symbol in self.open_trades: return False

        longs, shorts = self._contar_dir()
        if direction=='LONG'  and longs  >= MAX_SAME_DIR:
            self.stats['bl_corr']+=1; return False
        if direction=='SHORT' and shorts >= MAX_SAME_DIR:
            self.stats['bl_corr']+=1; return False

        tiene, _ = self._tiene_pos(symbol)
        if tiene: return False

        price    = sig['price']
        usdt_qty = round(max(POSITION_SIZE, MIN_TRADE), 2)
        tp_price = price * (1 + sig['tp_pct']/100) if direction=='LONG' \
                   else price * (1 - sig['tp_pct']/100)
        sl_price = price * (1 - sig['sl_pct']/100) if direction=='LONG' \
                   else price * (1 + sig['sl_pct']/100)

        emoji = "📈" if direction == 'LONG' else "📉"
        tm_st  = '✅TM'  if (direction=='LONG' and sig['tm_bull']) or (direction=='SHORT' and sig['tm_bear']) else '❌TM'
        rmi_st = '✅RMI' if (direction=='LONG' and sig['rmi_pos']) or (direction=='SHORT' and sig['rmi_neg']) else '⚪RMI'
        mom_st = f"MOM:{sig['mom']:+.4f}"

        log.info(f"\n  ➤ {direction} {symbol}")
        log.info(f"  Score:{sig['score']:.0f}/100 | {tm_st} {rmi_st} {mom_st}")
        log.info(f"  1h:{sig['trend_1h']} RSI1h:{sig['rsi_1h']:.0f} RSI15:{sig['rsi']:.0f} "
                 f"RMI:{sig['rsi_mfi']:.0f}")
        log.info(f"  {sig['reasons']}")
        log.info(f"  Entry:${price:.6f} | ${usdt_qty}×{LEVERAGE} | "
                 f"TP:{sig['tp_pct']:.2f}% SL:{sig['sl_pct']:.1f}%")

        oid, qty_c = self._place_entry(symbol, direction, usdt_qty, price)
        if not oid: return False

        qty_r, entry_r = self._esperar_pos(symbol, direction, ESPERA_POS)
        if qty_r is None:
            log.warning(f"  LIMIT no ejecutada → cancelando + MARKET")
            self._cancel_orders(symbol)
            time.sleep(0.5)
            side = 'BUY' if direction=='LONG' else 'SELL'
            dm = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol':symbol,'side':side,'positionSide':direction,
                'type':'MARKET','quantity':str(qty_c),
            }).json()
            if dm.get('code') == 0:
                qty_r, entry_r = self._esperar_pos(symbol, direction, 30)
            if qty_r is None:
                self.open_trades[symbol] = {
                    'direction':direction,'entry':price,'qty_c':qty_c,
                    'usdt_qty':usdt_qty,'tp':tp_price,'sl':sl_price,
                    'tp_pct':sig['tp_pct'],'sl_pct':sig['sl_pct'],
                    'highest':price,'lowest':price,'order_id':oid,
                    'tp_ok':False,'sl_ok':False,'opened_at':datetime.now(),'score':sig['score'],
                }
                self._tg(f"⚠️ {direction} {symbol} SIN TP/SL — FIJAR MANUAL")
                return True

        if entry_r and entry_r > 0:
            tp_price = entry_r*(1+sig['tp_pct']/100) if direction=='LONG' \
                       else entry_r*(1-sig['tp_pct']/100)
            sl_price = entry_r*(1-sig['sl_pct']/100) if direction=='LONG' \
                       else entry_r*(1+sig['sl_pct']/100)

        qf = qty_r if qty_r else qty_c
        ef = entry_r if (entry_r and entry_r > 0) else price

        tp_ok, sl_ok = self._tpsl(symbol, direction, qf, tp_price, sl_price)

        self.open_trades[symbol] = {
            'direction':direction,'entry':ef,'qty_c':qf,'usdt_qty':usdt_qty,
            'tp':tp_price,'sl':sl_price,'tp_pct':sig['tp_pct'],'sl_pct':sig['sl_pct'],
            'highest':ef,'lowest':ef,'order_id':oid,'tp_ok':tp_ok,'sl_ok':sl_ok,
            'opened_at':datetime.now(),'score':sig['score'],
        }
        self.stats['exec'] += 1

        self._tg(
            f"<b>{emoji} {direction} ABIERTO</b>\n<b>{symbol}</b> | Score:{sig['score']:.0f}/100\n"
            f"Entrada: ${ef:.6f}\n"
            f"{'✅' if tp_ok else '❌ MANUAL'} TP: ${tp_price:.6f} ({sig['tp_pct']:.2f}%)\n"
            f"{'✅' if sl_ok else '❌ MANUAL'} SL: ${sl_price:.6f} ({sig['sl_pct']:.1f}%)\n"
            f"Capital: ${usdt_qty} ×{LEVERAGE} = ${usdt_qty*LEVERAGE:.1f} USDT | qty:{qf}\n"
            f"{tm_st} {rmi_st} {mom_st} | RMI:{sig['rsi_mfi']:.0f}\n"
            f"1h:{sig['trend_1h']} RSI1h:{sig['rsi_1h']:.0f} BTC:{self._btc_change_1h:+.2f}%\n"
            f"{sig['reasons']}"
        )
        return True

    def close_trade(self, symbol, cur_price, reason):
        if symbol not in self.open_trades: return False
        t = self.open_trades[symbol]
        direction = t['direction']
        self._close_pos(symbol, direction, t)
        cambio = (cur_price-t['entry'])/t['entry'] if direction=='LONG' \
                 else (t['entry']-cur_price)/t['entry']
        pnl     = (t['usdt_qty']*LEVERAGE*cambio) - (t['usdt_qty']*LEVERAGE*COMISION_ACTUAL*2)
        pnl_pct = (pnl/t['usdt_qty'])*100
        self.stats['closed'] += 1; self.stats['pnl'] += pnl
        tipo = 'win' if pnl > 0 else 'loss'
        if pnl > 0: self.stats['wins']   += 1
        else:        self.stats['losses'] += 1
        total = self.stats['wins']+self.stats['losses']
        wr    = self.stats['wins']/total*100 if total else 0
        mins  = int((datetime.now()-t['opened_at']).total_seconds()/60)
        emoji = "✅" if pnl > 0 else "❌"
        log.info(f"  {emoji} {reason} {symbol} {direction} PnL:${pnl:+.3f}({pnl_pct:+.1f}%) {mins}min")
        self._tg(
            f"<b>{emoji} {direction} CERRADO — {reason}</b>\n<b>{symbol}</b>\n"
            f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ${t['entry']:.6f} → Exit: ${cur_price:.6f} | {mins}min\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}% "
            f"({self.stats['wins']}W/{self.stats['losses']}L)</b>"
        )
        self._cooldowns[symbol] = (time.time(), tipo)
        del self.open_trades[symbol]
        return True

    # ─────────────────────────────────── MONITOR

    async def _sync(self):
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
                    dir = t['direction']
                    tk  = self._ticker(sym)
                    cur = tk['price'] if tk else t['entry']
                    c   = (cur-t['entry'])/t['entry'] if dir=='LONG' else (t['entry']-cur)/t['entry']
                    pnl = (t['usdt_qty']*LEVERAGE*c) - (t['usdt_qty']*LEVERAGE*COMISION_ACTUAL*2)
                    pnl_pct = (pnl/t['usdt_qty'])*100
                    self.stats['closed']+=1; self.stats['pnl']+=pnl
                    tipo = 'win' if pnl>=0 else 'loss'
                    if pnl>=0: self.stats['wins']+=1
                    else:       self.stats['losses']+=1
                    total = self.stats['wins']+self.stats['losses']
                    wr = self.stats['wins']/total*100 if total else 0
                    mins = int((datetime.now()-t['opened_at']).total_seconds()/60)
                    emoji = "✅" if pnl>=0 else "❌"
                    self._tg(f"<b>{emoji} {dir} cerrado BingX</b>\n<b>{sym}</b>\n"
                             f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min\n"
                             f"Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                    self._cooldowns[sym] = (time.time(), tipo)
                    del self.open_trades[sym]
        except Exception as e: log.debug(f"sync: {e}")

    async def monitor(self):
        await self._sync()
        for sym in list(self.open_trades.keys()):
            try:
                t  = self.open_trades[sym]
                tk = self._ticker(sym)
                if not tk: continue
                cur = tk['price']
                dir = t['direction']
                if dir == 'LONG':
                    pnl_pct = (cur-t['entry'])/t['entry']*100
                    if TRAILING and cur > t['highest']:
                        t['highest'] = cur
                        if pnl_pct >= 0.6:
                            nsl = t['entry'] + (cur-t['entry'])*0.60
                            if nsl > t['sl']:
                                t['sl'] = nsl
                                log.info(f"  Trailing SL {sym}: ${nsl:.6f}")
                    hit_tp = cur >= t['tp']; hit_sl = cur <= t['sl']
                else:
                    pnl_pct = (t['entry']-cur)/t['entry']*100
                    if TRAILING and cur < t['lowest']:
                        t['lowest'] = cur
                        if pnl_pct >= 0.6:
                            nsl = t['entry'] - (t['entry']-cur)*0.60
                            if nsl < t['sl']:
                                t['sl'] = nsl
                                log.info(f"  Trailing SL {sym}: ${nsl:.6f}")
                    hit_tp = cur <= t['tp']; hit_sl = cur >= t['sl']
                if abs(pnl_pct) > 0.3:
                    log.info(f"  {sym} {dir}: {pnl_pct:+.2f}% | ${cur:.6f}")
                if hit_tp:   self.close_trade(sym, cur, "TAKE PROFIT")
                elif hit_sl: self.close_trade(sym, cur, "STOP LOSS")
            except Exception as e: log.debug(f"monitor {sym}: {e}")

    def _reporte(self):
        if datetime.now() - self._last_report < timedelta(hours=1): return
        self._last_report = datetime.now()
        total = self.stats['wins']+self.stats['losses']
        wr    = self.stats['wins']/total*100 if total else 0
        self._tg(
            f"<b>📊 Reporte horario — Dual Strategy</b>\n"
            f"PnL: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%\n"
            f"({self.stats['wins']}W/{self.stats['losses']}L | {self.stats['closed']} trades)\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES}\n"
            f"BTC 1h:{self._btc_change_1h:+.2f}% trend:{self._btc_trend_1h}\n"
            f"Bloq 1h:{self.stats['bl_1h']} RSI:{self.stats['bl_rsi']} corr:{self.stats['bl_corr']}"
        )

    def _tg(self, msg):
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id':TELEGRAM_CHAT,'text':msg,'parse_mode':'HTML'},
                    timeout=6)
        except: pass

    # ─────────────────────────────────── LOOP

    async def run(self):
        log.info(f"\n▶  Dual Strategy Bot — {'AUTO' if AUTO_TRADING else '⚠️ SEÑALES'}\n")
        iteration, last_refresh = 0, 0
        while True:
            try:
                iteration += 1
                if time.time() - last_refresh > 600:
                    self._get_symbols(); last_refresh = time.time()
                self._update_btc()
                total = self.stats['wins']+self.stats['losses']
                wr    = self.stats['wins']/total*100 if total else 0
                longs, shorts = self._contar_dir()
                log.info(f"\n{'='*65}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"L:{longs} S:{shorts}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                log.info(f"  BTC 1h:{self._btc_change_1h:+.2f}% {self._btc_trend_1h} | "
                         f"Bloq 1h:{self.stats['bl_1h']} RSI:{self.stats['bl_rsi']} "
                         f"corr:{self.stats['bl_corr']}")
                log.info(f"{'='*65}\n")
                await self.monitor()
                self._reporte()
                if len(self.open_trades) < MAX_TRADES:
                    found, entries = 0, 0
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES: break
                        if entries >= MAX_PER_CYCLE: break
                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            tm  = '✅TM'  if (sig['signal']=='LONG' and sig['tm_bull']) or \
                                           (sig['signal']=='SHORT' and sig['tm_bear']) else '❌TM'
                            rmi = '✅RMI' if (sig['signal']=='LONG' and sig['rmi_pos']) or \
                                           (sig['signal']=='SHORT' and sig['rmi_neg']) else '⚪RMI'
                            log.info(f"  ★ {sig['signal']} {sym} {sig['score']:.0f}/100 "
                                     f"{tm} {rmi} MOM:{sig['mom']:+.4f} 1h:{sig['trend_1h']}")
                            if self.open_trade(sym, sig): entries += 1
                        await asyncio.sleep(0.15)
                        if (i+1) % 25 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)}")
                    log.info(f"\n  {len(self.symbols)} pares | {found} señales | {entries} entradas")
                else:
                    log.info(f"  Max {MAX_TRADES} trades — esperando cierre")
                log.info(f"\n  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)
            except KeyboardInterrupt:
                log.info("Detenido"); break
            except Exception as e:
                log.error(f"Error #{iteration}: {e}"); await asyncio.sleep(20)


async def main():
    try: await DualStrategyBot().run()
    except Exception as e: log.error(f"Fatal: {e}")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: log.info("Terminado")
