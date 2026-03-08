"""
learning_engine.py - Motor de aprendizaje adaptativo
Registra todos los trades, analiza resultados y ajusta parametros
automaticamente para mejorar el rendimiento con el tiempo.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional
import statistics

log = logging.getLogger('bot27')

MEMORY_FILE = "bot27_memory.json"


class LearningEngine:
    """
    Aprende de cada trade:
    1. Registra entrada, salida, PnL, regimen de mercado
    2. Calcula WR, PF, avg PnL por simbolo/regimen/hora
    3. Ajusta min_confidence, sl_mult, tp_mult automaticamente
    4. Blacklistea simbolos con mal historial
    5. Identifica las mejores horas del dia para operar
    """

    def __init__(self, memory_file: str = MEMORY_FILE):
        self.memory_file = memory_file
        self.memory      = self._load()

    # ------------------------------------------------------------------
    # PERSISTENCIA
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return self._empty_memory()

    def _save(self):
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(self.memory, f, indent=2, default=str)

    def _empty_memory(self) -> dict:
        return {
            'version':     2,
            'created':     datetime.now().isoformat(),
            'total_trades': 0,
            'trades':      [],           # historial completo
            'symbol_stats': {},          # stats por simbolo
            'regime_stats': {},          # stats por regimen
            'hour_stats':   {},          # stats por hora UTC
            'params': {                  # parametros ajustados
                'min_confidence': 75,
                'sl_mult':        1.5,
                'tp_mult':        2.5,
                'leverage':       3,
                'risk_pct':       2.0,
            },
            'blacklist':   [],           # simbolos bloqueados
            'last_update': None,
        }

    # ------------------------------------------------------------------
    # REGISTRAR TRADE
    # ------------------------------------------------------------------

    def record_trade_open(self, symbol: str, signal: int, price: float,
                          sl: float, tp: float, size: float,
                          confidence: int, regime: str,
                          strategy: str = 'supertrend') -> str:
        """Registra apertura de trade. Retorna trade_id."""
        trade_id = f"{symbol}_{int(datetime.now().timestamp())}"
        hour     = datetime.utcnow().hour

        trade = {
            'id':         trade_id,
            'symbol':     symbol,
            'signal':     signal,
            'direction':  'LONG' if signal == 1 else 'SHORT',
            'entry':      price,
            'sl':         sl,
            'tp':         tp,
            'size':       size,
            'confidence': confidence,
            'regime':     regime,
            'strategy':   strategy,
            'hour_utc':   hour,
            'open_time':  datetime.now().isoformat(),
            'close_time': None,
            'exit':       None,
            'pnl_pct':    None,
            'pnl_usdt':   None,
            'result':     None,   # WIN / LOSS / BREAK_EVEN / OPEN
            'exit_reason': None,  # SL / TP / MANUAL / TIMEOUT
        }

        self.memory['trades'].append(trade)
        self.memory['total_trades'] += 1
        self._save()

        log.info(f"Trade registrado: {trade_id} | {trade['direction']} {symbol}")
        return trade_id

    def record_trade_close(self, trade_id: str, exit_price: float,
                           exit_reason: str = 'UNKNOWN'):
        """Registra cierre de trade y actualiza estadisticas."""
        trade = self._find_trade(trade_id)
        if not trade:
            log.warning(f"Trade no encontrado: {trade_id}")
            return

        entry   = trade['entry']
        signal  = trade['signal']
        size    = trade['size']

        # PnL
        if signal == 1:   # LONG
            pnl_pct = (exit_price - entry) / entry * 100
        else:             # SHORT
            pnl_pct = (entry - exit_price) / entry * 100

        pnl_usdt = size * pnl_pct / 100

        result = 'WIN' if pnl_pct > 0.1 else ('LOSS' if pnl_pct < -0.1 else 'BREAK_EVEN')

        trade['close_time']  = datetime.now().isoformat()
        trade['exit']        = exit_price
        trade['pnl_pct']     = round(pnl_pct, 4)
        trade['pnl_usdt']    = round(pnl_usdt, 4)
        trade['result']      = result
        trade['exit_reason'] = exit_reason

        self._update_stats(trade)
        self._adapt_params()
        self._save()

        log.info(f"Trade cerrado: {trade_id} | {result} | PnL: {pnl_pct:+.2f}% ({pnl_usdt:+.2f} USDT)")

    # ------------------------------------------------------------------
    # ESTADISTICAS
    # ------------------------------------------------------------------

    def _find_trade(self, trade_id: str) -> Optional[dict]:
        for t in self.memory['trades']:
            if t['id'] == trade_id:
                return t
        return None

    def _update_stats(self, trade: dict):
        """Actualiza stats por simbolo, regimen y hora."""
        for key, category in [
            (trade['symbol'],  'symbol_stats'),
            (trade['regime'],  'regime_stats'),
            (str(trade['hour_utc']), 'hour_stats'),
        ]:
            if key not in self.memory[category]:
                self.memory[category][key] = {
                    'trades': 0, 'wins': 0, 'losses': 0,
                    'total_pnl': 0.0, 'pnl_list': [],
                }
            s = self.memory[category][key]
            s['trades']    += 1
            s['total_pnl'] += trade['pnl_usdt'] or 0
            s['pnl_list'].append(trade['pnl_pct'] or 0)
            if trade['result'] == 'WIN':
                s['wins'] += 1
            elif trade['result'] == 'LOSS':
                s['losses'] += 1

    # ------------------------------------------------------------------
    # ADAPTACION DE PARAMETROS
    # ------------------------------------------------------------------

    def _adapt_params(self):
        """
        Ajusta automaticamente los parametros del bot basandose en
        los ultimos N trades.
        """
        recent = [t for t in self.memory['trades']
                  if t['result'] in ('WIN', 'LOSS', 'BREAK_EVEN')][-50:]

        if len(recent) < 10:
            return   # no hay suficientes datos todavia

        wins     = sum(1 for t in recent if t['result'] == 'WIN')
        losses   = sum(1 for t in recent if t['result'] == 'LOSS')
        total    = wins + losses
        wr       = wins / total if total > 0 else 0
        pnl_list = [t['pnl_pct'] for t in recent if t['pnl_pct'] is not None]
        avg_pnl  = statistics.mean(pnl_list) if pnl_list else 0

        params = self.memory['params']
        old    = dict(params)

        # --- Win Rate bajo -> subir min_confidence (ser mas selectivo) ---
        if wr < 0.45:
            params['min_confidence'] = min(params['min_confidence'] + 5, 90)
            log.info(f"[LEARN] WR bajo ({wr:.0%}) -> min_confidence sube a {params['min_confidence']}")
        elif wr > 0.65:
            params['min_confidence'] = max(params['min_confidence'] - 3, 65)
            log.info(f"[LEARN] WR alto ({wr:.0%}) -> min_confidence baja a {params['min_confidence']}")

        # --- PnL medio negativo -> ampliar SL (evitar stops prematuros) ---
        if avg_pnl < -1.0:
            params['sl_mult'] = min(params['sl_mult'] + 0.2, 3.0)
            log.info(f"[LEARN] Avg PnL negativo -> sl_mult sube a {params['sl_mult']}")
        elif avg_pnl > 2.0 and wr > 0.55:
            params['tp_mult'] = min(params['tp_mult'] + 0.2, 4.0)
            log.info(f"[LEARN] Buen rendimiento -> tp_mult sube a {params['tp_mult']}")

        # --- Muchas perdidas seguidas -> bajar riesgo ---
        last_5 = [t['result'] for t in recent[-5:]]
        consecutive_losses = 0
        for r in reversed(last_5):
            if r == 'LOSS':
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= 3:
            params['risk_pct'] = max(params['risk_pct'] - 0.5, 0.5)
            log.info(f"[LEARN] {consecutive_losses} perdidas seguidas -> risk_pct baja a {params['risk_pct']}")
        elif wr > 0.60 and avg_pnl > 1.0:
            params['risk_pct'] = min(params['risk_pct'] + 0.25, 3.0)
            log.info(f"[LEARN] Buen rendimiento -> risk_pct sube a {params['risk_pct']}")

        # Guardar log del cambio
        if params != old:
            self.memory.setdefault('param_history', []).append({
                'time':   datetime.now().isoformat(),
                'before': old,
                'after':  dict(params),
                'wr':     round(wr, 3),
                'avg_pnl': round(avg_pnl, 3),
            })

        self.memory['last_update'] = datetime.now().isoformat()

    # ------------------------------------------------------------------
    # BLACKLIST
    # ------------------------------------------------------------------

    def update_blacklist(self):
        """
        Blacklistea simbolos con >= 5 trades y WR < 35%.
        Los elimina de la blacklist si mejoran.
        """
        new_blacklist = []
        for sym, s in self.memory['symbol_stats'].items():
            if s['trades'] >= 5:
                wr = s['wins'] / s['trades']
                if wr < 0.35:
                    new_blacklist.append(sym)
                    log.info(f"[LEARN] Blacklist: {sym} (WR {wr:.0%} en {s['trades']} trades)")

        self.memory['blacklist'] = new_blacklist
        self._save()

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self.memory['blacklist']

    # ------------------------------------------------------------------
    # MEJORES HORAS
    # ------------------------------------------------------------------

    def get_best_hours(self) -> list:
        """Retorna lista de horas UTC con mejor rendimiento."""
        hour_stats = self.memory.get('hour_stats', {})
        if not hour_stats:
            return list(range(24))   # todas las horas si no hay datos

        good_hours = []
        for hour_str, s in hour_stats.items():
            if s['trades'] >= 3:
                wr = s['wins'] / s['trades']
                if wr >= 0.50:
                    good_hours.append(int(hour_str))

        return good_hours if good_hours else list(range(24))

    # ------------------------------------------------------------------
    # RESUMEN
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        closed = [t for t in self.memory['trades']
                  if t['result'] in ('WIN', 'LOSS', 'BREAK_EVEN')]
        if not closed:
            return {'total': 0, 'wr': 0, 'avg_pnl': 0, 'total_pnl': 0, 'wins': 0, 'losses': 0, 'params': self.memory['params'], 'blacklist': self.memory['blacklist']}

        wins     = sum(1 for t in closed if t['result'] == 'WIN')
        pnl_list = [t['pnl_pct'] for t in closed if t['pnl_pct'] is not None]
        total_pnl= sum(t['pnl_usdt'] for t in closed if t['pnl_usdt'] is not None)

        return {
            'total':     len(closed),
            'wins':      wins,
            'losses':    len(closed) - wins,
            'wr':        round(wins / len(closed) * 100, 1),
            'avg_pnl':   round(statistics.mean(pnl_list), 2) if pnl_list else 0,
            'total_pnl': round(total_pnl, 2),
            'params':    self.memory['params'],
            'blacklist': self.memory['blacklist'],
        }

    def print_summary(self):
        s = self.get_summary()
        print("\n" + "="*60)
        print("  BOT27 - MEMORIA Y APRENDIZAJE")
        print("="*60)
        print(f"  Trades totales:  {s['total']}")
        print(f"  Win Rate:        {s['wr']}%")
        print(f"  Wins / Losses:   {s['wins']} / {s['losses']}")
        print(f"  Avg PnL:         {s['avg_pnl']:+.2f}%")
        print(f"  PnL total:       {s['total_pnl']:+.2f} USDT")
        print(f"\n  Parametros actuales (aprendidos):")
        for k, v in s['params'].items():
            print(f"    {k:<20} {v}")
        if s['blacklist']:
            print(f"\n  Blacklist ({len(s['blacklist'])}):")
            for sym in s['blacklist']:
                print(f"    {sym}")
        print("="*60 + "\n")
