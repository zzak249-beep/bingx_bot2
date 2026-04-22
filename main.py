#!/usr/bin/env python3
"""
BOT LONGS v6.0-ALPHA — MÁXIMA PRECISIÓN + GESTIÓN AVANZADA
════════════════════════════════════════════════════════════════════════════════

MEJORAS v6.0 vs v5.9-FIXED:
  ✅ [M1]  QUALITY GATE: bloqueo duro Breadth<20%, excluye forex sintéticos
  ✅ [M2]  VOLATILITY REGIME: detecta compresión/expansión ATR antes de entrar
  ✅ [M3]  ORDER FLOW PROXY: volumen delta alcista como confirmación de entrada
  ✅ [M4]  MULTI-TIMEFRAME SCORE: confluencia 5m+1h+4h ponderada
  ✅ [M5]  DYNAMIC SL: SL ajustado por volatilidad real del símbolo
  ✅ [M6]  BREAKEVEN AGRESIVO: BE inmediato tras +0.5*SL de beneficio
  ✅ [M7]  PARTIAL CLOSE DINÁMICO: TP1 basado en ATR, no ratio fijo
  ✅ [M8]  MOMENTUM QUALITY FILTER: excluye microcaps y pares manipulados
  ✅ [M9]  LEARNING 2.0: ajuste de score más agresivo, blacklist por hora
  ✅ [M10] ANTI-CHOP: detecta mercados laterales y los bloquea
  ✅ [M11] POSITION SIZING DINÁMICO: Kelly fraccionado según WR reciente
  ✅ [M12] CIERRE PREVENTIVO: sale en verde si régimen se deteriora
  ✅ [M13] HEAT MAP HORARIO: aprende qué horas son rentables por símbolo
  ✅ [M14] SPREAD GUARD: rechaza entradas con spread >0.3%
  ✅ [M15] CORRELATION BLOCK: no abre 2 posiciones correlacionadas (>0.85)
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re, json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================================
# CONFIG
# ============================================================================

def clean(key, default, typ='str'):
    v = os.getenv(key, str(default)).strip()
    if v.startswith('"') and v.endswith('"'): v = v[1:-1]
    elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
    if typ in ('int', 'float'):
        v = v.replace(',', '.')
        m = re.match(r'^-?\d+\.?\d*', v)
        v = m.group(0) if m else str(default)
    if typ == 'int':   return int(float(v))
    if typ == 'float': return float(v)
    if typ == 'bool':  return v.lower() == 'true'
    return v

def _strip_quotes(s):
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

API_KEY    = _strip_quotes(os.getenv('BINGX_API_KEY',    ''))
API_SECRET = _strip_quotes(os.getenv('BINGX_API_SECRET', ''))
TG_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN', '')
TG_CHAT    = os.getenv('TELEGRAM_CHAT_ID',   '')

# ── Capital ────────────────────────────────────────────────────────────────
AUTO           = clean('AUTO_TRADING_ENABLED', 'true',  'bool')
POS_SIZE       = clean('MAX_POSITION_SIZE',    '10',    'float')
MIN_TRADE      = clean('MIN_TRADE_USDT',       '10',    'float')
_lev           = clean('LEVERAGE',             '2',     'int')
LEVERAGE       = min(_lev, 3)
MAX_TRADES     = clean('MAX_OPEN_TRADES',      '2',     'int')   # [M11] reducido a 2
RISK_PCT       = clean('RISK_PCT',             '0.8',   'float') # [M11] reducido
ACCOUNT_EQUITY = clean('ACCOUNT_EQUITY',       '100',   'float')

# ── TPs Escalonados ────────────────────────────────────────────────────────
TP1_PCT   = clean('TP1_PCT',   '40',  'float')
TP2_PCT   = clean('TP2_PCT',   '35',  'float')
TP1_RATIO = clean('TP1_RATIO', '2.0', 'float')
TP2_RATIO = clean('TP2_RATIO', '3.5', 'float')

# ── TP/SL ──────────────────────────────────────────────────────────────────
TP_MIN    = clean('TAKE_PROFIT_PCT', '1.5',  'float')
ATR_TP_M  = clean('ATR_TP_MULT',    '3.5',  'float')  # [M7] subido
MIN_RR    = clean('MIN_RR',         '2.5',  'float')  # [M4] más exigente
SL_ATR_M  = clean('SL_ATR_MULT',   '1.2',  'float')  # [M5] ajustado
SL_MAX_PCT = clean('SL_MAX_PCT',   '3.0',  'float')  # [M5] reducido de 3.5
SL_MIN_PCT = clean('SL_MIN_PCT',   '0.8',  'float')

# ── Trailing Stop ──────────────────────────────────────────────────────────
USE_TRAILING_EXIT = clean('USE_TRAILING_EXIT', 'true', 'bool')
TRAIL_RATE_PCT    = clean('TRAIL_RATE_PCT',    '1.2',  'float')  # más ajustado
TRAIL_ACTIVATION  = clean('TRAIL_ACTIVATION',  '0.6',  'float')  # activa antes [M6]

# ── Zombie cleanup ────────────────────────────────────────────────────────
ZOMBIE_CLEANUP_MIN = clean('ZOMBIE_CLEANUP_MIN', '10', 'int')
ZOMBIE_MAX_AGE_MIN = clean('ZOMBIE_MAX_AGE_MIN', '20', 'int')

# ── Símbolos y volumen ────────────────────────────────────────────────────
MIN_VOL   = clean('MIN_VOLUME_24H',  '500000',  'float')  # [M8] subido a 500K
MAX_SYMS  = clean('MAX_SYMBOLS',     '0',       'int')
MIN_SCORE = clean('MIN_SCORE',       '65',      'float')  # [M9] subido
BTC_BLOCK = clean('BTC_BEAR_BLOCK_PCT', '1.0', 'float')

# ── Momentum pre-filter ───────────────────────────────────────────────────
MOMENTUM_TOP_N      = clean('MOMENTUM_TOP_N',      '30',   'int')   # más selectivo
MOMENTUM_MIN_4H     = clean('MOMENTUM_MIN_4H',     '0.8',  'float') # [M8] subido
MOMENTUM_MIN_24H    = clean('MOMENTUM_MIN_24H',    '0.5',  'float') # [M8] subido
MOMENTUM_MAX_RSI    = clean('MOMENTUM_MAX_RSI',    '72',   'float') # más estricto
MOMENTUM_MIN_VOL_R  = clean('MOMENTUM_MIN_VOL_R',  '1.0',  'float')
MOMENTUM_MIN_VOL_ABS = clean('MOMENTUM_MIN_VOL_ABS', '1000000', 'float')  # [M8] 1M mínimo

# ── Régimen de mercado ────────────────────────────────────────────────────
REGIME_CHECK      = clean('REGIME_CHECK',      'true',  'bool')
BREADTH_MIN       = clean('BREADTH_MIN',        '0.45',  'float')  # [M1] subido
BREADTH_CRITICAL  = clean('BREADTH_CRITICAL',   '0.20',  'float')  # [M1] bloqueo duro
BTC_4H_CRASH_PCT  = clean('BTC_4H_CRASH_PCT',  '2.5',   'float')  # más sensible
BTC_4H_CRASH_PAUSE= clean('BTC_4H_CRASH_HOURS','3',      'int')
DAILY_LOSS_CAP_PCT= clean('DAILY_LOSS_CAP_PCT','8.0',   'float')  # más conservador
CAUTION_BLOCK     = clean('CAUTION_BLOCK',      'true',  'bool')
SCORE_BULL        = clean('SCORE_BULL',         '63',    'float')
SCORE_NEUTRAL     = clean('SCORE_NEUTRAL',      '72',    'float')  # más exigente

# ── Anti-chop [M10] ───────────────────────────────────────────────────────
CHOP_CHECK        = clean('CHOP_CHECK',         'true',  'bool')
CHOP_ATR_RATIO    = clean('CHOP_ATR_RATIO',     '0.6',   'float')  # ATR/rango comprimido

# ── VWAP ──────────────────────────────────────────────────────────────────
VWAP_CANDLES   = clean('VWAP_CANDLES',  '50',   'int')
VWAP_AS_FILTER = clean('VWAP_FILTER',  'true',  'bool')

# ── Motor Aurolo ──────────────────────────────────────────────────────────
AUROLO_EMA_LEN   = clean('AUROLO_EMA_LEN',   '55',   'int')
AUROLO_ZONA_AUTO = clean('AUROLO_ZONA_AUTO',  'true', 'bool')
AUROLO_ZONA_PCT  = clean('AUROLO_ZONA_PCT',   '0.8',  'float')
AUROLO_ZONA_VELAS = clean('AUROLO_ZONA_VELAS', '6',   'int')
AUROLO_MIN_PTS = clean('AUROLO_MIN_PTS', '2',     'int')
AUROLO_ENTRY   = clean('AUROLO_ENTRY',   'close', 'str')

# WaveTrend
WT_CH_LEN  = clean('WT_CH_LEN',  '10',  'int')
WT_AVG_LEN = clean('WT_AVG_LEN', '21',  'int')
WT_OB1     = clean('WT_OB1',     '60',  'float')
WT_OB2     = clean('WT_OB2',     '42',  'float')
WT_OS1     = clean('WT_OS1',     '-60', 'float')
WT_OS2     = clean('WT_OS2',     '-42', 'float')
WT_OS_ENTRY = clean('WT_OS_ENTRY', '-20', 'float')

# ADX
ADX_LEN    = clean('ADX_LEN',    '14',  'int')
ADX_DI_LEN = clean('ADX_DI_LEN', '14', 'int')
ADX_KEY    = clean('ADX_KEY',    '22',  'float')  # más exigente

# ── Circuit breaker ───────────────────────────────────────────────────────
CB_PCT     = clean('CIRCUIT_BREAKER_PCT', '5.0',  'float')  # más sensible
CB_HOURS   = clean('CB_PAUSE_HOURS',      '3',    'int')
MAX_STREAK = clean('MAX_LOSING_STREAK',   '3',    'int')   # [M9] reducido a 3

# ── Cooldowns ─────────────────────────────────────────────────────────────
CD_TP        = clean('COOLDOWN_TP_MIN',  '15',  'int')
CD_SL        = clean('COOLDOWN_SL_MIN', '360',  'int')  # 6h tras SL
CD_SL_TODAY  = clean('COOLDOWN_SL_TODAY', 'true', 'bool')
CD_SL_FAST_MIN   = clean('COOLDOWN_SL_FAST_MIN', '5', 'int')
CD_SL_FAST_HOURS = clean('COOLDOWN_SL_FAST_HOURS', '12', 'int')  # más largo

# ── Aprendizaje ───────────────────────────────────────────────────────────
LEARN_MIN_TRADES_SCORE = clean('LEARN_MIN_TRADES', '8', 'int')   # reacciona antes
LEARN_MIN_TRADES_BL    = clean('LEARN_MIN_TRADES_BL', '4', 'int')
SCORE_CAP_LOW          = clean('SCORE_CAP_LOW', '72',  'float')
SCORE_CAP_HIGH         = clean('SCORE_CAP_HIGH', '88', 'float')

# ── Misc ──────────────────────────────────────────────────────────────────
INTERVAL   = clean('CHECK_INTERVAL', '90', 'int')
LTV_WARN   = clean('LTV_WARNING_PCT', '70', 'float')  # más conservador
SCAN_WORKERS = clean('SCAN_WORKERS', '8', 'int')

_skip_raw  = os.getenv('SKIP_HOURS', '2,3')
SKIP_HOURS = set(int(x.strip()) for x in _skip_raw.split(',') if x.strip().isdigit())

BASE_URL   = "https://open-api.bingx.com"
FEE        = 0.0002
FEE_COST_PCT = FEE * LEVERAGE * 2 * 100
TP_MIN_FEE   = round(FEE_COST_PCT + 0.003 * 100, 3)

# [M1] Excluir stablecoins, forex puro Y patrones de pares sintéticos
EXCLUDE = {
    'USDC', 'BUSD', 'TUSD', 'FRAX', 'DAI', 'USDP', 'FDUSD',
    'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD',
}

# [M1] Patrones de pares sintéticos/forex a excluir
EXCLUDE_PATTERNS = [
    'NCSK', 'NCF', 'NCS', 'GBP2', 'JPY2', 'USD2', 'EUR2',
    'MSFT', 'AAPL', 'GOOGL', 'TSLA', 'AMZN',  # stocks sintéticos
]

BREADTH_COINS = [
    'BTC-USDT','ETH-USDT','BNB-USDT','SOL-USDT','XRP-USDT',
    'ADA-USDT','AVAX-USDT','DOGE-USDT','DOT-USDT','MATIC-USDT',
    'LINK-USDT','UNI-USDT','ATOM-USDT','LTC-USDT','BCH-USDT',
    'NEAR-USDT','APT-USDT','OP-USDT','ARB-USDT','SUI-USDT',
]

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
            if attempt < retries: time.sleep(2 ** attempt)
            else: log.error(f"API {endpoint}: {e}"); return {}

def pub(path, params=None):
    try:
        return requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=10).json()
    except:
        return {}

def _safe_float(val, default=0.0):
    if val is None: return default
    if isinstance(val, dict):
        for k in ('equity', 'balance', 'availableMargin', 'amount'):
            if k in val: return _safe_float(val[k], default)
        return default
    try: return float(val)
    except: return default

# ============================================================================
# INDICADORES
# ============================================================================

def ema(prices, n):
    if not prices: return 0
    if len(prices) < n: return sum(prices) / len(prices)
    k, e = 2 / (n + 1), prices[0]
    for p in prices[1:]: e = p * k + e * (1 - k)
    return e

def rsi(prices, n=14):
    if len(prices) < n + 1: return 50.0
    g = [max(prices[i] - prices[i-1], 0) for i in range(1, len(prices))]
    l = [max(prices[i-1] - prices[i], 0) for i in range(1, len(prices))]
    ag, al = sum(g[-n:]) / n, sum(l[-n:]) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

def atr_calc(highs, lows, closes, n=14):
    if len(closes) < 2: return 0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, min(len(closes), n+1))]
    return sum(trs) / len(trs) if trs else 0

def calc_vwap(closes, highs, lows, volumes, n=None):
    n = n or len(closes)
    c = closes[-n:]; h = highs[-n:]; l = lows[-n:]; v = volumes[-n:]
    tp_vol  = sum(((h[i]+l[i]+c[i])/3) * v[i] for i in range(len(c)))
    vol_sum = sum(v)
    return tp_vol / vol_sum if vol_sum > 0 else c[-1]

# [M2] Volatility Regime Detection
def volatility_regime(highs, lows, closes, n=14, lookback=50):
    """
    Detecta si el mercado está en expansión o compresión de volatilidad.
    Retorna: 'expanding', 'normal', 'compressed'
    """
    if len(closes) < lookback + n:
        return 'normal', 1.0

    atr_now = atr_calc(highs[-n:], lows[-n:], closes[-n:], n)
    atr_hist = []
    for i in range(lookback, 0, -10):
        a = atr_calc(highs[-(i+n):-i], lows[-(i+n):-i], closes[-(i+n):-i], n)
        if a > 0:
            atr_hist.append(a)

    if not atr_hist:
        return 'normal', 1.0

    atr_avg = sum(atr_hist) / len(atr_hist)
    ratio = atr_now / atr_avg if atr_avg > 0 else 1.0

    if ratio > 1.5:   return 'expanding', ratio
    elif ratio < 0.6: return 'compressed', ratio
    else:             return 'normal', ratio

# [M3] Order Flow Proxy — volumen delta
def order_flow_delta(closes, volumes, n=10):
    """
    Proxy del order flow: compara velas alcistas vs bajistas por volumen.
    Positivo = presión compradora. Rango: -1 a +1
    """
    if len(closes) < n + 1:
        return 0.0

    bull_vol = 0.0
    bear_vol = 0.0
    for i in range(-n, 0):
        if closes[i] >= closes[i-1]:
            bull_vol += volumes[i]
        else:
            bear_vol += volumes[i]

    total = bull_vol + bear_vol
    if total == 0:
        return 0.0
    return (bull_vol - bear_vol) / total  # -1 a +1

# [M10] Anti-Chop: detecta mercados laterales
def is_choppy(highs, lows, closes, n=20):
    """
    Detecta mercado lateral/choppy usando el Choppiness Index.
    CI > 61.8 = choppy, < 38.2 = tendencia fuerte
    """
    if len(closes) < n + 1:
        return False

    h = highs[-n:]; l = lows[-n:]; c = closes[-(n+1):]
    atr_sum = 0.0
    for i in range(1, n + 1):
        tr = max(h[i-1] - l[i-1],
                 abs(h[i-1] - c[i-1]),
                 abs(l[i-1] - c[i-1]))
        atr_sum += tr

    highest = max(h)
    lowest  = min(l)
    rango   = highest - lowest

    if rango == 0 or atr_sum == 0:
        return False

    ci = 100 * math.log10(atr_sum / rango) / math.log10(n)
    return ci > 61.8  # choppy si CI > 61.8

# [M15] Correlación entre símbolos
def correlation(a_prices, b_prices, n=20):
    """Correlación de Pearson entre dos series de precios."""
    n = min(n, len(a_prices), len(b_prices))
    if n < 5:
        return 0.0
    a = a_prices[-n:]; b = b_prices[-n:]
    ma = sum(a) / n; mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da  = math.sqrt(sum((x - ma)**2 for x in a))
    db  = math.sqrt(sum((x - mb)**2 for x in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)

# ============================================================================
# MOTOR AUROLO (mejorado)
# ============================================================================

def _wavetrend_series(closes, highs, lows, ch_len=10, avg_len=21):
    n = len(closes)
    if n < ch_len + avg_len + 2: return [0.0] * n
    hlc3 = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    k  = 2 / (ch_len + 1)
    esa = [hlc3[0]] * n
    for i in range(1, n): esa[i] = hlc3[i] * k + esa[i-1] * (1 - k)
    d  = [abs(hlc3[i] - esa[i]) for i in range(n)]
    de = [d[0]] * n
    for i in range(1, n): de[i] = d[i] * k + de[i-1] * (1 - k)
    ci = [(hlc3[i] - esa[i]) / (0.015 * de[i]) if de[i] != 0 else 0 for i in range(n)]
    k2  = 2 / (avg_len + 1)
    wt1 = [ci[0]] * n
    for i in range(1, n): wt1[i] = ci[i] * k2 + wt1[i-1] * (1 - k2)
    return wt1


def _adx_di_series(highs, lows, closes, di_len=14, adx_smooth=14):
    n = len(closes)
    if n < di_len + adx_smooth + 2:
        return [0.0]*n, [0.0]*n, [0.0]*n
    tr = [0.0]*n; pdm = [0.0]*n; ndm = [0.0]*n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr[i]  = max(h-l, abs(h-pc), abs(l-pc))
        up, dn = highs[i]-highs[i-1], lows[i-1]-lows[i]
        pdm[i] = max(up, 0) if up > dn else 0
        ndm[i] = max(dn, 0) if dn > up else 0
    def wilder(data, n):
        s = [0.0] * len(data)
        if n < len(data):
            s[n] = sum(data[1:n+1])
            for i in range(n+1, len(data)):
                s[i] = s[i-1] - s[i-1]/n + data[i]
        return s
    atr_s = wilder(tr, di_len); pdm_s = wilder(pdm, di_len); ndm_s = wilder(ndm, di_len)
    dip = [100*pdm_s[i]/atr_s[i] if atr_s[i]>0 else 0 for i in range(n)]
    din = [100*ndm_s[i]/atr_s[i] if atr_s[i]>0 else 0 for i in range(n)]
    dx  = [abs(dip[i]-din[i])/(dip[i]+din[i])*100 if (dip[i]+din[i])>0 else 0 for i in range(n)]
    adx_v = [0.0] * n
    start = di_len + adx_smooth
    if start < n:
        adx_v[start] = sum(dx[di_len:start+1]) / adx_smooth
        for i in range(start+1, n):
            adx_v[i] = (adx_v[i-1]*(adx_smooth-1) + dx[i]) / adx_smooth
    return adx_v, dip, din


def aurolo_signal(closes, highs, lows, volumes, opens, atr_v=None):
    result = {
        'puntos': 0, 'señal': 'NO', 'p1': False, 'p2': False, 'p3': False,
        'ema55': 0, 'zona_inf': 0, 'zona_sup': 0,
        'wt_now': 0, 'wt_prev': 0, 'adx_now': 0, 'dip': 0, 'din': 0,
        'sl_price': 0, 'sl_pct': 0, 'debilidad': False,
        'cambio_tend': False, 'descripcion': '', 'vol_ratio': 1,
        'of_delta': 0.0,  # [M3] order flow delta
    }

    min_len = AUROLO_EMA_LEN + WT_CH_LEN + WT_AVG_LEN + 5
    if len(closes) < min_len:
        result['descripcion'] = 'Datos insuficientes'
        return result

    price    = closes[-1]
    ema55    = ema(closes, AUROLO_EMA_LEN)
    result['ema55'] = ema55

    ema55_prev       = ema(closes[:-1], AUROLO_EMA_LEN)
    tendencia_ahora  = price > ema55
    tendencia_antes  = closes[-2] > ema55_prev if len(closes) >= 2 else tendencia_ahora
    result['cambio_tend'] = (tendencia_ahora != tendencia_antes)

    if not tendencia_ahora:
        result['señal'] = 'NO'
        result['descripcion'] = f'Bajista (p={round(price,4)} < EMA55={round(ema55,4)})'
        return result

    if AUROLO_ZONA_AUTO and atr_v and atr_v > 0:
        zona_pct = (atr_v / price * 100) * 1.0
        zona_pct = max(min(zona_pct, 2.0), 0.3)
    else:
        zona_pct = AUROLO_ZONA_PCT
    zona_inf = ema55 * (1 - zona_pct / 100)
    zona_sup = ema55 * (1 + zona_pct / 100)
    result['zona_inf'] = zona_inf
    result['zona_sup'] = zona_sup

    toco_zona = False
    n_velas = min(AUROLO_ZONA_VELAS, len(closes) - 1)
    for i in range(-n_velas, 0):
        c_i = closes[i]; l_i = lows[i]
        if AUROLO_ENTRY == 'close':
            if zona_inf <= c_i <= zona_sup:
                toco_zona = True; break
        else:
            if l_i <= zona_sup and c_i >= zona_inf * 0.993:
                toco_zona = True; break

    rebota = closes[-1] > ema55 * 0.999
    result['p1'] = toco_zona and rebota

    wt1      = _wavetrend_series(closes, highs, lows, WT_CH_LEN, WT_AVG_LEN)
    wt_now   = wt1[-1]
    wt_prev  = wt1[-2] if len(wt1) >= 2 else wt_now
    wt_prev2 = wt1[-3] if len(wt1) >= 3 else wt_prev
    result['wt_now'] = wt_now; result['wt_prev'] = wt_prev

    cruce_alc = (wt_now > wt_prev) and (wt_prev <= WT_OS_ENTRY or wt_prev2 <= WT_OS2)
    en_os     = wt_now <= WT_OS2
    result['p2'] = cruce_alc or (en_os and wt_now > wt_prev)

    adx_vals, dip_vals, din_vals = _adx_di_series(highs, lows, closes, ADX_DI_LEN, ADX_LEN)
    adx_now  = adx_vals[-1]; adx_prev = adx_vals[-2] if len(adx_vals)>=2 else adx_now
    dip_now  = dip_vals[-1]; din_now  = din_vals[-1]
    result['adx_now'] = adx_now; result['dip'] = dip_now; result['din'] = din_now

    adx_fuerte  = adx_now >= ADX_KEY
    di_alcista  = dip_now > din_now
    result['p3'] = adx_fuerte and di_alcista

    pts = int(result['p1']) + int(result['p2']) + int(result['p3'])
    result['puntos'] = pts

    # [M5] SL dinámico basado en ATR real
    atr_actual   = atr_v or atr_calc(highs, lows, closes, 14)
    min_reciente = min(lows[-8:-1]) if len(lows) >= 8 else lows[-1]
    sl_vulner    = min_reciente - atr_actual * SL_ATR_M
    sl_bajo_ema  = ema55 * (1 - 0.20/100)
    sl_calculado = min(sl_vulner, sl_bajo_ema)

    sl_max_price = price * (1 - SL_MAX_PCT / 100)
    sl_min_price = price * (1 - SL_MIN_PCT / 100)
    sl_price = max(sl_calculado, sl_max_price)
    sl_price = min(sl_price, sl_min_price)

    if sl_price >= price:
        sl_price = price * (1 - SL_MIN_PCT / 100)

    sl_pct = (price - sl_price) / price * 100
    if sl_pct < SL_MIN_PCT:
        sl_price = price * (1 - SL_MIN_PCT / 100)
        sl_pct   = SL_MIN_PCT

    result['sl_price'] = round(sl_price, 8)
    result['sl_pct']   = round(sl_pct, 3)

    wt_ob_baj = wt_now < wt_prev and wt_prev >= WT_OB2
    di_gira   = din_now > dip_now * 0.80
    adx_cayendo = adx_now < adx_prev
    result['debilidad'] = bool(adx_cayendo and (wt_ob_baj or wt_now >= WT_OB1) and di_gira)

    vol_avg = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else volumes[-1]
    result['vol_ratio'] = volumes[-1] / vol_avg if vol_avg > 0 else 1

    # [M3] Order flow delta
    result['of_delta'] = order_flow_delta(closes, volumes, 10)

    p1_icon = '✅' if result['p1'] else '❌'
    p2_icon = '✅' if result['p2'] else '❌'
    p3_icon = '✅' if result['p3'] else '❌'
    result['descripcion'] = (
        f"P1({p1_icon})EMA{AUROLO_EMA_LEN} | "
        f"P2({p2_icon})WT={round(wt_now,1)} | "
        f"P3({p3_icon})ADX={round(adx_now,1)} DI+={round(dip_now,1)} | "
        f"OF={round(result['of_delta'],2)}"
    )

    if pts >= 3:   result['señal'] = 'LONG_3/3'
    elif pts == 2: result['señal'] = 'LONG_2/3'
    elif pts == 1: result['señal'] = 'LONG_1/3'
    else:          result['señal'] = 'NO'

    return result


def vwap_contexto(closes, highs, lows, volumes, n=50):
    if len(closes) < n: return closes[-1], True
    vwap = calc_vwap(closes, highs, lows, volumes, n)
    return vwap, closes[-1] > vwap


# ============================================================================
# APRENDIZAJE 2.0 [M9] [M13]
# ============================================================================

class Learning:
    def __init__(self):
        self.history       = []
        self.sym_stats     = defaultdict(lambda: {'w':0,'l':0,'pnl':0.0,'n':0})
        self.opt_score     = MIN_SCORE
        self.blacklist     = set()
        self.streak        = 0
        self.last10        = []
        self.by_hour       = defaultdict(lambda: {'w':0,'l':0,'pnl':0.0})
        self.by_pts        = defaultdict(lambda: {'w':0,'l':0,'pnl':0.0})
        self.by_btc        = defaultdict(lambda: {'w':0,'l':0,'pnl':0.0})
        self.by_reason     = defaultdict(lambda: {'n':0,'pnl':0.0})
        self.factor_wins   = defaultdict(int)
        self.factor_losses = defaultdict(int)
        self.score_boost   = {}
        self.daily_losers  = set()
        self._daily_date   = datetime.utcnow().date()
        # [M13] Blacklist horaria por símbolo
        self.hour_blacklist = defaultdict(set)  # hora -> set(symbols)
        # [M11] Kelly tracking
        self.kelly_mult = 1.0

    def _check_daily_reset(self):
        today = datetime.utcnow().date()
        if today != self._daily_date:
            self.daily_losers = set()
            self._daily_date = today

    def _score_cap(self):
        n = len(self.history)
        if n < LEARN_MIN_TRADES_SCORE:
            return SCORE_CAP_LOW
        return SCORE_CAP_HIGH

    def record(self, symbol, score, pnl, win, hora_utc=None,
               pts_aurolo=0, btc_dir='flat', reason='?', factors=None):
        self._check_daily_reset()
        hora = hora_utc or datetime.utcnow().hour
        rec = {
            'ts': datetime.now().isoformat(), 'sym': symbol,
            'score': score, 'pnl': pnl, 'win': win,
            'hora': hora, 'pts': pts_aurolo, 'btc': btc_dir,
            'reason': reason, 'factors': factors or [],
        }
        self.history.append(rec); self.last10.append(rec)
        if len(self.last10) > 10: self.last10.pop(0)
        s = self.sym_stats[symbol]; s['n'] += 1; s['pnl'] += pnl
        k = 'w' if win else 'l'
        if win:
            s['w'] += 1; self.streak = 0
        else:
            s['l'] += 1; self.streak += 1
            if CD_SL_TODAY and 'SL' in reason.upper():
                self.daily_losers.add(symbol)
            # [M13] Si pierde en esta hora, registrar
            self.hour_blacklist[hora].add(symbol)

        self.by_hour[hora][k] += 1; self.by_hour[hora]['pnl'] += pnl
        self.by_pts[pts_aurolo][k]   += 1; self.by_pts[pts_aurolo]['pnl']   += pnl
        self.by_btc[btc_dir][k]      += 1; self.by_btc[btc_dir]['pnl']      += pnl
        self.by_reason[reason]['n']  += 1; self.by_reason[reason]['pnl']    += pnl
        for f in (factors or []):
            if win: self.factor_wins[f]   += 1
            else:   self.factor_losses[f] += 1
        self._adjust()
        if len(self.history) % 10 == 0: self._reporte()

    def _adjust(self):
        n = len(self.history)
        cap = self._score_cap()
        if n >= LEARN_MIN_TRADES_SCORE:
            wr = sum(1 for t in self.last10 if t['win']) / len(self.last10)

            # [M9] Ajuste más agresivo que v5.9
            if wr < 0.20:
                self.opt_score = min(self.opt_score + 15, cap)
                log.warning(f"  [LEARN] 🚨 WR crítico {int(wr*100)}% → score +15")
            elif wr < 0.30:
                self.opt_score = min(self.opt_score + 8, cap)
            elif wr < 0.40:
                self.opt_score = min(self.opt_score + 3, cap)
            elif wr > 0.65:
                self.opt_score = max(self.opt_score - 2, MIN_SCORE)
            elif wr > 0.75:
                self.opt_score = max(self.opt_score - 4, MIN_SCORE)

            # [M11] Kelly fraccionado: ajusta multiplicador de posición
            avg_win  = sum(t['pnl'] for t in self.last10 if t['win'])  / max(sum(1 for t in self.last10 if t['win']), 1)
            avg_loss = sum(abs(t['pnl']) for t in self.last10 if not t['win']) / max(sum(1 for t in self.last10 if not t['win']), 1)
            if avg_loss > 0 and avg_win > 0:
                kelly = (wr - (1 - wr) / (avg_win / avg_loss))
                self.kelly_mult = max(0.3, min(1.0, kelly * 0.5))  # kelly fraccionado
        else:
            if self.opt_score > cap:
                self.opt_score = cap
        self.opt_score = max(self.opt_score, MIN_SCORE)

        for sym, s in self.sym_stats.items():
            tot = s['w'] + s['l']
            if (tot >= LEARN_MIN_TRADES_BL and
                    s['pnl'] < -1.0 and  # más sensible
                    s['w'] / tot < 0.30):  # más estricto
                if sym not in self.blacklist:
                    self.blacklist.add(sym)
                    log.warning(f"  [LEARN] 🚫 {sym} → blacklist")

        if n >= 10:  # reacciona antes
            for f in set(list(self.factor_wins) + list(self.factor_losses)):
                w = self.factor_wins.get(f, 0); l = self.factor_losses.get(f, 0)
                if w+l < 4: continue
                wr_f = w/(w+l)
                if wr_f < 0.30:   self.score_boost[f] = -12
                elif wr_f > 0.70: self.score_boost[f] = +8
                else:             self.score_boost.pop(f, None)

    def hora_ok(self, h):
        d = self.by_hour.get(h)
        if not d: return True, "ok"
        tot = d['w']+d['l']
        if tot < 5: return True, "ok"
        wr_hora = d['w'] / tot
        # [M13] Más estricto: bloquea si WR<30% en esa hora
        if wr_hora < 0.30:
            return False, f"hora {h}h WR={int(wr_hora*100)}%"
        return True, "ok"

    def sym_hora_ok(self, sym, h):
        """[M13] Bloquea símbolo específico si perdió en esta hora."""
        return sym not in self.hour_blacklist.get(h, set())

    def bonus_pts(self, pts) -> int:
        d = self.by_pts.get(pts)
        if not d: return 0
        tot = d['w']+d['l']
        if tot < 5: return 0
        wr = d['w']/tot
        if wr > 0.65: return +12
        if wr < 0.35: return -18
        return 0

    def get_kelly_size(self, base_size):
        """[M11] Ajusta tamaño de posición por Kelly fraccionado."""
        return round(base_size * self.kelly_mult, 2)

    def ok(self, sym, score, hora=None):
        self._check_daily_reset()
        if sym in self.blacklist:
            return False, "blacklist"
        if sym in self.daily_losers:
            return False, "SL hoy"
        if hora is not None and not self.sym_hora_ok(sym, hora):
            return False, f"sym perdió hora {hora}h"
        threshold = max(self.opt_score, MIN_SCORE)
        if score < threshold:
            return False, f"score {int(score)}<{int(threshold)}"
        if self.streak >= MAX_STREAK:
            return False, f"streak -{self.streak}"
        return True, "ok"

    def adj(self, factors):
        return sum(self.score_boost.get(f, 0) for f in factors)

    def _reporte(self):
        n = len(self.history)
        wr  = sum(1 for t in self.history if t['win'])/n*100 if n else 0
        pnl = sum(t['pnl'] for t in self.history)
        log.info(f"[LEARN] #{n//10}: WR={int(wr)}% PnL=${pnl:+.4f} Score={int(self.opt_score)} Kelly={self.kelly_mult:.2f}")
        try:
            if TG_TOKEN and TG_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={'chat_id': TG_CHAT,
                          'text': f"<b>🧠 LEARN v6.0 — {n} trades</b>\nWR:{int(wr)}% PnL:${pnl:+.4f} Score≥{int(self.opt_score)} Kelly×{self.kelly_mult:.2f}",
                          'parse_mode': 'HTML'},
                    timeout=6
                )
        except: pass

    def save(self, fp='/tmp/bot_learn_v60.json'):
        try:
            json.dump({
                'history': self.history[-200:], 'sym_stats': dict(self.sym_stats),
                'opt_score': self.opt_score, 'blacklist': list(self.blacklist),
                'by_hour': dict(self.by_hour), 'by_pts': dict(self.by_pts),
                'by_btc': dict(self.by_btc), 'by_reason': dict(self.by_reason),
                'factor_wins': dict(self.factor_wins),
                'factor_losses': dict(self.factor_losses),
                'score_boost': self.score_boost,
                'daily_losers': list(self.daily_losers),
                'kelly_mult': self.kelly_mult,
                'hour_blacklist': {str(k): list(v) for k, v in self.hour_blacklist.items()},
            }, open(fp,'w'), indent=2)
        except: pass

    def load(self, fp='/tmp/bot_learn_v60.json'):
        for path in [fp,
                     '/tmp/bot_learn_v59f.json',
                     '/tmp/bot_learn_v59.json',
                     '/tmp/bot_learn_v58.json',
                     '/tmp/bot_learn.json']:
            try:
                if not os.path.exists(path): continue
                d = json.load(open(path))
                self.history    = d.get('history',[])
                self.sym_stats  = defaultdict(lambda:{'w':0,'l':0,'pnl':0.0,'n':0}, d.get('sym_stats',{}))
                raw_score       = d.get('opt_score', MIN_SCORE)
                self.blacklist  = set(d.get('blacklist',[]))
                self.by_hour    = defaultdict(lambda:{'w':0,'l':0,'pnl':0.0}, d.get('by_hour',{}))
                self.by_pts     = defaultdict(lambda:{'w':0,'l':0,'pnl':0.0}, d.get('by_pts',{}))
                self.by_btc     = defaultdict(lambda:{'w':0,'l':0,'pnl':0.0}, d.get('by_btc',{}))
                self.by_reason  = defaultdict(lambda:{'n':0,'pnl':0.0}, d.get('by_reason',{}))
                self.factor_wins   = defaultdict(int, d.get('factor_wins',{}))
                self.factor_losses = defaultdict(int, d.get('factor_losses',{}))
                self.score_boost   = d.get('score_boost',{})
                self.daily_losers  = set(d.get('daily_losers', []))
                self.kelly_mult    = d.get('kelly_mult', 1.0)
                raw_bl = d.get('hour_blacklist', {})
                self.hour_blacklist = defaultdict(set, {int(k): set(v) for k, v in raw_bl.items()})
                cap = self._score_cap()
                self.opt_score = max(min(raw_score, cap), MIN_SCORE)
                log.info(f"  [LEARN] {len(self.history)} trades | Score:{int(self.opt_score)} | BL:{len(self.blacklist)} | Kelly:{self.kelly_mult:.2f}")
                return
            except: continue


# ============================================================================
# BOT PRINCIPAL v6.0-ALPHA
# ============================================================================

class LongBot:
    _opening = False

    def __init__(self):
        log.info("=" * 72)
        log.info("  BOT LONGS v6.0-ALPHA — MÁXIMA PRECISIÓN")
        log.info(f"  Capital: ${POS_SIZE} | Riesgo: {RISK_PCT}%/trade | {LEVERAGE}x")
        log.info(f"  Score: bull≥{SCORE_BULL} neutral≥{SCORE_NEUTRAL} | Min puntos Aurolo: {AUROLO_MIN_PTS}/3")
        log.info(f"  Volumen mínimo: ${MIN_VOL:,.0f} | Breadth mín: {int(BREADTH_MIN*100)}%")
        log.info(f"  MEJORAS: QualityGate+VolRegime+OrderFlow+AntiChop+KellySizing+CorrBlock")
        log.info("=" * 72)

        self.symbols         = []
        self.trades          = {}
        self._contracts      = {}
        self._cooldowns      = {}
        self._pending_orders = {}
        self._last_report    = datetime.now() - timedelta(hours=3)
        self._last_zombie_clean = 0
        self._last_momentum_refresh = 0
        self._btc_1h         = 0.0
        self._btc_4h         = 0.0
        self._btc_ok         = True
        self._regime         = 'neutral'
        self._regime_until   = None
        self._breadth        = 0.5
        self._mode           = 'hedge'
        self._daily_pnl      = 0.0
        self._daily_date     = datetime.utcnow().date()
        self._equity_start   = ACCOUNT_EQUITY
        self._cb_active      = False
        self._cb_until       = None
        self._momentum_cache = set()
        self._momentum_ranked = []
        # [M15] Caché de precios para correlación
        self._price_cache    = {}
        self.learn           = Learning()
        self.learn.load()
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0,'fees':0.0}

        if not self._connect(): log.error("❌ Sin conexión BingX"); sys.exit(1)
        self._detect_mode()
        self._load_contracts()
        self._refresh_symbols()
        n_killed = self._nuke_zombie_orders()
        self._recover()

        self._tg(
            f"<b>🤖 Bot LONGS v6.0-ALPHA</b>\n"
            f"Símbolos: {len(self.symbols)} | Vol≥${MIN_VOL/1e3:.0f}K\n"
            f"Quality Gate: ✅ | Anti-Chop: ✅ | Kelly Sizing: ✅\n"
            f"Order Flow: ✅ | Corr Block: ✅\n"
            f"🧟 Zombies eliminados: {n_killed}\n"
            f"♻️ Posiciones recuperadas: {len(self.trades)}"
        )

    # ── Conexión ──────────────────────────────────────────────────────────
    def _connect(self) -> bool:
        global AUTO, ACCOUNT_EQUITY
        if not AUTO: return True
        if not API_KEY or not API_SECRET:
            log.error("❌ API keys no configuradas"); AUTO = False; return False
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') == 0:
            b = d.get('data',{})
            if isinstance(b, list):
                eq = 0.0
                for item in b:
                    v = _safe_float(item)
                    if v > 0: eq = v; break
            else:
                eq = _safe_float(b.get('equity', b.get('balance', 0)))
                if eq <= 0:
                    for key, val in b.items():
                        v = _safe_float(val)
                        if v > 0: eq = v; break
            if eq > 0:
                ACCOUNT_EQUITY = eq
                self._equity_start = eq
            log.info(f"✅ BingX conectado | ${ACCOUNT_EQUITY:.2f} USDT")
            return True
        log.error(f"❌ [{d.get('code')}]: {d.get('msg')}")
        AUTO = False; return False

    def _detect_mode(self):
        try:
            d = api('GET', '/openApi/swap/v2/user/positions', {'symbol':'BTC-USDT'})
            for p in (d.get('data') or []):
                s = str(p.get('positionSide','')).upper()
                if s in ('LONG','SHORT'): self._mode='hedge'; log.info("  Modo: HEDGE"); return
                if s == 'BOTH': self._mode='oneway'; log.info("  Modo: ONE-WAY"); return
        except: pass
        log.info("  Modo: HEDGE (default)")

    def _load_contracts(self):
        d = pub('/openApi/swap/v2/quote/contracts')
        if d.get('code') == 0:
            for c in d.get('data',[]):
                s = c.get('symbol','')
                if s: self._contracts[s] = {
                    'step': float(c.get('tradeMinQuantity',1)),
                    'prec': int(c.get('quantityPrecision',2)),
                    'ctval': float(c.get('contractSize',1)),
                }
            log.info(f"  Contratos: {len(self._contracts)}")

    def _refresh_symbols(self):
        """[M1] Obtiene símbolos con Quality Gate: excluye forex sintéticos."""
        d = pub('/openApi/swap/v2/quote/ticker')
        if d.get('code') != 0:
            self.symbols = self.symbols or ['BTC-USDT','ETH-USDT','SOL-USDT']; return
        items = []
        for t in d.get('data',[]):
            sym = t.get('symbol','')
            if not sym.endswith('-USDT'): continue
            base = sym.replace('-USDT','').upper()

            # Excluir stablecoins
            if any(base == ex for ex in EXCLUDE): continue
            if any(base.startswith(ex) for ex in EXCLUDE): continue

            # [M1] Excluir pares sintéticos/forex
            if any(p in base for p in EXCLUDE_PATTERNS): continue

            # [M8] Volumen mínimo más alto
            try:
                price = float(t.get('lastPrice',0))
                vol = float(t.get('volume',0)) * price
                if vol >= MIN_VOL and price > 0:
                    items.append({'sym':sym,'vol':vol,'price':price})
            except: continue

        items.sort(key=lambda x: x['vol'], reverse=True)
        if MAX_SYMS > 0:
            items = items[:MAX_SYMS]

        self.symbols = [x['sym'] for x in items]
        log.info(f"  Símbolos activos: {len(self.symbols)} (vol>${MIN_VOL/1e3:.0f}K, excl. sintéticos)")

    # ── Quality Gate [M1] ─────────────────────────────────────────────────
    def _quality_gate(self) -> tuple:
        """Bloqueo duro antes de cualquier entrada."""
        # Breadth crítico
        if self._breadth < BREADTH_CRITICAL:
            return False, f"🚫 BREADTH CRÍTICO {int(self._breadth*100)}% (<{int(BREADTH_CRITICAL*100)}%)"
        # Régimen bear
        if self._regime == 'bear':
            return False, "régimen bear"
        # CAUTION bloqueado
        if CAUTION_BLOCK and self._regime == 'caution':
            return False, "régimen caution"
        # Crash guard activo
        if self._regime_until and datetime.utcnow() < self._regime_until:
            remaining = int((self._regime_until - datetime.utcnow()).total_seconds() / 60)
            return False, f"crash guard {remaining}min"
        return True, "ok"

    # ── Pre-filtro momentum [M8] ──────────────────────────────────────────
    def _get_momentum_leaders(self, top_n=None):
        """Filtra microcaps y pares con volumen < 1M USDT."""
        top_n = top_n or MOMENTUM_TOP_N
        scored = []

        def _score_sym(sym):
            try:
                # [M8] Verificar volumen absoluto mínimo antes de analizar
                tk = self._ticker(sym)
                if not tk or tk['price'] <= 0:
                    return None

                c1h, h1h, l1h, v1h, _ = self._klines(sym, '1h', 48)
                if not c1h or len(c1h) < 25:
                    return None

                price = c1h[-1]
                if price <= 0:
                    return None

                # [M8] Verificar volumen 24h real
                vol_24h = sum(v1h[-24:]) * price if len(v1h) >= 24 else 0
                if vol_24h < MOMENTUM_MIN_VOL_ABS:
                    return None

                mom_4h  = (c1h[-1] - c1h[-5])  / c1h[-5]  * 100 if len(c1h) >= 5  else 0
                mom_24h = (c1h[-1] - c1h[-25]) / c1h[-25] * 100 if len(c1h) >= 25 else 0

                if mom_4h < MOMENTUM_MIN_4H or mom_24h < MOMENTUM_MIN_24H:
                    return None

                e9  = ema(c1h, 9)
                e21 = ema(c1h, 21)
                if not (price > e9 > e21):
                    return None

                vol_avg_6h = sum(v1h[-7:-1]) / 6 if len(v1h) >= 7 else v1h[-1]
                vol_ratio  = v1h[-1] / vol_avg_6h if vol_avg_6h > 0 else 1
                if vol_ratio < MOMENTUM_MIN_VOL_R:
                    return None

                rsi_val = rsi(c1h, 14)
                if rsi_val > MOMENTUM_MAX_RSI or rsi_val < 35:
                    return None

                atr_v = atr_calc(h1h, l1h, c1h, 14)
                atr_pct = atr_v / price * 100 if price > 0 else 0
                if atr_pct < 0.10:
                    return None

                # [M10] Verificar que no esté choppy en 1h
                if CHOP_CHECK and is_choppy(h1h, l1h, c1h, 20):
                    return None

                # [M3] Order flow positivo
                of_delta = order_flow_delta(c1h, v1h, 10)
                if of_delta < -0.2:  # presión vendedora
                    return None

                mscore = (
                    mom_4h  * 3.0   +
                    mom_24h * 0.5   +
                    (vol_ratio - 1) * 10 +
                    (rsi_val - 50)  * 0.2 +
                    (atr_pct - 0.5) * 2.0 +
                    of_delta * 15           # [M3] bonus order flow
                )

                # Guardar precios para correlación [M15]
                self._price_cache[sym] = c1h[-20:]

                return (sym, mscore, mom_4h, mom_24h, round(vol_ratio, 2), round(rsi_val, 1))

            except Exception as e:
                log.debug(f"momentum {sym}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
            futures = {ex.submit(_score_sym, sym): sym for sym in self.symbols}
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    if result:
                        scored.append(result)
                except: pass

        scored.sort(key=lambda x: x[1], reverse=True)
        leaders = scored[:top_n]

        if leaders:
            top5_info = [(s, f"{m4:.1f}%4h", f"vol×{vr}") for s, _, m4, _, vr, _ in leaders[:5]]
            log.info(f"  🏆 Top momentum: {top5_info}")

        self._momentum_cache  = set(s for s, *_ in leaders)
        self._momentum_ranked = [s for s, *_ in leaders]
        self._last_momentum_refresh = time.time()

        return self._momentum_ranked

    # ── Correlación [M15] ────────────────────────────────────────────────
    def _corr_block(self, candidate_sym) -> bool:
        """
        Bloquea entrada si el candidato está correlacionado >0.85
        con alguna posición abierta.
        """
        if not self.trades:
            return False
        cand_prices = self._price_cache.get(candidate_sym)
        if not cand_prices:
            return False
        for sym in self.trades:
            open_prices = self._price_cache.get(sym)
            if not open_prices:
                continue
            corr = correlation(cand_prices, open_prices)
            if corr > 0.85:
                log.debug(f"  [CORR] {candidate_sym} correlado {corr:.2f} con {sym}")
                return True
        return False

    # ── Scan paralelo ─────────────────────────────────────────────────────
    def _analyze_parallel(self, symbols_batch):
        results = []
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
            futures = {ex.submit(self.analyze, sym): sym for sym in symbols_batch}
            for fut in as_completed(futures):
                try:
                    sig = fut.result()
                    if sig:
                        results.append((futures[fut], sig))
                except Exception as e:
                    log.debug(f"analyze error: {e}")
        results.sort(key=lambda x: x[1]['score'], reverse=True)
        return results

    # ── Zombie cleanup ────────────────────────────────────────────────────
    def _nuke_zombie_orders(self) -> int:
        if not AUTO: return 0
        protected_ids = set()
        for sym in list(self.trades.keys()):
            d = api('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': sym})
            for o in (d.get('data', {}).get('orders') or []):
                otype = str(o.get('type', '')).upper()
                if 'STOP' in otype or 'TRAILING' in otype:
                    oid = o.get('orderId')
                    if oid: protected_ids.add(str(oid))

        killed = 0
        now_ms = int(time.time() * 1000)
        all_syms_to_check = set(self.symbols or [])
        try:
            d_pos = api('GET', '/openApi/swap/v2/user/positions', {})
            for p in (d_pos.get('data') or []):
                s = p.get('symbol', '')
                if s: all_syms_to_check.add(s)
        except: pass

        for sym in list(all_syms_to_check)[:80]:
            try:
                d = api('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': sym})
                orders = d.get('data', {}).get('orders') or []
                for o in orders:
                    oid   = str(o.get('orderId', ''))
                    otype = str(o.get('type', '')).upper()
                    otime = int(o.get('time', now_ms) or now_ms)
                    age_min = (now_ms - otime) / 60000
                    if oid in protected_ids: continue
                    should_cancel = (
                        otype in ('LIMIT', 'TRIGGER', 'STOP', 'TAKE_PROFIT') and
                        (sym not in self.trades or age_min > ZOMBIE_MAX_AGE_MIN)
                    )
                    if should_cancel:
                        r = api('DELETE', '/openApi/swap/v2/trade/order',
                                {'symbol': sym, 'orderId': oid})
                        if r.get('code') == 0:
                            killed += 1
                            log.info(f"  🧟 Zombie: {sym} {otype} age={age_min:.0f}min")
                        time.sleep(0.12)
            except Exception as e:
                log.debug(f"  zombie scan {sym}: {e}")

        if killed > 0:
            log.info(f"  ✅ Zombies eliminados: {killed}")
        self._last_zombie_clean = time.time()
        return killed

    # ── Régimen ───────────────────────────────────────────────────────────
    def _update_market_regime(self):
        if not REGIME_CHECK: return
        c4h, *_ = self._klines('BTC-USDT', '4h', 10)
        if c4h and len(c4h) >= 4:
            self._btc_4h = (c4h[-1] - c4h[-4]) / c4h[-4] * 100
            if self._btc_4h < -BTC_4H_CRASH_PCT:
                if not self._regime_until or datetime.utcnow() > self._regime_until:
                    self._regime_until = datetime.utcnow() + timedelta(hours=BTC_4H_CRASH_PAUSE)
                    self._tg(f"<b>🚨 CRASH GUARD</b>\nBTC {self._btc_4h:.1f}% en 4h → Pausa {BTC_4H_CRASH_PAUSE}h")

        bulls = 0; total = 0
        for coin in BREADTH_COINS[:10]:
            try:
                c, *_ = self._klines(coin, '1h', 25)
                if c and len(c) >= 21:
                    e21 = ema(c, 21)
                    if c[-1] > e21: bulls += 1
                    total += 1
            except: pass
        if total > 0:
            self._breadth = bulls / total

        btc_bear    = (self._btc_4h < -1.5) or (self._btc_1h < -BTC_BLOCK)
        low_breadth = self._breadth < BREADTH_MIN

        if btc_bear and low_breadth:    nuevo = 'bear'
        elif btc_bear or low_breadth:   nuevo = 'caution'
        elif self._btc_4h > 1.0 and self._breadth > 0.60: nuevo = 'bull'
        else:                           nuevo = 'neutral'

        if nuevo != self._regime:
            log.info(f"  📊 RÉGIMEN: {self._regime} → {nuevo}")
        self._regime = nuevo

    def _regime_ok(self) -> tuple:
        return self._quality_gate()

    def _score_min_for_regime(self) -> float:
        if self._regime == 'bull':
            return max(self.learn.opt_score, SCORE_BULL)
        return max(self.learn.opt_score, SCORE_NEUTRAL)

    # ── Posiciones ────────────────────────────────────────────────────────
    def _get_exchange_positions(self, symbol=None):
        params = {}
        if symbol: params['symbol'] = symbol
        d = api('GET', '/openApi/swap/v2/user/positions', params)
        result = defaultdict(lambda: {'long':0.0,'short':0.0})
        for p in (d.get('data') or []):
            try:
                amt=float(p.get('positionAmt',0) or 0); sym=p.get('symbol','')
                side=str(p.get('positionSide','')).upper()
                if not sym or abs(amt)==0: continue
                if side=='LONG' or (side=='BOTH' and amt>0): result[sym]['long']=abs(amt)
                elif side=='SHORT' or (side=='BOTH' and amt<0): result[sym]['short']=abs(amt)
            except: continue
        return result

    def _has_any_position(self, symbol) -> bool:
        pos = self._get_exchange_positions(symbol)
        return pos[symbol]['long']>0 or pos[symbol]['short']>0

    def _order_close_short(self, sym, qty):
        params = {'symbol':sym,'side':'BUY','type':'MARKET','quantity':str(qty)}
        if self._mode == 'hedge': params['positionSide'] = 'SHORT'
        else: params['reduceOnly'] = 'true'
        return api('POST', '/openApi/swap/v2/trade/order', params)

    def _recover(self):
        if not AUTO: return
        all_pos = self._get_exchange_positions(); n_rec=0; n_sh=0
        for sym, sides in all_pos.items():
            if sides['short'] > 0:
                log.warning(f"  ⚠️ SHORT huérfano: {sym} → cerrando")
                if self._order_close_short(sym, sides['short']).get('code')==0:
                    n_sh+=1
                time.sleep(0.5)
            if sides['long'] > 0 and sym not in self.trades:
                d2 = api('GET','/openApi/swap/v2/user/positions',{'symbol':sym})
                entry = 0.0
                for p in (d2.get('data') or []):
                    s2=str(p.get('positionSide','')).upper(); a2=float(p.get('positionAmt',0) or 0)
                    if (s2=='LONG' and abs(a2)>0) or (s2=='BOTH' and a2>0):
                        entry=float(p.get('avgPrice') or p.get('entryPrice') or 0); break
                if entry<=0: continue
                qty = sides['long']
                sl_rec = entry * (1 - SL_MAX_PCT / 100)
                self.trades[sym] = {
                    'entry': entry, 'qty_total': qty, 'qty_runner': qty,
                    'qty_tp1': round(qty * TP1_PCT/100, 6),
                    'qty_tp2': round(qty * TP2_PCT/100, 6),
                    'tp1_hit': False, 'tp2_hit': False,
                    'tp1_price': entry * (1 + TP1_RATIO * SL_MAX_PCT / 100),
                    'tp2_price': entry * (1 + TP2_RATIO * SL_MAX_PCT / 100),
                    'sl': sl_rec, 'sl_orig': sl_rec, 'sl_pct': SL_MAX_PCT,
                    'highest': entry, 'opened': datetime.now(),
                    'score': 0, 'ema25': entry, 'ema55': entry,
                    'aurolo_pts': 0, 'entrada_label': '?',
                    'usdt': POS_SIZE, 'pnl_parcial': 0.0,
                    'factors': [], 'hora_utc': datetime.utcnow().hour,
                    'btc_dir': self._btc_dir(),
                    'debilidad_alertada': False,
                    'trailing_placed': False,
                    'be_placed': False,  # [M6]
                }
                n_rec+=1
                log.info(f"  ♻️ LONG recuperado: {sym} @ ${entry:.6f}")
        log.info(f"  Recuperadas: {n_rec} | SHORTs cerrados: {n_sh}")

    def _klines(self, symbol, interval='5m', limit=130):
        d = pub('/openApi/swap/v3/quote/klines',
                {'symbol':symbol,'interval':interval,'limit':limit})
        if d.get('code')==0 and d.get('data'):
            kl = d['data']
            return ([float(k['close']) for k in kl],[float(k['high']) for k in kl],
                    [float(k['low']) for k in kl],[float(k['volume']) for k in kl],
                    [float(k['open']) for k in kl])
        return None,None,None,None,None

    def _ticker(self, sym):
        d = pub('/openApi/swap/v2/quote/ticker',{'symbol':sym})
        if d.get('code')==0 and d.get('data'):
            t=d['data']
            return {'price':float(t.get('lastPrice',0)),'change':float(t.get('priceChangePercent',0))}
        return None

    def _update_btc(self):
        c,*_ = self._klines('BTC-USDT','1h',4)
        if c and len(c)>=2:
            self._btc_1h=(c[-1]-c[-2])/c[-2]*100; self._btc_ok=self._btc_1h>=-BTC_BLOCK
        else: self._btc_ok=True

    def _btc_dir(self):
        if self._btc_1h > 0.5: return 'up'
        if self._btc_1h < -0.5: return 'down'
        return 'flat'

    def _update_equity(self):
        global ACCOUNT_EQUITY
        d=api('GET','/openApi/swap/v2/user/balance')
        if d.get('code')==0:
            b=d.get('data',{})
            if isinstance(b, list):
                for item in b:
                    v = _safe_float(item)
                    if v > 0: ACCOUNT_EQUITY = v; break
            else:
                eq=_safe_float(b.get('equity', b.get('balance', 0)))
                if eq <= 0:
                    for key, val in b.items():
                        v = _safe_float(val)
                        if v > 0: eq = v; break
                if eq>0: ACCOUNT_EQUITY=eq

    def _check_ltv(self):
        if not AUTO: return
        d=api('GET','/openApi/swap/v2/user/balance')
        if d.get('code')!=0: return
        try:
            b=d.get('data',{}); eq=_safe_float(b.get('equity', b.get('balance', 0)))
            mg=_safe_float(b.get('usedMargin', b.get('initialMargin', 0)))
            ltv_pct = mg / eq * 100 if eq > 0 else 0
            if eq>0 and ltv_pct >= LTV_WARN:
                self._tg("<b>⚠️ LTV ALTO — cerrando posiciones</b>")
                for sym in list(self.trades):
                    tk=self._ticker(sym)
                    if tk: self._close_all(sym,tk['price'],"LTV EMERGENCIA")
        except: pass

    def analyze(self, symbol):
        """Análisis completo con todas las mejoras v6.0."""
        if symbol in self.trades: return None
        if not self._cd_ok(symbol): return None
        if symbol in self._pending_orders: return None
        hora = datetime.utcnow().hour
        if hora in SKIP_HOURS: return None

        # [M1] Quality Gate
        gate_ok, gate_reason = self._quality_gate()
        if not gate_ok: return None
        if not self._btc_ok: return None
        if self._cb_active: return None

        hora_ok, _ = self.learn.hora_ok(hora)
        if not hora_ok: return None

        c5, h5, l5, v5, o5 = self._klines(symbol, '5m', 130)
        if not c5 or len(c5) < AUROLO_EMA_LEN + 50: return None

        c1h, h1h, l1h, v1h, _ = self._klines(symbol, '1h', 60)
        c4h, h4h, l4h, v4h, _ = self._klines(symbol, '4h', 40)

        tk = self._ticker(symbol)
        if not tk or tk['price'] <= 0: return None
        price = tk['price']; change_24 = tk['change']

        trend_1h = 0; rsi_1h = 50.0
        if c1h and len(c1h) >= 25:
            e9_1h = ema(c1h, 9); e21_1h = ema(c1h, 21)
            rsi_1h = rsi(c1h, 14)
            if e9_1h > e21_1h: trend_1h = 1
            elif e9_1h < e21_1h: trend_1h = -1
        if trend_1h == -1: return None

        trend_4h = 0; rsi_4h = 50.0
        if c4h and len(c4h) >= 21:
            e9_4h = ema(c4h, 9); e21_4h = ema(c4h, 21)
            rsi_4h = rsi(c4h, 14)
            if e9_4h > e21_4h: trend_4h = 1
            elif e9_4h < e21_4h: trend_4h = -1
        if trend_4h == -1: return None

        # [M4] Exigir al menos trend_1h alcista (ya verificado) + no sobrecomprado en 4h
        if rsi_4h > 78: return None  # sobrecomprado en TF mayor

        atr_v   = atr_calc(h5, l5, c5, 14)
        atr_pct = atr_v / price * 100 if price > 0 else 0
        if atr_pct < 0.10: return None
        if change_24 > 20.0: return None
        if change_24 < -10.0: return None  # más conservador

        # [M2] Régimen de volatilidad
        vol_regime, vol_ratio_atr = 'normal', 1.0
        if c5 and h5 and l5:
            vol_regime, vol_ratio_atr = volatility_regime(h5, l5, c5)
        # Evitar entrar en volatilidad extrema
        if vol_regime == 'expanding' and vol_ratio_atr > 2.5:
            log.debug(f"  {symbol}: vol expandida {vol_ratio_atr:.1f}x — skip")
            return None

        # [M10] Anti-chop en 5m
        if CHOP_CHECK and is_choppy(h5, l5, c5, 20):
            log.debug(f"  {symbol}: mercado choppy — skip")
            return None

        # [M14] Spread guard
        d_book = pub('/openApi/swap/v2/quote/bookTicker', {'symbol': symbol})
        if d_book.get('code') == 0 and d_book.get('data'):
            ask = float(d_book['data'].get('askPrice', 0) or 0)
            bid = float(d_book['data'].get('bidPrice', 0) or ask)
            if bid > 0:
                spread_pct = (ask - bid) / bid * 100
                if spread_pct > 0.3:
                    log.debug(f"  {symbol}: spread {spread_pct:.2f}% — skip")
                    return None

        sig_aurolo = aurolo_signal(c5, h5, l5, v5, o5, atr_v)

        if sig_aurolo['puntos'] < AUROLO_MIN_PTS: return None
        if sig_aurolo['cambio_tend']: return None

        # [M3] Order flow: mínimo neutro o positivo
        of_delta = sig_aurolo['of_delta']
        if of_delta < -0.3:  # presión vendedora fuerte
            log.debug(f"  {symbol}: order flow negativo {of_delta:.2f} — skip")
            return None

        vwap_val, precio_sobre_vwap = vwap_contexto(c5, h5, l5, v5, VWAP_CANDLES)
        if VWAP_AS_FILTER and not precio_sobre_vwap: return None

        sl_price = sig_aurolo['sl_price']
        sl_pct   = sig_aurolo['sl_pct']

        if sl_pct < SL_MIN_PCT * 0.9: return None
        if sl_pct > SL_MAX_PCT * 1.1: return None

        tp1_price = price * (1 + sl_pct * TP1_RATIO / 100)
        tp2_price = price * (1 + sl_pct * TP2_RATIO / 100)
        tp_ref    = max(sl_pct * MIN_RR, TP_MIN, atr_pct * ATR_TP_M)
        rr        = tp_ref / sl_pct if sl_pct > 0 else 0

        if rr < MIN_RR * 0.75: return None

        tp1_neto = sl_pct * TP1_RATIO - FEE_COST_PCT
        if tp1_neto < 0.4: return None

        # ── Scoring v6.0 ─────────────────────────────────────────────────
        score = 0; reasons = []; factors = []
        pts   = sig_aurolo['puntos']

        if pts == 3:   score += 50; reasons.append("Aurolo3/3(50)"); factors.append("aurolo_3")
        elif pts == 2: score += 30; reasons.append("Aurolo2/3(30)"); factors.append("aurolo_2")
        elif pts == 1: score += 15; reasons.append("Aurolo1/3(15)"); factors.append("aurolo_1")

        if sig_aurolo['p1']: score += 10; factors.append("p1_tend")
        if sig_aurolo['p2']: score += 10; factors.append("p2_wt")
        if sig_aurolo['p3']: score += 10; factors.append("p3_adx")

        wt_val = sig_aurolo['wt_now']
        if wt_val <= WT_OS1:   score += 10; factors.append("wt_deep")
        elif wt_val <= WT_OS2: score += 5;  factors.append("wt_os")

        adx_val = sig_aurolo['adx_now']
        if adx_val > ADX_KEY * 1.5: score += 8;  factors.append("adx_strong")
        elif adx_val > ADX_KEY:     score += 4;  factors.append("adx_ok")

        vr = sig_aurolo['vol_ratio']
        if vr >= 2.0:   score += 10; factors.append("vol_fuerte")
        elif vr >= 1.4: score += 5;  factors.append("vol_medio")

        # [M3] Order flow bonus
        if of_delta > 0.3:   score += 10; factors.append("of_bull_strong")
        elif of_delta > 0.1: score += 5;  factors.append("of_bull")
        elif of_delta < -0.1: score -= 5; factors.append("of_bear")

        if precio_sobre_vwap: score += 8;  factors.append("vwap_arriba")
        else:                 score -= 8;  factors.append("vwap_abajo")

        if trend_1h == 1: score += 12; factors.append("trend_1h_up")
        if trend_4h == 1: score += 10; factors.append("trend_4h_up")

        # [M4] Multi-TF confluencia bonus
        if trend_1h == 1 and trend_4h == 1:
            score += 8; factors.append("mtf_confluencia")

        if self._regime == 'bull':      score += 10; factors.append("regime_bull")
        elif self._regime == 'caution': score -= 10; factors.append("regime_caution")

        if self._btc_1h > 1.0:    score += 8;  factors.append("btc_up")
        elif self._btc_1h > 0.3:  score += 4;  factors.append("btc_ok")
        elif self._btc_1h < -0.5: score -= 8;  factors.append("btc_down")

        if self._btc_4h > 1.5:   score += 8;  factors.append("btc4h_up")
        elif self._btc_4h < -1.0: score -= 12; factors.append("btc4h_down")

        if rsi_1h < 40:   score += 8; factors.append("rsi_1h_os")
        elif rsi_1h < 55: score += 4; factors.append("rsi_1h_ok")

        if sl_pct < SL_MAX_PCT * 0.6: score += 5; factors.append("sl_tight")

        if self._breadth > 0.65:   score += 8;  factors.append("breadth_good")
        elif self._breadth < 0.45: score -= 10; factors.append("breadth_bad")

        # [M2] Bonus volatilidad en expansión controlada
        if vol_regime == 'expanding' and vol_ratio_atr < 1.8:
            score += 6; factors.append("vol_expanding")
        elif vol_regime == 'compressed':
            score -= 5; factors.append("vol_compressed")  # breakout pendiente = riesgo

        if symbol in self._momentum_cache:
            score += 8; factors.append("momentum_leader")

        bonus_p = self.learn.bonus_pts(pts)
        if bonus_p != 0: score += bonus_p
        adj = self.learn.adj(factors)
        if adj != 0: score += adj

        score_min = self._score_min_for_regime()
        if score < score_min:
            log.debug(f"  {symbol}: score {int(score)}<{int(score_min)}")
            return None

        ok, reason = self.learn.ok(symbol, score, hora)
        if not ok: return None

        e25 = ema(c5, 25)
        e55 = sig_aurolo['ema55']

        # Guardar precios para correlación
        if c1h:
            self._price_cache[symbol] = c1h[-20:]

        return {
            'price': price, 'change': change_24, 'score': score,
            'score_min': score_min,
            'aurolo_pts': pts,
            'aurolo_p1': sig_aurolo['p1'], 'aurolo_p2': sig_aurolo['p2'], 'aurolo_p3': sig_aurolo['p3'],
            'aurolo_wt': sig_aurolo['wt_now'], 'aurolo_adx': sig_aurolo['adx_now'],
            'aurolo_dip': sig_aurolo['dip'],   'aurolo_din': sig_aurolo['din'],
            'aurolo_desc': sig_aurolo['descripcion'], 'aurolo_señal': sig_aurolo['señal'],
            'sl_price': round(sl_price, 8), 'sl_pct': round(sl_pct, 3),
            'tp1_price': round(tp1_price, 8), 'tp2_price': round(tp2_price, 8),
            'tp_pct': round(tp_ref, 2), 'rr': round(rr, 2),
            'tp1_neto': round(tp1_neto, 3),
            'vwap': vwap_val, 'ema25': e25, 'ema55': e55,
            'zona_inf': sig_aurolo['zona_inf'], 'zona_sup': sig_aurolo['zona_sup'],
            'trend_1h': trend_1h, 'trend_4h': trend_4h,
            'rsi_1h': rsi_1h, 'rsi_4h': rsi_4h,
            'vol_ratio': vr, 'atr_pct': atr_pct,
            'vol_regime': vol_regime, 'vol_ratio_atr': vol_ratio_atr,
            'of_delta': of_delta,
            'reasons': ' | '.join(reasons), 'factors': factors,
            'hora_utc': hora, 'btc_dir': self._btc_dir(),
            'precio_sobre_vwap': precio_sobre_vwap,
            'regime': self._regime, 'breadth': self._breadth,
            'momentum_leader': symbol in self._momentum_cache,
        }

    def _set_lev(self, sym):
        for side in ('LONG','SHORT'):
            try: api('POST','/openApi/swap/v2/trade/leverage',
                     {'symbol':sym,'side':side,'leverage':str(LEVERAGE)})
            except: pass

    def _calc_qty(self, sym, price, sl_price):
        info  = self._contracts.get(sym, {'step':1,'prec':2,'ctval':1})
        step  = max(float(info.get('step',1)), 1e-6)
        prec  = int(info.get('prec',2))
        ctval = max(float(info.get('ctval',1)), 1e-9)
        ppc   = price * ctval
        if ppc <= 0: return None, 0

        # [M11] Kelly fraccionado
        base_size = self.learn.get_kelly_size(POS_SIZE)

        if sl_price < price:
            dist_pct = (price-sl_price)/price*100
            riesgo   = ACCOUNT_EQUITY * (RISK_PCT/100)
            notional = min(riesgo / (dist_pct/100), base_size*LEVERAGE)
            notional = max(notional, MIN_TRADE)
        else:
            notional = max(base_size*LEVERAGE, MIN_TRADE)
        qty = math.ceil((notional/ppc)/step)*step; qty=round(qty,prec); val=qty*ppc
        for _ in range(200):
            if val>=MIN_TRADE: break
            qty+=step; qty=round(qty,prec); val=qty*ppc
        return (qty, round(val,4)) if val>=MIN_TRADE else (None,0)

    def _order(self, sym, side, qty, otype='MARKET', price=None, stop_price=None,
               reduce_only=False, activation_price=None, price_rate=None):
        params = {'symbol':sym,'side':side.upper(),'type':otype,'quantity':str(qty)}
        if self._mode=='hedge': params['positionSide']='LONG'
        else:
            if side.upper()=='SELL' or reduce_only: params['reduceOnly']='true'
        if price:            params['price']=str(round(price,8)); params['timeInForce']='GTC'
        if stop_price:       params['stopPrice']=str(round(stop_price,8))
        if activation_price: params['activationPrice']=str(round(activation_price,8))
        if price_rate:       params['priceRate']=str(price_rate)
        return api('POST','/openApi/swap/v2/trade/order',params)

    def _confirm_pos(self, sym, timeout=15):
        for _ in range(timeout):
            d=api('GET','/openApi/swap/v2/user/positions',{'symbol':sym})
            for p in (d.get('data') or []):
                amt=float(p.get('positionAmt',0) or 0); side=str(p.get('positionSide','')).upper()
                if (side=='LONG' and abs(amt)>0) or (side=='BOTH' and amt>0):
                    return abs(amt),float(p.get('avgPrice') or p.get('entryPrice') or 0)
            time.sleep(1)
        return None,None

    def _cancel_open(self, sym):
        d=api('GET','/openApi/swap/v2/trade/openOrders',{'symbol':sym})
        cancelled = 0
        for o in (d.get('data',{}).get('orders') or []):
            oid=o.get('orderId')
            if oid:
                r = api('DELETE','/openApi/swap/v2/trade/order',
                        {'symbol':sym,'orderId':str(oid)})
                if r.get('code') == 0: cancelled += 1
                time.sleep(0.1)
        return cancelled

    def _place_sl(self, sym, qty, sl_price):
        d=self._order(sym,'SELL',qty,'STOP_MARKET',stop_price=sl_price)
        if d.get('code')==0: return True
        sl_limit = sl_price * 0.999
        d=self._order(sym,'SELL',qty,'STOP',price=sl_limit,stop_price=sl_price)
        if d.get('code')==0: return True
        sl_adj = sl_price * 0.998
        d=self._order(sym,'SELL',qty,'STOP_MARKET',stop_price=sl_adj)
        return d.get('code')==0

    def _place_trailing_stop(self, sym, qty, activation_price, trail_rate_pct):
        params = {
            'symbol': sym, 'side': 'SELL',
            'type': 'TRAILING_STOP_MARKET',
            'quantity': str(qty),
            'activationPrice': str(round(activation_price, 8)),
            'priceRate': str(trail_rate_pct),
        }
        if self._mode == 'hedge': params['positionSide'] = 'LONG'
        else: params['reduceOnly'] = 'true'
        d = api('POST', '/openApi/swap/v2/trade/order', params)
        return d.get('code') == 0

    def _chase_limit_entry(self, sym, qty):
        d = pub('/openApi/swap/v2/quote/bookTicker', {'symbol': sym})
        ask_price = None
        if d.get('code') == 0 and d.get('data'):
            ask_price = float(d['data'].get('askPrice', 0) or 0)
        if not ask_price or ask_price <= 0:
            tk = self._ticker(sym)
            if tk: ask_price = tk['price'] * 1.0002
        if not ask_price: return None, {}

        bid_price = float(d.get('data', {}).get('bidPrice', 0) or ask_price * 0.999)
        spread_pct = (ask_price - bid_price) / bid_price * 100 if bid_price > 0 else 1
        if spread_pct > 0.3:  # [M14] más estricto
            log.debug(f"  {sym}: spread {spread_pct:.2f}% en entrada → market")
            d = self._order(sym, 'BUY', qty, 'MARKET')
            if d.get('code') != 0: return None, {}
            return self._confirm_pos(sym, 10)

        limit_price = round(ask_price * 1.0005, 8)
        d = self._order(sym, 'BUY', qty, 'LIMIT', price=limit_price)
        if d.get('code') != 0:
            d = self._order(sym, 'BUY', qty, 'MARKET')
            if d.get('code') != 0: return None, {}
        for i in range(12):
            time.sleep(1)
            filled_qty, fill_price = self._confirm_pos(sym, 1)
            if filled_qty and fill_price:
                return filled_qty, fill_price
        self._cancel_open(sym)
        time.sleep(0.5)
        filled_qty, fill_price = self._confirm_pos(sym, 2)
        if filled_qty: return filled_qty, fill_price
        dm = self._order(sym, 'BUY', qty, 'MARKET')
        if dm.get('code') == 0:
            return self._confirm_pos(sym, 10)
        return None, None

    def open_trade(self, sym, sig):
        if not AUTO or sym in self.trades: return False
        if LongBot._opening or len(self.trades)>=MAX_TRADES: return False
        if sym in self._pending_orders: return False
        if self._has_any_position(sym):
            log.warning(f"  ⛔ {sym} ya tiene posición"); return False

        # [M15] Bloquear por correlación
        if self._corr_block(sym):
            log.info(f"  🔗 {sym} bloqueado por correlación con posición abierta")
            return False

        LongBot._opening = True
        try: return self._open(sym, sig)
        finally: LongBot._opening = False

    def _open(self, sym, sig):
        price    = sig['price']
        sl_price = sig['sl_price']
        pts      = sig['aurolo_pts']
        label    = sig['aurolo_señal']
        momentum = '🏆' if sig.get('momentum_leader') else ''
        of_icon  = '📈' if sig['of_delta'] > 0.2 else ''

        log.info(f"\n  🎯 LONG {sym} [{label}]{momentum}{of_icon} | Score:{int(sig['score'])}/{int(sig['score_min'])} | RR:{sig['rr']:.2f}:1 | OF:{sig['of_delta']:.2f}")
        self._set_lev(sym); time.sleep(0.2)
        qty, notional = self._calc_qty(sym, price, sl_price)
        if not qty: return False

        self._pending_orders[sym] = 'pending'
        filled_qty, fill_price = self._chase_limit_entry(sym, qty)
        if not filled_qty or not fill_price:
            log.error(f"  ❌ No se pudo abrir {sym}")
            self._pending_orders.pop(sym, None)
            return False

        sl_pct_real = sig['sl_pct']
        sl_real     = fill_price * (1 - sl_pct_real / 100)
        sl_real = min(sl_real, fill_price * (1 - SL_MIN_PCT / 100))
        sl_real = max(sl_real, fill_price * (1 - SL_MAX_PCT / 100))
        tp1_price = fill_price * (1 + sl_pct_real * TP1_RATIO / 100)
        tp2_price = fill_price * (1 + sl_pct_real * TP2_RATIO / 100)

        sl_ok = self._place_sl(sym, filled_qty, sl_real)
        if not sl_ok:
            time.sleep(2); sl_ok = self._place_sl(sym, filled_qty, sl_real)
        if not sl_ok:
            log.error("  ❌ SL crítico — cerrando")
            self._order(sym,'SELL',filled_qty,'MARKET')
            self._pending_orders.pop(sym, None)
            return False

        trailing_placed = False
        if USE_TRAILING_EXIT:
            activation = fill_price * (1 + TRAIL_ACTIVATION / 100)
            trailing_placed = self._place_trailing_stop(sym, filled_qty, activation, TRAIL_RATE_PCT)

        trade = {
            'entry': fill_price, 'qty_total': filled_qty, 'qty_runner': filled_qty,
            'qty_tp1': round(filled_qty * TP1_PCT/100, 6),
            'qty_tp2': round(filled_qty * TP2_PCT/100, 6),
            'tp1_hit': False, 'tp2_hit': False,
            'tp1_price': tp1_price, 'tp2_price': tp2_price,
            'sl': sl_real, 'sl_orig': sl_real, 'sl_pct': sl_pct_real,
            'highest': fill_price, 'opened': datetime.now(),
            'score': sig['score'], 'ema25': sig['ema25'], 'ema55': sig['ema55'],
            'aurolo_pts': pts, 'entrada_label': label,
            'vwap': sig['vwap'], 'usdt': POS_SIZE, 'pnl_parcial': 0.0,
            'factors': sig['factors'], 'hora_utc': sig['hora_utc'],
            'btc_dir': sig['btc_dir'], 'debilidad_alertada': False,
            'trailing_placed': trailing_placed,
            'be_placed': False,  # [M6] breakeven agresivo
        }
        self.trades[sym] = trade
        self._pending_orders.pop(sym, None)
        self.stats['exec'] += 1; self.stats['fees'] += notional * FEE

        p1 = "✅" if sig['aurolo_p1'] else "❌"
        p2 = "✅" if sig['aurolo_p2'] else "❌"
        p3 = "✅" if sig['aurolo_p3'] else "❌"

        self._tg(
            f"<b>🟢 LONG [{label}]{momentum}</b> — <b>{sym}</b>\n"
            f"Score: {int(sig['score'])}/{int(sig['score_min'])} | RR: {sig['rr']:.2f}:1 | {sig['regime']}\n"
            f"{p1} P1 EMA55  {p2} P2 WT:{sig['aurolo_wt']:.1f}  {p3} P3 ADX:{sig['aurolo_adx']:.1f}\n"
            f"📍 ${fill_price:.6f} | SL: ${sl_real:.6f} (-{sl_pct_real:.2f}%)\n"
            f"OrderFlow: {sig['of_delta']:+.2f} | VolReg: {sig['vol_regime']}\n"
            f"Kelly: ×{self.learn.kelly_mult:.2f} | Trailing: {'✅' if trailing_placed else '❌'}"
        )
        return True

    def _close_partial(self, sym, qty, exit_price, label):
        if qty <= 0: return 0
        d = self._order(sym, 'SELL', qty, 'MARKET')
        if d.get('code') != 0: return 0
        t = self.trades[sym]
        chg  = (exit_price - t['entry']) / t['entry']
        frac = qty / t['qty_total']
        net  = POS_SIZE*LEVERAGE*chg*frac - POS_SIZE*LEVERAGE*FEE*2*frac
        t['pnl_parcial'] += net; t['qty_runner'] -= qty
        self.stats['fees'] += POS_SIZE*LEVERAGE*FEE*2*frac
        self._daily_pnl += net; self.stats['pnl'] += net
        log.info(f"  💰 {label} {sym}: ${net:+.4f}")
        self._tg(f"<b>💰 {label}</b> — {sym}\n${exit_price:.6f}\nPnL: ${net:+.4f}")
        return net

    def _close_all(self, sym, exit_price, reason):
        if sym not in self.trades: return False
        t = self.trades[sym]
        qty_rem = t['qty_runner']
        if qty_rem > 0: self._order(sym,'SELL',qty_rem,'MARKET')
        frac_r = qty_rem / t['qty_total'] if t['qty_total'] > 0 else 0
        chg_r  = (exit_price - t['entry']) / t['entry']
        net_r  = POS_SIZE*LEVERAGE*chg_r*frac_r - POS_SIZE*LEVERAGE*FEE*2*frac_r
        net_total = t['pnl_parcial'] + net_r
        win = net_total > 0

        self.stats['closed'] += 1; self.stats['pnl'] += net_r
        self.stats['fees']   += POS_SIZE*LEVERAGE*FEE*2*frac_r
        self._daily_pnl      += net_r
        if win: self.stats['wins'] += 1
        else:   self.stats['losses'] += 1

        total = self.stats['wins']+self.stats['losses']
        wr    = self.stats['wins']/total*100 if total else 0
        mins  = int((datetime.now()-t['opened']).total_seconds()/60)
        emoji = "✅" if win else "❌"
        log.info(f"  {emoji} {reason} | ${net_total:+.4f} | {mins}min | WR:{wr:.0f}%")

        self.learn.record(
            symbol=sym, score=t['score'], pnl=net_total, win=win,
            hora_utc=t.get('hora_utc',datetime.utcnow().hour),
            pts_aurolo=t.get('aurolo_pts',0),
            btc_dir=t.get('btc_dir','flat'),
            reason=reason, factors=t.get('factors',[]),
        )

        if 'STOP LOSS' in reason or 'SL' in reason:
            if mins < CD_SL_FAST_MIN:
                self._cooldowns[sym] = (time.time() + CD_SL_FAST_HOURS * 3600, 'SL_FAST')
            else:
                self._set_cd(sym, 'SL')
        else:
            self._set_cd(sym, 'TP')

        self._tg(
            f"<b>{'✅' if win else '❌'} CERRADO — {reason}</b>\n"
            f"<b>{sym}</b> | {mins}min\n"
            f"${t['entry']:.6f} → ${exit_price:.6f}\n"
            f"<b>PnL: ${net_total:+.4f} | WR: {wr:.0f}%</b>"
        )
        if self.stats['closed'] % 3 == 0: self.learn.save()
        del self.trades[sym]
        self._cancel_open(sym)
        return True

    async def monitor(self):
        for sym in list(self.trades.keys()):
            try:
                t  = self.trades[sym]
                tk = self._ticker(sym)
                if not tk: continue
                cur = tk['price']

                c5, h5, l5, v5, _ = self._klines(sym, '5m', 80)
                if c5:
                    t['ema25'] = ema(c5, 25)
                    t['ema55'] = ema(c5, AUROLO_EMA_LEN)

                if c5 and h5 and l5 and not t.get('debilidad_alertada', False):
                    atr_live = atr_calc(h5, l5, c5, 14)
                    sig_live = aurolo_signal(c5, h5, l5, v5 or [1]*len(c5), c5, atr_live)
                    if sig_live['debilidad']:
                        t['debilidad_alertada'] = True
                        self._tg(f"<b>⚠️ DEBILIDAD — {sym}</b>")
                    if sig_live['cambio_tend'] and (cur-t['entry'])/t['entry']*100 > 0:
                        self._close_all(sym, cur, "CAMBIO TENDENCIA"); continue

                if cur > t['highest']: t['highest'] = cur

                # [M12] Cierre preventivo si régimen se deteriora
                gate_ok, _ = self._quality_gate()
                if not gate_ok and self._breadth < 0.25:
                    pnl_pct = (cur - t['entry']) / t['entry'] * 100
                    if pnl_pct > 0.3:
                        self._close_all(sym, cur, "RÉGIMEN DETERIORADO (preventivo)"); continue
                    elif pnl_pct < -1.5:
                        self._close_all(sym, cur, "STOP PREVENTIVO RÉGIMEN"); continue

                # [M6] Breakeven agresivo: tras +0.5*SL_PCT de beneficio
                if not t.get('be_placed') and not t.get('trailing_placed'):
                    be_trigger_pct = t['sl_pct'] * 0.5
                    pnl_pct = (cur - t['entry']) / t['entry'] * 100
                    if pnl_pct >= be_trigger_pct:
                        be_price = t['entry'] * 1.0008  # BE + fees
                        if be_price > t['sl']:
                            # Actualizar SL a breakeven
                            self._cancel_open(sym)
                            time.sleep(0.2)
                            if self._place_sl(sym, t['qty_runner'], be_price):
                                t['sl'] = be_price
                                t['be_placed'] = True
                                log.info(f"  🛡️ BE {sym} → ${be_price:.6f}")

                if t.get('trailing_placed') and USE_TRAILING_EXIT:
                    if cur <= t['sl']:
                        self._close_all(sym, cur, "STOP LOSS")
                    continue

                if not t['tp1_hit'] and cur >= t['tp1_price']:
                    self._close_partial(sym, t['qty_tp1'], cur, f"TP1({int(TP1_PCT)}%)")
                    t['tp1_hit'] = True
                    be = t['entry'] * 1.0008
                    if be > t['sl']:
                        t['sl'] = be
                        # Recolocar SL en BE
                        self._cancel_open(sym)
                        time.sleep(0.2)
                        self._place_sl(sym, t['qty_runner'], be)
                    continue

                if t['tp1_hit'] and not t['tp2_hit'] and cur >= t['tp2_price']:
                    self._close_partial(sym, t['qty_tp2'], cur, f"TP2({int(TP2_PCT)}%)")
                    t['tp2_hit'] = True
                    continue

                if cur <= t['sl']:
                    self._close_all(sym, cur, "STOP LOSS")

            except Exception as e:
                log.debug(f"monitor {sym}: {e}")

    def _cd_ok(self, sym):
        ts = self._cooldowns.get(sym)
        if not ts: return True
        resume, _ = ts if isinstance(ts, tuple) else (ts, 'TP')
        if time.time() >= resume: del self._cooldowns[sym]; return True
        return False

    def _set_cd(self, sym, reason='TP'):
        mins = CD_TP if reason == 'TP' else CD_SL
        self._cooldowns[sym] = (time.time() + mins*60, reason)

    def _daily_reset(self):
        today = datetime.utcnow().date()
        if today != self._daily_date:
            self._daily_pnl=0.0; self._daily_date=today
            self._cb_active=False; self._cb_until=None
            self.learn.streak=0; self._update_equity()
            self._equity_start = ACCOUNT_EQUITY
            log.info("📅 Nuevo día — reset diario")

    def _circuit_check(self):
        self._daily_reset()
        if self._cb_active:
            if self._cb_until and datetime.utcnow() > self._cb_until:
                self._cb_active=False; self._daily_pnl=0.0
                log.info("  🔓 Circuit breaker OFF")
            return self._cb_active
        if self._equity_start > 0:
            eq_loss_pct = abs(self._daily_pnl) / self._equity_start * 100
            if self._daily_pnl < 0 and eq_loss_pct > DAILY_LOSS_CAP_PCT:
                self._cb_active=True
                self._cb_until=datetime.utcnow()+timedelta(hours=CB_HOURS)
                self._tg(f"<b>🔒 DAILY LOSS CAP</b>\n{eq_loss_pct:.1f}% | Pausa {CB_HOURS}h")
                return True
        cb_threshold = ACCOUNT_EQUITY * (CB_PCT / 100)
        if self._daily_pnl < -cb_threshold:
            self._cb_active=True
            self._cb_until=datetime.utcnow()+timedelta(hours=CB_HOURS)
            self._tg(f"<b>🔒 CIRCUIT BREAKER</b>\n${self._daily_pnl:.3f} | Pausa {CB_HOURS}h")
        return self._cb_active

    def _report(self):
        if datetime.now()-self._last_report < timedelta(hours=2): return
        self._last_report = datetime.now()
        total = self.stats['wins']+self.stats['losses']
        wr    = self.stats['wins']/total*100 if total else 0
        pos   = ""
        for sym,t in self.trades.items():
            tk=self._ticker(sym); cur=tk['price'] if tk else t['entry']
            pct=(cur-t['entry'])/t['entry']*100
            be_icon = '🛡️' if t.get('be_placed') else ''
            pos += f"  {'🎯' if t.get('trailing_placed') else '📌'}{be_icon} {sym}[{t['aurolo_pts']}/3]: {pct:+.2f}%\n"

        momentum_top3 = ', '.join(self._momentum_ranked[:3]) if self._momentum_ranked else 'N/A'
        self._tg(
            f"<b>📊 Reporte v6.0-ALPHA</b>\n"
            f"PnL: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}% | {total}t\n"
            f"Régimen: {self._regime} | Breadth: {int(self._breadth*100)}%\n"
            f"Kelly: ×{self.learn.kelly_mult:.2f} | Score≥{int(self.learn.opt_score)}\n"
            f"🏆 Top momentum: {momentum_top3}\n"
            + (pos if pos else "  Sin posiciones\n")
        )

    def _tg(self, msg):
        try:
            if TG_TOKEN and TG_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                    timeout=6
                )
        except: pass

    async def run(self):
        log.info(f"\n🚀 Bot LONGS v6.0-ALPHA | {len(self.symbols)} símbolos | {SCAN_WORKERS} workers\n")
        iteration=0; last_sym=last_ltv=last_hedge=last_eq=last_regime=last_momentum=0

        while True:
            try:
                iteration += 1; self._daily_reset()
                if time.time()-last_sym     > 600:  self._refresh_symbols();    last_sym=time.time()
                if time.time()-last_ltv     > 300:  self._check_ltv();          last_ltv=time.time()
                if time.time()-last_hedge   > 600:
                    for sym, sides in self._get_exchange_positions().items():
                        if sides['short'] > 0:
                            self._order_close_short(sym, sides['short']); time.sleep(0.3)
                    last_hedge=time.time()
                if time.time()-last_eq      > 1800: self._update_equity();      last_eq=time.time()
                if time.time()-last_regime  > 300:
                    self._update_market_regime(); last_regime=time.time()

                if time.time()-last_momentum > 900:
                    log.info("  🏆 Actualizando líderes de momentum...")
                    self._get_momentum_leaders()
                    last_momentum = time.time()

                if time.time() - self._last_zombie_clean > ZOMBIE_CLEANUP_MIN * 60:
                    self._nuke_zombie_orders()

                self._update_btc()
                if self._circuit_check():
                    await asyncio.sleep(INTERVAL); continue

                total=self.stats['wins']+self.stats['losses']
                wr=self.stats['wins']/total*100 if total else 0
                score_min = self._score_min_for_regime()

                log.info(f"\n{'='*72}")
                log.info(
                    f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                    f"Abiertos:{len(self.trades)}/{MAX_TRADES} | "
                    f"PnL:${self.stats['pnl']:+.4f} | WR:{wr:.0f}%"
                )
                log.info(
                    f"  BTC1h:{self._btc_1h:+.2f}% BTC4h:{self._btc_4h:+.2f}% | "
                    f"Régimen:{self._regime} | Breadth:{int(self._breadth*100)}% | "
                    f"Score≥{int(score_min)} | Kelly:{self.learn.kelly_mult:.2f}"
                )
                log.info(f"{'='*72}\n")

                await self.monitor()
                self._report()

                if len(self.trades) < MAX_TRADES:
                    gate_ok, gate_reason = self._quality_gate()
                    if not gate_ok:
                        log.info(f"  ⏸️ Quality Gate: {gate_reason}")
                        await asyncio.sleep(INTERVAL); continue

                    momentum_syms = list(self._momentum_cache) if self._momentum_cache else []
                    rest = [s for s in self.symbols
                            if s not in momentum_syms and s not in self.trades]

                    if not momentum_syms:
                        log.info("  🏆 Primera carga de momentum...")
                        momentum_syms = self._get_momentum_leaders()
                        last_momentum = time.time()
                        rest = [s for s in self.symbols
                                if s not in momentum_syms and s not in self.trades]

                    scan_order = momentum_syms + rest[:50]
                    log.info(
                        f"  🔍 Scan: {len(momentum_syms)} líderes + {len(rest[:50])} fallback "
                        f"({SCAN_WORKERS} workers)..."
                    )

                    signals = self._analyze_parallel(scan_order)
                    found = len(signals)
                    log.info(f"  ✅ {found} señales encontradas")

                    for sym, sig in signals:
                        if len(self.trades) >= MAX_TRADES: break
                        ml = '🏆' if sig.get('momentum_leader') else ''
                        of = f"OF:{sig['of_delta']:+.2f}"
                        log.info(
                            f"  💡 {ml}{sym} [{sig['aurolo_señal']}] | "
                            f"Score:{int(sig['score'])}/{int(sig['score_min'])} | "
                            f"RR:{sig['rr']:.2f}:1 | {of} | {sig['vol_regime']}"
                        )
                        if self.open_trade(sym, sig):
                            await asyncio.sleep(3)
                else:
                    log.info("  ⏸️ Max trades — monitoreando")

                await asyncio.sleep(INTERVAL)

            except KeyboardInterrupt: log.info("⏹️ Detenido"); break
            except Exception as e:
                log.error(f"❌ Error #{iteration}: {e}", exc_info=True)
                await asyncio.sleep(20)

        self.learn.save()


async def main():
    bot = LongBot()
    await bot.run()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: log.info("👋 Bot terminado")
