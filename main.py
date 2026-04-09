#!/usr/bin/env python3
"""
BOT LONGS v5.8 — MLP Tactical Bridge (Aurolo) — FIXED + OPTIMIZADO
════════════════════════════════════════════════════════════════════════════════

CORRECCIONES v5.8 vs v5.7:
  FIX 1.  SL mínimo corregido — lógica min/max estaba invertida → SL 0.40% imposible
  FIX 2.  Entrada MARKET directa — LIMIT 0.05% casi nunca llenaba, siempre caía a MARKET
  FIX 3.  TP1_RATIO 2.0 / TP2_RATIO 3.5 — TP anteriores no cubrían fees
  FIX 4.  MIN_RR subido a 2.2 — RR 1.8 con fees 2x leverage daba break-even imposible
  FIX 5.  MIN_VOL subido a 5M — evita altcoins ilíquidas tipo BEAT-USDT
  FIX 6.  Cooldown 8h si SL ocurre en < 10 minutos (falsa señal)
  FIX 7.  learn.ok() verificado en arranque — opt_score no puede bajar de MIN_SCORE
  FIX 8.  Filtro TP neto post-fees antes de entrar (mínimo +0.4% neto en TP1)
  FIX 9.  Circuit breaker relativo a equity real, no a POS_SIZE fijo
  FIX 10. Score mínimo forzado a 65 al arranque, sin importar estado guardado
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re, json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from collections import defaultdict

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
MAX_TRADES     = clean('MAX_OPEN_TRADES',      '3',     'int')
RISK_PCT       = clean('RISK_PCT',             '1.0',   'float')
ACCOUNT_EQUITY = clean('ACCOUNT_EQUITY',       '100',   'float')

# ── TPs Escalonados ────────────────────────────────────────────────────────
TP1_PCT   = clean('TP1_PCT',   '40',  'float')
TP2_PCT   = clean('TP2_PCT',   '35',  'float')
# FIX 3: TP ratios aumentados para cubrir fees y ser rentables
TP1_RATIO = clean('TP1_RATIO', '2.0', 'float')   # v5.8: era 1.2 → mínimo 2× SL
TP2_RATIO = clean('TP2_RATIO', '3.5', 'float')   # v5.8: era 2.5 → mínimo 3.5× SL

# ── TP/SL ──────────────────────────────────────────────────────────────────
TP_MIN    = clean('TAKE_PROFIT_PCT', '1.5',  'float')  # v5.8: era 2.5 — ajustado
ATR_TP_M  = clean('ATR_TP_MULT',    '3.0',  'float')
# FIX 4: MIN_RR subido — con fees 2x leverage necesitas RR > 2
MIN_RR    = clean('MIN_RR',         '2.2',  'float')   # v5.8: era 1.8
SL_ATR_M  = clean('SL_ATR_MULT',   '1.5',  'float')
SL_MAX_PCT = clean('SL_MAX_PCT',   '3.5',  'float')
SL_MIN_PCT = clean('SL_MIN_PCT',   '0.8',  'float')   # mínimo garantizado

# ── Filtros de contexto ────────────────────────────────────────────────────
# FIX 5: MIN_VOL subido a 5M para evitar coins ilíquidas
MIN_VOL   = clean('MIN_VOLUME_24H',     '5000000', 'float')  # v5.8: era 1M → 5M
MAX_SYMS  = clean('MAX_SYMBOLS',        '40',     'int')
MIN_SCORE = clean('MIN_SCORE',          '65',     'float')
BTC_BLOCK = clean('BTC_BEAR_BLOCK_PCT', '1.0',    'float')

# ── v5.7/5.8 Régimen de mercado ────────────────────────────────────────────
REGIME_CHECK      = clean('REGIME_CHECK',      'true',  'bool')
BREADTH_MIN       = clean('BREADTH_MIN',        '0.40',  'float')
BTC_4H_CRASH_PCT  = clean('BTC_4H_CRASH_PCT',  '3.0',   'float')
BTC_4H_CRASH_PAUSE= clean('BTC_4H_CRASH_HOURS','2',      'int')
DAILY_LOSS_CAP_PCT= clean('DAILY_LOSS_CAP_PCT','10.0',  'float')

# ── VWAP ──────────────────────────────────────────────────────────────────
VWAP_CANDLES   = clean('VWAP_CANDLES',  '50',   'int')
VWAP_AS_FILTER = clean('VWAP_FILTER',  'true',  'bool')

# ── Motor Principal: Aurolo MLP Tactical Bridge ────────────────────────────
AUROLO_EMA_LEN   = clean('AUROLO_EMA_LEN',   '55',   'int')
AUROLO_ZONA_AUTO = clean('AUROLO_ZONA_AUTO',  'true', 'bool')
AUROLO_ZONA_PCT  = clean('AUROLO_ZONA_PCT',   '0.8',  'float')
AUROLO_ZONA_VELAS = clean('AUROLO_ZONA_VELAS', '6',   'int')

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
ADX_KEY    = clean('ADX_KEY',    '20',  'float')

# Configuración señal
AUROLO_MIN_PTS = clean('AUROLO_MIN_PTS', '2',     'int')
AUROLO_ENTRY   = clean('AUROLO_ENTRY',   'close', 'str')

# ── Circuit breaker ────────────────────────────────────────────────────────
CB_PCT     = clean('CIRCUIT_BREAKER_PCT', '6.0',  'float')
CB_HOURS   = clean('CB_PAUSE_HOURS',      '2',    'int')
MAX_STREAK = clean('MAX_LOSING_STREAK',   '4',    'int')

# ── Cooldowns ─────────────────────────────────────────────────────────────
CD_TP        = clean('COOLDOWN_TP_MIN',  '10',  'int')
CD_SL        = clean('COOLDOWN_SL_MIN', '240',  'int')   # 4 horas
CD_SL_TODAY  = clean('COOLDOWN_SL_TODAY', 'true', 'bool')
# FIX 6: cooldown extra si SL muy rápido (< 10 min)
CD_SL_FAST_MIN   = clean('COOLDOWN_SL_FAST_MIN', '8', 'int')   # minutos máx para considerar SL rápido
CD_SL_FAST_HOURS = clean('COOLDOWN_SL_FAST_HOURS', '8', 'int') # horas de cooldown si SL rápido

# ── Aprendizaje ───────────────────────────────────────────────────────────
LEARN_MIN_TRADES_SCORE = clean('LEARN_MIN_TRADES', '10', 'int')
LEARN_MIN_TRADES_BL    = clean('LEARN_MIN_TRADES_BL', '5', 'int')
SCORE_CAP_LOW          = clean('SCORE_CAP_LOW', '70',  'float')
SCORE_CAP_HIGH         = clean('SCORE_CAP_HIGH', '85', 'float')

# ── Misc ───────────────────────────────────────────────────────────────────
INTERVAL   = clean('CHECK_INTERVAL', '90', 'int')
LTV_WARN   = clean('LTV_WARNING_PCT', '75', 'float')

_skip_raw  = os.getenv('SKIP_HOURS', '2,3')
SKIP_HOURS = set(int(x.strip()) for x in _skip_raw.split(',') if x.strip().isdigit())

BASE_URL   = "https://open-api.bingx.com"
FEE        = 0.0002
# FIX 8: coste real de fees con leverage
FEE_COST_PCT = FEE * LEVERAGE * 2 * 100   # % de coste mínimo por operación completa
TP_MIN_FEE   = round(FEE_COST_PCT + 0.003 * 100, 3)

EXCLUDE = {
    'DOW','SP500','GOLD','SILVER','XAU','OIL','BRENT','EUR','GBP','JPY',
    'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN','MSTR',
    'WHEAT','CORN','SUGAR','PAXG','XAUT',
}

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

# ============================================================================
# MOTOR AUROLO v5.8
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
    adx_cayendo = adx_now < adx_prev
    result['p3'] = adx_fuerte and di_alcista

    pts = int(result['p1']) + int(result['p2']) + int(result['p3'])
    result['puntos'] = pts

    # ── FIX 1: SL INTELIGENTE — lógica min/max corregida ─────────────────
    # sl_max_price = precio más LEJANO permitido (price * 0.965 si SL_MAX=3.5%)
    # sl_min_price = precio más CERCANO permitido (price * 0.992 si SL_MIN=0.8%)
    # El SL calculado debe estar ENTRE estos dos límites
    atr_actual   = atr_v or atr_calc(highs, lows, closes, 14)
    min_reciente = min(lows[-8:-1]) if len(lows) >= 8 else lows[-1]
    sl_vulner    = min_reciente - atr_actual * SL_ATR_M
    sl_bajo_ema  = ema55 * (1 - 0.20/100)
    sl_calculado = min(sl_vulner, sl_bajo_ema)

    # Límites absolutos
    sl_max_price = price * (1 - SL_MAX_PCT / 100)  # no puede ser MÁS LEJANO que esto
    sl_min_price = price * (1 - SL_MIN_PCT / 100)  # no puede ser MÁS CERCANO que esto

    # Aplicar límites correctamente:
    # 1. Si sl_calculado es más lejano que el máximo → acercar al máximo
    sl_price = max(sl_calculado, sl_max_price)
    # 2. Si sl_calculado es más cercano que el mínimo → alejar al mínimo
    sl_price = min(sl_price, sl_min_price)

    # Validación final: sl_price debe estar por debajo del precio actual
    if sl_price >= price:
        sl_price = price * (1 - SL_MIN_PCT / 100)

    sl_pct = (price - sl_price) / price * 100
    # Guardia extra: sl_pct nunca puede ser < SL_MIN_PCT
    if sl_pct < SL_MIN_PCT:
        sl_price = price * (1 - SL_MIN_PCT / 100)
        sl_pct   = SL_MIN_PCT

    result['sl_price'] = round(sl_price, 8)
    result['sl_pct']   = round(sl_pct, 3)

    wt_ob_baj = wt_now < wt_prev and wt_prev >= WT_OB2
    di_gira   = din_now > dip_now * 0.80
    result['debilidad'] = bool(adx_cayendo and (wt_ob_baj or wt_now >= WT_OB1) and di_gira)

    vol_avg = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else volumes[-1]
    result['vol_ratio'] = volumes[-1] / vol_avg if vol_avg > 0 else 1

    p1_icon = '✅' if result['p1'] else '❌'
    p2_icon = '✅' if result['p2'] else '❌'
    p3_icon = '✅' if result['p3'] else '❌'
    result['descripcion'] = (
        f"P1({p1_icon})EMA{AUROLO_EMA_LEN} | "
        f"P2({p2_icon})WT={round(wt_now,1)} | "
        f"P3({p3_icon})ADX={round(adx_now,1)} DI+={round(dip_now,1)}"
    )

    if pts >= 3:   result['señal'] = 'LONG_3/3'
    elif pts == 2: result['señal'] = 'LONG_2/3'
    elif pts == 1: result['señal'] = 'ESPERAR'
    else:          result['señal'] = 'NO'

    return result


def vwap_contexto(closes, highs, lows, volumes, n=50):
    if len(closes) < n: return closes[-1], True
    vwap = calc_vwap(closes, highs, lows, volumes, n)
    return vwap, closes[-1] > vwap


# ============================================================================
# APRENDIZAJE v5.8
# ============================================================================

class Learning:
    def __init__(self):
        self.history       = []
        self.sym_stats     = defaultdict(lambda: {'w':0,'l':0,'pnl':0.0,'n':0})
        # FIX 10: opt_score siempre arranca en MIN_SCORE
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
        rec = {
            'ts': datetime.now().isoformat(), 'sym': symbol,
            'score': score, 'pnl': pnl, 'win': win,
            'hora': hora_utc or datetime.utcnow().hour,
            'pts': pts_aurolo, 'btc': btc_dir,
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

        self.by_hour[rec['hora']][k] += 1; self.by_hour[rec['hora']]['pnl'] += pnl
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
            if wr < 0.30:
                self.opt_score = min(self.opt_score + 5, cap)
                log.warning(f"  [LEARN] ⬆️ Score subido a {int(self.opt_score)} (WR={int(wr*100)}%)")
            elif wr < 0.40:
                self.opt_score = min(self.opt_score + 2, cap)
            elif wr > 0.65:
                self.opt_score = max(self.opt_score - 2, MIN_SCORE)
            elif wr > 0.75:
                self.opt_score = max(self.opt_score - 4, MIN_SCORE)
        else:
            if self.opt_score > cap:
                self.opt_score = cap

        # FIX 7: opt_score nunca puede bajar de MIN_SCORE
        self.opt_score = max(self.opt_score, MIN_SCORE)

        for sym, s in self.sym_stats.items():
            tot = s['w'] + s['l']
            if (tot >= LEARN_MIN_TRADES_BL and
                    s['pnl'] < -1.5 and
                    s['w'] / tot < 0.25):
                if sym not in self.blacklist:
                    self.blacklist.add(sym)
                    log.warning(f"  [LEARN] 🚫 {sym} → blacklist ({tot}t, WR={int(s['w']/tot*100)}%)")

        if n >= 15:
            for f in set(list(self.factor_wins) + list(self.factor_losses)):
                w = self.factor_wins.get(f, 0); l = self.factor_losses.get(f, 0)
                if w+l < 5: continue
                wr_f = w/(w+l)
                if wr_f < 0.30:   self.score_boost[f] = -10
                elif wr_f > 0.70: self.score_boost[f] = +6
                else:             self.score_boost.pop(f, None)

    def hora_ok(self, h):
        d = self.by_hour.get(h)
        if not d: return True, "ok"
        tot = d['w']+d['l']
        if tot < 6: return True, "ok"
        wr_hora = d['w'] / tot
        if wr_hora < 0.25:
            return False, f"hora {h}h WR={int(wr_hora*100)}%"
        return True, "ok"

    def bonus_pts(self, pts) -> int:
        d = self.by_pts.get(pts)
        if not d: return 0
        tot = d['w']+d['l']
        if tot < 5: return 0
        wr = d['w']/tot
        if wr > 0.65: return +10
        if wr < 0.35: return -15
        return 0

    def ok(self, sym, score):
        self._check_daily_reset()
        if sym in self.blacklist:
            return False, "blacklist"
        if sym in self.daily_losers:
            return False, "SL hoy"
        # FIX 7: comparación forzada contra MAX(opt_score, MIN_SCORE)
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
        pts_txt = ""
        for p in sorted(self.by_pts):
            d = self.by_pts[p]; tot = d['w']+d['l']
            if tot > 0:
                pts_txt += f"  {p}/3 pts: WR={int(d['w']/tot*100)}% PnL=${d['pnl']:.2f} ({tot}t)\n"
        reas_txt = ""
        for r, d in sorted(self.by_reason.items(), key=lambda x: x[1]['pnl'], reverse=True):
            reas_txt += f"  {r}: ${d['pnl']:+.2f} ({d['n']}x)\n"

        msg = (
            f"<b>🧠 APRENDIZAJE v5.8 — {n} trades</b>\n"
            f"WR: {int(wr)}% | PnL: ${pnl:+.4f} | Score mín: {int(self.opt_score)}\n"
            f"Blacklist: {len(self.blacklist)} | SL hoy: {len(self.daily_losers)} | Cap: {int(self._score_cap())}\n\n"
            f"<b>📊 Por puntos Aurolo:</b>\n{pts_txt or '  Sin datos\n'}"
            f"<b>🚪 Cierres:</b>\n{reas_txt or '  Sin datos\n'}"
        )
        log.info(f"[LEARN] #{n//10}: WR={int(wr)}% PnL=${pnl:+.4f} Score={int(self.opt_score)}")
        try:
            if TG_TOKEN and TG_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                    timeout=6
                )
        except: pass

    def save(self, fp='/tmp/bot_learn_v58.json'):
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
            }, open(fp,'w'), indent=2)
        except: pass

    def load(self, fp='/tmp/bot_learn_v58.json'):
        for path in [fp, '/tmp/bot_learn_v57.json', '/tmp/bot_learn_v56.json', '/tmp/bot_learn.json']:
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
                cap = self._score_cap()
                # FIX 10: al cargar, opt_score nunca puede ser < MIN_SCORE
                self.opt_score = max(min(raw_score, cap), MIN_SCORE)
                log.info(f"  [LEARN] {len(self.history)} trades | Score: {int(self.opt_score)} (cap={int(cap)}) | BL: {len(self.blacklist)} | SL hoy: {len(self.daily_losers)}")
                return
            except: continue


# ============================================================================
# BOT PRINCIPAL v5.8
# ============================================================================

class LongBot:
    _opening = False

    def __init__(self):
        log.info("=" * 72)
        log.info("  BOT LONGS v5.8 — SL-Fixed + TP-Optimized + Market-Entry")
        log.info(f"  Capital: ${POS_SIZE} | Riesgo: {RISK_PCT}%/trade | {LEVERAGE}x")
        log.info(f"  SL: ATR×{SL_ATR_M} | mín={SL_MIN_PCT}% | máx={SL_MAX_PCT}%  [FIX 1]")
        log.info(f"  TP1 ratio:{TP1_RATIO}× | TP2 ratio:{TP2_RATIO}× | MIN_RR:{MIN_RR}  [FIX 3/4]")
        log.info(f"  Entrada: MARKET directo  [FIX 2]")
        log.info(f"  Score mín: {MIN_SCORE} | VOL mín: ${MIN_VOL/1e6:.0f}M  [FIX 5]")
        log.info(f"  CD SL: {CD_SL}min | SL rápido (<{CD_SL_FAST_MIN}min) → {CD_SL_FAST_HOURS}h  [FIX 6]")
        log.info("=" * 72)

        self.symbols      = []
        self.trades       = {}
        self._contracts   = {}
        self._cooldowns   = {}
        self._last_report = datetime.now() - timedelta(hours=3)
        self._btc_1h      = 0.0
        self._btc_4h      = 0.0
        self._btc_ok      = True
        self._regime      = 'neutral'
        self._regime_until= None
        self._breadth     = 0.5
        self._mode        = 'hedge'
        self._daily_pnl   = 0.0
        self._daily_date  = datetime.utcnow().date()
        self._equity_start= ACCOUNT_EQUITY
        self._cb_active   = False
        self._cb_until    = None
        self.learn        = Learning()
        self.learn.load()
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0,'fees':0.0}

        if not self._connect(): log.error("❌ Sin conexión BingX"); sys.exit(1)
        self._detect_mode()
        self._load_contracts()
        self._refresh_symbols()
        self._recover()

        self._tg(
            f"<b>🤖 Bot LONGS v5.8 — SL-Fixed + MARKET Entry</b>\n"
            f"Motor: EMA{AUROLO_EMA_LEN}+WT+ADX | Mín {AUROLO_MIN_PTS}/3\n"
            f"SL: ATR×{SL_ATR_M} mín={SL_MIN_PCT}% (CORREGIDO) | TP1:{TP1_RATIO}× TP2:{TP2_RATIO}×\n"
            f"Score≥{MIN_SCORE} | VOL≥${MIN_VOL/1e6:.0f}M | Entrada MARKET\n"
            f"Posiciones recuperadas: {len(self.trades)}"
        )

    # ── conexión ────────────────────────────────────────────────────────────

    def _connect(self) -> bool:
        global AUTO, ACCOUNT_EQUITY
        if not AUTO: return True
        if not API_KEY or not API_SECRET:
            log.error("❌ API keys no configuradas"); AUTO = False; return False
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') == 0:
            b = d.get('data',{})
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
        d = pub('/openApi/swap/v2/quote/ticker')
        if d.get('code') != 0:
            self.symbols = self.symbols or ['BTC-USDT','ETH-USDT','SOL-USDT']; return
        items = []
        for t in d.get('data',[]):
            sym = t.get('symbol','')
            if not sym.endswith('-USDT'): continue
            base = sym.replace('-USDT','').upper()
            if any(ex in base for ex in EXCLUDE): continue
            try:
                price = float(t.get('lastPrice',0)); vol = float(t.get('volume',0))*price
                if vol >= MIN_VOL and price > 0: items.append({'sym':sym,'vol':vol})
            except: continue
        items.sort(key=lambda x: x['vol'], reverse=True)
        self.symbols = [x['sym'] for x in items[:MAX_SYMS]]
        log.info(f"  Símbolos: {len(self.symbols)}")

    # ── detección de régimen de mercado ──────────────────────────────────

    def _update_market_regime(self):
        if not REGIME_CHECK: return

        c4h, *_ = self._klines('BTC-USDT', '4h', 10)
        if c4h and len(c4h) >= 4:
            self._btc_4h = (c4h[-1] - c4h[-4]) / c4h[-4] * 100
            if self._btc_4h < -BTC_4H_CRASH_PCT:
                if not self._regime_until or datetime.utcnow() > self._regime_until:
                    self._regime_until = datetime.utcnow() + timedelta(hours=BTC_4H_CRASH_PAUSE)
                    log.warning(f"  🚨 BTC CRASH {self._btc_4h:.1f}% en 4h — PAUSA {BTC_4H_CRASH_PAUSE}h")
                    self._tg(
                        f"<b>🚨 CRASH GUARD ACTIVO</b>\n"
                        f"BTC cayó {self._btc_4h:.1f}% en 4h\n"
                        f"Bot pausado {BTC_4H_CRASH_PAUSE}h"
                    )

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

        if btc_bear and low_breadth:
            nuevo = 'bear'
        elif btc_bear or low_breadth:
            nuevo = 'caution'
        elif self._btc_4h > 1.0 and self._breadth > 0.60:
            nuevo = 'bull'
        else:
            nuevo = 'neutral'

        if nuevo != self._regime:
            log.info(f"  📊 RÉGIMEN: {self._regime} → {nuevo} | BTC4h:{self._btc_4h:+.1f}% breadth:{int(self._breadth*100)}%")
            if nuevo == 'bear':
                self._tg(
                    f"<b>🐻 RÉGIMEN BAJISTA</b>\n"
                    f"BTC 4h: {self._btc_4h:+.1f}% | Breadth: {int(self._breadth*100)}%\n"
                    f"Entradas suspendidas"
                )
        self._regime = nuevo

    def _regime_ok(self) -> tuple:
        if self._regime_until and datetime.utcnow() < self._regime_until:
            remaining = int((self._regime_until - datetime.utcnow()).total_seconds() / 60)
            return False, f"crash guard {remaining}min"
        if self._regime == 'bear':
            return False, "régimen bajista"
        return True, "ok"

    # ── posiciones ────────────────────────────────────────────────────────

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
                }
                n_rec+=1
                log.info(f"  ♻️ LONG recuperado: {sym} @ ${entry:.6f}")
        log.info(f"  Recuperadas: {n_rec} | SHORTs cerrados: {n_sh}")

    def _scan_orphan_shorts(self):
        if not AUTO: return
        for sym, sides in self._get_exchange_positions().items():
            if sides['short'] > 0:
                self._order_close_short(sym, sides['short']); time.sleep(0.3)

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
        if symbol in self.trades: return None
        if not self._cd_ok(symbol): return None
        hora = datetime.utcnow().hour
        if hora in SKIP_HOURS: return None

        regime_ok, regime_reason = self._regime_ok()
        if not regime_ok:
            log.debug(f"  {symbol}: bloq régimen ({regime_reason})")
            return None

        if not self._btc_ok: return None
        if self._cb_active: return None

        hora_ok, hora_reason = self.learn.hora_ok(hora)
        if not hora_ok:
            log.debug(f"  {symbol}: bloq hora ({hora_reason})")
            return None

        c5, h5, l5, v5, o5 = self._klines(symbol, '5m', 130)
        if not c5 or len(c5) < AUROLO_EMA_LEN + 50: return None

        c1h, h1h, l1h, v1h, _ = self._klines(symbol, '1h', 50)
        c4h, h4h, l4h, v4h, _ = self._klines(symbol, '4h', 30)

        tk = self._ticker(symbol)
        if not tk or tk['price'] <= 0: return None
        price = tk['price']; change_24 = tk['change']

        # 1H trend
        trend_1h = 0; rsi_1h = 50.0
        if c1h and len(c1h) >= 25:
            e9_1h = ema(c1h, 9); e21_1h = ema(c1h, 21)
            rsi_1h = rsi(c1h, 14)
            if e9_1h > e21_1h: trend_1h = 1
            elif e9_1h < e21_1h: trend_1h = -1
        if trend_1h == -1: return None

        # 4H trend
        trend_4h = 0
        if c4h and len(c4h) >= 21:
            e9_4h = ema(c4h, 9); e21_4h = ema(c4h, 21)
            if e9_4h > e21_4h: trend_4h = 1
            elif e9_4h < e21_4h: trend_4h = -1
        if trend_4h == -1:
            log.debug(f"  {symbol}: 4H bajista — skip")
            return None

        atr_v   = atr_calc(h5, l5, c5, 14)
        atr_pct = atr_v / price * 100 if price > 0 else 0
        if atr_pct < 0.15:    return None
        if change_24 > 20.0:  return None
        if change_24 < -12.0: return None

        sig_aurolo = aurolo_signal(c5, h5, l5, v5, o5, atr_v)

        if sig_aurolo['puntos'] < AUROLO_MIN_PTS:
            return None

        if sig_aurolo['cambio_tend']:
            return None

        vwap_val, precio_sobre_vwap = vwap_contexto(c5, h5, l5, v5, VWAP_CANDLES)

        if VWAP_AS_FILTER and not precio_sobre_vwap:
            log.debug(f"  {symbol}: bajo VWAP (filtro duro)")
            return None

        sl_price = sig_aurolo['sl_price']
        sl_pct   = sig_aurolo['sl_pct']

        # FIX 1: validación adicional del SL aquí también
        if sl_pct < SL_MIN_PCT * 0.9:
            log.debug(f"  {symbol}: SL {sl_pct:.2f}% < mínimo {SL_MIN_PCT}% — skip")
            return None
        if sl_pct > SL_MAX_PCT * 1.1:
            return None

        tp1_price = price * (1 + sl_pct * TP1_RATIO / 100)
        tp2_price = price * (1 + sl_pct * TP2_RATIO / 100)
        tp_ref    = max(sl_pct * MIN_RR, TP_MIN, atr_pct * ATR_TP_M)
        rr        = tp_ref / sl_pct if sl_pct > 0 else 0

        if rr < MIN_RR * 0.75:
            return None

        # FIX 8: filtro de TP neto post-fees
        tp1_neto = sl_pct * TP1_RATIO - FEE_COST_PCT
        if tp1_neto < 0.4:
            log.debug(f"  {symbol}: TP1 neto {tp1_neto:.2f}% insuficiente — skip")
            return None

        # ── SCORING ──────────────────────────────────────────────────────
        score = 0; reasons = []; factors = []
        pts   = sig_aurolo['puntos']

        if pts == 3:   score += 50; reasons.append("Aurolo3/3(50)"); factors.append("aurolo_3")
        elif pts == 2: score += 30; reasons.append("Aurolo2/3(30)"); factors.append("aurolo_2")

        if sig_aurolo['p1']: score += 10; reasons.append("P1_Tend(10)"); factors.append("p1_tend")
        if sig_aurolo['p2']: score += 10; reasons.append("P2_WT(10)");   factors.append("p2_wt")
        if sig_aurolo['p3']: score += 10; reasons.append("P3_ADX(10)");  factors.append("p3_adx")

        wt_val = sig_aurolo['wt_now']
        if wt_val <= WT_OS1:
            score += 8; reasons.append(f"WT_deep({int(wt_val)})(8)"); factors.append("wt_deep")
        elif wt_val <= WT_OS2:
            score += 4; reasons.append(f"WT_os({int(wt_val)})(4)"); factors.append("wt_os")

        adx_val = sig_aurolo['adx_now']
        if adx_val > ADX_KEY * 1.4:
            score += 6; reasons.append("ADX_strong(6)"); factors.append("adx_strong")

        vr = sig_aurolo['vol_ratio']
        if vr >= 2.0:
            score += 10; reasons.append(f"Vol{vr:.1f}x(10)"); factors.append("vol_fuerte")
        elif vr >= 1.4:
            score += 5;  reasons.append(f"Vol{vr:.1f}x(5)");  factors.append("vol_medio")

        if precio_sobre_vwap:
            score += 8; reasons.append("VWAP↑(8)"); factors.append("vwap_arriba")
        else:
            score -= 8; reasons.append("VWAP↓(-8)"); factors.append("vwap_abajo")

        if trend_1h == 1:
            score += 12; reasons.append("1H↑(12)"); factors.append("trend_1h_up")
        if trend_4h == 1:
            score += 10; reasons.append("4H↑(10)"); factors.append("trend_4h_up")

        if self._regime == 'bull':
            score += 10; reasons.append("RegBull(10)"); factors.append("regime_bull")
        elif self._regime == 'caution':
            score -= 10; reasons.append("RegCaut(-10)"); factors.append("regime_caution")

        if self._btc_1h > 1.0:
            score += 8; reasons.append("BTC↑(8)"); factors.append("btc_up")
        elif self._btc_1h > 0.3:
            score += 4; reasons.append("BTC~(4)"); factors.append("btc_ok")
        elif self._btc_1h < -0.5:
            score -= 8; reasons.append("BTC↓(-8)"); factors.append("btc_down")

        if self._btc_4h > 1.5:
            score += 8; reasons.append("BTC4h↑(8)"); factors.append("btc4h_up")
        elif self._btc_4h < -1.0:
            score -= 12; reasons.append("BTC4h↓(-12)"); factors.append("btc4h_down")

        if rsi_1h < 40:
            score += 8; reasons.append(f"RSI1H{int(rsi_1h)}(8)"); factors.append("rsi_1h_os")
        elif rsi_1h < 55:
            score += 4; reasons.append(f"RSI1H{int(rsi_1h)}(4)"); factors.append("rsi_1h_ok")

        if sl_pct < SL_MAX_PCT * 0.6:
            score += 5; reasons.append("SL_tight(5)"); factors.append("sl_tight")

        if self._breadth > 0.65:
            score += 8; reasons.append(f"Breadth{int(self._breadth*100)}%(8)"); factors.append("breadth_good")
        elif self._breadth < 0.35:
            score -= 10; reasons.append(f"Breadth{int(self._breadth*100)}%(-10)"); factors.append("breadth_bad")

        bonus_p = self.learn.bonus_pts(pts)
        if bonus_p != 0:
            score += bonus_p; reasons.append(f"LearnPts({bonus_p:+d})"); factors.append(f"learn_pts_{pts}")

        adj = self.learn.adj(factors)
        if adj != 0:
            score += adj; reasons.append(f"FactAdj({adj:+d})")

        ok, reason = self.learn.ok(symbol, score)
        if not ok:
            log.debug(f"  {symbol}: rechazado ({reason}) score={int(score)}")
            return None

        e25 = ema(c5, 25)
        e55 = sig_aurolo['ema55']

        return {
            'price': price, 'change': change_24, 'score': score,
            'score_min': self.learn.opt_score,
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
            'trend_1h': trend_1h, 'trend_4h': trend_4h, 'rsi_1h': rsi_1h,
            'vol_ratio': vr, 'atr_pct': atr_pct,
            'reasons': ' | '.join(reasons), 'factors': factors,
            'hora_utc': hora, 'btc_dir': self._btc_dir(),
            'precio_sobre_vwap': precio_sobre_vwap,
            'regime': self._regime, 'breadth': self._breadth,
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
        if sl_price < price:
            dist_pct = (price-sl_price)/price*100
            riesgo   = ACCOUNT_EQUITY * (RISK_PCT/100)
            notional = min(riesgo / (dist_pct/100), POS_SIZE*LEVERAGE)
            notional = max(notional, MIN_TRADE)
        else:
            notional = max(POS_SIZE*LEVERAGE, MIN_TRADE)
        qty = math.ceil((notional/ppc)/step)*step; qty=round(qty,prec); val=qty*ppc
        for _ in range(200):
            if val>=MIN_TRADE: break
            qty+=step; qty=round(qty,prec); val=qty*ppc
        return (qty, round(val,4)) if val>=MIN_TRADE else (None,0)

    def _order(self, sym, side, qty, otype='MARKET', price=None, stop_price=None):
        params = {'symbol':sym,'side':side.upper(),'type':otype,'quantity':str(qty)}
        if self._mode=='hedge': params['positionSide']='LONG'
        else:
            if side.upper()=='SELL': params['reduceOnly']='true'
        if price:       params['price']=str(round(price,8)); params['timeInForce']='GTC'
        if stop_price:  params['stopPrice']=str(round(stop_price,8))
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
        for o in (d.get('data',{}).get('orders') or []):
            oid=o.get('orderId')
            if oid: api('DELETE','/openApi/swap/v2/trade/order',{'symbol':sym,'orderId':str(oid)})

    def _place_sl(self, sym, qty, sl_price):
        d=self._order(sym,'SELL',qty,'STOP_MARKET',stop_price=sl_price)
        ok=d.get('code')==0
        if not ok:
            sl_limit = sl_price * 0.999
            d=self._order(sym,'SELL',qty,'STOP',price=sl_limit,stop_price=sl_price)
            ok=d.get('code')==0
        log.info(f"  {'✅' if ok else '❌'} SL @ ${sl_price:.6f}")
        return ok

    def open_trade(self, sym, sig):
        if not AUTO or sym in self.trades: return False
        if LongBot._opening or len(self.trades)>=MAX_TRADES: return False
        if self._has_any_position(sym):
            log.warning(f"  ⛔ {sym} ya tiene posición → omitiendo"); return False
        LongBot._opening = True
        try: return self._open(sym, sig)
        finally: LongBot._opening = False

    def _open(self, sym, sig):
        price    = sig['price']
        sl_price = sig['sl_price']
        pts      = sig['aurolo_pts']
        label    = sig['aurolo_señal']

        log.info(f"\n  🎯 LONG {sym} [{label}] | Score:{int(sig['score'])} | RR:{sig['rr']:.2f}:1")
        log.info(f"  {sig['aurolo_desc']}")
        log.info(f"  SL:{sig['sl_pct']:.2f}% (mín garantizado {SL_MIN_PCT}%) | TP1 neto:{sig['tp1_neto']:.2f}%")
        log.info(f"  Régimen: {sig['regime']} | Breadth: {int(sig['breadth']*100)}%")

        self._set_lev(sym); time.sleep(0.2)
        qty, notional = self._calc_qty(sym, price, sl_price)
        if not qty: return False

        # FIX 2: entrada MARKET directa — el LIMIT 0.05% casi nunca llenaba
        log.info(f"  📥 Entrada MARKET — {qty} contratos @ ~${price:.6f}")
        d = self._order(sym, 'BUY', qty, 'MARKET')
        if d.get('code') != 0:
            log.error(f"  ❌ MARKET: {d.get('msg')}"); return False

        filled_qty, fill_price = self._confirm_pos(sym, 15)
        if not filled_qty:
            log.error(f"  ❌ No se confirmó posición para {sym}"); return False

        # Recalcular SL/TP con precio real de fill
        sl_pct_real = sig['sl_pct']
        sl_real     = fill_price * (1 - sl_pct_real / 100)
        # Garantizar que sl_real respeta el mínimo también con fill_price real
        sl_real = min(sl_real, fill_price * (1 - SL_MIN_PCT / 100))
        sl_real = max(sl_real, fill_price * (1 - SL_MAX_PCT / 100))

        tp1_price   = fill_price * (1 + sl_pct_real * TP1_RATIO / 100)
        tp2_price   = fill_price * (1 + sl_pct_real * TP2_RATIO / 100)

        sl_ok = self._place_sl(sym, filled_qty, sl_real)
        if not sl_ok:
            time.sleep(2); sl_ok = self._place_sl(sym, filled_qty, sl_real)
        if not sl_ok:
            log.error("  ❌ SL crítico — cerrando posición")
            self._order(sym,'SELL',filled_qty,'MARKET'); return False

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
        }
        self.trades[sym] = trade
        self.stats['exec']  += 1
        self.stats['fees']  += notional * FEE

        p1 = "✅" if sig['aurolo_p1'] else "❌"
        p2 = "✅" if sig['aurolo_p2'] else "❌"
        p3 = "✅" if sig['aurolo_p3'] else "❌"

        self._tg(
            f"<b>🟢 LONG [{label}]</b> — <b>{sym}</b>\n"
            f"Score: {int(sig['score'])} | RR: {sig['rr']:.2f}:1 | Régimen: {sig['regime']}\n\n"
            f"<b>🔍 Aurolo {pts}/3:</b>\n"
            f"{p1} P1 EMA{AUROLO_EMA_LEN}: ${sig['ema55']:.4f}\n"
            f"{p2} P2 WT: {sig['aurolo_wt']:.1f}\n"
            f"{p3} P3 ADX: {sig['aurolo_adx']:.1f} | DI+:{sig['aurolo_dip']:.1f} DI-:{sig['aurolo_din']:.1f}\n\n"
            f"📍 Entrada: ${fill_price:.6f}\n"
            f"🎯 TP1 ({int(TP1_PCT)}%): ${tp1_price:.6f} (+{sl_pct_real*TP1_RATIO:.2f}%)\n"
            f"🎯 TP2 ({int(TP2_PCT)}%): ${tp2_price:.6f} (+{sl_pct_real*TP2_RATIO:.2f}%)\n"
            f"🏃 Runner ({int(100-TP1_PCT-TP2_PCT)}%): EMA25\n"
            f"🛑 SL: ${sl_real:.6f} (-{sl_pct_real:.2f}%)\n"
            f"4H: {'🟢' if sig['trend_4h']==1 else '⚪'} | BTC: {self._btc_1h:+.2f}%"
        )
        return True

    def _close_partial(self, sym, qty, exit_price, label):
        if qty <= 0: return 0
        d = self._order(sym, 'SELL', qty, 'MARKET')
        if d.get('code') != 0:
            log.error(f"  ❌ Parcial {label} {sym}: {d.get('msg')}"); return 0
        t = self.trades[sym]
        chg  = (exit_price - t['entry']) / t['entry']
        frac = qty / t['qty_total']
        net  = POS_SIZE*LEVERAGE*chg*frac - POS_SIZE*LEVERAGE*FEE*2*frac
        t['pnl_parcial'] += net; t['qty_runner'] -= qty
        self.stats['fees'] += POS_SIZE*LEVERAGE*FEE*2*frac
        self._daily_pnl   += net; self.stats['pnl'] += net
        log.info(f"  💰 {label} {sym}: ${net:+.4f} | Resta:{t['qty_runner']:.4f}")
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

        log.info(f"  {emoji} {reason} | ${net_total:+.4f} ({net_total/POS_SIZE*100:+.1f}%) | {mins}min | WR:{wr:.0f}%")

        self.learn.record(
            symbol=sym, score=t['score'], pnl=net_total, win=win,
            hora_utc=t.get('hora_utc',datetime.utcnow().hour),
            pts_aurolo=t.get('aurolo_pts',0),
            btc_dir=t.get('btc_dir','flat'),
            reason=reason, factors=t.get('factors',[]),
        )

        # FIX 6: cooldown extendido si SL muy rápido
        if 'STOP LOSS' in reason or 'SL' in reason:
            if mins < CD_SL_FAST_MIN:
                fast_cd_secs = CD_SL_FAST_HOURS * 3600
                self._cooldowns[sym] = (time.time() + fast_cd_secs, 'SL_FAST')
                log.warning(f"  🚫 {sym}: SL en {mins}min → cooldown {CD_SL_FAST_HOURS}h (SL rápido)")
                self._tg(f"<b>⚠️ SL RÁPIDO — {sym}</b>\nSL en {mins}min → cooldown {CD_SL_FAST_HOURS}h")
            else:
                self._set_cd(sym, 'SL')
        else:
            self._set_cd(sym, 'TP')

        self._tg(
            f"<b>{'✅' if win else '❌'} CERRADO — {reason}</b>\n"
            f"<b>{sym}</b> | {t.get('entrada_label','?')} | {mins}min\n"
            f"${t['entry']:.6f} → ${exit_price:.6f}\n"
            f"Parcial: ${t['pnl_parcial']:+.4f} | Runner: ${net_r:+.4f}\n"
            f"<b>PnL: ${net_total:+.4f} ({net_total/POS_SIZE*100:+.1f}%) | WR: {wr:.0f}%</b>"
        )
        if self.stats['closed'] % 3 == 0: self.learn.save()
        del self.trades[sym]
        return True

    async def monitor(self):
        for sym in list(self.trades.keys()):
            try:
                t  = self.trades[sym]
                tk = self._ticker(sym)
                if not tk: continue
                cur = tk['price']
                pct = (cur - t['entry']) / t['entry'] * 100

                c5, h5, l5, v5, _ = self._klines(sym, '5m', 80)
                if c5:
                    t['ema25'] = ema(c5, 25)
                    t['ema55'] = ema(c5, AUROLO_EMA_LEN)

                if c5 and h5 and l5 and not t.get('debilidad_alertada', False):
                    atr_live = atr_calc(h5, l5, c5, 14)
                    sig_live = aurolo_signal(c5, h5, l5, v5 or [1]*len(c5), c5, atr_live)
                    if sig_live['debilidad']:
                        t['debilidad_alertada'] = True
                        self._tg(
                            f"<b>⚠️ DEBILIDAD — {sym}</b>\n"
                            f"Momentum agotándose | {pct:+.2f}% desde entrada\n"
                            f"WT={sig_live['wt_now']:.1f} | ADX={sig_live['adx_now']:.1f} cayendo"
                        )
                    if sig_live['cambio_tend'] and pct > 0:
                        self._close_all(sym, cur, "CAMBIO TENDENCIA"); continue

                if cur > t['highest']: t['highest'] = cur

                if not t['tp1_hit'] and cur >= t['tp1_price']:
                    self._close_partial(sym, t['qty_tp1'], cur, f"TP1({int(TP1_PCT)}%)")
                    t['tp1_hit'] = True
                    be = t['entry'] * 1.0008
                    if be > t['sl']: t['sl'] = be
                    continue

                if t['tp1_hit'] and not t['tp2_hit'] and cur >= t['tp2_price']:
                    self._close_partial(sym, t['qty_tp2'], cur, f"TP2({int(TP2_PCT)}%)")
                    t['tp2_hit'] = True
                    locked = t['entry'] + (t['highest'] - t['entry']) * 0.5
                    if locked > t['sl']: t['sl'] = locked
                    continue

                if t['tp2_hit']:
                    if c5 and l5:
                        min_rec = min(l5[-4:]) if len(l5) >= 4 else l5[-1]
                        trailing = max(t['ema25'], min_rec * 0.999)
                        if trailing > t['sl']: t['sl'] = trailing
                    if cur < t['ema25'] and c5 and c5[-1] < t['ema25'] and c5[-2] < t['ema25']:
                        self._close_all(sym, cur, "EMA25 RUNNER"); continue

                elif t['tp1_hit']:
                    if cur < t['ema25'] and c5 and c5[-1] < t['ema25'] and c5[-2] < t['ema25']:
                        self._close_all(sym, cur, "EMA25 PRE-TP2"); continue

                elif pct > 0.5 and cur < t['ema25']:
                    if c5 and c5[-1] < t['ema25'] and c5[-2] < t['ema25']:
                        self._close_all(sym, cur, "EMA25 EARLY"); continue

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
                self._tg("<b>🔓 Circuit breaker OFF</b>")
            return self._cb_active

        # FIX 9: daily loss cap relativo a equity real
        if self._equity_start > 0:
            eq_loss_pct = abs(self._daily_pnl) / self._equity_start * 100
            if self._daily_pnl < 0 and eq_loss_pct > DAILY_LOSS_CAP_PCT:
                self._cb_active=True
                self._cb_until=datetime.utcnow()+timedelta(hours=CB_HOURS)
                log.warning(f"  🔒 DAILY LOSS CAP | {eq_loss_pct:.1f}% pérdida hoy (equity ${self._equity_start:.2f})")
                self._tg(f"<b>🔒 DAILY LOSS CAP</b>\nPérdida: {eq_loss_pct:.1f}% hoy | Equity base: ${self._equity_start:.2f} | Pausa {CB_HOURS}h")
                return True

        # Circuit breaker absoluto de respaldo
        cb_threshold = ACCOUNT_EQUITY * (CB_PCT / 100)
        if self._daily_pnl < -cb_threshold:
            self._cb_active=True
            self._cb_until=datetime.utcnow()+timedelta(hours=CB_HOURS)
            log.warning(f"  🔒 CIRCUIT BREAKER | ${self._daily_pnl:.3f}")
            self._tg(f"<b>🔒 CIRCUIT BREAKER</b>\nPérdida: ${self._daily_pnl:.3f} | Pausa {CB_HOURS}h")
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
            tp_st = "TP1✅TP2✅" if t['tp2_hit'] else "TP1✅" if t['tp1_hit'] else "→TP1"
            pos += f"  📌 {sym}[{t['aurolo_pts']}/3]: {pct:+.2f}% {tp_st}\n"

        self._tg(
            f"<b>📊 Reporte v5.8</b>\n"
            f"PnL: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}% | {total}t\n"
            f"Día: ${self._daily_pnl:+.4f} | Equity: ${ACCOUNT_EQUITY:.2f}\n"
            f"Score: {int(self.learn.opt_score)} (cap {int(self.learn._score_cap())})\n"
            f"Régimen: {self._regime} | Breadth: {int(self._breadth*100)}% | BTC4h: {self._btc_4h:+.1f}%\n"
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
        log.info("\n🚀 Bot LONGS v5.8 — SL-Fixed + MARKET Entry + TP Optimized\n")
        iteration=0; last_sym=last_ltv=last_hedge=last_eq=last_regime=0

        while True:
            try:
                iteration += 1; self._daily_reset()
                if time.time()-last_sym    > 600:  self._refresh_symbols();       last_sym=time.time()
                if time.time()-last_ltv    > 300:  self._check_ltv();             last_ltv=time.time()
                if time.time()-last_hedge  > 600:  self._scan_orphan_shorts();    last_hedge=time.time()
                if time.time()-last_eq     > 1800: self._update_equity();         last_eq=time.time()
                if time.time()-last_regime > 300:
                    self._update_market_regime()
                    last_regime=time.time()

                self._update_btc()
                if self._circuit_check():
                    await asyncio.sleep(INTERVAL); continue

                total=self.stats['wins']+self.stats['losses']
                wr=self.stats['wins']/total*100 if total else 0

                log.info(f"\n{'='*72}")
                log.info(
                    f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                    f"Abiertos:{len(self.trades)}/{MAX_TRADES} | "
                    f"PnL:${self.stats['pnl']:+.4f} | WR:{wr:.0f}%"
                )
                log.info(
                    f"  BTC1h:{self._btc_1h:+.2f}% BTC4h:{self._btc_4h:+.2f}% | "
                    f"Régimen:{self._regime} | Breadth:{int(self._breadth*100)}%"
                )
                log.info(f"{'='*72}\n")

                await self.monitor()
                self._report()

                if len(self.trades) < MAX_TRADES:
                    regime_ok, regime_reason = self._regime_ok()
                    if not regime_ok:
                        log.info(f"  ⏸️ Sin entradas: {regime_reason}")
                        await asyncio.sleep(INTERVAL); continue

                    log.info(f"  Escaneando {len(self.symbols)} símbolos...")
                    found = 0
                    for i, sym in enumerate(self.symbols):
                        if len(self.trades) >= MAX_TRADES: break
                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            log.info(
                                f"  💡 {sym} [{sig['aurolo_señal']}] | "
                                f"Score:{int(sig['score'])}/{int(self.learn.opt_score)} | "
                                f"RR:{sig['rr']:.2f}:1 | SL:{sig['sl_pct']:.2f}% | TP1net:{sig['tp1_neto']:.2f}%"
                            )
                            if self.open_trade(sym, sig):
                                await asyncio.sleep(3)
                        if (i+1) % 15 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)}")
                        await asyncio.sleep(0.12)
                    log.info(f"  ✅ Scan: {found} señales")
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
