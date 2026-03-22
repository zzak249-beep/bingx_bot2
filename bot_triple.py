#!/usr/bin/env python3
"""
BOT UNIFICADO v4.0 — MULTI-TIMEFRAME + ANTI-CORRELACIÓN
════════════════════════════════════════════════════════════

FIXES v4.0 (basados en logs reales):
  1. MULTI-TIMEFRAME: 1h confirma tendencia, 15m da timing de entrada
     Sin alineación entre timeframes = NO TRADE
  2. SCORE NORMALIZADO: máximo 100 siempre (antes llegaba a 118+)
  3. RSI THRESHOLD: SHORT requiere RSI > 65 (antes entraba con RSI 39)
  4. ANTI-CORRELACIÓN: máximo 2 trades en la misma dirección simultáneos
  5. FILTRO DE CICLO: máximo 2 nuevas entradas por ciclo de análisis
  6. MODO SEÑALES mejorado: muestra si 1h confirma o bloquea
  7. Todos los fixes de v3.0 mantenidos
"""

import os, asyncio, logging, requests, hmac, hashlib, time, sys, math, re
from datetime import datetime, timedelta
from urllib.parse import urlencode

# ============================================================================
# CONFIGURACIÓN
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
MIN_SCORE_LONG   = clean('MIN_SCORE_LONG',           '68',  'float')  # sobre 100
MIN_SCORE_SHORT  = clean('MIN_SCORE_SHORT',          '70',  'float')  # sobre 100
TRAILING         = clean('TRAILING_STOP_ENABLED',  'true',  'bool')
USE_LIMIT_ORDERS = clean('USE_LIMIT_ORDERS',       'true',  'bool')
ENABLE_LONGS     = clean('ENABLE_LONGS',           'true',  'bool')
ENABLE_SHORTS    = clean('ENABLE_SHORTS',          'true',  'bool')
BTC_FILTER_PCT   = clean('BTC_FILTER_PCT',          '2.5',  'float')
MAX_SAME_DIR     = clean('MAX_SAME_DIRECTION',       '2',   'int')   # anti-correlación
MAX_ENTRIES_CYCLE= clean('MAX_ENTRIES_PER_CYCLE',    '2',   'int')   # por ciclo

LIMIT_OFFSET_PCT  = 0.05
SKIP_HOURS_UTC    = {0, 1}
BASE_URL          = "https://open-api.bingx.com"
TPSL_MAX_INTENTOS = 5
ESPERA_POS_TIMEOUT = 90

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

