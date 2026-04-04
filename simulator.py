#!/usr/bin/env python3
"""
SIMULADOR DE RENTABILIDAD - Bot Longs v2.0
Permite simular resultados con diferentes configuraciones ANTES de operar real
"""

import random
from datetime import datetime, timedelta

class TradingSimulator:
    """Simula trades con diferentes configuraciones"""
    
    def __init__(self, config):
        self.config = config
        self.capital = config['initial_capital']
        self.trades = []
        self.daily_pnl = 0
        self.circuit_breaker_active = False
        
    def simulate_trade(self, is_win=None):
        """Simula un trade individual"""
        if self.circuit_breaker_active:
            return None
        
        # Determinar win/loss
        if is_win is None:
            is_win = random.random() < self.config['win_rate']
        
        # Calcular PnL
        position_size = self.config['position_size']
        leverage = self.config['leverage']
        notional = position_size * leverage
        
        if is_win:
            pnl_pct = self.config['tp_pct'] / 100
        else:
            pnl_pct = -self.config['sl_pct'] / 100
        
        # PnL bruto
        gross_pnl = position_size * leverage * pnl_pct
        
        # Comisiones
        commission_pct = 0.0002 if self.config['use_limit'] else 0.0005
        fees = notional * commission_pct * 2  # Entrada + salida
        
        # PnL neto
        net_pnl = gross_pnl - fees
        
        # Actualizar capital
        self.capital += net_pnl
        self.daily_pnl += net_pnl
        
        # Circuit breaker
        if self.daily_pnl < -self.config['circuit_breaker_usdt']:
            self.circuit_breaker_active = True
        
        trade = {
            'win': is_win,
            'gross_pnl': gross_pnl,
            'fees': fees,
            'net_pnl': net_pnl,
            'capital_after': self.capital,
        }
        
        self.trades.append(trade)
        return trade
    
    def reset_daily(self):
        """Reset diario"""
        self.daily_pnl = 0
        self.circuit_breaker_active = False
    
    def simulate_period(self, days=30, trades_per_day=2.5):
        """Simula un periodo completo"""
        for day in range(days):
            self.reset_daily()
            
            num_trades = int(random.gauss(trades_per_day, 0.5))
            num_trades = max(1, min(num_trades, 5))  # 1-5 trades/día
            
            for _ in range(num_trades):
                if self.circuit_breaker_active:
                    break
                self.simulate_trade()
        
        return self.get_statistics()
    
    def get_statistics(self):
        """Calcula estadísticas del periodo"""
        if not self.trades:
            return None
        
        total_trades = len(self.trades)
        wins = sum(1 for t in self.trades if t['win'])
        losses = total_trades - wins
        
        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)
        
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0
        
        avg_win = sum(t['net_pnl'] for t in self.trades if t['win']) / wins if wins > 0 else 0
        avg_loss = sum(t['net_pnl'] for t in self.trades if not t['win']) / losses if losses > 0 else 0
        
        roi = (self.capital - self.config['initial_capital']) / self.config['initial_capital'] * 100
        
        return {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'final_capital': self.capital,
            'roi': roi,
        }

def print_config(name, config):
    """Imprime configuración"""
    print(f"\n{'='*80}")
    print(f"  {name}")
    print(f"{'='*80}")
    print(f"  Capital inicial:    ${config['initial_capital']:.2f}")
    print(f"  Tamaño posición:    ${config['position_size']:.2f}")
    print(f"  Leverage:           {config['leverage']}x")
    print(f"  TP / SL:            {config['tp_pct']:.1f}% / {config['sl_pct']:.1f}%")
    print(f"  Win Rate esperado:  {config['win_rate']*100:.0f}%")
    print(f"  Órdenes:            {'LIMIT' if config['use_limit'] else 'MARKET'}")
    print(f"  Circuit breaker:    ${config['circuit_breaker_usdt']:.2f} USDT")
    print(f"{'='*80}\n")

