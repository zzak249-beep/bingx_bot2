#!/usr/bin/env python3
"""
main_bot.py v3 - BOT27 completo con todas las mejoras
- Descarga paralela (5x mas rapido)
- Gestion de riesgo avanzada (drawdown diario, correlacion)
- Comandos Telegram (/status /balance /trades /pause)
- Reporte diario automatico
- Filtro de volumen y liquidez
- Divergencias RSI
- Log deduplicado
"""
import os, sys, time, logging, traceback
from datetime import datetime, date

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---- LOGGING sin duplicados ----
log = logging.getLogger('bot27')
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    fh  = logging.FileHandler('bot27.log', encoding='utf-8')
    fh.setFormatter(fmt)
    ch  = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ch)

# ---- CONFIG ----
def cfg(k, d=''): return os.environ.get(k, d).strip()

BINGX_API_KEY    = cfg('BINGX_API_KEY')
BINGX_SECRET_KEY = cfg('BINGX_SECRET_KEY')
TELEGRAM_TOKEN   = cfg('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = cfg('TELEGRAM_CHAT_ID')
DRY_RUN          = cfg('DRY_RUN', 'true').lower() == 'true'
PRESET           = cfg('PRESET', 'balanced')
MAX_SYMBOLS      = int(cfg('MAX_SYMBOLS', '100'))
MAX_OPEN_TRADES  = int(cfg('MAX_OPEN_TRADES', '3'))
LEVERAGE         = int(cfg('LEVERAGE', '3'))
RISK_PCT         = float(cfg('RISK_PCT', '2.0'))
_iv              = cfg('INTERVAL', '1h')
INTERVAL         = _iv if _iv in ['1m','5m','15m','30m','1h','2h','4h','1d'] else '1h'
CYCLE_SECONDS    = {'1m':60,'5m':300,'15m':900,'30m':1800,'1h':3600,'2h':7200,'4h':14400,'1d':86400}.get(INTERVAL, 3600)
FILTER_VOLUME    = cfg('FILTER_VOLUME', 'true').lower() == 'true'
MAX_DAILY_LOSS   = float(cfg('MAX_DAILY_LOSS_PCT', '5.0'))

# ---- IMPORTS ----
from bingx_api_supertrend import BingXAPI
from strategy_supertrend  import SupertrendRSIStrategy
from config_supertrend    import get_config
from market_regime        import MarketRegimeDetector, RangingStrategy, Regime
from learning_engine      import LearningEngine
from bingx_trader         import BingXTrader
from telegram_alerts      import TelegramBot
from risk_manager         import RiskManager


class Bot27:
    def __init__(self):
        log.info("Iniciando BOT27 v3...")
        self.api         = BingXAPI(workers=5)
        self.learner     = LearningEngine()
        self.regime      = MarketRegimeDetector()
        self.risk        = RiskManager(max_daily_loss_pct=MAX_DAILY_LOSS,
                                       max_correlated_trades=2,
                                       max_total_risk_pct=RISK_PCT * MAX_OPEN_TRADES)
        self.telegram    = None
        self.trader      = None
        self.cycle       = 0
        self.open_trades = {}
        self.paused      = False
        self._last_report_day = None
        self._build_strategies()

        if BINGX_API_KEY and BINGX_SECRET_KEY:
            self.trader = BingXTrader(
                api_key=BINGX_API_KEY, secret_key=BINGX_SECRET_KEY,
                risk_pct=self.params['risk_pct'], leverage=LEVERAGE, dry_run=DRY_RUN)
        else:
            log.warning("Sin API keys BingX - solo senales")

        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            self.telegram = TelegramBot(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
            self._register_commands()
            self.telegram.start_polling()
        else:
            log.warning("Sin Telegram configurado")

        log.info(f"BOT27 v3 listo | {PRESET} | {INTERVAL} | DryRun:{DRY_RUN}")

    def _build_strategies(self):
        self.params = self.learner.memory['params']
        c = get_config(PRESET)
        c['min_confidence'] = self.params['min_confidence']
        c['sl_mult']        = self.params['sl_mult']
        c['tp_mult']        = self.params['tp_mult']
        self.st_strategy      = SupertrendRSIStrategy(**c)
        self.ranging_strategy = RangingStrategy()

    def _register_commands(self):
        tg = self.telegram
        tg.register_command('status',  self._cmd_status)
        tg.register_command('balance', self._cmd_balance)
        tg.register_command('trades',  self._cmd_trades)
        tg.register_command('stats',   self._cmd_stats)
        tg.register_command('pause',   self._cmd_pause)
        tg.register_command('resume',  self._cmd_resume)

    def _cmd_status(self):
        rs = self.risk.get_status()
        s  = self.learner.get_summary()
        bal = self.trader.get_balance() if self.trader else 0
        return (f"<b>BOT27 STATUS</b>\n"
                f"Ciclo: #{self.cycle} | {INTERVAL}\n"
                f"Trades abiertos: {len(self.open_trades)}/{MAX_OPEN_TRADES}\n"
                f"Balance: {bal:.2f} USDT\n"
                f"PnL hoy: {rs['daily_pnl']:+.2f} USDT\n"
                f"Trading: {'PAUSADO' if self.paused or rs['trading_halted'] else 'ACTIVO'}\n"
                f"WR total: {s.get('wr',0)}% ({s.get('total',0)} trades)")

    def _cmd_balance(self):
        bal = self.trader.get_balance() if self.trader else 0
        return f"Balance disponible: <b>{bal:.2f} USDT</b>"

    def _cmd_trades(self):
        if not self.open_trades:
            return "Sin trades abiertos."
        lines = ["<b>Trades abiertos:</b>"]
        for sym, tid in self.open_trades.items():
            t = self.learner._find_trade(tid)
            if t:
                lines.append(f"  {t['direction']} {sym} @ {t['entry']:.6f}")
        return '\n'.join(lines)

    def _cmd_stats(self):
        s = self.learner.get_summary()
        p = s.get('params', {})
        return (f"<b>Estadisticas BOT27</b>\n"
                f"Trades: {s.get('total',0)} | WR: {s.get('wr',0)}%\n"
                f"PnL total: {s.get('total_pnl',0):+.2f} USDT\n"
                f"min_conf: {p.get('min_confidence',75)} | risk: {p.get('risk_pct',2)}%\n"
                f"Blacklist: {len(s.get('blacklist',[]))} pares")

    def _cmd_pause(self):
        self.paused = True
        return "Trading PAUSADO. Usa /resume para reanudar."

    def _cmd_resume(self):
        self.paused = False
        return "Trading REANUDADO."

    # ---- BUCLE PRINCIPAL ----
    def run_forever(self):
        balance = self.trader.get_balance() if self.trader else 0.0
        if self.telegram:
            self.telegram.startup(PRESET, INTERVAL, MAX_SYMBOLS, balance, DRY_RUN)
        self.learner.print_summary()

        while True:
            try:
                self.cycle += 1
                log.info("=" * 60)
                log.info(f"CICLO #{self.cycle} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                self._daily_report_check()
                self._run_cycle()
                log.info(f"Ciclo #{self.cycle} OK. Esperando {CYCLE_SECONDS}s...")
                time.sleep(CYCLE_SECONDS)
            except KeyboardInterrupt:
                log.info("Detenido por usuario.")
                break
            except Exception as e:
                log.error(f"Error ciclo #{self.cycle}: {e}")
                traceback.print_exc()
                if self.telegram:
                    self.telegram.error(str(e)[:200])
                time.sleep(60)

    def _daily_report_check(self):
        today = date.today()
        if self._last_report_day != today and datetime.now().hour == 0:
            if self.telegram and self.trader:
                bal = self.trader.get_balance()
                self.telegram.daily_report(bal, self.learner.get_summary(),
                                           self.risk.get_status())
            self._last_report_day = today

    def _run_cycle(self):
        self._build_strategies()
        if self.trader:
            self.trader.risk_pct = self.params['risk_pct']

        # Simbolos con filtro de liquidez
        symbols = self.api.get_swap_symbols()
        symbols = [s for s in symbols if not self.learner.is_blacklisted(s)]
        if FILTER_VOLUME:
            symbols = self.api.filter_by_volume(symbols)
        if len(symbols) > MAX_SYMBOLS:
            symbols = symbols[:MAX_SYMBOLS]

        # Descarga paralela
        market_data = self.api.get_market_data(symbols, INTERVAL, limit=100)
        if not market_data:
            log.error("Sin datos de mercado")
            return

        self._check_closed_positions()
        longs = shorts = neutrals = 0
        open_count = len(self.open_trades)

        for symbol, df in market_data.items():
            if len(df) < 50:
                continue
            reg_info = self.regime.detect(df)
            regime   = reg_info['regime']

            if regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                result   = self.st_strategy.get_signal(df)
                strategy = 'supertrend'
            elif regime == Regime.RANGING:
                result   = self.ranging_strategy.get_signal(df)
                strategy = 'bb_ranging'
            else:
                result   = self.st_strategy.get_signal(df)
                result['confidence'] = int(result['confidence'] * 0.7)
                strategy = 'supertrend_volatile'

            signal     = result['signal']
            confidence = result['confidence']
            price      = float(df['close'].iloc[-1])

            if signal == 0:
                neutrals += 1
                continue

            # Filtro de alineacion con tendencia
            if regime == Regime.TRENDING_UP   and signal == -1: neutrals += 1; continue
            if regime == Regime.TRENDING_DOWN and signal == 1:  neutrals += 1; continue

            direction = 'LONG' if signal == 1 else 'SHORT'
            log.info(f"SENAL {direction} {symbol} conf:{confidence}% RSI:{result['rsi']:.1f} {regime.value}")

            if self.telegram:
                self.telegram.signal_alert(symbol, signal, confidence, result['rsi'],
                    price, result['sl'], result['tp'], result['reason'],
                    regime.value, result.get('divergence','none'))

            if signal == 1: longs += 1
            else:           shorts += 1

            # Verificar si se puede tradear
            if self.paused:
                continue
            if open_count >= MAX_OPEN_TRADES or symbol in self.open_trades:
                continue

            # Risk manager
            can, reason = self.risk.can_trade(symbol, self.open_trades,
                                              self.trader.get_balance() if self.trader else 0,
                                              self.params['risk_pct'])
            if not can:
                log.info(f"Trade bloqueado por risk manager: {reason}")
                continue

            if self.trader:
                trade_result = self.trader.open_position(symbol, signal, price,
                                                         result['sl'], result['tp'])
                if trade_result.get('success'):
                    tid = self.learner.record_trade_open(
                        symbol=symbol, signal=signal, price=price,
                        sl=result['sl'], tp=result['tp'], size=trade_result['size'],
                        confidence=confidence, regime=regime.value, strategy=strategy)
                    self.open_trades[symbol] = tid
                    open_count += 1
                    if self.telegram:
                        self.telegram.trade_opened(trade_result)

        balance = self.trader.get_balance() if self.trader else 0.0
        summary = self.learner.get_summary()
        log.info(f"Ciclo #{self.cycle}: LONG:{longs} SHORT:{shorts} NEUTRAL:{neutrals} Balance:{balance:.2f}")

        if self.telegram and self.cycle % 6 == 0:
            self.telegram.cycle_summary(self.cycle, longs, shorts, neutrals,
                                        balance, summary, self.risk.get_status())

        if self.cycle % 10 == 0:
            self.learner.update_blacklist()

    def _check_closed_positions(self):
        if not self.trader or not self.open_trades:
            return
        open_pos = {p.get('symbol'): p for p in self.trader.get_open_positions()}
        closed   = []
        for symbol, tid in self.open_trades.items():
            if symbol not in open_pos:
                df = self.api.get_klines(symbol, INTERVAL, limit=5)
                exit_price = float(df['close'].iloc[-1]) if not df.empty else 0.0
                trade      = self.learner._find_trade(tid)
                reason     = 'UNKNOWN'
                if trade and exit_price > 0:
                    reason = 'TP' if (
                        (trade['signal']==1  and exit_price >= trade['tp']*0.98) or
                        (trade['signal']==-1 and exit_price <= trade['tp']*1.02)
                    ) else 'SL'
                self.learner.record_trade_close(tid, exit_price, reason)

                # Risk manager registra PnL
                if trade:
                    bal = self.trader.get_balance()
                    self.risk.record_pnl(trade.get('pnl_usdt', 0) or 0, bal)
                    if self.telegram:
                        self.telegram.trade_closed(symbol, trade['direction'],
                            trade.get('pnl_pct',0) or 0,
                            trade.get('pnl_usdt',0) or 0,
                            trade.get('result','UNKNOWN'))
                    # Alerta si se pausa por drawdown
                    if self.risk.trading_halted and self.telegram:
                        self.telegram.risk_halt(self.risk.daily_pnl, bal)

                closed.append(symbol)
                log.info(f"Posicion cerrada: {symbol} ({reason})")
        for s in closed:
            del self.open_trades[s]


if __name__ == '__main__':
    print("")
    print("=" * 60)
    print("  BOT27 v3 - MAX RENDIMIENTO + APRENDIZAJE + 24/7")
    print("=" * 60)
    print(f"  Preset:        {PRESET}")
    print(f"  Intervalo:     {INTERVAL}")
    print(f"  Modo:          {'SIMULACION' if DRY_RUN else 'LIVE REAL'}")
    print(f"  Telegram:      {'SI' if TELEGRAM_TOKEN else 'NO'}")
    print(f"  BingX API:     {'SI' if BINGX_API_KEY else 'NO (solo senales)'}")
    print(f"  Filtro vol:    {'SI' if FILTER_VOLUME else 'NO'}")
    print(f"  Limite diario: {MAX_DAILY_LOSS}%")
    print("=" * 60)
    print("")
    bot = Bot27()
    bot.run_forever()