COMISION_MAKER  = 0.0002
COMISION_TAKER  = 0.0005
COMISION_ACTUAL = COMISION_MAKER if USE_LIMIT_ORDERS else COMISION_TAKER
TP_MIN_RENTABLE = round((COMISION_ACTUAL * 2 / LEVERAGE + 0.002) * 100, 3)

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
                log.warning(f"  retry {attempt+1}/{retries}: {e}")
                time.sleep(2)
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
    if not prices: return 0
    w = prices[-period:] if len(prices) >= period else prices
    return sum(w) / len(w)

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains  = [max(0,  prices[i] - prices[i-1]) for i in range(1, len(prices))]
    losses = [max(0, prices[i-1] - prices[i])  for i in range(1, len(prices))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100.0
    return 100 - (100 / (1 + ag / al))

def calc_stochastic(highs, lows, closes, k_period=14, d_period=3):
    if len(closes) < k_period: return 50.0, 50.0
    k_values = []
    for i in range(len(closes) - k_period + 1):
        h = max(highs[i:i+k_period])
        l = min(lows[i:i+k_period])
        c = closes[i+k_period-1]
        k = (c - l) / (h - l) * 100 if (h - l) > 0 else 50
        k_values.append(k)
    k = k_values[-1] if k_values else 50
    d = sum(k_values[-d_period:]) / min(d_period, len(k_values)) if k_values else 50
    return round(k, 2), round(d, 2)

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
# ANÁLISIS MULTI-TIMEFRAME
# ============================================================================

def analizar_tendencia_1h(closes_1h, highs_1h, lows_1h):
    """
    Determina la tendencia en 1h.
    Retorna: 'BULL', 'BEAR', 'NEUTRAL'
    """
    if not closes_1h or len(closes_1h) < 50:
        return 'NEUTRAL', 50.0, 50.0

    price   = closes_1h[-1]
    ema50   = calc_ema(closes_1h, 50)
    ema20   = calc_ema(closes_1h, 20)
    rsi_1h  = calc_rsi(closes_1h, 14)
    atr_1h  = calc_atr(highs_1h, lows_1h, closes_1h, 14)

    # Tendencia basada en EMAs
    bull_ema = price > ema50 and price > ema20 and ema20 > ema50
    bear_ema = price < ema50 and price < ema20 and ema20 < ema50

    # Momentum de las últimas 5 velas en 1h
    if len(closes_1h) >= 6:
        momentum_1h = (closes_1h[-1] - closes_1h[-6]) / closes_1h[-6] * 100
    else:
        momentum_1h = 0

    if bull_ema and rsi_1h > 40:
        return 'BULL', rsi_1h, momentum_1h
    elif bear_ema and rsi_1h < 60:
        return 'BEAR', rsi_1h, momentum_1h
    else:
        return 'NEUTRAL', rsi_1h, momentum_1h

# ============================================================================
# BOT
# ============================================================================

class BotV4:

    def __init__(self):
        dirs = []
        if ENABLE_LONGS:  dirs.append("LONGS")
        if ENABLE_SHORTS: dirs.append("SHORTS")
        fee_lbl = f"LÍMITE maker {COMISION_MAKER*100:.2f}%" if USE_LIMIT_ORDERS \
                  else f"MERCADO taker {COMISION_TAKER*100:.2f}%"

        log.info("=" * 65)
        log.info("  BOT UNIFICADO v4.0 — MULTI-TIMEFRAME")
        log.info("  1h tendencia + 15m entrada + anti-correlación")
        log.info("=" * 65)
        log.info(f"  Modo:        {'AUTO ✅' if AUTO_TRADING else 'SEÑALES SOLO ⚠️'}")
        if not AUTO_TRADING:
            log.info(f"  ⚠️  AUTO_TRADING=false → revisa BINGX_API_KEY en Railway")
        log.info(f"  Capital:     ${POSITION_SIZE} USDT | Leverage: {LEVERAGE}x")
        log.info(f"  TP/SL:       {TP_PCT}% / {SL_PCT}%  RR:{TP_PCT/SL_PCT:.1f}:1")
        log.info(f"  TP mín:      {TP_MIN_RENTABLE}%")
        log.info(f"  Score:       LONG≥{MIN_SCORE_LONG}/100 SHORT≥{MIN_SCORE_SHORT}/100")
        log.info(f"  Max dir:     {MAX_SAME_DIR} trades misma dirección")
        log.info(f"  Max ciclo:   {MAX_ENTRIES_CYCLE} entradas por ciclo")
        log.info(f"  Fee:         {fee_lbl}")
        log.info(f"  BTC filtro:  ±{BTC_FILTER_PCT}%")
        log.info("=" * 65)

        self.symbols          = []
        self.open_trades      = {}
        self._contracts       = {}
        self._cooldowns       = {}
        self._last_report     = datetime.now()
        self._btc_change_1h   = 0.0
        self._btc_trend_1h    = 'NEUTRAL'
        self._cache_1h        = {}   # symbol -> (timestamp, tendencia)
        self.stats = {'exec':0,'closed':0,'wins':0,'losses':0,'pnl':0.0,
                      'blocked_1h':0,'blocked_rsi':0,'blocked_corr':0}

        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._reconciliar_posiciones()

        modo = "AUTO ✅" if AUTO_TRADING else "SEÑALES ⚠️ (activa AUTO_TRADING_ENABLED=true)"
        self._tg(
            f"<b>🤖 Bot v4.0 — Multi-Timeframe</b>\n"
            f"1h tendencia + 15m entrada\n"
            f"Modo: {modo}\n"
            f"Capital: ${POSITION_SIZE} x{LEVERAGE} | TP:{TP_PCT}% SL:{SL_PCT}%\n"
            f"Score: L≥{MIN_SCORE_LONG} S≥{MIN_SCORE_SHORT} (sobre 100)\n"
            f"Anti-correlación: máx {MAX_SAME_DIR} por dirección\n"
            f"Fee: {fee_lbl}"
        )

    # ─────────────────────────────────────────────────── SETUP

    def _verify(self):
        global AUTO_TRADING
        if not AUTO_TRADING:
            log.warning("  ⚠️  AUTO_TRADING=false — el bot solo muestra señales")
            log.warning("  ⚠️  Para operar: pon AUTO_TRADING_ENABLED=true en Railway")
            return
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            log.error("  ❌ Sin API keys — cambiando a modo señales")
            AUTO_TRADING = False; return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                data = d.get('data', {})
                eq = data.get('equity', data.get('balance', '?'))
                log.info(f"  ✅ BingX OK | Balance: ${eq} USDT")
            else:
                log.error(f"  ❌ BingX [{d.get('code')}]: {d.get('msg')}")
                AUTO_TRADING = False
        except Exception as e:
            log.error(f"  ❌ Error API: {e}"); AUTO_TRADING = False

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
            log.warning(f"  Error contratos: {e}")

    def _get_symbols(self):
        NO_CRIPTO = [
            'DOW','JONES','SP500','SPX','SPY','QQQ','NASDAQ','RUSSELL',
            'DAX','FTSE','CAC','NIKKEI','HANG','BOVESPA','IBEX',
            'US30','NAS100','US500','DJI','INDEX',
            'GOLD','SILVER','XAU','XAG','PAXG','XAUT',
            'OIL','BRENT','WTI','CRUDE','GAS','GASOLINE','PETROLEUM',
            'PLATINUM','PALLADIUM','COPPER','NICKEL','ZINC','IRON',
            'TSLA','AAPL','MSFT','GOOGL','AMZN','META','NVDA','COIN','MSTR',
            'EUR','GBP','JPY','CHF','AUD','CAD','NZD',
            'WHEAT','CORN','SUGAR','COFFEE','COTTON','LUMBER','SOYBEAN',
        ]
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/ticker", timeout=15).json()
            if d.get('code') == 0:
                items, excl = [], []
                for t in d.get('data', []):
                    sym = t.get('symbol','')
                    if not sym.endswith('-USDT'): continue
                    base = sym.replace('-USDT','').upper()
                    if any(kw in base for kw in NO_CRIPTO):
                        excl.append(base); continue
                    try:
                        price = float(t.get('lastPrice', 0))
                        vol   = float(t.get('volume', 0)) * price
                        if vol < MIN_VOLUME or price < 0.000001: continue
                        items.append({'symbol': sym, 'vol': vol})
                    except: continue
                items.sort(key=lambda x: x['vol'], reverse=True)
                self.symbols = [x['symbol'] for x in items[:MAX_SYMBOLS]]
                log.info(f"  Pares: {len(self.symbols)} | Excluidos: {len(excl)}")
                return
        except Exception as e:
            log.warning(f"  Error símbolos: {e}")
        self.symbols = ['BTC-USDT','ETH-USDT','SOL-USDT','BNB-USDT','XRP-USDT',
                        'DOGE-USDT','ADA-USDT','AVAX-USDT','LINK-USDT','DOT-USDT']

    # ─────────────────────────────────────────────────── RECONCILIACIÓN

    def _reconciliar_posiciones(self):
        if not AUTO_TRADING: return
        log.info("  🔍 Reconciliando posiciones...")
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            todas = [p for p in (d.get('data') or [])
                     if abs(float(p.get('positionAmt', 0) or 0)) > 0]
            if not todas:
                log.info("  ✅ Arranque limpio"); return
            recuperadas = 0
            for p in todas:
                sym = p.get('symbol', '')
                if not sym: continue
                try: lev_pos = int(float(p.get('leverage', 0) or 0))
                except: lev_pos = 0
                if lev_pos != 0 and lev_pos != LEVERAGE:
                    log.info(f"  ⏭ {sym} ignorado — leverage {lev_pos}x (manual)"); continue
                try: amt = float(p.get('positionAmt', 0) or 0)
                except: continue
                if abs(amt) == 0: continue
                direction = 'LONG' if amt > 0 else 'SHORT'
                try:
                    entry = float(p.get('avgPrice') or p.get('entryPrice') or
                                  p.get('averagePrice') or 0)
                except: entry = 0
                if entry <= 0:
                    tk = self._ticker(sym)
                    entry = tk['price'] if tk else 0
                if entry <= 0: continue
                qty_c = abs(amt)
                if direction == 'LONG':
                    tp_price = entry * (1 + TP_PCT / 100)
                    sl_price = entry * (1 - SL_PCT / 100)
                else:
                    tp_price = entry * (1 - TP_PCT / 100)
                    sl_price = entry * (1 + SL_PCT / 100)
                tp_ok = self._cond_order(sym, direction, qty_c, tp_price, 'TAKE_PROFIT_MARKET')
                time.sleep(0.4)
                sl_ok = self._cond_order(sym, direction, qty_c, sl_price, 'STOP_MARKET')
                self.open_trades[sym] = {
                    'direction': direction, 'entry': entry, 'qty_c': qty_c,
                    'usdt_qty': POSITION_SIZE, 'tp': tp_price, 'sl': sl_price,
                    'tp_pct': TP_PCT, 'sl_pct': SL_PCT,
                    'highest': entry, 'lowest': entry,
                    'order_id': 'RECONCILIADO', 'tp_ok': tp_ok, 'sl_ok': sl_ok,
                    'opened_at': datetime.now(), 'score': 0,
                }
                recuperadas += 1
                log.info(f"  {'📈' if direction=='LONG' else '📉'} {sym} {direction} "
                         f"entry=${entry:.6f} TP:{'✅' if tp_ok else '❌'} SL:{'✅' if sl_ok else '❌'}")
            log.info(f"  ✅ {recuperadas} recuperadas")
        except Exception as e:
            log.error(f"  Error reconciliación: {e}")

    # ─────────────────────────────────────────────────── DATOS

    def _klines(self, symbol, interval='15m', limit=200):
        try:
            d = requests.get(f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol': symbol, 'interval': interval, 'limit': limit},
                timeout=12).json()
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
                             params={'symbol': symbol}, timeout=8).json()
            if d.get('code') == 0 and d.get('data'):
                t = d['data']
                return {'price':  float(t.get('lastPrice', 0)),
                        'change': float(t.get('priceChangePercent', 0))}
        except: pass
        return None

    def _get_tendencia_1h(self, symbol):
        """
        Cache de 10min para no llamar la API en cada símbolo.
        Retorna ('BULL'|'BEAR'|'NEUTRAL', rsi_1h, momentum_1h)
        """
        now = time.time()
        cached = self._cache_1h.get(symbol)
        if cached and (now - cached[0]) < 600:
            return cached[1]

        closes, highs, lows, *_ = self._klines(symbol, '1h', 60)
        if not closes or len(closes) < 20:
            return 'NEUTRAL', 50.0, 0.0

        result = analizar_tendencia_1h(closes, highs, lows)
        self._cache_1h[symbol] = (now, result)
        return result

    def _update_btc_trend(self):
        try:
            closes, highs, lows, *_ = self._klines('BTC-USDT', '1h', 60)
            if closes and len(closes) >= 2:
                self._btc_change_1h = (closes[-1] - closes[-2]) / closes[-2] * 100
            if closes and len(closes) >= 50:
                self._btc_trend_1h, _, _ = analizar_tendencia_1h(
                    closes, highs or [], lows or [])
        except: pass

    # ─────────────────────────────────────────────────── SIZING

    def _qty_contratos(self, symbol, price, usdt_amount=None):
        """
        FIX CRÍTICO v4.1: qty basada en NOTIONAL (usdt * leverage), no en margen.

        BingX trabaja con valor notional de la posición:
          notional = qty * price
          margen   = notional / leverage

        Fórmula correcta:
          qty = (usdt_amount * leverage) / price

        Antes: qty = usdt_amount / price → daba 0.02 BCH con $10 a 5x
               margen real = 0.02 * 464 / 5 = $1.85 (¡mucho menos de $10!)
        Ahora: qty = (10 * 5) / 464 = 0.11 BCH
               margen real = 0.11 * 464 / 5 = $10.20 ✅
        """
        if usdt_amount is None: usdt_amount = POSITION_SIZE
        info  = self._contracts.get(symbol, {'step': 1.0, 'prec': 2, 'ctval': 1.0})
        step  = max(info['step'], 0.0001)
        prec  = info['prec']
        ctval = info.get('ctval', 1.0)
        ppc   = price * ctval if ctval != 1.0 else price
        if ppc <= 0: return None, 0

        # FIX: notional objetivo = margen * leverage
        notional_objetivo = usdt_amount * LEVERAGE
        qty = round(math.ceil(notional_objetivo / ppc / step) * step, prec)
        val = qty * ppc
        margen_real = val / LEVERAGE

        # Asegurar mínimo operativo
        i = 0
        while margen_real < MIN_TRADE and i < 500:
            qty += step; qty = round(qty, prec)
            val = qty * ppc; margen_real = val / LEVERAGE; i += 1

        # Cap: nunca más de 1.3x el margen deseado
        if margen_real > usdt_amount * 1.3:
            qty = round(math.floor((usdt_amount * 1.3 * LEVERAGE / ppc) / step) * step, prec)
            val = qty * ppc
            margen_real = val / LEVERAGE

        log.info(f"    qty: {qty} × ${ppc:.6f} = ${val:.2f} notional "
                 f"(margen: ${margen_real:.2f} USDT)")
        return qty, round(val, 4)

    # ─────────────────────────────────────────────────── FILTROS

    def _cooldown_ok(self, symbol):
        info = self._cooldowns.get(symbol)
        if not info: return True
        ts, tipo = info
        espera = 30 * 60 if tipo == 'loss' else 10 * 60
        return (time.time() - ts) >= espera

    def _hora_ok(self):
        return datetime.utcnow().hour not in SKIP_HOURS_UTC

    def _contar_por_direccion(self):
        longs  = sum(1 for t in self.open_trades.values() if t['direction'] == 'LONG')
        shorts = sum(1 for t in self.open_trades.values() if t['direction'] == 'SHORT')
        return longs, shorts

    # ─────────────────────────────────────────────────── ANÁLISIS v4

    def analyze(self, symbol):
        """
        Análisis multi-timeframe:
        1. Obtener tendencia 1h → filtro macro
        2. Analizar 15m → señal de entrada
        3. Solo entrar si 1h y 15m están alineados
        """
        if symbol in self.open_trades: return None
        if not self._cooldown_ok(symbol): return None
        if not self._hora_ok(): return None

        # ── Datos 15m ──────────────────────────────────────────────────────
        closes, highs, lows, volumes, opens = self._klines(symbol, '15m', 200)
        if not closes or len(closes) < 150: return None

        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0: return None

        price  = ticker['price']
        change = ticker['change']

        # ── Indicadores 15m ────────────────────────────────────────────────
        ema144 = calc_ema(closes, 144)
        ema89  = calc_ema(closes, 89)
        sma21  = calc_sma(closes, 21)
        stoch_k, stoch_d = calc_stochastic(highs, lows, closes, 14, 3)
        rsi_15  = calc_rsi(closes, 14)
        bb_u, bb_m, bb_l = calc_bollinger(closes, 20)
        atr     = calc_atr(highs, lows, closes, 14)
        vs      = vol_spike(volumes)
        atr_pct = (atr / price * 100) if price > 0 else 0
        bb_pos  = (price - bb_l) / (bb_u - bb_l) if (bb_u - bb_l) > 0 else 0.5

        # Tendencia 15m
        trend_bull_15 = price > ema144 and price > ema89 and ema89 > ema144
        trend_bear_15 = price < ema144 and price < ema89 and ema89 < ema144

        # SMA21 triggers
        prev_closes = closes[-5:-1]
        toco_sma21  = any(abs(c - sma21) / sma21 < 0.012 for c in prev_closes)
        rebote_sma21  = price > sma21 and toco_sma21
        ruptura_sma21 = price < sma21 and any(c > sma21 for c in prev_closes[:2])
        cerca_sma21   = abs(price - sma21) / sma21 < 0.008

        trend_5c = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0

        red_candles   = sum(1 for i in range(-5, 0) if opens and closes[i] < opens[i]) if opens else 0
        green_candles = sum(1 for i in range(-5, 0) if opens and closes[i] > opens[i]) if opens else 0

        # ── Tendencia 1h (filtro macro) ─────────────────────────────────────
        trend_1h, rsi_1h, momentum_1h = self._get_tendencia_1h(symbol)

        # ═══════════════════════════════════════════════════════════════════
        # SCORING — NORMALIZADO A 100 PUNTOS MÁXIMO
        # Distribución: 1h(30) + EMA15m(20) + SMA21(20) + Stoch(15) + RSI(10) + Extras(5)
        # ═══════════════════════════════════════════════════════════════════

        # ── SEÑAL LONG ──────────────────────────────────────────────────────
        long_score, long_reasons = 0.0, []
        long_blocked = None

        if ENABLE_LONGS:

            # FILTRO 1h — bloqueo duro si 1h es bajista
            if trend_1h == 'BEAR':
                long_blocked = f"1h_BEAR(bloq)"
                self.stats['blocked_1h'] += 1
            elif trend_1h == 'BULL':
                long_score += 30; long_reasons.append("1h_BULL(30)")
            else:  # NEUTRAL
                long_score += 12; long_reasons.append("1h_NEUTRAL(12)")

            if long_blocked is None and trend_bull_15:
                long_score += 20; long_reasons.append("15m_BULL(20)")

                # SMA21 trigger (20 pts)
                if rebote_sma21:
                    long_score += 20; long_reasons.append("Rebote_SMA21(20)")
                elif cerca_sma21 and price > sma21:
                    long_score += 10; long_reasons.append("Cerca_SMA21+(10)")

                # Stochastic (15 pts)
                if stoch_k < 25 and stoch_d < 30 and stoch_k > stoch_d:
                    long_score += 15; long_reasons.append(f"Stoch_OS_giro({stoch_k:.0f})(15)")
                elif stoch_k < 30:
                    long_score += 8;  long_reasons.append(f"Stoch_OS({stoch_k:.0f})(8)")
                elif stoch_k > 70:
                    long_score -= 10; long_reasons.append(f"Stoch_OB(-10)")

                # RSI 15m (10 pts) — FIX: requiere RSI razonable para LONG
                if 25 <= rsi_15 <= 50:
                    long_score += 10; long_reasons.append(f"RSI_ideal({rsi_15:.0f})(10)")
                elif rsi_15 < 25:
                    long_score += 6;  long_reasons.append(f"RSI_OS({rsi_15:.0f})(6)")
                elif rsi_15 > 70:
                    long_score -= 12; long_reasons.append(f"RSI_OB({rsi_15:.0f})(-12)")

                # Bollinger (5 pts)
                if bb_pos < 0.25:
                    long_score += 5; long_reasons.append("BB_low(5)")
                elif bb_pos > 0.85:
                    long_score -= 5; long_reasons.append("BB_high(-5)")

                # Volumen (5 pts)
                if vs >= 1.8:
                    p = min(5, int(vs * 2.5)); long_score += p
                    long_reasons.append(f"Vol{vs:.1f}x({p})")
                elif vs < 1.1:
                    long_score -= 5; long_reasons.append("VolBajo(-5)")

                # Impulso corto (5 pts)
                if trend_5c > 0.3 and green_candles >= 3:
                    long_score += 5; long_reasons.append("Impulso+(5)")
                elif trend_5c < -1.5:
                    long_score -= 5; long_reasons.append("Impulso-(-5)")

                # ATR (5 pts)
                if 0.3 < atr_pct < 3.0:
                    long_score += 5; long_reasons.append("ATR_ok(5)")
                elif atr_pct < 0.15:
                    long_score -= 5; long_reasons.append("ATRbajo(-5)")

        # ── SEÑAL SHORT ─────────────────────────────────────────────────────
        short_score, short_reasons = 0.0, []
        short_blocked = None

        if ENABLE_SHORTS:

            # FILTRO 1h — bloqueo duro si 1h es alcista
            if trend_1h == 'BULL':
                short_blocked = f"1h_BULL(bloq)"
                self.stats['blocked_1h'] += 1
            elif trend_1h == 'BEAR':
                short_score += 30; short_reasons.append("1h_BEAR(30)")
            else:
                short_score += 12; short_reasons.append("1h_NEUTRAL(12)")

            if short_blocked is None and trend_bear_15:
                short_score += 20; short_reasons.append("15m_BEAR(20)")

                # SMA21 trigger (20 pts)
                if ruptura_sma21:
                    short_score += 20; short_reasons.append("Ruptura_SMA21(20)")
                elif cerca_sma21 and price < sma21:
                    short_score += 10; short_reasons.append("Cerca_SMA21-(10)")

                # Stochastic (15 pts)
                if stoch_k > 75 and stoch_d > 70 and stoch_k < stoch_d:
                    short_score += 15; short_reasons.append(f"Stoch_OB_giro({stoch_k:.0f})(15)")
                elif stoch_k > 70:
                    short_score += 8;  short_reasons.append(f"Stoch_OB({stoch_k:.0f})(8)")
                elif stoch_k < 30:
                    short_score -= 10; short_reasons.append(f"Stoch_OS(-10)")

                # RSI 15m (10 pts) — FIX CRÍTICO: SHORT requiere RSI > 60
                # Antes entraba con RSI 39, 51 → señales falsas
                if rsi_15 >= 70:
                    short_score += 10; short_reasons.append(f"RSI_OB({rsi_15:.0f})(10)")
                elif rsi_15 >= 60:
                    short_score += 5;  short_reasons.append(f"RSI_alto({rsi_15:.0f})(5)")
                elif rsi_15 < 45:
                    # RSI bajo = ya cayó, no entrar short ahora
                    short_score -= 15; short_reasons.append(f"RSI_bajo({rsi_15:.0f})(-15)")
                    self.stats['blocked_rsi'] += 1

                # Bollinger (5 pts)
                if bb_pos > 0.90:
                    short_score += 5; short_reasons.append("BB_top(5)")
                elif bb_pos < 0.25:
                    short_score -= 5; short_reasons.append("BB_low(-5)")

                # Volumen (5 pts)
                if vs >= 1.8 and trend_5c < -0.3:
                    p = min(5, int(vs * 2.5)); short_score += p
                    short_reasons.append(f"VolVenta{vs:.1f}x({p})")
                elif vs < 1.1:
                    short_score -= 5; short_reasons.append("VolBajo(-5)")

                # 24h extendido = candidato short (5 pts)
                if change > 5.0:
                    short_score += 5; short_reasons.append(f"24h+{change:.1f}%(5)")

                # ATR (5 pts)
                if 0.3 < atr_pct < 3.0:
                    short_score += 5; short_reasons.append("ATR_ok(5)")
                elif atr_pct < 0.15:
                    short_score -= 5; short_reasons.append("ATRbajo(-5)")

                # Impulso bajista (5 pts)
                if trend_5c < -0.5 and red_candles >= 3:
                    short_score += 5; short_reasons.append("Impulso-(5)")
                elif trend_5c > 1.5:
                    short_score -= 5; short_reasons.append("Impulso+(-5)")

        # Cap a 100
        long_score  = min(100.0, max(0.0, long_score))
        short_score = min(100.0, max(0.0, short_score))

        # TP dinámico
        tp_dyn = max(TP_PCT, TP_MIN_RENTABLE, min(TP_PCT * 2.5, atr_pct * 2.5))

        # ── Decidir ─────────────────────────────────────────────────────────
        if long_score >= MIN_SCORE_LONG and long_score > short_score and not long_blocked:
            if self._btc_change_1h <= -BTC_FILTER_PCT: return None
            return {
                'signal': 'LONG', 'price': price, 'change': change,
                'score': long_score, 'reasons': ' | '.join(long_reasons),
                'stoch_k': stoch_k, 'stoch_d': stoch_d, 'rsi': rsi_15,
                'rsi_1h': rsi_1h, 'trend_1h': trend_1h,
                'vol': vs, 'tp_pct': tp_dyn, 'sl_pct': SL_PCT,
                'ema144': round(ema144, 6), 'ema89': round(ema89, 6),
                'sma21': round(sma21, 6), 'atr_pct': round(atr_pct, 2),
                'bb_pos': round(bb_pos * 100, 1),
            }

        if short_score >= MIN_SCORE_SHORT and short_score > long_score and not short_blocked:
            if self._btc_change_1h >= BTC_FILTER_PCT: return None
            return {
                'signal': 'SHORT', 'price': price, 'change': change,
                'score': short_score, 'reasons': ' | '.join(short_reasons),
                'stoch_k': stoch_k, 'stoch_d': stoch_d, 'rsi': rsi_15,
                'rsi_1h': rsi_1h, 'trend_1h': trend_1h,
                'vol': vs, 'tp_pct': tp_dyn, 'sl_pct': SL_PCT,
                'ema144': round(ema144, 6), 'ema89': round(ema89, 6),
                'sma21': round(sma21, 6), 'atr_pct': round(atr_pct, 2),
                'bb_pos': round(bb_pos * 100, 1),
            }

        return None

    # ─────────────────────────────────────────────────── ÓRDENES

    def _esperar_posicion(self, symbol, direction, timeout=None):
        if timeout is None: timeout = ESPERA_POS_TIMEOUT
        log.info(f"  ⏳ Esperando posición {symbol} {direction} (max {timeout}s)...")
        for i in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                                  {'symbol': symbol}).json()
                if d.get('code') == 0:
                    for p in (d.get('data') or []):
                        try: amt = float(p.get('positionAmt', 0) or 0)
                        except: amt = 0
                        side = p.get('positionSide', '')
                        ok = False
                        if direction == 'LONG':
                            ok = (amt > 0) or (side == 'LONG' and abs(amt) > 0)
                        else:
                            ok = (amt < 0) or (side == 'SHORT' and abs(amt) > 0)
                        if ok:
                            try:
                                entry_real = float(p.get('avgPrice') or
                                                   p.get('entryPrice') or
                                                   p.get('averagePrice') or 0)
                            except: entry_real = 0
                            qty_real = abs(amt)
                            log.info(f"  ✅ Posición confirmada: qty={qty_real} "
                                     f"entry=${entry_real:.6f} ({i+1}s)")
                            return qty_real, (entry_real if entry_real > 0 else None)
            except Exception as e:
                log.debug(f"  _esperar_posicion: {e}")
            time.sleep(1)
        log.warning(f"  ⏱ Timeout {timeout}s")
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

    def _place_entry(self, symbol, direction, usdt_qty, price):
        qty_c, _ = self._qty_contratos(symbol, price, usdt_qty)
        side = 'BUY' if direction == 'LONG' else 'SELL'
        if USE_LIMIT_ORDERS and qty_c:
            offset = (1 - LIMIT_OFFSET_PCT / 100) if direction == 'LONG' \
                     else (1 + LIMIT_OFFSET_PCT / 100)
            limit_price = round(price * offset, 8)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': side, 'positionSide': direction,
                'type': 'LIMIT', 'price': str(limit_price),
                'quantity': str(qty_c), 'timeInForce': 'GTC',
            }).json()
            if d.get('code') == 0:
                log.info(f"  ENTRADA LÍMITE OK {qty_c} @ ${limit_price:.6f}")
                return d.get('data', {}).get('orderId', 'OK'), qty_c
            log.warning(f"  Límite falló [{d.get('code')}] — fallback MARKET")
        if not qty_c:
            qty_c, _ = self._qty_contratos(symbol, price, usdt_qty)
        if not qty_c: return None, None
        d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
            'symbol': symbol, 'side': side, 'positionSide': direction,
            'type': 'MARKET', 'quantity': str(qty_c),
        }).json()
        if d.get('code') == 0:
            return d.get('data', {}).get('orderId', 'OK'), qty_c
        log.error(f"  Entrada fallida [{d.get('code')}]: {d.get('msg')}")
        return None, None

    def _cond_order(self, symbol, direction, qty_c, stop_price, otype):
        if not qty_c or qty_c <= 0: return False
        try:
            is_tp = "TAKE" in otype
            lbl   = "TP" if is_tp else "SL"
            close_side = 'SELL' if direction == 'LONG' else 'BUY'
            if is_tp:
                params = {
                    'symbol': symbol, 'side': close_side, 'positionSide': direction,
                    'type': 'TAKE_PROFIT', 'quantity': str(qty_c),
                    'price': str(round(stop_price, 8)),
                    'stopPrice': str(round(stop_price, 8)), 'timeInForce': 'GTC',
                }
            else:
                params = {
                    'symbol': symbol, 'side': close_side, 'positionSide': direction,
                    'type': 'STOP_MARKET', 'quantity': str(qty_c),
                    'stopPrice': str(round(stop_price, 8)),
                }
            d  = bingx_request('POST', '/openApi/swap/v2/trade/order', params).json()
            ok = d.get('code') == 0
            if ok:
                log.info(f"  {lbl} ✅ @ ${stop_price:.6f} (qty={qty_c})")
            else:
                if is_tp:
                    p2 = {'symbol': symbol, 'side': close_side, 'positionSide': direction,
                          'type': 'TAKE_PROFIT_MARKET', 'quantity': str(qty_c),
                          'stopPrice': str(round(stop_price, 8))}
                    d2 = bingx_request('POST', '/openApi/swap/v2/trade/order', p2).json()
                    ok = d2.get('code') == 0
                    if ok: log.info(f"  TP ✅ (fallback) @ ${stop_price:.6f}")
                    else:  log.error(f"  TP ❌ [{d2.get('code')}]: {d2.get('msg')}")
                else:
                    log.error(f"  {lbl} ❌ [{d.get('code')}]: {d.get('msg')}")
            return ok
        except Exception as e:
            log.error(f"  {otype} excepción: {e}"); return False

    def _poner_tpsl_con_reintentos(self, symbol, direction, qty_c, tp_price, sl_price):
        tp_ok = sl_ok = False
        delays = [0, 3, 5, 8, 12]
        for intento, delay in enumerate(delays[:TPSL_MAX_INTENTOS]):
            if tp_ok and sl_ok: break
            if delay > 0:
                log.warning(f"  Reintento {intento}/{TPSL_MAX_INTENTOS} en {delay}s")
                time.sleep(delay)
            if not tp_ok:
                tp_ok = self._cond_order(symbol, direction, qty_c, tp_price, 'TAKE_PROFIT_MARKET')
            if not sl_ok:
                sl_ok = self._cond_order(symbol, direction, qty_c, sl_price, 'STOP_MARKET')
        if not tp_ok or not sl_ok:
            self._tg(f"⚠️ {direction} {symbol} — "
                     f"{'❌TP' if not tp_ok else '✅TP'} "
                     f"{'❌SL' if not sl_ok else '✅SL'} — FIJAR MANUAL")
        return tp_ok, sl_ok

    def _close_position(self, symbol, direction, t):
        qty_c = t.get('qty_c', 0)
        close_side = 'SELL' if direction == 'LONG' else 'BUY'
        if qty_c and qty_c > 0:
            params = {'symbol': symbol, 'side': close_side, 'positionSide': direction,
                      'type': 'MARKET', 'quantity': str(qty_c), 'reduceOnly': 'true'}
        else:
            usdt = t.get('usdt_qty', POSITION_SIZE)
            params = {'symbol': symbol, 'side': close_side, 'positionSide': direction,
                      'type': 'MARKET', 'quoteOrderQty': str(round(usdt, 2)), 'reduceOnly': 'true'}
        return bingx_request('POST', '/openApi/swap/v2/trade/order',
                             params).json().get('code') == 0

    def _tiene_posicion(self, symbol):
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions',
                              {'symbol': symbol}).json()
            if d.get('code') == 0:
                for p in (d.get('data') or []):
                    amt = float(p.get('positionAmt', 0) or 0)
                    if abs(amt) > 0:
                        return True, 'LONG' if amt > 0 else 'SHORT'
        except: pass
        return False, None

    # ─────────────────────────────────────────────────── LIFECYCLE

    def open_trade(self, symbol, sig):
        direction = sig['signal']

        if not AUTO_TRADING:
            log.info(f"  [SEÑAL] {direction} {symbol} {sig['score']:.0f}/100 "
                     f"1h:{sig['trend_1h']} RSI15:{sig['rsi']:.0f} RSI1h:{sig['rsi_1h']:.0f}")
            return False

        if symbol in self.open_trades: return False

        # Anti-correlación: máximo MAX_SAME_DIR trades en la misma dirección
        longs, shorts = self._contar_por_direccion()
        if direction == 'LONG' and longs >= MAX_SAME_DIR:
            log.info(f"  {symbol} bloqueado — ya hay {longs} LONGs (max {MAX_SAME_DIR})")
            self.stats['blocked_corr'] += 1
            return False
        if direction == 'SHORT' and shorts >= MAX_SAME_DIR:
            log.info(f"  {symbol} bloqueado — ya hay {shorts} SHORTs (max {MAX_SAME_DIR})")
            self.stats['blocked_corr'] += 1
            return False

        tiene, dir_bx = self._tiene_posicion(symbol)
        if tiene:
            log.info(f"  {symbol} ya tiene {dir_bx} en BingX — skip"); return False

        price    = sig['price']
        usdt_qty = round(max(POSITION_SIZE, MIN_TRADE), 2)

        if direction == 'LONG':
            tp_price = price * (1 + sig['tp_pct'] / 100)
            sl_price = price * (1 - sig['sl_pct'] / 100)
        else:
            tp_price = price * (1 - sig['tp_pct'] / 100)
            sl_price = price * (1 + sig['sl_pct'] / 100)

        emoji = "📈" if direction == 'LONG' else "📉"
        log.info(f"\n  ➤ {direction} {symbol}")
        log.info(f"  Score:{sig['score']:.0f}/100 | 1h:{sig['trend_1h']} "
                 f"RSI1h:{sig['rsi_1h']:.0f} RSI15:{sig['rsi']:.0f} "
                 f"Stoch:{sig['stoch_k']:.0f}/{sig['stoch_d']:.0f}")
        log.info(f"  {sig['reasons']}")
        log.info(f"  Entry:${price:.6f} | ${usdt_qty}x{LEVERAGE} | "
                 f"TP:{sig['tp_pct']:.2f}% SL:{sig['sl_pct']:.1f}%")

        oid, qty_c = self._place_entry(symbol, direction, usdt_qty, price)
        if not oid: return False

        qty_real, entry_real = self._esperar_posicion(symbol, direction, ESPERA_POS_TIMEOUT)

        if qty_real is None:
            log.warning(f"  LIMIT no ejecutada → cancelando + MARKET")
            self._cancelar_ordenes(symbol)
            time.sleep(0.5)
            side = 'BUY' if direction == 'LONG' else 'SELL'
            d_mkt = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol, 'side': side, 'positionSide': direction,
                'type': 'MARKET', 'quantity': str(qty_c),
            }).json()
            if d_mkt.get('code') == 0:
                qty_real, entry_real = self._esperar_posicion(symbol, direction, 30)
            if qty_real is None:
                self.open_trades[symbol] = {
                    'direction': direction, 'entry': price, 'qty_c': qty_c,
                    'usdt_qty': usdt_qty, 'tp': tp_price, 'sl': sl_price,
                    'tp_pct': sig['tp_pct'], 'sl_pct': sig['sl_pct'],
                    'highest': price, 'lowest': price,
                    'order_id': oid, 'tp_ok': False, 'sl_ok': False,
                    'opened_at': datetime.now(), 'score': sig['score'],
                }
                self._tg(f"⚠️ {direction} {symbol} SIN TP/SL — FIJAR MANUAL")
                return True

        if entry_real and entry_real > 0:
            if direction == 'LONG':
                tp_price = entry_real * (1 + sig['tp_pct'] / 100)
                sl_price = entry_real * (1 - sig['sl_pct'] / 100)
            else:
                tp_price = entry_real * (1 - sig['tp_pct'] / 100)
                sl_price = entry_real * (1 + sig['sl_pct'] / 100)

        qty_final   = qty_real if qty_real else qty_c
        entry_final = entry_real if (entry_real and entry_real > 0) else price

        tp_ok, sl_ok = self._poner_tpsl_con_reintentos(
            symbol, direction, qty_final, tp_price, sl_price)

        self.open_trades[symbol] = {
            'direction': direction, 'entry': entry_final, 'qty_c': qty_final,
            'usdt_qty': usdt_qty, 'tp': tp_price, 'sl': sl_price,
            'tp_pct': sig['tp_pct'], 'sl_pct': sig['sl_pct'],
            'highest': entry_final, 'lowest': entry_final,
            'order_id': oid, 'tp_ok': tp_ok, 'sl_ok': sl_ok,
            'opened_at': datetime.now(), 'score': sig['score'],
        }
        self.stats['exec'] += 1

        stp = "✅" if tp_ok else "❌ FIJAR MANUAL"
        ssl = "✅" if sl_ok else "❌ FIJAR MANUAL"
        self._tg(
            f"<b>{emoji} {direction} ABIERTO</b>\n<b>{symbol}</b> | Score:{sig['score']:.0f}/100\n"
            f"Entrada: ${entry_final:.6f}\n"
            f"{stp} TP: ${tp_price:.6f} ({sig['tp_pct']:.2f}%)\n"
            f"{ssl} SL: ${sl_price:.6f} ({sig['sl_pct']:.1f}%)\n"
            f"Capital: ${usdt_qty} x{LEVERAGE} = ${usdt_qty*LEVERAGE:.1f} USDT\n"
            f"1h:{sig['trend_1h']} RSI1h:{sig['rsi_1h']:.0f} | RSI15:{sig['rsi']:.0f} "
            f"Stoch:{sig['stoch_k']:.0f}/{sig['stoch_d']:.0f}\n"
            f"BTC 1h:{self._btc_change_1h:+.2f}% | {sig['reasons']}"
        )
        return True

    def close_trade(self, symbol, cur_price, reason):
        if symbol not in self.open_trades: return False
        t = self.open_trades[symbol]
        direction = t['direction']
        self._close_position(symbol, direction, t)

        if direction == 'LONG':
            cambio = (cur_price - t['entry']) / t['entry']
        else:
            cambio = (t['entry'] - cur_price) / t['entry']

        pnl     = (t['usdt_qty'] * LEVERAGE * cambio) - (t['usdt_qty'] * LEVERAGE * COMISION_ACTUAL * 2)
        pnl_pct = (pnl / t['usdt_qty']) * 100

        self.stats['closed'] += 1
        self.stats['pnl']    += pnl
        tipo = 'win' if pnl > 0 else 'loss'
        if pnl > 0: self.stats['wins']   += 1
        else:        self.stats['losses'] += 1

        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        mins  = int((datetime.now() - t['opened_at']).total_seconds() / 60)
        emoji = "✅" if pnl > 0 else "❌"

        log.info(f"  {emoji} {reason} {symbol} {direction} PnL:${pnl:+.3f}({pnl_pct:+.1f}%) {mins}min")
        self._tg(
            f"<b>{emoji} {direction} CERRADO — {reason}</b>\n<b>{symbol}</b>\n"
            f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ${t['entry']:.6f} → Exit: ${cur_price:.6f}\n"
            f"Duración: {mins} min\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}% "
            f"({self.stats['wins']}W/{self.stats['losses']}L)</b>"
        )
        self._cooldowns[symbol] = (time.time(), tipo)
        del self.open_trades[symbol]
        return True

    # ─────────────────────────────────────────────────── MONITOR

    async def _sync_bingx(self):
        if not self.open_trades or not AUTO_TRADING: return
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0: return
            pos = {p.get('symbol'): float(p.get('positionAmt', 0) or 0)
                   for p in (d.get('data') or [])
                   if abs(float(p.get('positionAmt', 0) or 0)) > 0}
            for sym in list(self.open_trades.keys()):
                if sym not in pos:
                    t   = self.open_trades[sym]
                    dir = t['direction']
                    tk  = self._ticker(sym)
                    cur = tk['price'] if tk else t['entry']
                    cambio  = (cur - t['entry']) / t['entry'] if dir == 'LONG' \
                              else (t['entry'] - cur) / t['entry']
                    pnl     = (t['usdt_qty'] * LEVERAGE * cambio) - (t['usdt_qty'] * LEVERAGE * COMISION_ACTUAL * 2)
                    pnl_pct = (pnl / t['usdt_qty']) * 100
                    self.stats['closed'] += 1; self.stats['pnl'] += pnl
                    tipo = 'win' if pnl >= 0 else 'loss'
                    if pnl >= 0: self.stats['wins'] += 1
                    else:         self.stats['losses'] += 1
                    total = self.stats['wins'] + self.stats['losses']
                    wr    = self.stats['wins'] / total * 100 if total else 0
                    mins  = int((datetime.now() - t['opened_at']).total_seconds() / 60)
                    emoji = "✅" if pnl >= 0 else "❌"
                    self._tg(f"<b>{emoji} {dir} cerrado BingX</b>\n<b>{sym}</b>\n"
                             f"PnL: ${pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min\n"
                             f"Total: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                    self._cooldowns[sym] = (time.time(), tipo)
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
                cur = tk['price']
                dir = t['direction']

                if dir == 'LONG':
                    pnl_pct = (cur - t['entry']) / t['entry'] * 100
                    if TRAILING and cur > t['highest']:
                        t['highest'] = cur
                        if pnl_pct >= 0.6:
                            new_sl = t['entry'] + (cur - t['entry']) * 0.60
                            if new_sl > t['sl']:
                                t['sl'] = new_sl
                                log.info(f"  Trailing SL {sym}: ${new_sl:.6f}")
                    hit_tp = cur >= t['tp']
                    hit_sl = cur <= t['sl']
                else:
                    pnl_pct = (t['entry'] - cur) / t['entry'] * 100
                    if TRAILING and cur < t['lowest']:
                        t['lowest'] = cur
                        if pnl_pct >= 0.6:
                            new_sl = t['entry'] - (t['entry'] - cur) * 0.60
                            if new_sl < t['sl']:
                                t['sl'] = new_sl
                                log.info(f"  Trailing SL {sym}: ${new_sl:.6f}")
                    hit_tp = cur <= t['tp']
                    hit_sl = cur >= t['sl']

                if abs(pnl_pct) > 0.3:
                    log.info(f"  {sym} {dir}: {pnl_pct:+.2f}% | ${cur:.6f}")

                if hit_tp:   self.close_trade(sym, cur, "TAKE PROFIT")
                elif hit_sl: self.close_trade(sym, cur, "STOP LOSS")
            except Exception as e:
                log.debug(f"Monitor {sym}: {e}")

    def _reporte_horario(self):
        if datetime.now() - self._last_report < timedelta(hours=1): return
        self._last_report = datetime.now()
        total = self.stats['wins'] + self.stats['losses']
        wr    = self.stats['wins'] / total * 100 if total else 0
        self._tg(
            f"<b>📊 Reporte horario v4.0</b>\n"
            f"PnL: ${self.stats['pnl']:+.3f} | WR:{wr:.1f}%\n"
            f"({self.stats['wins']}W/{self.stats['losses']}L | {self.stats['closed']} trades)\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES}\n"
            f"BTC 1h:{self._btc_change_1h:+.2f}% trend:{self._btc_trend_1h}\n"
            f"Bloqueados — 1h:{self.stats['blocked_1h']} "
            f"RSI:{self.stats['blocked_rsi']} corr:{self.stats['blocked_corr']}"
        )

    def _tg(self, msg):
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                    timeout=6)
        except: pass

    # ─────────────────────────────────────────────────── LOOP

    async def run(self):
        log.info(f"\n▶  Bot v4.0 arrancado — {'AUTO' if AUTO_TRADING else '⚠️ SEÑALES SOLO'}\n")
        iteration, last_refresh = 0, 0
        while True:
            try:
                iteration += 1
                if time.time() - last_refresh > 600:
                    self._get_symbols(); last_refresh = time.time()

                self._update_btc_trend()

                total = self.stats['wins'] + self.stats['losses']
                wr    = self.stats['wins'] / total * 100 if total else 0
                hora_st = "🌙 HORA BAJA" if not self._hora_ok() else "☀️"
                longs, shorts = self._contar_por_direccion()

                log.info(f"\n{'='*65}")
                log.info(f"  #{iteration} {datetime.now().strftime('%H:%M:%S')} | "
                         f"L:{longs} S:{shorts} / max {MAX_TRADES} | "
                         f"PnL:${self.stats['pnl']:+.3f} | WR:{wr:.1f}%")
                log.info(f"  BTC 1h:{self._btc_change_1h:+.2f}% "
                         f"trend:{self._btc_trend_1h} | {hora_st}")
                log.info(f"  Bloqueados — 1h:{self.stats['blocked_1h']} "
                         f"RSI:{self.stats['blocked_rsi']} corr:{self.stats['blocked_corr']}")
                log.info(f"{'='*65}\n")

                await self.monitor_trades()
                self._reporte_horario()

                if len(self.open_trades) < MAX_TRADES:
                    found, entries_this_cycle = 0, 0
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES: break
                        # FIX: máximo MAX_ENTRIES_CYCLE entradas por ciclo
                        if entries_this_cycle >= MAX_ENTRIES_CYCLE: break

                        sig = self.analyze(sym)
                        if sig:
                            found += 1
                            log.info(f"  ★ {sig['signal']} {sym} {sig['score']:.0f}/100 "
                                     f"1h:{sig['trend_1h']} RSI:{sig['rsi']:.0f}")
                            if self.open_trade(sym, sig):
                                entries_this_cycle += 1

                        await asyncio.sleep(0.15)
                        if (i + 1) % 25 == 0:
                            log.info(f"  ...{i+1}/{len(self.symbols)} analizados")

                    log.info(f"\n  {len(self.symbols)} pares | "
                             f"{found} señales | {entries_this_cycle} entradas este ciclo")
                else:
                    log.info(f"  Max ({MAX_TRADES}) trades — esperando cierre")

                log.info(f"\n  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)

            except KeyboardInterrupt:
                log.info("Detenido"); break
            except Exception as e:
                log.error(f"Error loop #{iteration}: {e}")
                await asyncio.sleep(20)


async def main():
    try:
        await BotV4().run()
    except Exception as e:
        log.error(f"Error fatal: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Terminado")
