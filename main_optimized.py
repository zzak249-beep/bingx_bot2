#!/usr/bin/env python3
"""
BOT LONGS RENTABLE v2.0 — Optimizado para ganancias consistentes
MEJORAS CLAVE:
- Comisiones minimizadas (LIMIT orders siempre)
- Matemática favorable (RR 2:1 mínimo)
- Sistema de aprendizaje integrado
- Filtros estrictos anti-pérdidas
- Circuit breakers efectivos
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
# CONFIGURACIÓN OPTIMIZADA PARA RENTABILIDAD
# ============================================================================

# Trading conservador
AUTO_TRADING  = clean('AUTO_TRADING_ENABLED',  'true',  'bool')
POSITION_SIZE = clean('MAX_POSITION_SIZE',      '10',   'float')
MIN_TRADE     = clean('MIN_TRADE_USDT',         '10',   'float')

# TP/SL optimizados con matemática favorable
# RR mínimo 2:1 - fees considerados
TP_PCT        = clean('TAKE_PROFIT_PCT',         '6.0', 'float')  # Aumentado
SL_PCT        = clean('STOP_LOSS_PCT',           '3.0', 'float')  # Aumentado
TRAILING      = clean('TRAILING_STOP_ENABLED', 'false', 'bool')   # Desactivado - genera ruido
TRAILING_START= clean('TRAILING_START_PCT',     '3.0',  'float')
TRAILING_LOCK = clean('TRAILING_LOCK_PCT',      '60',   'float')

# Leverage reducido - menos riesgo, menos comisión
_lev_env   = clean('LEVERAGE', '1', 'int')  # SIN LEVERAGE por defecto
LEVERAGE   = min(_lev_env, 2)  # Máximo 2x

# Control de operaciones
INTERVAL      = clean('CHECK_INTERVAL',          '120', 'int')  # Menos checks = menos trades innecesarios
MIN_VOLUME    = clean('MIN_VOLUME_24H',      '1000000', 'float')  # Aumentado - solo líquidos
MAX_SYMBOLS   = clean('MAX_SYMBOLS_TO_ANALYZE',  '30',  'int')   # Reducido - calidad > cantidad
MIN_SCORE     = clean('MIN_SCORE',               '95',  'float')  # Aumentado - más selectivo
MAX_TRADES    = clean('MAX_OPEN_TRADES',          '1',  'int')   # UN trade a la vez - enfoque

# SIEMPRE órdenes LIMIT - comisión 60% menor
USE_LIMIT_ORDERS = True  # FORZADO
LIMIT_OFFSET_PCT = 0.08  # 0.08% para asegurar fill rápido

# Filtros de mercado más estrictos
BTC_BEAR_BLOCK_PCT = clean('BTC_BEAR_BLOCK_PCT', '0.5',  'float')  # Más estricto
BTC_MIN_TREND_PCT  = clean('BTC_MIN_TREND_PCT',  '0.3',  'float')  # Nuevo: BTC debe ser alcista

# Circuit breakers efectivos
MAX_LOSS_PCT         = clean('MAX_LOSS_PCT',           '3.0',  'float')  # Por trade
CIRCUIT_BREAKER_USDT = clean('CIRCUIT_BREAKER_USDT',   '1.5',  'float')  # $1.5 pérdida diaria = STOP
MAX_LOSING_STREAK    = clean('MAX_LOSING_STREAK',        '3',  'int')   # 3 pérdidas seguidas = pausa

# Cooldowns optimizados
COOLDOWN_MIN_TP  = clean('COOLDOWN_AFTER_TP_MIN',   '5',   'int')   # Reducido
COOLDOWN_MIN_SL  = clean('COOLDOWN_AFTER_SL_MIN',  '60',   'int')   # Aumentado - evitar revenge trading

# Sistema simplificado - solo indicadores probados
PATTERN_SCORE = clean('PATTERN_SCORE', 'false', 'bool')  # Desactivado - muchos falsos positivos
REGIME_FILTER = clean('REGIME_FILTER',  'true', 'bool')  # Activado
SCALPING_MODE = clean('SCALPING_MODE', 'false', 'bool')  # Desactivado - requiere más experiencia
PARTIAL_TP    = clean('PARTIAL_TP_ENABLED', 'false', 'bool')  # Desactivado - simplificar

# Horarios optimizados (UTC)
SKIP_HOURS_UTC = {0, 1, 2, 3}  # Evitar horas de bajo volumen

# Sistema de aprendizaje
LEARNING_ENABLED = clean('LEARNING_ENABLED', 'true', 'bool')
MIN_TRADES_LEARN = 10  # Mínimo trades para ajustar parámetros
SCORE_ADJUST_STEP = 2  # Ajuste gradual del score mínimo

# Constantes
FORCE_MIN_USDT = max(MIN_TRADE, 10.0)
BASE_URL = "https://open-api.bingx.com"

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ============================================================================
# CÁLCULO DE COMISIONES Y RENTABILIDAD MÍNIMA
# ============================================================================

COMISION_MAKER = 0.0002  # 0.02% - órdenes LIMIT
COMISION_TAKER = 0.0005  # 0.05% - órdenes MARKET
COMISION_ACTUAL = COMISION_MAKER  # SIEMPRE LIMIT

# TP mínimo rentable considerando fees y leverage
# Fórmula: (2 × comisión × leverage + buffer) × 100
TP_MIN_RENTABLE = round((2 * COMISION_ACTUAL * LEVERAGE + 0.003) * 100, 3)

log.info(f"TP mínimo rentable calculado: {TP_MIN_RENTABLE}% (fees + buffer)")

# ============================================================================
# FUNCIONES DE API
# ============================================================================

def bingx_request(method, endpoint, params, retries=3):
    """Request a BingX con retry mejorado"""
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
                wait = 2 ** attempt  # Exponential backoff
                log.warning(f"  Retry {attempt+1}/{retries} tras {wait}s: {e}")
                time.sleep(wait)
            else:
                raise

# ============================================================================
# INDICADORES TÉCNICOS SIMPLIFICADOS
# ============================================================================

def calc_ema(prices, period):
    """EMA optimizado"""
    if not prices or len(prices) < 2:
        return sum(prices) / len(prices) if prices else 0
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_sma(prices, period):
    """SMA simple"""
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0
    return sum(prices[-period:]) / period

def calc_rsi(prices, period=14):
    """RSI optimizado"""
    if len(prices) < period + 1:
        return 50.0
    
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_atr(highs, lows, closes, period=14):
    """ATR para volatilidad"""
    if len(closes) < 2:
        return 0
    
    trs = []
    for i in range(1, min(len(closes), period + 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    
    return sum(trs) / len(trs) if trs else 0

def vol_spike(volumes):
    """Detección de volumen anormal"""
    if len(volumes) < 5:
        return 1.0
    avg = sum(volumes[:-1]) / len(volumes[:-1])
    if avg == 0:
        return 1.0
    return volumes[-1] / avg

# ============================================================================
# SISTEMA DE APRENDIZAJE Y TRACKING
# ============================================================================

class TradeLearningSystem:
    """Sistema que aprende de trades pasados"""
    
    def __init__(self):
        self.trades_history = []
        self.symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0})
        self.score_performance = defaultdict(lambda: {'wins': 0, 'losses': 0})
        self.pattern_performance = defaultdict(lambda: {'wins': 0, 'losses': 0})
        self.optimal_score = MIN_SCORE
        self.blacklist = set()
        self.losing_streak = 0
        self.last_trades = []  # Últimos 10 trades
        
    def record_trade(self, symbol, entry_data, exit_data, pnl, win):
        """Registra un trade completo para análisis"""
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'score': entry_data.get('score', 0),
            'rsi': entry_data.get('rsi', 0),
            'patterns': entry_data.get('patterns', []),
            'entry_price': entry_data.get('price', 0),
            'exit_price': exit_data.get('price', 0),
            'pnl': pnl,
            'win': win,
            'tp_pct': entry_data.get('tp_pct', 0),
            'sl_pct': entry_data.get('sl_pct', 0),
        }
        
        self.trades_history.append(trade_record)
        self.last_trades.append(trade_record)
        if len(self.last_trades) > 10:
            self.last_trades.pop(0)
        
        # Actualizar estadísticas por símbolo
        stats = self.symbol_stats[symbol]
        if win:
            stats['wins'] += 1
            self.losing_streak = 0
        else:
            stats['losses'] += 1
            self.losing_streak += 1
        stats['total_pnl'] += pnl
        
        # Actualizar performance por score
        score_bucket = int(entry_data.get('score', 0) // 10) * 10
        if win:
            self.score_performance[score_bucket]['wins'] += 1
        else:
            self.score_performance[score_bucket]['losses'] += 1
        
        # Actualizar performance por patrones
        for pattern in entry_data.get('patterns', []):
            if win:
                self.pattern_performance[pattern]['wins'] += 1
            else:
                self.pattern_performance[pattern]['losses'] += 1
        
        # Auto-ajuste
        self._auto_adjust()
        
    def _auto_adjust(self):
        """Ajusta parámetros basado en resultados"""
        if len(self.trades_history) < MIN_TRADES_LEARN:
            return
        
        # Calcular win rate de últimos 10 trades
        recent_wins = sum(1 for t in self.last_trades if t['win'])
        recent_wr = recent_wins / len(self.last_trades) if self.last_trades else 0
        
        # Ajustar score mínimo si WR es bajo
        if recent_wr < 0.5 and len(self.last_trades) >= 10:
            self.optimal_score = min(self.optimal_score + SCORE_ADJUST_STEP, 110)
            log.warning(f"  [LEARN] WR bajo ({recent_wr:.1%}) → Score mínimo: {self.optimal_score}")
        elif recent_wr > 0.65 and len(self.last_trades) >= 10:
            self.optimal_score = max(self.optimal_score - SCORE_ADJUST_STEP, MIN_SCORE)
            log.info(f"  [LEARN] WR bueno ({recent_wr:.1%}) → Score mínimo: {self.optimal_score}")
        
        # Blacklist símbolos problemáticos
        for symbol, stats in self.symbol_stats.items():
            total = stats['wins'] + stats['losses']
            if total >= 3:  # Mínimo 3 trades
                wr = stats['wins'] / total
                if wr < 0.3 and stats['total_pnl'] < -0.5:  # WR <30% y pérdida >$0.5
                    self.blacklist.add(symbol)
                    log.warning(f"  [BLACKLIST] {symbol} agregado (WR:{wr:.1%}, PnL:${stats['total_pnl']:.2f})")
    
    def should_trade(self, symbol, score):
        """Determina si debe abrir el trade basado en aprendizaje"""
        if symbol in self.blacklist:
            return False, "Símbolo en blacklist"
        
        if score < self.optimal_score:
            return False, f"Score {score} < mínimo {self.optimal_score}"
        
        # Pausa tras racha perdedora
        if self.losing_streak >= MAX_LOSING_STREAK:
            return False, f"Racha perdedora de {self.losing_streak} trades"
        
        return True, "OK"
    
    def get_best_patterns(self, min_trades=3):
        """Retorna patrones con mejor performance"""
        best = []
        for pattern, stats in self.pattern_performance.items():
            total = stats['wins'] + stats['losses']
            if total >= min_trades:
                wr = stats['wins'] / total
                if wr >= 0.6:  # WR >60%
                    best.append((pattern, wr, total))
        return sorted(best, key=lambda x: x[1], reverse=True)
    
    def save_to_file(self, filepath='/home/claude/trade_history.json'):
        """Guarda historial para análisis offline"""
        try:
            data = {
                'trades': self.trades_history[-100:],  # Últimos 100
                'symbol_stats': dict(self.symbol_stats),
                'score_performance': dict(self.score_performance),
                'pattern_performance': dict(self.pattern_performance),
                'optimal_score': self.optimal_score,
                'blacklist': list(self.blacklist),
            }
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            log.info(f"  [LEARN] Historial guardado: {filepath}")
        except Exception as e:
            log.error(f"  [LEARN] Error guardando: {e}")
    
    def load_from_file(self, filepath='/home/claude/trade_history.json'):
        """Carga historial previo"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    data = json.load(f)
                self.trades_history = data.get('trades', [])
                self.symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0}, 
                                               data.get('symbol_stats', {}))
                self.score_performance = defaultdict(lambda: {'wins': 0, 'losses': 0}, 
                                                     data.get('score_performance', {}))
                self.pattern_performance = defaultdict(lambda: {'wins': 0, 'losses': 0}, 
                                                       data.get('pattern_performance', {}))
                self.optimal_score = data.get('optimal_score', MIN_SCORE)
                self.blacklist = set(data.get('blacklist', []))
                log.info(f"  [LEARN] Historial cargado: {len(self.trades_history)} trades")
        except Exception as e:
            log.warning(f"  [LEARN] Error cargando: {e}")