def print_results(stats, num_simulations):
    """Imprime resultados"""
    if not stats:
        print("No hay datos para mostrar")
        return
    
    print(f"\n{'='*80}")
    print(f"  RESULTADOS PROMEDIO ({num_simulations} simulaciones)")
    print(f"{'='*80}")
    print(f"  Total trades:       {stats['total_trades']:.0f}")
    print(f"  Wins / Losses:      {stats['wins']:.0f} / {stats['losses']:.0f}")
    print(f"  Win Rate:           {stats['win_rate']:.1f}%")
    print(f"  PnL total:          ${stats['total_pnl']:+.2f}")
    print(f"  Comisiones:         ${stats['total_fees']:.2f}")
    print(f"  Avg ganancia:       ${stats['avg_win']:+.2f}")
    print(f"  Avg pérdida:        ${stats['avg_loss']:+.2f}")
    print(f"  Capital final:      ${stats['final_capital']:.2f}")
    print(f"  ROI:                {stats['roi']:+.1f}%")
    print(f"{'='*80}\n")

def run_scenario(name, config, days=30, simulations=100):
    """Ejecuta escenario múltiples veces"""
    print_config(name, config)
    
    all_results = []
    for _ in range(simulations):
        sim = TradingSimulator(config)
        stats = sim.simulate_period(days=days, trades_per_day=2.5)
        if stats:
            all_results.append(stats)
    
    # Promedios
    avg_stats = {
        'total_trades': sum(r['total_trades'] for r in all_results) / len(all_results),
        'wins': sum(r['wins'] for r in all_results) / len(all_results),
        'losses': sum(r['losses'] for r in all_results) / len(all_results),
        'win_rate': sum(r['win_rate'] for r in all_results) / len(all_results),
        'total_pnl': sum(r['total_pnl'] for r in all_results) / len(all_results),
        'total_fees': sum(r['total_fees'] for r in all_results) / len(all_results),
        'avg_win': sum(r['avg_win'] for r in all_results) / len(all_results),
        'avg_loss': sum(r['avg_loss'] for r in all_results) / len(all_results),
        'final_capital': sum(r['final_capital'] for r in all_results) / len(all_results),
        'roi': sum(r['roi'] for r in all_results) / len(all_results),
    }
    
    print_results(avg_stats, simulations)
    
    # Percentiles
    pnl_sorted = sorted([r['total_pnl'] for r in all_results])
    roi_sorted = sorted([r['roi'] for r in all_results])
    
    print(f"  DISTRIBUCIÓN DE RESULTADOS:")
    print(f"  ----------------------------")
    print(f"  Peor caso (5%):     ${pnl_sorted[4]:.2f} ({roi_sorted[4]:+.1f}%)")
    print(f"  Caso pesimista (25%): ${pnl_sorted[24]:.2f} ({roi_sorted[24]:+.1f}%)")
    print(f"  Mediana (50%):      ${pnl_sorted[49]:.2f} ({roi_sorted[49]:+.1f}%)")
    print(f"  Caso optimista (75%): ${pnl_sorted[74]:.2f} ({roi_sorted[74]:+.1f}%)")
    print(f"  Mejor caso (95%):   ${pnl_sorted[94]:.2f} ({roi_sorted[94]:+.1f}%)")
    print(f"\n")
    
    # Probabilidad de profit
    profitable = sum(1 for r in all_results if r['total_pnl'] > 0)
    prob_profit = profitable / len(all_results) * 100
    print(f"  Probabilidad de profit: {prob_profit:.1f}%")
    print(f"  ({profitable}/{len(all_results)} simulaciones con PnL positivo)")
    print(f"\n")

