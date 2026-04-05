#!/usr/bin/env python3
"""
BOT LONGS v5.2 — Estrategia VWAP Whale Analytics (fiel al video)
═══════════════════════════════════════════════════════════════════
Estrategia exacta del video "Este Indicador de Scalping 5M me hizo
ganar 11790€ esta semana" — Whale Analytics:

  SETUP:  VWAP Breakout + Retesteo = entrada de alta probabilidad
  FILTRO: VWAP plano → manos quietas (no operar en rango)
  FILTRO: 1H debe confirmar tendencia alcista antes de entrar en 5M
  ENTRADA: En la RUPTURA del VWAP (vela que cierra sobre el VWAP
           con momentum, no esperar al retesteo)
  STOP:   Bajo el VWAP (nivel institucional clave) + margen ATR
  SALIDA: Cuando el precio cruza la EMA25 hacia abajo (salida maestra)
  RIESGO: Regla del 1% — tamaño de posición basado en la distancia
          entre entrada y SL (bajo el VWAP)

CAMBIOS vs v5.1:
  v5.2-A  Entrada en la RUPTURA del VWAP (candle cierra > VWAP con fuerza)
  v5.2-B  SL dinámico BAJO el VWAP (no % fijo desde entrada)
  v5.2-C  Tamaño de posición calculado por riesgo real (regla 1%)
  v5.2-D  EMA25 exit sin restricción de mínimo profit (salida siempre)
  v5.2-E  Señal de retesteo como entrada alternativa de mayor calidad
  v5.2-F  VWAP plano: filtro visual mejorado con banda de rango

HEREDADO de v5.1 (bugs fix):
  FIX-HEDGE-01: Previene abrir LONG si ya existe SHORT mismo símbolo
  FIX-HEDGE-02: _recover() cierra SHORTs huérfanos automáticamente
  FIX-HEDGE-03: Verificación en exchange antes de abrir
  FIX-HEDGE-04: _order() SELL nunca abre SHORT accidentalmente
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
POS_SIZE   = clean('MAX_POSITION_SIZE',    '10',   'float')   # USDT capital por trade
MIN_TRADE  = clean('MIN_TRADE_USDT',       '10',   'float')
_lev       = clean('LEVERAGE',             '2',    'int')
LEVERAGE   = min(_lev, 3)
MAX_TRADES = clean('MAX_OPEN_TRADES',      '3',    'int')

# ── Riesgo (Regla del 1% del video) ───────────────────────────────────────
# El tamaño de posición se calcula para no perder más del RISK_PCT
# de la cuenta en un solo trade (distancia entrada → SL bajo VWAP)
RISK_PCT   = clean('RISK_PCT',             '1.0',  'float')   # % cuenta por trade
ACCOUNT_EQUITY = clean('ACCOUNT_EQUITY',  '100',  'float')   # USDT cuenta total

# ── TP/SL ──────────────────────────────────────────────────────────────────
# v5.2: El SL se coloca BAJO el VWAP (no % fijo)
# TP sigue siendo dinámico basado en ATR / RR mínimo
TP_MIN     = clean('TAKE_PROFIT_PCT',      '3.0',  'float')   # TP mínimo aceptable
SL_VWAP_MARGIN = clean('SL_VWAP_MARGIN',  '0.15', 'float')   # Margen bajo VWAP (%)
ATR_TP_M   = clean('ATR_TP_MULT',          '2.5',  'float')
MIN_RR     = clean('MIN_RR',               '2.0',  'float')   # RR mínimo 2:1

# ── Filtros ────────────────────────────────────────────────────────────────
MIN_VOL    = clean('MIN_VOLUME_24H',       '500000','float')
MAX_SYMS   = clean('MAX_SYMBOLS',          '60',   'int')
MIN_SCORE  = clean('MIN_SCORE',            '50',   'float')
BTC_BLOCK  = clean('BTC_BEAR_BLOCK_PCT',   '2.0',  'float')

# ── VWAP params (estrategia Whale Analytics) ───────────────────────────────
VWAP_FLAT_PCT       = clean('VWAP_FLAT_PCT',      '0.15', 'float')  # VWAP plano si slope < 0.15%
VWAP_BREAK_MIN_PCT  = clean('VWAP_BREAK_MIN_PCT', '0.10', 'float')  # Ruptura mín sobre VWAP
VWAP_RETEST_PCT     = clean('VWAP_RETEST_PCT',    '0.30', 'float')  # Retest: dentro del 0.30% del VWAP
VWAP_CANDLES        = clean('VWAP_CANDLES',       '50',   'int')    # Velas para calcular VWAP
VWAP_SLOPE_CANDLES  = clean('VWAP_SLOPE_CANDLES', '20',   'int')    # Velas para medir pendiente

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
    """VWAP = Σ(precio_típico × volumen) / Σvolumen"""
    n = n or len(closes)
    c = closes[-n:]; h = highs[-n:]; l = lows[-n:]; v = volumes[-n:]
    typical = [(h[i] + l[i] + c[i]) / 3 for i in range(len(c))]
    tp_vol  = sum(typical[i] * v[i] for i in range(len(c)))
    vol_sum = sum(v)
    return tp_vol / vol_sum if vol_sum > 0 else c[-1]

def vwap_slope_pct(closes, highs, lows, volumes, n=20):
    """
    Pendiente del VWAP entre hace 5 velas y ahora.
    Retorna % de cambio — detecta si el VWAP está plano (mercado lateral).
    """
    if len(closes) < n * 2:
        return 0.0
    vwap_now  = calc_vwap(closes,      highs,      lows,      volumes,      n)
    vwap_prev = calc_vwap(closes[:-5], highs[:-5], lows[:-5], volumes[:-5], n)
    return (vwap_now - vwap_prev) / vwap_prev * 100 if vwap_prev > 0 else 0.0

# ============================================================================
# LÓGICA ESTRATEGIA VWAP — Whale Analytics (v5.2)
# ============================================================================

def analizar_setup_vwap(closes, highs, lows, volumes, opens):
    """
    Detecta los DOS tipos de entrada de la estrategia del video:

    TIPO A — RUPTURA (entrada agresiva):
      • El VWAP tiene pendiente alcista (no plano)
      • La vela actual rompe el VWAP con cierre claro por encima
      • Volumen de ruptura superior al promedio
      • EMA25 por debajo del precio (tendencia intacta)
      → Entrada inmediata, SL bajo el VWAP

    TIPO B — RETESTEO (entrada conservadora, mayor calidad):
      • Hubo una ruptura previa del VWAP (hace 2-10 velas)
      • El precio retrocedió a tocar el VWAP (retest)
      • Ahora rebota con vela alcista cerrando por encima
      → Entrada en el rebote, SL bajo el VWAP

    Retorna:
      {
        'tipo': 'A'|'B'|None,
        'vwap': float,           ← valor actual del VWAP
        'sl_price': float,       ← precio SL (bajo el VWAP)
        'calidad': 0-100,        ← puntuación del setup
        'slope': float,          ← pendiente VWAP
        'vol_ratio': float,      ← ratio volumen ruptura
        'descripcion': str
      }
    """
    result = {'tipo': None, 'vwap': 0, 'sl_price': 0,
              'calidad': 0, 'slope': 0, 'vol_ratio': 1, 'descripcion': ''}

    if len(closes) < VWAP_CANDLES + 15:
        return result

    vwap_val = calc_vwap(closes, highs, lows, volumes, VWAP_CANDLES)
    slope    = vwap_slope_pct(closes, highs, lows, volumes, VWAP_SLOPE_CANDLES)
    price    = closes[-1]

    result['vwap']  = vwap_val
    result['slope'] = slope

    # ── FILTRO 1: VWAP NO puede estar plano ──────────────────────────────
    # "Si el VWAP está plano, tus manos se quedan quietas" — video
    if abs(slope) < VWAP_FLAT_PCT:
        result['descripcion'] = f'VWAP plano (slope={slope:.3f}%) — no operar'
        return result

    # ── FILTRO 2: VWAP con pendiente alcista para longs ──────────────────
    if slope <= 0:
        result['descripcion'] = f'VWAP bajista (slope={slope:.3f}%) — no operar'
        return result

    # SL siempre va bajo el VWAP + margen de seguridad
    sl_price = vwap_val * (1 - SL_VWAP_MARGIN / 100)
    result['sl_price'] = sl_price

    # ── Volumen de la vela actual vs promedio ─────────────────────────────
    vol_avg   = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else volumes[-1]
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1
    result['vol_ratio'] = vol_ratio

    # ══════════════════════════════════════════════════════════════════════
    # TIPO A: RUPTURA del VWAP (entrada agresiva)
    # "Entramos en la ruptura. Stop bajo el VWAP y objetivo" — video
    # ══════════════════════════════════════════════════════════════════════
    pct_sobre_vwap = (price - vwap_val) / vwap_val * 100

    # La vela actual acaba de romper el VWAP (cerró por encima)
    prev_close = closes[-2] if len(closes) >= 2 else price
    ruptura_reciente = (prev_close <= vwap_val * 1.001) and (price > vwap_val * (1 + VWAP_BREAK_MIN_PCT / 100))

    if ruptura_reciente and 0 < pct_sobre_vwap < 1.5:
        calidad = 55
        if slope > 0.3:   calidad += 15   # VWAP con buena pendiente
        if vol_ratio >= 1.5: calidad += 15  # Volumen de confirmación
        if slope > 0.6:   calidad += 10   # Tendencia fuerte
        if vol_ratio >= 2.0: calidad += 5  # Volumen explosivo

        result.update({
            'tipo': 'A',
            'calidad': min(calidad, 100),
            'descripcion': f'RUPTURA VWAP | slope={slope:.2f}% | vol={vol_ratio:.1f}x | +{pct_sobre_vwap:.2f}% sobre VWAP'
        })
        return result

    # ══════════════════════════════════════════════════════════════════════
    # TIPO B: RETESTEO del VWAP (entrada conservadora, mayor calidad)
    # Patrón de 3 fases: Ruptura → Retest → Rebote
    # ══════════════════════════════════════════════════════════════════════
    ventana = min(12, len(closes) - 5)
    fase_ruptura  = False
    fase_retest   = False
    fase_rebote   = False
    candles_desde_retest = 0

    for i in range(-ventana, -1):
        c_i = closes[i]
        l_i = lows[i]
        o_i = opens[i] if opens else c_i

        # Fase 1: vela que rompió el VWAP con claridad
        if not fase_ruptura:
            if c_i > vwap_val * (1 + VWAP_BREAK_MIN_PCT / 100):
                fase_ruptura = True
            continue

        # Fase 2: retest — el precio volvió cerca del VWAP
        if fase_ruptura and not fase_retest:
            toque_pct = abs(l_i - vwap_val) / vwap_val * 100
            if toque_pct < VWAP_RETEST_PCT:
                fase_retest = True
                candles_desde_retest = 0
            continue

        # Fase 3: rebote alcista tras el retest
        if fase_ruptura and fase_retest:
            candles_desde_retest += 1
            if c_i > o_i and c_i > vwap_val:  # vela verde cerrando sobre VWAP
                fase_rebote = True
                break

    if fase_ruptura and fase_retest and fase_rebote and price > vwap_val:
        calidad = 70  # Retesteo tiene más calidad que ruptura directa
        if slope > 0.3:     calidad += 10
        if pct_sobre_vwap < 0.5: calidad += 10  # Recién rebotó
        if vol_ratio >= 1.3: calidad += 5
        if slope > 0.6:     calidad += 5

        result.update({
            'tipo': 'B',
            'calidad': min(calidad, 100),
            'descripcion': f'RETESTEO VWAP | slope={slope:.2f}% | vol={vol_ratio:.1f}x | +{pct_sobre_vwap:.2f}% sobre VWAP'
        })
        return result

    result['descripcion'] = 'Sin setup VWAP válido'
    return result


def calcular_qty_por_riesgo(precio_entrada, sl_price, capital_usdt, riesgo_pct):
    """
    Regla del 1% del video:
    Tamaño de posición = (Capital × Riesgo%) / (Entrada - SL)
    Así, si el SL se activa, la pérdida es exactamente el % configurado.
    Retorna cantidad en unidades del activo.
    """
    if sl_price >= precio_entrada:
        return 0, 0
    riesgo_usdt    = capital_usdt * (riesgo_pct / 100)
    distancia_sl   = precio_entrada - sl_price
    distancia_pct  = distancia_sl / precio_entrada * 100
    qty_usdt       = riesgo_usdt / (distancia_pct / 100)  # en USDT nocional
    return qty_usdt, distancia_pct


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
        if sym in self.blacklist:     return False, "blacklist"
        if score < self.opt_score:    return False, f"score {score:.0f}<{self.opt_score:.0f}"
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
# BOT PRINCIPAL v5.2
# ============================================================================

class LongBot:
    _opening = False

    def __init__(self):
        log.info("=" * 72)
        log.info("  BOT LONGS v5.2 — VWAP Whale Analytics Strategy")
        log.info(f"  Capital: ${POS_SIZE} | Riesgo/trade: {RISK_PCT}% | Apalancamiento: {LEVERAGE}x")
        log.info(f"  TP mín: {TP_MIN}% | SL: bajo VWAP -{SL_VWAP_MARGIN}% | RR mín: {MIN_RR}:1")
        log.info(f"  VWAP plano: <{VWAP_FLAT_PCT}% slope | Break mín: {VWAP_BREAK_MIN_PCT}%")
        log.info(f"  Entradas: RUPTURA (Tipo A) + RETESTEO (Tipo B)")
        log.info(f"  Salida: EMA25 cruce bajista (sin restricción de profit)")
        log.info(f"  FIX-HEDGE: Prevención doble dirección ON ✅")
        log.info("=" * 72)

        self.symbols      = []
        self.trades       = {}
        self._contracts   = {}
        self._cooldowns   = {}
        self._last_report = datetime.now() - timedelta(hours=3)
        self._btc_1h      = 0.0
        self._btc_ok      = True
        self._mode        = 'hedge'
        self._daily_pnl   = 0.0
        self._daily_date  = datetime.utcnow().date()
        self._cb_active   = False
        self._cb_until    = None
        self.learn        = Learning()
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
            f"<b>🤖 Bot LONGS v5.2 — VWAP Whale Analytics</b>\n"
            f"Capital: ${POS_SIZE} | Riesgo: {RISK_PCT}%/trade | {LEVERAGE}x\n"
            f"Entradas: Ruptura + Retesteo VWAP | Salida: EMA25\n"
            f"SL: bajo el VWAP (institucional)\n"
            f"✅ Sin doble dirección por símbolo\n"
            f"Posiciones recuperadas: {len(self.trades)}"
        )

    # ════════════════════════════════════════════════════════════════
    # SETUP
    # ════════════════════════════════════════════════════════════════

    def _connect(self) -> bool:
        global AUTO, ACCOUNT_EQUITY
        if not AUTO: return True
        if not API_KEY or not API_SECRET:
            log.error("❌ API keys no configuradas")
            AUTO = False; return False
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') == 0:
            b  = d.get('data', {})
            eq = float(b.get('equity', b.get('balance', 0)) or 0)
            if eq > 0:
                ACCOUNT_EQUITY = eq
                log.info(f"✅ BingX conectado | ${eq:.2f} USDT")
            else:
                log.info(f"✅ BingX conectado | ${b.get('equity','?')} USDT")
            return True
        log.error(f"❌ [{d.get('code')}]: {d.get('msg')}")
        AUTO = False; return False

    def _detect_mode(self):
        try:
            d = api('GET', '/openApi/swap/v2/user/positions', {'symbol': 'BTC-USDT'})
            for p in (d.get('data') or []):
                side = str(p.get('positionSide', '')).upper()
                if side in ('LONG', 'SHORT'):
                    self._mode = 'hedge'; log.info("  Modo: HEDGE"); return
                if side == 'BOTH':
                    self._mode = 'oneway'; log.info("  Modo: ONE-WAY"); return
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

    # ════════════════════════════════════════════════════════════════
    # FIX-HEDGE: Consulta posiciones reales en el exchange
    # ════════════════════════════════════════════════════════════════

    def _get_exchange_positions(self, symbol=None):
        params = {}
        if symbol: params['symbol'] = symbol
        d = api('GET', '/openApi/swap/v2/user/positions', params)
        result = defaultdict(lambda: {'long': 0.0, 'short': 0.0})
        for p in (d.get('data') or []):
            try:
                amt  = float(p.get('positionAmt', 0) or 0)
                sym  = p.get('symbol', '')
                side = str(p.get('positionSide', '')).upper()
                if not sym or abs(amt) == 0: continue
                if side == 'LONG'  or (side == 'BOTH' and amt > 0): result[sym]['long']  = abs(amt)
                elif side == 'SHORT' or (side == 'BOTH' and amt < 0): result[sym]['short'] = abs(amt)
            except: continue
        return result

    def _has_any_position(self, symbol) -> bool:
        pos = self._get_exchange_positions(symbol)
        return pos[symbol]['long'] > 0 or pos[symbol]['short'] > 0

    def _order_close_short(self, sym, qty):
        params = {'symbol': sym, 'side': 'BUY', 'type': 'MARKET', 'quantity': str(qty)}
        if self._mode == 'hedge': params['positionSide'] = 'SHORT'
        else: params['reduceOnly'] = 'true'
        return api('POST', '/openApi/swap/v2/trade/order', params)

    def _recover(self):
        if not AUTO: return
        all_positions = self._get_exchange_positions()
        n_recovered = 0; n_closed_short = 0

        for sym, sides in all_positions.items():
            if sides['short'] > 0:
                log.warning(f"  ⚠️  SHORT huérfano: {sym} qty={sides['short']:.4f} → cerrando")
                d = self._order_close_short(sym, sides['short'])
                if d.get('code') == 0:
                    log.info(f"  ✅ SHORT cerrado: {sym}"); n_closed_short += 1
                    self._tg(f"<b>🔧 SHORT huérfano cerrado</b>\n{sym}")
                else:
                    log.error(f"  ❌ No se pudo cerrar SHORT {sym}: {d.get('msg')}")
                time.sleep(0.5)

            if sides['long'] > 0 and sym not in self.trades:
                d2 = api('GET', '/openApi/swap/v2/user/positions', {'symbol': sym})
                entry = 0.0
                for p in (d2.get('data') or []):
                    side = str(p.get('positionSide','')).upper()
                    amt  = float(p.get('positionAmt',0) or 0)
                    if (side=='LONG' and abs(amt)>0) or (side=='BOTH' and amt>0):
                        entry = float(p.get('avgPrice') or p.get('entryPrice') or 0); break
                if entry <= 0: continue

                # SL recuperado: bajo el precio de entrada × margen
                sl_rec = entry * (1 - (SL_VWAP_MARGIN + 0.5) / 100)
                self.trades[sym] = {
                    'entry': entry, 'qty': sides['long'], 'usdt': POS_SIZE,
                    'tp': entry * (1 + TP_MIN / 100),
                    'sl': sl_rec,
                    'tp_pct': TP_MIN, 'sl_pct': SL_VWAP_MARGIN,
                    'sl_tipo': 'recuperado',
                    'highest': entry, 'opened': datetime.now(),
                    'score': 0, 'ema25': entry, 'vwap': entry,
                    'entrada_tipo': 'R',   # Recuperado
                }
                n_recovered += 1
                log.info(f"  ♻️  LONG recuperado: {sym} @ ${entry:.6f}")

        log.info(f"  Recuperadas: {n_recovered} LONG | SHORTs cerrados: {n_closed_short}")

    def _scan_orphan_shorts(self):
        if not AUTO: return
        all_positions = self._get_exchange_positions()
        for sym, sides in all_positions.items():
            if sides['short'] > 0:
                log.warning(f"  ⚠️  SHORT huérfano (scan): {sym} → cerrando")
                d = self._order_close_short(sym, sides['short'])
                if d.get('code') == 0:
                    self._tg(f"<b>🔧 SHORT huérfano cerrado (scan)</b>\n{sym}")
                time.sleep(0.3)

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

    def _update_equity(self):
        """Actualiza el equity de cuenta para la regla del 1%."""
        global ACCOUNT_EQUITY
        d = api('GET', '/openApi/swap/v2/user/balance')
        if d.get('code') == 0:
            b  = d.get('data', {})
            eq = float(b.get('equity', 0) or b.get('balance', 0))
            if eq > 0:
                ACCOUNT_EQUITY = eq

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
    # ANÁLISIS v5.2 — Fiel a la estrategia del video
    # ════════════════════════════════════════════════════════════════

    def analyze(self, symbol):
        if symbol in self.trades: return None
        if not self._cd_ok(symbol): return None
        if datetime.utcnow().hour in SKIP_HOURS: return None
        if not self._btc_ok: return None
        if self._cb_active: return None

        # ── Datos 5M (señal principal) ──────────────────────────────
        c5, h5, l5, v5, o5 = self._klines(symbol, '5m', 120)
        if not c5 or len(c5) < 70: return None

        tk = self._ticker(symbol)
        if not tk or tk['price'] <= 0: return None
        price     = tk['price']
        change_24 = tk['change']

        # ── Contexto 1H (filtro del video) ──────────────────────────
        # "Alineación de Temporalidades: usar el 1H para confirmar
        #  la tendencia antes de entrar en 5M" — video
        c1h, h1h, l1h, v1h, _ = self._klines(symbol, '1h', 50)
        trend_1h = 0; rsi_1h = 50.0
        if c1h and len(c1h) >= 25:
            e9_1h   = ema(c1h, 9)
            e21_1h  = ema(c1h, 21)
            rsi_1h  = rsi(c1h, 14)
            vwap_1h = calc_vwap(c1h, h1h, l1h, v1h, 30)
            if e9_1h > e21_1h and c1h[-1] > vwap_1h:
                trend_1h = 1    # 1H alcista ✅
            elif e9_1h < e21_1h and c1h[-1] < vwap_1h:
                trend_1h = -1   # 1H bajista ❌

        # Filtro duro: 1H bajista = no operar longs
        if trend_1h == -1:
            return None

        # ── Indicadores 5M ──────────────────────────────────────────
        e25     = ema(c5, 25)
        e9_5m   = ema(c5, 9)
        rsi_v   = rsi(c5, 14)
        atr_v   = atr_calc(h5, l5, c5, 14)
        atr_pct = atr_v / price * 100 if price > 0 else 0

        # ── Setup VWAP (lógica del video) ────────────────────────────
        setup = analizar_setup_vwap(c5, h5, l5, v5, o5)

        if not setup['tipo']:
            return None   # Sin setup = sin trade

        vwap_val  = setup['vwap']
        sl_price  = setup['sl_price']
        sl_pct    = (price - sl_price) / price * 100

        # ── TP dinámico basado en ATR y RR mínimo ───────────────────
        tp_atr_pct = atr_pct * ATR_TP_M
        tp_pct     = max(TP_MIN, sl_pct * MIN_RR, tp_atr_pct, TP_MIN_FEE)
        rr         = tp_pct / sl_pct if sl_pct > 0 else 0

        # Filtrar si el RR es demasiado bajo
        if rr < MIN_RR * 0.8:
            return None

        # ── Filtros adicionales ──────────────────────────────────────
        if atr_pct < 0.15:   return None  # Volatilidad mínima
        if rsi_v > 75:       return None  # RSI sobrecomprado extremo
        if change_24 > 20.0: return None  # Pump extremo
        if price < e25 * 0.99: return None  # Bajo la EMA25 (tendencia rota)

        # ── SCORING v5.2 ─────────────────────────────────────────────
        score   = 0
        reasons = []

        # Setup VWAP — señal principal (0-50)
        base_calidad = setup['calidad']
        score += int(base_calidad * 0.5)
        tipo_label = "RUPTURA" if setup['tipo'] == 'A' else "RETESTEO"
        reasons.append(f"{tipo_label}({base_calidad:.0f}%)")

        # Contexto 1H (0-20)
        if trend_1h == 1:
            score += 20; reasons.append("1H↑(20)")
        # trend_1h == -1 ya filtrado arriba

        # EMA25 alineada (0-15)
        if price > e25 and e9_5m > e25:
            score += 15; reasons.append("EMA25↑(15)")
        elif price > e25:
            score += 8;  reasons.append("EMA25(8)")

        # RSI óptimo (0-15)
        if 40 <= rsi_v <= 60:
            score += 15; reasons.append(f"RSI{rsi_v:.0f}(15)")
        elif rsi_v < 40:
            score += 10; reasons.append(f"RSIsobrev{rsi_v:.0f}(10)")
        elif rsi_v < 70:
            score += 5;  reasons.append(f"RSI{rsi_v:.0f}(5)")

        # Volumen ruptura (0-12)
        vr = setup['vol_ratio']
        if vr >= 2.0:   score += 12; reasons.append(f"Vol{vr:.1f}x(12)")
        elif vr >= 1.4: score += 7;  reasons.append(f"Vol{vr:.1f}x(7)")

        # BTC alcista (0-8)
        if self._btc_1h > 1.0:
            score += 8; reasons.append(f"BTC+{self._btc_1h:.1f}%(8)")
        elif self._btc_1h > 0.3:
            score += 4; reasons.append(f"BTC+{self._btc_1h:.1f}%(4)")

        # RSI 1H favorable (0-10)
        if rsi_1h < 40:  score += 10; reasons.append(f"RSI1H{rsi_1h:.0f}(10)")
        elif rsi_1h < 55: score += 5; reasons.append(f"RSI1H{rsi_1h:.0f}(5)")

        # Retesteo suma extra por ser mayor calidad (0-10)
        if setup['tipo'] == 'B':
            score += 10; reasons.append("Retest+10")

        # ── Aprendizaje ──────────────────────────────────────────────
        ok, reason = self.learn.ok(symbol, score)
        if not ok: return None

        if score >= self.learn.opt_score:
            return {
                'price':        price,
                'change':       change_24,
                'score':        score,
                'score_min':    self.learn.opt_score,
                'rsi':          rsi_v,
                'rsi_1h':       rsi_1h,
                'vol_ratio':    vr,
                'atr_pct':      atr_pct,
                'tp_pct':       round(tp_pct, 2),
                'sl_pct':       round(sl_pct, 2),
                'sl_price':     round(sl_price, 8),   # ← SL bajo el VWAP
                'rr':           round(rr, 2),
                'vwap':         vwap_val,
                'slope':        setup['slope'],
                'entrada_tipo': setup['tipo'],         # A=Ruptura, B=Retesteo
                'calidad':      base_calidad,
                'ema25':        e25,
                'trend_1h':     trend_1h,
                'reasons':      ' | '.join(reasons),
                'descripcion':  setup['descripcion'],
            }
        return None

    # ════════════════════════════════════════════════════════════════
    # GESTIÓN POSICIONES
    # ════════════════════════════════════════════════════════════════

    def _set_lev(self, symbol):
        for side in ('LONG', 'SHORT'):
            try:
                api('POST', '/openApi/swap/v2/trade/leverage',
                    {'symbol': symbol, 'side': side, 'leverage': str(LEVERAGE)})
            except Exception as e:
                log.debug(f"  lev {side}: {e}")

    def _calc_qty(self, symbol, price, sl_price=None):
        """
        v5.2: Calcula qty según la Regla del 1%:
        Pérdida máxima = RISK_PCT% de la cuenta.
        Si no hay sl_price, usa POS_SIZE × LEVERAGE como fallback.
        """
        info  = self._contracts.get(symbol, {'step':1,'prec':2,'ctval':1})
        step  = max(float(info.get('step',1)), 1e-6)
        prec  = int(info.get('prec', 2))
        ctval = max(float(info.get('ctval',1)), 1e-9)
        ppc   = price * ctval

        if ppc <= 0: return None, 0

        if sl_price and sl_price < price:
            notional_usdt, _ = calcular_qty_por_riesgo(
                price, sl_price, ACCOUNT_EQUITY, RISK_PCT)
            # Aplicar límite máximo de posición
            notional_usdt = min(notional_usdt, POS_SIZE * LEVERAGE)
            notional_usdt = max(notional_usdt, MIN_TRADE)
        else:
            notional_usdt = max(POS_SIZE * LEVERAGE, MIN_TRADE)

        qty = math.ceil((notional_usdt / ppc) / step) * step
        qty = round(qty, prec)
        val = qty * ppc

        for _ in range(200):
            if val >= MIN_TRADE: break
            qty += step; qty = round(qty, prec); val = qty * ppc

        return (qty, round(val, 4)) if val >= MIN_TRADE else (None, 0)

    def _order(self, sym, side, qty, otype='MARKET', price=None, stop_price=None):
        """
        FIX-HEDGE-04: SELL siempre cierra LONG (positionSide=LONG en hedge).
        Nunca puede abrir un SHORT desde este método.
        """
        params = {'symbol': sym, 'side': side.upper(),
                  'type': otype, 'quantity': str(qty)}
        if self._mode == 'hedge':
            params['positionSide'] = 'LONG'
        else:
            if side.upper() == 'SELL':
                params['reduceOnly'] = 'true'
        if price:       params['price']     = str(round(price, 8)); params['timeInForce'] = 'GTC'
        if stop_price:  params['stopPrice'] = str(round(stop_price, 8))
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

    def _place_tp_sl(self, sym, qty, tp_price, sl_price):
        """Coloca TP y SL. El SL va BAJO EL VWAP (ya calculado en analyze)."""
        tp_ok = sl_ok = False
        d = self._order(sym, 'SELL', qty, 'TAKE_PROFIT_MARKET', stop_price=tp_price)
        tp_ok = d.get('code') == 0
        log.info(f"  {'✅' if tp_ok else '❌'} TP @ ${tp_price:.6f}")
        time.sleep(0.3)
        d = self._order(sym, 'SELL', qty, 'STOP_MARKET', stop_price=sl_price)
        sl_ok = d.get('code') == 0
        if not sl_ok:
            d = self._order(sym, 'SELL', qty, 'STOP',
                            price=sl_price*0.999, stop_price=sl_price)
            sl_ok = d.get('code') == 0
        log.info(f"  {'✅' if sl_ok else '❌'} SL @ ${sl_price:.6f} (bajo VWAP)")
        return tp_ok, sl_ok

    def open_trade(self, sym, sig):
        if not AUTO or sym in self.trades: return False
        if LongBot._opening or len(self.trades) >= MAX_TRADES: return False

        # FIX-HEDGE-01: Verificar en exchange
        if self._has_any_position(sym):
            log.warning(f"  ⛔ {sym} ya tiene posición en exchange — omitiendo")
            return False

        LongBot._opening = True
        try:
            return self._open(sym, sig)
        finally:
            LongBot._opening = False

    def _open(self, sym, sig):
        price    = sig['price']
        sl_price = sig['sl_price']
        tipo_txt = "🔴 RUPTURA" if sig['entrada_tipo'] == 'A' else "🟢 RETESTEO"

        log.info(f"\n  🎯 LONG {sym} [{tipo_txt}] | Score:{sig['score']:.0f} "
                 f"| RR:{sig['rr']:.2f}:1 | Calidad:{sig['calidad']:.0f}%")
        log.info(f"  {sig['descripcion']}")
        log.info(f"  Entrada:${price:.6f} | VWAP:${sig['vwap']:.6f} | SL:${sl_price:.6f}")

        self._set_lev(sym)
        time.sleep(0.2)

        qty, notional = self._calc_qty(sym, price, sl_price)
        if not qty: return False

        # Entrada con limit ligeramente bajo precio para mejor fill
        limit_p = round(price * (1 - 0.05/100), 8)
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

        # Recalcular TP desde precio real de entrada
        tp_price = fill_price * (1 + sig['tp_pct'] / 100)

        # SL sigue bajo el VWAP (no cambia con el fill)
        sl_final = sl_price

        tp_ok, sl_ok = self._place_tp_sl(sym, filled_qty, tp_price, sl_final)
        if not sl_ok:
            time.sleep(2)
            tp_ok, sl_ok = self._place_tp_sl(sym, filled_qty, tp_price, sl_final)
        if not sl_ok:
            log.error("  ❌ SL crítico — cerrando posición")
            self._order(sym, 'SELL', filled_qty, 'MARKET')
            return False

        sl_pct_real = (fill_price - sl_final) / fill_price * 100
        rr_real     = sig['tp_pct'] / sl_pct_real if sl_pct_real > 0 else 0

        self.trades[sym] = {
            'entry':       fill_price,
            'qty':         filled_qty,
            'usdt':        POS_SIZE,
            'tp':          tp_price,
            'sl':          sl_final,
            'sl_vwap':     sig['vwap'],   # Nivel VWAP de referencia del SL
            'tp_pct':      sig['tp_pct'],
            'sl_pct':      sl_pct_real,
            'highest':     fill_price,
            'opened':      datetime.now(),
            'score':       sig['score'],
            'ema25':       sig['ema25'],
            'vwap':        sig['vwap'],
            'entrada_tipo': sig['entrada_tipo'],
        }
        self.stats['exec']  += 1
        self.stats['fees']  += notional * FEE

        self._tg(
            f"<b>🟢 LONG {tipo_txt}</b> — <b>{sym}</b>\n"
            f"Score: {sig['score']:.0f} | Calidad: {sig['calidad']:.0f}% | RR: {rr_real:.2f}:1\n"
            f"📍 Entrada:  ${fill_price:.6f}\n"
            f"📊 VWAP:     ${sig['vwap']:.6f} (slope: {sig['slope']:+.2f}%)\n"
            f"🎯 TP:       ${tp_price:.6f} (+{sig['tp_pct']:.2f}%)\n"
            f"🛑 SL (VWAP): ${sl_final:.6f} (-{sl_pct_real:.2f}%)\n"
            f"📐 EMA25:    ${sig['ema25']:.6f}\n"
            f"1H: {'🟢 alcista' if sig['trend_1h']==1 else '⚪ neutral'} | "
            f"BTC: {self._btc_1h:+.2f}%"
        )
        return True

    def close_trade(self, sym, exit_price, reason):
        if sym not in self.trades: return False
        t = self.trades[sym]
        self._order(sym, 'SELL', t['qty'], 'MARKET')

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
        tipo  = t.get('entrada_tipo', '?')

        log.info(f"  {emoji} {reason} | ${net:+.4f} ({pct:+.1f}%) | {mins}min | WR:{wr:.0f}% | [{tipo}]")
        self._set_cd(sym, 'TP' if 'PROFIT' in reason else 'SL')
        self._tg(
            f"<b>{emoji} LONG CERRADO — {reason}</b>\n"
            f"<b>{sym}</b> | Entrada: {'Ruptura' if tipo=='A' else 'Retesteo' if tipo=='B' else tipo} | {mins}min\n"
            f"${t['entry']:.6f} → ${exit_price:.6f}\n"
            f"SL estaba bajo VWAP: ${t['sl_vwap']:.6f}\n"
            f"PnL: ${net:+.4f} ({pct:+.1f}%)\n"
            f"<b>Total: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}%</b>"
        )
        if self.stats['closed'] % 5 == 0: self.learn.save()
        del self.trades[sym]
        return True

    # ════════════════════════════════════════════════════════════════
    # MONITOR — Salida por EMA25 (salida maestra del video)
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
                c5, *_ = self._klines(sym, '5m', 30)
                if c5:
                    t['ema25'] = ema(c5, 25)

                # ── SALIDA MAESTRA: EMA25 cruce bajista ──────────────
                # "Salidas Profesionales: la EMA25 te dice exactamente
                #  cuándo cerrar tu operación" — video
                # v5.2: Sin restricción de profit mínimo (salida siempre)
                if cur < t['ema25']:
                    if c5 and c5[-1] < t['ema25'] and c5[-2] < t['ema25']:
                        # 2 velas consecutivas bajo la EMA25 = salida confirmada
                        self.close_trade(sym, cur, "EMA25 CRUCE")
                        continue

                # ── Trailing stop (bloquea ganancia) ─────────────────
                if cur > t['highest']:
                    t['highest'] = cur
                    if pct >= 2.5:
                        # Proteger 55% de la ganancia acumulada
                        locked = t['entry'] + (cur - t['entry']) * 0.55
                        if locked > t['sl']:
                            t['sl'] = locked
                            log.info(f"  📈 Trail {sym}: SL→${locked:.6f}")

                # ── TP / SL fijos ─────────────────────────────────────
                if cur >= t['tp']:
                    self.close_trade(sym, cur, "TAKE PROFIT")
                elif cur <= t['sl']:
                    self.close_trade(sym, cur, "STOP LOSS (bajo VWAP)")

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
            self._cb_active  = False
            self._cb_until   = None
            self.learn.streak = 0
            log.info("📅 Nuevo día — equity actualizado")
            self._update_equity()

    def _circuit_check(self) -> bool:
        self._daily_reset()
        if self._cb_active:
            if self._cb_until and datetime.utcnow() > self._cb_until:
                self._cb_active = False
                self._daily_pnl = 0.0
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
            tipo = t.get('entrada_tipo','?')
            pos += f"  📌 {sym} [{tipo}]: {pct:+.2f}% | EMA25:${t['ema25']:.4f} | SL:${t['sl']:.4f}\n"
        self._tg(
            f"<b>📊 Reporte LONGS v5.2</b>\n"
            f"PnL: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}% | {total} trades\n"
            f"Día: ${self._daily_pnl:+.4f} (límite -${CB_USDT})\n"
            f"Equity: ${ACCOUNT_EQUITY:.2f} | Fees: ${self.stats['fees']:.4f}\n"
            f"Abiertos: {len(self.trades)}/{MAX_TRADES} | BTC: {self._btc_1h:+.2f}%\n"
            f"Circuit: {'🔒' if self._cb_active else '🔓'} | Score mín: {self.learn.opt_score:.0f}\n"
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
        log.info("\n🚀 Bot LONGS v5.2 — VWAP Whale Analytics arrancado\n")
        iteration       = 0
        last_sym_refr   = 0
        last_ltv_check  = 0
        last_hedge_scan = 0
        last_equity_upd = 0

        while True:
            try:
                iteration += 1
                self._daily_reset()

                if time.time() - last_sym_refr > 600:
                    self._refresh_symbols(); last_sym_refr = time.time()

                if time.time() - last_ltv_check > 300:
                    self._check_ltv(); last_ltv_check = time.time()

                if time.time() - last_hedge_scan > 600:
                    self._scan_orphan_shorts(); last_hedge_scan = time.time()

                if time.time() - last_equity_upd > 1800:
                    self._update_equity(); last_equity_upd = time.time()

                self._update_btc()

                if self._circuit_check():
                    log.warning("  🔒 Circuit breaker activo")
                    await asyncio.sleep(INTERVAL); continue

                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0

                log.info(f"\n{'='*72}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"Abiertos:{len(self.trades)}/{MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.4f} | WR:{wr:.0f}%")
                log.info(f"  BTC:{self._btc_1h:+.2f}% {'🟢' if self._btc_ok else '🔴'} | "
                         f"Equity:${ACCOUNT_EQUITY:.2f} | Score mín:{self.learn.opt_score:.0f}")
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
                            tipo_icon = "🔴" if sig['entrada_tipo'] == 'A' else "🟢"
                            log.info(
                                f"  💡 {tipo_icon} {sym} | "
                                f"{'RUPTURA' if sig['entrada_tipo']=='A' else 'RETESTEO'} | "
                                f"Score:{sig['score']:.0f} | RR:{sig['rr']:.2f}:1 | "
                                f"SL:${sig['sl_price']:.4f} (VWAP-{SL_VWAP_MARGIN}%)"
                            )
                            if self.open_trade(sym, sig):
                                await asyncio.sleep(3)
                        if (i+1) % 15 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)}")
                        await asyncio.sleep(0.12)
                    log.info(f"  ✅ Scan: {found} señales (A=Ruptura, B=Retesteo)")
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