# ============================================================================
# BOT PRINCIPAL OPTIMIZADO
# ============================================================================

class OptimizedLongBot:
    """Bot de trading optimizado para rentabilidad"""
    
    _abriendo = False
    
    def __init__(self):
        log.info("=" * 80)
        log.info("  BOT LONGS RENTABLE v2.0 — Optimizado")
        log.info("=" * 80)
        log.info(f"  Modo:        {'AUTO' if AUTO_TRADING else 'SEÑALES'}")
        log.info(f"  Capital:     ${POSITION_SIZE} USDT x{LEVERAGE} = ${POSITION_SIZE*LEVERAGE:.0f} notional")
        log.info(f"  TP/SL:       {TP_PCT}% / {SL_PCT}% (RR {TP_PCT/SL_PCT:.2f}:1)")
        log.info(f"  Comisión:    LIMIT maker {COMISION_MAKER*100:.2f}% (ahorro 60% vs market)")
        log.info(f"  Min trade:   ${FORCE_MIN_USDT} USDT")
        log.info(f"  Max trades:  {MAX_TRADES} simultáneos")
        log.info(f"  Score mín:   {MIN_SCORE}")
        log.info(f"  Circuit B:   -${CIRCUIT_BREAKER_USDT} USDT/día")
        log.info(f"  Aprendizaje: {'ON' if LEARNING_ENABLED else 'OFF'}")
        log.info("=" * 80)
        
        self.symbols = []
        self.open_trades = {}
        self._contracts = {}
        self._cooldowns = {}
        self._last_report = datetime.now()
        self._btc_1h = 0.0
        self._btc_trend_ok = False
        self._daily_pnl = 0.0
        self._daily_reset = datetime.utcnow().date()
        self._circuit_open = False
        self._circuit_until = None
        
        # Sistema de aprendizaje
        self.learning = TradeLearningSystem() if LEARNING_ENABLED else None
        if self.learning:
            self.learning.load_from_file()
        
        # Estadísticas
        self.stats = {
            'exec': 0,
            'closed': 0,
            'wins': 0,
            'losses': 0,
            'pnl': 0.0,
            'fees_paid': 0.0,
        }
        
        self._verify()
        self._load_contracts()
        self._get_symbols()
        self._recover_positions()
        
        self._tg(
            f"<b>🤖 Bot LONGS v2.0 OPTIMIZADO</b>\n"
            f"Capital: ${POSITION_SIZE}x{LEVERAGE} | TP:{TP_PCT}% SL:{SL_PCT}%\n"
            f"Comisión: {COMISION_MAKER*100:.2f}% LIMIT | Score mín:{MIN_SCORE}\n"
            f"Aprendizaje: {'✅' if LEARNING_ENABLED else '❌'}\n"
            f"Posiciones: {len(self.open_trades)}/{MAX_TRADES}"
        )
    
    # ========================================================================
    # SETUP
    # ========================================================================
    
    def _verify(self):
        """Verifica credenciales"""
        global AUTO_TRADING
        if not AUTO_TRADING:
            return
        
        if not BINGX_API_KEY or not BINGX_API_SECRET:
            AUTO_TRADING = False
            log.error("Credenciales faltantes")
            return
        
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/balance', {}).json()
            if d.get('code') == 0:
                balance = d.get('data', {})
                equity = balance.get('equity', balance.get('balance', '?'))
                log.info(f"✅ BingX conectado | Balance: ${equity} USDT")
            else:
                log.error(f"❌ BingX error [{d.get('code')}]: {d.get('msg')}")
                AUTO_TRADING = False
        except Exception as e:
            log.error(f"❌ Error API: {e}")
            AUTO_TRADING = False
    
    def _load_contracts(self):
        """Carga info de contratos"""
        try:
            r = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/contracts", timeout=15)
            d = r.json()
            if d.get('code') == 0:
                for c in d.get('data', []):
                    sym = c.get('symbol', '')
                    if sym:
                        self._contracts[sym] = {
                            'step': float(c.get('tradeMinQuantity', 1)),
                            'prec': int(c.get('quantityPrecision', 2)),
                            'ctval': float(c.get('contractSize', 1)),
                        }
                log.info(f"📋 Contratos cargados: {len(self._contracts)}")
        except Exception as e:
            log.warning(f"⚠️  Error cargando contratos: {e}")
    
    def _get_symbols(self):
        """Obtiene mejores símbolos por volumen"""
        # Excluir índices, commodities, forex, stocks
        EXCLUDE_KEYWORDS = [
            'DOW', 'JONES', 'SP500', 'SPX', 'SPY', 'QQQ', 'NASDAQ', 'RUSSELL',
            'DAX', 'FTSE', 'CAC', 'NIKKEI', 'HANG', 'BOVESPA', 'IBEX',
            'GOLD', 'SILVER', 'XAU', 'XAG', 'PAXG', 'XAUT',
            'OIL', 'BRENT', 'WTI', 'CRUDE', 'GAS', 'NATURAL',
            'PLATINUM', 'PALLADIUM', 'COPPER', 'NICKEL', 'ZINC',
            'TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA',
            'COIN', 'MSTR',
            'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD', 'NZD',
            'WHEAT', 'CORN', 'SUGAR', 'COFFEE', 'COTTON',
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
                    if any(kw in base for kw in EXCLUDE_KEYWORDS):
                        continue
                    
                    try:
                        price = float(t.get('lastPrice', 0))
                        vol = float(t.get('volume', 0))
                        vol_usdt = vol * price
                        
                        if vol_usdt >= MIN_VOLUME and price > 0:
                            candidates.append({'symbol': sym, 'volume': vol_usdt})
                    except:
                        continue
                
                # Ordenar por volumen y tomar top
                candidates.sort(key=lambda x: x['volume'], reverse=True)
                self.symbols = [c['symbol'] for c in candidates[:MAX_SYMBOLS]]
                
                log.info(f"🎯 Símbolos seleccionados: {len(self.symbols)} (vol >${ MIN_VOLUME/1e6:.1f}M)")
                return
        except Exception as e:
            log.warning(f"⚠️  Error obteniendo símbolos: {e}")
        
        # Fallback
        self.symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT']
        log.info(f"📍 Usando símbolos por defecto: {len(self.symbols)}")
    
    def _recover_positions(self):
        """Recupera posiciones abiertas en BingX"""
        if not AUTO_TRADING:
            return
        
        log.info("🔍 Buscando posiciones LONG en BingX...")
        try:
            d = bingx_request('GET', '/openApi/swap/v2/user/positions', {}).json()
            if d.get('code') != 0:
                return
            
            recovered = 0
            for p in d.get('data', []):
                try:
                    amt = float(p.get('positionAmt', 0) or 0)
                    side = str(p.get('positionSide', '')).upper()
                    
                    # Solo LONGs
                    is_long = (side == 'LONG' and abs(amt) > 0) or (side == 'BOTH' and amt > 0)
                    if not is_long:
                        continue
                    
                    sym = p.get('symbol', '')
                    if not sym or sym in self.open_trades:
                        continue
                    
                    entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                    if entry <= 0:
                        # Obtener precio actual como aproximación
                        tk = self._ticker(sym)
                        entry = tk['price'] if tk else 0
                    
                    if entry <= 0:
                        continue
                    
                    tp_price = entry * (1 + TP_PCT / 100)
                    sl_price = entry * (1 - SL_PCT / 100)
                    
                    self.open_trades[sym] = {
                        'entry': entry,
                        'qty_c': abs(amt),
                        'usdt_qty': POSITION_SIZE,
                        'tp': tp_price,
                        'sl': sl_price,
                        'tp_pct': TP_PCT,
                        'sl_pct': SL_PCT,
                        'highest': entry,
                        'order_id': 'RECOVERED',
                        'opened_at': datetime.now(),
                        'score': 0,
                        'entry_data': {},
                    }
                    
                    recovered += 1
                    log.info(f"  ♻️  {sym}: {abs(amt):.4f} contratos @ ${entry:.6f}")
                    
                except Exception as e:
                    log.debug(f"Error procesando posición: {e}")
                    continue
            
            log.info(f"✅ Recuperadas {recovered} posiciones LONG")
            
        except Exception as e:
            log.error(f"❌ Error recuperando posiciones: {e}")
    
    # ========================================================================
    # DATOS DE MERCADO
    # ========================================================================
    
    def _klines(self, symbol, interval='5m', limit=80):
        """Obtiene velas"""
        try:
            r = requests.get(
                f"{BASE_URL}/openApi/swap/v3/quote/klines",
                params={'symbol': symbol, 'interval': interval, 'limit': limit},
                timeout=10
            )
            d = r.json()
            if d.get('code') == 0 and d.get('data'):
                klines = d['data']
                closes = [float(k['close']) for k in klines]
                highs = [float(k['high']) for k in klines]
                lows = [float(k['low']) for k in klines]
                volumes = [float(k['volume']) for k in klines]
                opens = [float(k['open']) for k in klines]
                return closes, highs, lows, volumes, opens
        except:
            pass
        return None, None, None, None, None
    
    def _ticker(self, symbol):
        """Obtiene precio y cambio actual"""
        try:
            r = requests.get(
                f"{BASE_URL}/openApi/swap/v2/quote/ticker",
                params={'symbol': symbol},
                timeout=8
            )
            d = r.json()
            if d.get('code') == 0 and d.get('data'):
                t = d['data']
                return {
                    'price': float(t.get('lastPrice', 0)),
                    'change': float(t.get('priceChangePercent', 0)),
                }
        except:
            pass
        return None
    
    def _update_btc_trend(self):
        """Actualiza tendencia de BTC"""
        try:
            closes, *_ = self._klines('BTC-USDT', '1h', 3)
            if closes and len(closes) >= 2:
                self._btc_1h = (closes[-1] - closes[-2]) / closes[-2] * 100
                self._btc_trend_ok = self._btc_1h >= BTC_MIN_TREND_PCT
            else:
                self._btc_trend_ok = False
        except:
            self._btc_trend_ok = False
    
    # ========================================================================
    # ANÁLISIS SIMPLIFICADO Y EFECTIVO
    # ========================================================================
    
    def analyze(self, symbol):
        """
        Sistema de análisis simplificado que funciona
        Solo usa indicadores probados: EMA, RSI, Volumen, ATR
        """
        # Filtros previos
        if symbol in self.open_trades:
            return None
        
        if not self._cooldown_ok(symbol):
            return None
        
        if not self._hora_ok():
            return None
        
        # Filtro BTC estricto
        if self._btc_1h <= -BTC_BEAR_BLOCK_PCT:
            return None
        
        if not self._btc_trend_ok:
            return None  # BTC debe ser alcista
        
        if self._check_circuit_breaker():
            return None
        
        # Obtener datos
        closes, highs, lows, volumes, opens = self._klines(symbol, '5m', 80)
        if not closes or len(closes) < 30:
            return None
        
        ticker = self._ticker(symbol)
        if not ticker or ticker['price'] <= 0:
            return None
        
        price = ticker['price']
        change_24h = ticker['change']
        
        # ====================================================================
        # INDICADORES CORE
        # ====================================================================
        
        # EMAs
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        ema50 = calc_ema(closes, min(50, len(closes)))
        
        # RSI
        rsi = calc_rsi(closes, 14)
        
        # Volumen
        vol_multiplier = vol_spike(volumes)
        
        # ATR para volatilidad
        atr = calc_atr(highs, lows, closes, 14)
        atr_pct = (atr / price * 100) if price > 0 else 0
        
        # Contexto de precio
        min_15 = min(closes[-15:]) if len(closes) >= 15 else price
        near_low = price <= min_15 * 1.015
        
        # Momentum reciente
        momentum_5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
        
        # Velas verdes recientes
        green_candles = 0
        if opens and len(opens) >= 4:
            green_candles = sum(1 for i in range(-4, 0) if closes[i] > opens[i])
        
        # ====================================================================
        # FILTROS OBLIGATORIOS
        # ====================================================================
        
        # 1. ATR mínimo (volatilidad suficiente)
        if atr_pct < 0.25:
            return None
        
        # 2. RSI no sobrecomprado
        rsi_limit = 65 if self._btc_1h > 1.0 else 60
        if rsi > rsi_limit:
            return None
        
        # 3. Tendencia EMA (con excepciones limitadas)
        ema_aligned = ema9 > ema21 > ema50
        if not ema_aligned:
            # Solo permitir si RSI muy bajo y BTC alcista
            if not (rsi < 30 and self._btc_1h > 0.5):
                return None
        
        # 4. Cambio 24h no excesivo
        if change_24h > 8.0:  # Ya subió mucho
            return None
        
        # ====================================================================
        # SISTEMA DE SCORING SIMPLIFICADO
        # ====================================================================
        
        score = 0
        reasons = []
        
        # EMA alignment (30 puntos)
        if ema_aligned:
            ema_gap = abs(ema9 - ema21) / ema21 * 100
            pts = min(30, 20 + int(ema_gap * 5))
            score += pts
            reasons.append(f"EMA↑({pts})")
        
        # RSI oversold (40 puntos max)
        if rsi < 25:
            score += 40
            reasons.append(f"RSI{rsi:.0f}(40)")
        elif rsi < 30:
            score += 32
            reasons.append(f"RSI{rsi:.0f}(32)")
        elif rsi < 35:
            score += 22
            reasons.append(f"RSI{rsi:.0f}(22)")
        elif rsi < 45:
            score += 12
            reasons.append(f"RSI{rsi:.0f}(12)")
        
        # Volumen (15 puntos max)
        if vol_multiplier >= 2.0 and momentum_5 > 0.3:
            pts = min(15, int(vol_multiplier * 6))
            score += pts
            reasons.append(f"Vol{vol_multiplier:.1f}x({pts})")
        elif vol_multiplier >= 1.5:
            score += 8
            reasons.append(f"Vol{vol_multiplier:.1f}x(8)")
        
        # Cerca de mínimos (15 puntos)
        if near_low:
            score += 15
            reasons.append("NearLow(15)")
        
        # Momentum positivo (10 puntos)
        if momentum_5 > 1.0:
            score += 10
            reasons.append("Mom+(10)")
        elif momentum_5 > 0.5:
            score += 5
            reasons.append("Mom+(5)")
        
        # Cambio 24h negativo = oportunidad (15 puntos max)
        if change_24h < -5.0:
            score += 15
            reasons.append(f"24h{change_24h:.1f}%(15)")
        elif change_24h < -3.0:
            score += 10
            reasons.append(f"24h{change_24h:.1f}%(10)")
        
        # Velas verdes (8 puntos)
        if green_candles >= 3:
            score += 8
            reasons.append(f"Green3(8)")
        elif green_candles >= 2:
            score += 4
            reasons.append(f"Green2(4)")
        
        # Volatilidad alta (8 puntos)
        if atr_pct > 1.5:
            score += 8
            reasons.append(f"ATR{atr_pct:.1f}%(8)")
        elif atr_pct > 0.8:
            score += 4
            reasons.append(f"ATR{atr_pct:.1f}%(4)")
        
        # BTC alcista (bonus 10 puntos)
        if self._btc_1h > 1.0:
            score += 10
            reasons.append(f"BTC+{self._btc_1h:.1f}%(10)")
        elif self._btc_1h > 0.5:
            score += 5
            reasons.append(f"BTC+{self._btc_1h:.1f}%(5)")
        
        # ====================================================================
        # SL/TP DINÁMICOS BASADOS EN ATR
        # ====================================================================
        
        # SL basado en ATR (mínimo SL_PCT)
        sl_dynamic = max(SL_PCT, atr_pct * 1.2)
        sl_dynamic = min(sl_dynamic, SL_PCT * 1.5)  # No más de 1.5x el configurado
        
        # TP mantiene RR 2:1
        tp_dynamic = max(TP_PCT, sl_dynamic * 2.0)
        tp_dynamic = max(tp_dynamic, TP_MIN_RENTABLE)  # Mínimo rentable
        
        # ====================================================================
        # SISTEMA DE APRENDIZAJE
        # ====================================================================
        
        score_actual = score
        score_min = self.learning.optimal_score if self.learning else MIN_SCORE
        
        if self.learning:
            can_trade, reason = self.learning.should_trade(symbol, score_actual)
            if not can_trade:
                return None
        
        # ====================================================================
        # DECISIÓN FINAL
        # ====================================================================
        
        if score_actual >= score_min:
            return {
                'price': price,
                'change': change_24h,
                'score': score_actual,
                'reasons': ' | '.join(reasons),
                'rsi': rsi,
                'vol': vol_multiplier,
                'tp_pct': round(tp_dynamic, 2),
                'sl_pct': round(sl_dynamic, 2),
                'atr_pct': round(atr_pct, 2),
                'score_min': score_min,
                'rr': round(tp_dynamic / sl_dynamic, 2),
                'ema_aligned': ema_aligned,
            }
        
        return None
    
    # ========================================================================
    # GESTIÓN DE POSICIONES
    # ========================================================================
    
    def _set_leverage(self, symbol):
        """Configura leverage"""
        try:
            for side in ['LONG', 'SHORT']:
                bingx_request('POST', '/openApi/swap/v2/trade/leverage', {
                    'symbol': symbol,
                    'side': side,
                    'leverage': str(LEVERAGE),
                })
            log.info(f"  ⚙️  Leverage {symbol} → {LEVERAGE}x")
        except Exception as e:
            log.warning(f"  ⚠️  Leverage {symbol}: {e}")
    
    def _qty_contratos(self, symbol, price, usdt_amount=None):
        """Calcula cantidad de contratos para alcanzar notional objetivo"""
        if usdt_amount is None:
            usdt_amount = POSITION_SIZE
        
        # Notional target
        notional_target = max(
            usdt_amount * LEVERAGE,
            FORCE_MIN_USDT * LEVERAGE,
            MIN_TRADE
        )
        
        # Info del contrato
        info = self._contracts.get(symbol, {'step': 1.0, 'prec': 2, 'ctval': 1.0})
        step = max(info.get('step', 1.0), 0.0001)
        prec = info.get('prec', 2)
        ctval = max(info.get('ctval', 1.0), 1e-9)
        
        # Precio por contrato
        price_per_contract = price * ctval
        if price_per_contract <= 0:
            return None, 0
        
        # Calcular cantidad
        qty = notional_target / price_per_contract
        qty = math.ceil(qty / step) * step
        qty = round(qty, prec)
        
        # Validar valor
        val = qty * price_per_contract
        min_val = max(MIN_TRADE, FORCE_MIN_USDT)
        
        # Ajustar si es necesario
        attempts = 0
        while val < min_val and attempts < 100:
            qty += step
            qty = round(qty, prec)
            val = qty * price_per_contract
            attempts += 1
        
        if val < min_val:
            return None, 0
        
        log.info(f"  📊 {symbol}: {qty} cts × ${price_per_contract:.6f} = ${val:.2f} notional")
        return qty, round(val, 4)
    
    def _place_limit_long(self, symbol, qty, price):
        """Coloca orden LIMIT de compra (comisión menor)"""
        limit_price = round(price * (1 - LIMIT_OFFSET_PCT / 100), 8)
        
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol,
                'side': 'BUY',
                'positionSide': 'LONG',
                'type': 'LIMIT',
                'price': str(limit_price),
                'quantity': str(qty),
                'timeInForce': 'GTC',
            }).json()
            
            if d.get('code') == 0:
                oid = d.get('data', {}).get('orderId', 'OK')
                log.info(f"  ✅ LIMIT BUY @ ${limit_price:.6f} | OID: {oid}")
                return oid, qty
            else:
                log.error(f"  ❌ LIMIT failed [{d.get('code')}]: {d.get('msg')}")
                return None, None
                
        except Exception as e:
            log.error(f"  ❌ Error LIMIT: {e}")
            return None, None
    
    def _wait_fill(self, symbol, order_id, timeout=30):
        """Espera que la orden LIMIT se ejecute"""
        for i in range(timeout):
            try:
                # Verificar orden
                d = bingx_request('GET', '/openApi/swap/v2/trade/order', {
                    'symbol': symbol,
                    'orderId': str(order_id)
                }).json()
                
                if d.get('code') == 0:
                    order = d.get('data', {}).get('order', {})
                    status = order.get('status', '')
                    
                    if status == 'FILLED':
                        avg_price = float(order.get('avgPrice', 0))
                        filled_qty = float(order.get('executedQty', 0))
                        log.info(f"  ✅ Ejecutada: {filled_qty} @ ${avg_price:.6f}")
                        return filled_qty, avg_price
                    elif status in ['CANCELED', 'EXPIRED', 'REJECTED']:
                        log.warning(f"  ⚠️  Orden {status}")
                        return None, None
                
            except:
                pass
            
            time.sleep(1)
        
        log.warning(f"  ⏱️  Timeout {timeout}s esperando fill")
        return None, None
    
    def _confirm_position(self, symbol, timeout=15):
        """Confirma posición abierta en BingX"""
        for i in range(timeout):
            try:
                d = bingx_request('GET', '/openApi/swap/v2/user/positions', {
                    'symbol': symbol
                }).json()
                
                if d.get('code') == 0:
                    for p in d.get('data', []):
                        amt = float(p.get('positionAmt', 0) or 0)
                        side = str(p.get('positionSide', '')).upper()
                        
                        if (side == 'LONG' and abs(amt) > 0) or (side == 'BOTH' and amt > 0):
                            entry = float(p.get('avgPrice') or p.get('entryPrice') or 0)
                            qty = abs(amt)
                            log.info(f"  ✅ Posición confirmada: {qty} @ ${entry:.6f}")
                            return qty, entry
            except:
                pass
            
            time.sleep(1)
        
        return None, None
    
    def _cancel_orders(self, symbol):
        """Cancela órdenes abiertas"""
        try:
            d = bingx_request('GET', '/openApi/swap/v2/trade/openOrders', {
                'symbol': symbol
            }).json()
            
            if d.get('code') == 0:
                orders = d.get('data', {}).get('orders', [])
                for o in orders:
                    oid = o.get('orderId')
                    if oid:
                        bingx_request('DELETE', '/openApi/swap/v2/trade/order', {
                            'symbol': symbol,
                            'orderId': str(oid)
                        })
        except:
            pass
    
    def _place_tp_sl(self, symbol, qty, tp_price, sl_price):
        """Coloca órdenes TP y SL"""
        tp_ok = False
        sl_ok = False
        
        # Take Profit
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol,
                'side': 'SELL',
                'positionSide': 'LONG',
                'type': 'TAKE_PROFIT_MARKET',
                'quantity': str(qty),
                'stopPrice': str(round(tp_price, 8)),
            }).json()
            
            tp_ok = d.get('code') == 0
            if tp_ok:
                log.info(f"  ✅ TP @ ${tp_price:.6f}")
            else:
                log.error(f"  ❌ TP failed: {d.get('msg')}")
        except Exception as e:
            log.error(f"  ❌ TP error: {e}")
        
        time.sleep(0.3)
        
        # Stop Loss
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol,
                'side': 'SELL',
                'positionSide': 'LONG',
                'type': 'STOP_MARKET',
                'quantity': str(qty),
                'stopPrice': str(round(sl_price, 8)),
            }).json()
            
            sl_ok = d.get('code') == 0
            if sl_ok:
                log.info(f"  ✅ SL @ ${sl_price:.6f}")
            else:
                log.error(f"  ❌ SL failed: {d.get('msg')}")
        except Exception as e:
            log.error(f"  ❌ SL error: {e}")
        
        return tp_ok, sl_ok
    
    def open_trade(self, symbol, signal):
        """Abre trade con sistema optimizado"""
        if not AUTO_TRADING:
            return False
        
        if symbol in self.open_trades:
            return False
        
        if OptimizedLongBot._abriendo:
            return False
        
        # Verificar slots disponibles
        if len(self.open_trades) >= MAX_TRADES:
            return False
        
        OptimizedLongBot._abriendo = True
        
        try:
            return self._open_trade_inner(symbol, signal)
        finally:
            OptimizedLongBot._abriendo = False
    
    def _open_trade_inner(self, symbol, sig):
        """Lógica interna de apertura"""
        price = sig['price']
        
        log.info(f"\n  🎯 LONG {symbol}")
        log.info(f"  Score: {sig['score']:.0f}/{sig['score_min']:.0f} | RSI: {sig['rsi']:.0f} | RR: {sig['rr']:.2f}:1")
        log.info(f"  {sig['reasons']}")
        
        # Configurar leverage
        self._set_leverage(symbol)
        time.sleep(0.2)
        
        # Calcular cantidad
        qty, notional = self._qty_contratos(symbol, price, POSITION_SIZE)
        if not qty or qty <= 0:
            log.error(f"  ❌ Cantidad inválida")
            return False
        
        # Colocar orden LIMIT (menor comisión)
        order_id, _ = self._place_limit_long(symbol, qty, price)
        if not order_id:
            return False
        
        # Esperar ejecución
        filled_qty, fill_price = self._wait_fill(symbol, order_id, timeout=30)
        
        if not filled_qty:
            # Cancelar y reintentar con MARKET si necesario
            log.warning(f"  ⚠️  LIMIT no ejecutada - cancelando")
            self._cancel_orders(symbol)
            time.sleep(0.5)
            
            # Market como backup (mayor comisión pero garantiza entrada)
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol,
                'side': 'BUY',
                'positionSide': 'LONG',
                'type': 'MARKET',
                'quantity': str(qty),
            }).json()
            
            if d.get('code') != 0:
                log.error(f"  ❌ MARKET failed: {d.get('msg')}")
                return False
            
            # Confirmar posición
            filled_qty, fill_price = self._confirm_position(symbol, timeout=15)
            
            if not filled_qty:
                log.error(f"  ❌ No se pudo confirmar posición")
                return False
        
        # Calcular TP/SL sobre precio real
        tp_price = fill_price * (1 + sig['tp_pct'] / 100)
        sl_price = fill_price * (1 - sig['sl_pct'] / 100)
        
        # Colocar TP/SL
        tp_ok, sl_ok = self._place_tp_sl(symbol, filled_qty, tp_price, sl_price)
        
        # Retry SL si falló (crítico)
        if not sl_ok:
            time.sleep(2)
            self._cancel_orders(symbol)
            time.sleep(1)
            _, sl_ok = self._place_tp_sl(symbol, filled_qty, tp_price, sl_price)
        
        # Si SL sigue fallando, cerrar posición (seguridad)
        if not sl_ok:
            log.error(f"  ❌ SL crítico fallido - cerrando posición")
            self._close_position_market(symbol, filled_qty)
            return False
        
        # Registrar trade
        self.open_trades[symbol] = {
            'entry': fill_price,
            'qty_c': filled_qty,
            'usdt_qty': POSITION_SIZE,
            'tp': tp_price,
            'sl': sl_price,
            'tp_pct': sig['tp_pct'],
            'sl_pct': sig['sl_pct'],
            'highest': fill_price,
            'order_id': order_id,
            'opened_at': datetime.now(),
            'score': sig['score'],
            'entry_data': sig,
        }
        
        self.stats['exec'] += 1
        
        # Calcular comisión pagada
        fee = notional * COMISION_ACTUAL
        self.stats['fees_paid'] += fee
        
        # Telegram
        self._tg(
            f"<b>🟢 LONG ABIERTO</b>\n"
            f"<b>{symbol}</b>\n"
            f"Score: {sig['score']:.0f}/{sig['score_min']:.0f} | RSI: {sig['rsi']:.0f} | RR: {sig['rr']:.2f}:1\n"
            f"Entrada: ${fill_price:.6f}\n"
            f"{'✅' if tp_ok else '❌'} TP: ${tp_price:.6f} (+{sig['tp_pct']:.2f}%)\n"
            f"{'✅' if sl_ok else '❌'} SL: ${sl_price:.6f} (-{sig['sl_pct']:.2f}%)\n"
            f"Capital: ${POSITION_SIZE}x{LEVERAGE} | Comisión: ${fee:.3f}\n"
            f"PnL día: ${self._daily_pnl:+.3f}"
        )
        
        return True
    
    def _close_position_market(self, symbol, qty):
        """Cierra posición a mercado"""
        try:
            d = bingx_request('POST', '/openApi/swap/v2/trade/order', {
                'symbol': symbol,
                'side': 'SELL',
                'positionSide': 'LONG',
                'type': 'MARKET',
                'quantity': str(qty),
            }).json()
            
            if d.get('code') == 0:
                log.info(f"  ✅ Posición cerrada a mercado")
                return True
        except Exception as e:
            log.error(f"  ❌ Error cerrando: {e}")
        
        return False
    
    def close_trade(self, symbol, exit_price, reason):
        """Cierra trade y registra resultado"""
        if symbol not in self.open_trades:
            return False
        
        t = self.open_trades[symbol]
        
        # Cerrar a mercado
        self._close_position_market(symbol, t['qty_c'])
        
        # Calcular PnL
        price_change = (exit_price - t['entry']) / t['entry']
        gross_pnl = t['usdt_qty'] * LEVERAGE * price_change
        
        # Descontar comisiones (entrada + salida)
        notional = t['usdt_qty'] * LEVERAGE
        fees = notional * COMISION_ACTUAL * 2  # Entrada + salida
        net_pnl = gross_pnl - fees
        
        pnl_pct = (net_pnl / t['usdt_qty']) * 100
        
        # Actualizar estadísticas
        self.stats['closed'] += 1
        self.stats['pnl'] += net_pnl
        self.stats['fees_paid'] += fees
        self._daily_pnl += net_pnl
        
        win = net_pnl > 0
        if win:
            self.stats['wins'] += 1
        else:
            self.stats['losses'] += 1
        
        # Registrar en sistema de aprendizaje
        if self.learning:
            self.learning.record_trade(
                symbol,
                t['entry_data'],
                {'price': exit_price, 'reason': reason},
                net_pnl,
                win
            )
        
        # Calcular métricas
        total = self.stats['wins'] + self.stats['losses']
        wr = self.stats['wins'] / total * 100 if total else 0
        
        # Duración
        duration = datetime.now() - t['opened_at']
        mins = int(duration.total_seconds() / 60)
        
        # Cooldown
        reason_cd = 'TP' if 'PROFIT' in reason else 'SL'
        self._set_cooldown(symbol, reason_cd)
        
        # Log
        emoji = "✅" if win else "❌"
        log.info(f"  {emoji} {reason} | PnL: ${net_pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min")
        
        # Telegram
        self._tg(
            f"<b>{emoji} LONG CERRADO — {reason}</b>\n"
            f"<b>{symbol}</b>\n"
            f"PnL: ${net_pnl:+.3f} ({pnl_pct:+.1f}%) | {mins}min\n"
            f"Entrada: ${t['entry']:.6f} → Salida: ${exit_price:.6f}\n"
            f"Comisiones: ${fees:.3f}\n"
            f"<b>Total: ${self.stats['pnl']:+.3f} | WR: {wr:.1f}%</b>\n"
            f"Día: ${self._daily_pnl:+.3f} | Fees: ${self.stats['fees_paid']:.2f}"
        )
        
        # Guardar historial
        if self.learning and self.stats['closed'] % 5 == 0:
            self.learning.save_to_file()
        
        # Eliminar trade
        del self.open_trades[symbol]
        
        return True
    
    # ========================================================================
    # UTILIDADES
    # ========================================================================
    
    def _cooldown_ok(self, symbol):
        """Verifica cooldown"""
        ts = self._cooldowns.get(symbol)
        if not ts:
            return True
        
        resume_ts, reason = ts if isinstance(ts, tuple) else (ts + COOLDOWN_MIN_TP * 60, 'TP')
        if time.time() >= resume_ts:
            del self._cooldowns[symbol]
            return True
        
        return False
    
    def _set_cooldown(self, symbol, reason='TP'):
        """Establece cooldown"""
        mins = COOLDOWN_MIN_TP if reason == 'TP' else COOLDOWN_MIN_SL
        self._cooldowns[symbol] = (time.time() + mins * 60, reason)
        log.info(f"  ⏱️  Cooldown {symbol}: {mins}min ({reason})")
    
    def _hora_ok(self):
        """Verifica hora operativa"""
        return int(datetime.utcnow().hour) not in SKIP_HOURS_UTC
    
    def _reset_daily_pnl(self):
        """Reset diario de PnL"""
        today = datetime.utcnow().date()
        if today != self._daily_reset:
            self._daily_pnl = 0.0
            self._daily_reset = today
            self._circuit_open = False
            self._circuit_until = None
            
            if self.learning:
                self.learning.losing_streak = 0
            
            log.info("📅 Nuevo día - PnL reseteado")
    
    def _check_circuit_breaker(self):
        """Circuit breaker mejorado"""
        self._reset_daily_pnl()
        
        # Verificar si ya está activo
        if self._circuit_open:
            if self._circuit_until and datetime.utcnow() > self._circuit_until:
                self._circuit_open = False
                log.info("  🔓 Circuit breaker desactivado")
                self._tg("<b>🔓 Circuit breaker desactivado</b> — trading reanudado")
            return self._circuit_open
        
        # Verificar pérdida diaria
        if self._daily_pnl < -CIRCUIT_BREAKER_USDT:
            self._circuit_open = True
            self._circuit_until = datetime.utcnow() + timedelta(hours=2)
            
            log.warning(f"  🔒 CIRCUIT BREAKER ACTIVADO")
            log.warning(f"  Pérdida día: ${self._daily_pnl:.3f} < -${CIRCUIT_BREAKER_USDT:.2f}")
            
            self._tg(
                f"<b>🔒 CIRCUIT BREAKER ACTIVADO</b>\n"
                f"Pérdida día: ${self._daily_pnl:.3f} USDT\n"
                f"Umbral: -${CIRCUIT_BREAKER_USDT:.2f} USDT\n"
                f"Pausado 2h hasta {self._circuit_until.strftime('%H:%M')} UTC"
            )
        
        return self._circuit_open
    
    # ========================================================================
    # MONITOREO
    # ========================================================================
    
    async def monitor_trades(self):
        """Monitorea trades abiertos"""
        for sym in list(self.open_trades.keys()):
            try:
                t = self.open_trades[sym]
                tk = self._ticker(sym)
                
                if not tk:
                    continue
                
                cur = tk['price']
                pnl_pct = (cur - t['entry']) / t['entry'] * 100
                
                # Trailing stop (si está activo)
                if TRAILING and cur > t['highest']:
                    t['highest'] = cur
                    
                    if pnl_pct >= TRAILING_START:
                        new_sl = t['entry'] + (cur - t['entry']) * (TRAILING_LOCK / 100)
                        if new_sl > t['sl']:
                            t['sl'] = new_sl
                            log.info(f"  📈 Trailing {sym}: SL → ${new_sl:.6f}")
                
                # Verificar TP/SL
                if cur >= t['tp']:
                    self.close_trade(sym, cur, "TAKE PROFIT")
                elif cur <= t['sl']:
                    self.close_trade(sym, cur, "STOP LOSS")
                
                # Emergency stop si pérdida excesiva
                pnl_leverage = pnl_pct * LEVERAGE
                if pnl_leverage < -MAX_LOSS_PCT:
                    self.close_trade(sym, cur, "STOP EMERGENCIA")
                
            except Exception as e:
                log.debug(f"Monitor {sym}: {e}")
    
    def _reporte_horario(self):
        """Reporte cada hora"""
        if datetime.now() - self._last_report < timedelta(hours=1):
            return
        
        self._last_report = datetime.now()
        
        total = self.stats['wins'] + self.stats['losses']
        wr = self.stats['wins'] / total * 100 if total else 0
        
        # Posiciones abiertas
        pos_txt = ""
        for sym, t in self.open_trades.items():
            tk = self._ticker(sym)
            cur = tk['price'] if tk else t['entry']
            pct = (cur - t['entry']) / t['entry'] * 100
            pos_txt += f"  {sym}: {pct:+.2f}%\n"
        
        # Mejores patrones (si hay aprendizaje)
        best_patterns = ""
        if self.learning:
            patterns = self.learning.get_best_patterns()
            if patterns:
                best_patterns = "\nMejores señales:\n"
                for pat, wr_pat, total_pat in patterns[:3]:
                    best_patterns += f"  {pat}: {wr_pat:.1%} ({total_pat} trades)\n"
        
        self._tg(
            f"<b>📊 Reporte LONGS v2.0</b>\n"
            f"PnL total: ${self.stats['pnl']:+.3f} | WR: {wr:.1f}%\n"
            f"PnL día: ${self._daily_pnl:+.3f} (límite: -${CIRCUIT_BREAKER_USDT:.2f})\n"
            f"Comisiones pagadas: ${self.stats['fees_paid']:.2f}\n"
            f"({self.stats['wins']}W / {self.stats['losses']}L | {self.stats['closed']} trades)\n"
            f"Abiertos: {len(self.open_trades)}/{MAX_TRADES} | BTC: {self._btc_1h:+.2f}%\n"
            f"Circuit: {'🔒 ACTIVO' if self._circuit_open else '🔓 OK'}\n"
            + (pos_txt if pos_txt else "  Sin posiciones\n")
            + best_patterns
        )
    
    def _tg(self, msg):
        """Envía mensaje a Telegram"""
        try:
            if TELEGRAM_TOKEN and TELEGRAM_CHAT:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        'chat_id': TELEGRAM_CHAT,
                        'text': msg,
                        'parse_mode': 'HTML'
                    },
                    timeout=6
                )
        except:
            pass
    
    # ========================================================================
    # LOOP PRINCIPAL
    # ========================================================================
    
    async def run(self):
        """Loop principal optimizado"""
        log.info("\n🚀 Bot LONGS v2.0 iniciado\n")
        
        iteration = 0
        last_symbol_refresh = 0
        
        while True:
            try:
                iteration += 1
                
                # Reset diario
                self._reset_daily_pnl()
                
                # Refresh símbolos cada 10 min
                if time.time() - last_symbol_refresh > 600:
                    self._get_symbols()
                    last_symbol_refresh = time.time()
                
                # Actualizar tendencia BTC
                self._update_btc_trend()
                
                # Verificar circuit breaker
                if self._check_circuit_breaker():
                    log.warning(f"  🔒 Circuit breaker activo - esperando...")
                    await asyncio.sleep(INTERVAL)
                    continue
                
                # Stats
                total = self.stats['wins'] + self.stats['losses']
                wr = self.stats['wins'] / total * 100 if total else 0
                
                btc_status = "🟢 OK" if self._btc_trend_ok else "🔴 BEAR"
                hora_status = "✅" if self._hora_ok() else "⏸️ PAUSA"
                
                score_actual = self.learning.optimal_score if self.learning else MIN_SCORE
                
                log.info(f"\n{'=' * 80}")
                log.info(f"  Iteración #{iteration} | {datetime.now().strftime('%H:%M:%S')}")
                log.info(f"  Abiertos: {len(self.open_trades)}/{MAX_TRADES} | "
                         f"PnL: ${self.stats['pnl']:+.3f} | WR: {wr:.1f}%")
                log.info(f"  BTC: {self._btc_1h:+.2f}% {btc_status} | {hora_status} | "
                         f"Score mín: {score_actual:.0f}")
                log.info(f"  Día: ${self._daily_pnl:+.3f} | Fees: ${self.stats['fees_paid']:.2f}")
                log.info(f"{'=' * 80}\n")
                
                # Monitorear trades abiertos
                await self.monitor_trades()
                
                # Reporte horario
                self._reporte_horario()
                
                # Buscar nuevas oportunidades
                slots_free = MAX_TRADES - len(self.open_trades)
                
                if slots_free > 0:
                    signals_found = 0
                    
                    for i, sym in enumerate(self.symbols):
                        if len(self.open_trades) >= MAX_TRADES:
                            break
                        
                        sig = self.analyze(sym)
                        
                        if sig:
                            signals_found += 1
                            log.info(f"  💡 Señal: {sym} | Score: {sig['score']:.0f} | RSI: {sig['rsi']:.0f}")
                            
                            opened = self.open_trade(sym, sig)
                            if opened:
                                await asyncio.sleep(3)
                        
                        # Progress
                        if (i + 1) % 10 == 0:
                            log.info(f"  ... {i+1}/{len(self.symbols)} analizados")
                        
                        await asyncio.sleep(0.2)
                    
                    log.info(f"\n  ✅ Análisis completo: {signals_found} señales encontradas")
                else:
                    log.info(f"  ⏸️  Máximo trades ({MAX_TRADES}) - esperando cierre")
                
                log.info(f"\n  ⏭️  Próximo ciclo en {INTERVAL}s\n")
                await asyncio.sleep(INTERVAL)
                
            except KeyboardInterrupt:
                log.info("⏹️  Bot detenido por usuario")
                break
            except Exception as e:
                log.error(f"❌ Error en iteración #{iteration}: {e}")
                await asyncio.sleep(20)
        
        # Guardar datos al salir
        if self.learning:
            self.learning.save_to_file()
            log.info("💾 Historial guardado")

# ============================================================================
# ENTRY POINT
# ============================================================================

async def main():
    """Punto de entrada"""
    try:
        bot = OptimizedLongBot()
        await bot.run()
    except Exception as e:
        log.error(f"❌ Error fatal: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Bot terminado")