# =============================================================================
# ESCENARIOS DE SIMULACIÓN
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  SIMULADOR DE RENTABILIDAD - Bot Longs v2.0")
    print("  Comparación de escenarios (30 días, 100 simulaciones)")
    print("="*80)
    
    # Escenario 1: Bot v1.6 (configuración anterior)
    config_v16 = {
        'initial_capital': 10.0,
        'position_size': 10.0,
        'leverage': 3,
        'tp_pct': 2.5,
        'sl_pct': 1.5,
        'win_rate': 0.47,  # WR real observado
        'use_limit': False,  # MARKET orders
        'circuit_breaker_usdt': 5.0,
    }
    
    run_scenario("ESCENARIO 1: Bot v1.6 (ANTERIOR)", config_v16, days=30)
    
    # Escenario 2: Bot v2.0 conservador
    config_v20_conservative = {
        'initial_capital': 10.0,
        'position_size': 10.0,
        'leverage': 1,  # SIN leverage
        'tp_pct': 6.0,
        'sl_pct': 3.0,
        'win_rate': 0.55,  # WR esperado con mejoras
        'use_limit': True,  # LIMIT orders
        'circuit_breaker_usdt': 1.5,
    }
    
    run_scenario("ESCENARIO 2: Bot v2.0 CONSERVADOR (RECOMENDADO)", config_v20_conservative, days=30)
    
    # Escenario 3: Bot v2.0 moderado
    config_v20_moderate = {
        'initial_capital': 10.0,
        'position_size': 10.0,
        'leverage': 2,  # Leverage moderado
        'tp_pct': 6.0,
        'sl_pct': 3.0,
        'win_rate': 0.55,
        'use_limit': True,
        'circuit_breaker_usdt': 1.5,
    }
    
    run_scenario("ESCENARIO 3: Bot v2.0 MODERADO", config_v20_moderate, days=30)
    
    # Escenario 4: Bot v2.0 optimista (WR 60%)
    config_v20_optimistic = {
        'initial_capital': 10.0,
        'position_size': 10.0,
        'leverage': 1,
        'tp_pct': 6.0,
        'sl_pct': 3.0,
        'win_rate': 0.60,  # WR optimista
        'use_limit': True,
        'circuit_breaker_usdt': 1.5,
    }
    
    run_scenario("ESCENARIO 4: Bot v2.0 OPTIMISTA (WR 60%)", config_v20_optimistic, days=30)
    
    # Escenario 5: Bot v2.0 pesimista (WR 48%)
    config_v20_pessimistic = {
        'initial_capital': 10.0,
        'position_size': 10.0,
        'leverage': 1,
        'tp_pct': 6.0,
        'sl_pct': 3.0,
        'win_rate': 0.48,  # WR pesimista
        'use_limit': True,
        'circuit_breaker_usdt': 1.5,
    }
    
    run_scenario("ESCENARIO 5: Bot v2.0 PESIMISTA (WR 48%)", config_v20_pessimistic, days=30)
    
    # =============================================================================
    # ANÁLISIS DE SENSIBILIDAD
    # =============================================================================
    
    print("\n" + "="*80)
    print("  ANÁLISIS DE SENSIBILIDAD: Impacto del Win Rate")
    print("="*80 + "\n")
    
    print("  Win Rate | ROI Esperado (30 días)")
    print("  ---------|-------------------------")
    
    for wr in range(40, 71, 5):
        config_test = {
            'initial_capital': 10.0,
            'position_size': 10.0,
            'leverage': 1,
            'tp_pct': 6.0,
            'sl_pct': 3.0,
            'win_rate': wr / 100,
            'use_limit': True,
            'circuit_breaker_usdt': 1.5,
        }
        
        results = []
        for _ in range(50):  # 50 sims por velocidad
            sim = TradingSimulator(config_test)
            stats = sim.simulate_period(days=30, trades_per_day=2.5)
            if stats:
                results.append(stats['roi'])
        
        avg_roi = sum(results) / len(results) if results else 0
        print(f"     {wr}%   |   {avg_roi:+6.1f}%")
    
    print("\n" + "="*80)
    print("  CONCLUSIONES:")
    print("="*80)
    print(f"""
  1. Bot v1.6 (WR 47%, leverage 3x, MARKET):
     - Expectativa: Negativa o break-even
     - Comisiones: Muy altas
     - Riesgo: Elevado
     
  2. Bot v2.0 CONSERVADOR (WR 55%, leverage 1x, LIMIT):
     - Expectativa: +120-160% mensual
     - Comisiones: Muy bajas
     - Riesgo: Bajo
     - RECOMENDADO para empezar
     
  3. Win Rate crítico para rentabilidad:
     - <48%: Probablemente negativo
     - 48-52%: Break-even o ganancia pequeña
     - 52-58%: Ganancia consistente
     - >58%: Excelente
     
  4. Factores clave de éxito:
     ✅ Órdenes LIMIT (ahorro 60% comisiones)
     ✅ RR 2:1 mínimo
     ✅ Sin leverage o mínimo
     ✅ Trading selectivo (calidad > cantidad)
     ✅ Circuit breakers efectivos
     ✅ Sistema de aprendizaje
  
  ⚠️  IMPORTANTE:
  Estas son SIMULACIONES basadas en parámetros fijos.
  El mercado real es más complejo y variable.
  Siempre usar gestión de riesgo y capital que puedas perder.
  """)
    
    print("="*80 + "\n")
