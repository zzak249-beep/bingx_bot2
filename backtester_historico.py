#!/usr/bin/env python3
"""
backtester_historico.py - Backtesting con datos históricos REALES

Soporta:
  - CSV con trades (date, symbol, pnl, hours, etc)
  - JSON con historial de trades
  
Proyecta ROI con diferentes estrategias

Uso:
  python backtester_historico.py --data trades.csv
  python backtester_historico.py --data trades.json
"""

import json
import csv
import argparse
import statistics
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple

# ═══════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ═══════════════════════════════════════════════════════════════

class DataLoader:
    """Carga trades de CSV o JSON"""
    
    @staticmethod
    def load_csv(filepath: str) -> List[Dict]:
        """Cargar trades de CSV"""
        trades = []
        try:
            with open(filepath, encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trade = {
                        'date': row.get('date', row.get('timestamp', '')),
                        'symbol': row.get('symbol', 'UNKNOWN'),
                        'side': row.get('side', row.get('type', 'long')).lower(),
                        'pnl': float(row.get('pnl', row.get('profit', 0))),
                        'entry': float(row.get('entry', row.get('open_price', 0))),
                        'exit': float(row.get('exit', row.get('close_price', 0))),
                        'size': float(row.get('size', row.get('quantity', 0))),
                        'hours': float(row.get('hours', row.get('duration_hours', 1))),
                    }
                    trades.append(trade)
            print(f"✅ Cargados {len(trades)} trades de {filepath}")
            return trades
        except Exception as e:
            print(f"❌ Error cargando CSV: {e}")
            return []
    
    @staticmethod
    def load_json(filepath: str) -> List[Dict]:
        """Cargar trades de JSON"""
        try:
            with open(filepath) as f:
                data = json.load(f)
                
            # Si es dict, extraer lista de trades
            if isinstance(data, dict):
                trades = data.get('trades', [])
            else:
                trades = data
            
            print(f"✅ Cargados {len(trades)} trades de {filepath}")
            return trades
        except Exception as e:
            print(f"❌ Error cargando JSON: {e}")
            return []
    
    @staticmethod
    def load_file(filepath: str) -> List[Dict]:
        """Auto-detectar formato y cargar"""
        if filepath.endswith('.csv'):
            return DataLoader.load_csv(filepath)
        elif filepath.endswith('.json'):
            return DataLoader.load_json(filepath)
        else:
            print(f"❌ Formato no soportado: {filepath}")
            return []

# ═══════════════════════════════════════════════════════════════
# ANÁLISIS DE DATOS
# ═══════════════════════════════════════════════════════════════

class TradeAnalyzer:
    """Analiza trades históricos"""
    
    def __init__(self, trades: List[Dict]):
        self.trades = trades
        self.stats = self._calculate_stats()
    
    def _calculate_stats(self) -> Dict:
        """Calcular estadísticas globales"""
        if not self.trades:
            return {}
        
        pnls = [t['pnl'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        stats = {
            'total_trades': len(self.trades),
            'wins': len(wins),
            'losses': len(losses),
            'wr': len(wins) / len(self.trades) * 100 if self.trades else 0,
            'total_pnl': sum(pnls),
            'avg_win': statistics.mean(wins) if wins else 0,
            'avg_loss': statistics.mean(losses) if losses else 0,
            'max_win': max(wins) if wins else 0,
            'max_loss': min(losses) if losses else 0,
            'pf': abs(sum(wins) / sum(losses)) if losses else 0,
            'sharpe': 0,
        }
        
        # Sharpe Ratio
        if len(pnls) > 1:
            try:
                std_dev = statistics.stdev(pnls)
                if std_dev > 0:
                    stats['sharpe'] = (statistics.mean(pnls) / std_dev) * (252 ** 0.5)
            except:
                stats['sharpe'] = 0
        
        return stats
    
    def get_stats_by_pair(self) -> Dict[str, Dict]:
        """Estadísticas por par"""
        pairs = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnls': []})
        
        for trade in self.trades:
            symbol = trade['symbol']
            pnl = trade['pnl']
            pairs[symbol]['pnls'].append(pnl)
            if pnl > 0:
                pairs[symbol]['wins'] += 1
            else:
                pairs[symbol]['losses'] += 1
        
        result = {}
        for symbol, data in pairs.items():
            pnls = data['pnls']
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            
            result[symbol] = {
                'trades': len(pnls),
                'wr': len(wins) / len(pnls) * 100,
                'pnl': sum(pnls),
                'avg_win': statistics.mean(wins) if wins else 0,
                'avg_loss': statistics.mean(losses) if losses else 0,
            }
        
        return result
    
    def get_stats_by_period(self, period_days: int = 7) -> List[Dict]:
        """Estadísticas por período de tiempo"""
        # Asumir que trades tienen 'date'
        periods = defaultdict(list)
        
        for trade in self.trades:
            date_str = trade.get('date', '')
            # Simplificado: agrupar por semana
            periods[date_str[:7]].append(trade['pnl'])
        
        result = []
        for period, pnls in sorted(periods.items()):
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            
            result.append({
                'period': period,
                'trades': len(pnls),
                'wr': len(wins) / len(pnls) * 100,
                'pnl': sum(pnls),
                'avg_win': statistics.mean(wins) if wins else 0,
                'avg_loss': statistics.mean(losses) if losses else 0,
            })
        
        return result

# ═══════════════════════════════════════════════════════════════
# PROYECCIONES
# ═══════════════════════════════════════════════════════════════

class Projector:
    """Proyecta ROI futuro basado en histórico"""
    
    def __init__(self, stats: Dict):
        self.stats = stats
    
    def project_monthly(self, months: int = 12) -> Dict:
        """Proyectar ROI mensual"""
        wr = self.stats['wr'] / 100
        avg_win = self.stats['avg_win']
        avg_loss = abs(self.stats['avg_loss'])
        trades_per_month = (self.stats['total_trades'] / 12)  # Asumir 1 año histórico
        
        if trades_per_month == 0:
            trades_per_month = 50  # Default
        
        # Simular N meses
        results = []
        capital = 100
        
        for month in range(1, months + 1):
            # Trades en el mes
            month_trades = int(trades_per_month)
            
            # PnL esperado
            wins = int(month_trades * wr)
            losses = month_trades - wins
            
            monthly_pnl = (wins * avg_win) - (losses * avg_loss)
            monthly_roi = (monthly_pnl / capital) * 100
            
            capital += monthly_pnl
            
            results.append({
                'month': month,
                'trades': month_trades,
                'pnl': monthly_pnl,
                'roi': monthly_roi,
                'capital': capital,
            })
        
        return {
            'projection': results,
            'final_capital': capital,
            'total_roi': ((capital - 100) / 100) * 100,
            'avg_monthly_roi': statistics.mean([r['roi'] for r in results]),
        }
    
    def project_with_improvements(self) -> Dict:
        """Proyectar con mejoras (Opción 1, 2, 3)"""
        wr = self.stats['wr'] / 100
        avg_win = self.stats['avg_win']
        avg_loss = abs(self.stats['avg_loss'])
        trades_per_month = (self.stats['total_trades'] / 12) or 50
        
        scenarios = {
            'ACTUAL': {
                'leverage': 1,
                'trades_mult': 1.0,
                'ratio_mult': 1.0,
                'wr_mult': 1.0,
            },
            'OPCIÓN 1 (TP:SL 3:1)': {
                'leverage': 1,
                'trades_mult': 1.0,
                'ratio_mult': 2.0,  # Ratio AvgWin:AvgLoss sube
                'wr_mult': 0.90,     # WR baja un poco
            },
            'OPCIÓN 2 (Learner)': {
                'leverage': 1,
                'trades_mult': 2.5,  # Más trades
                'ratio_mult': 2.0,
                'wr_mult': 0.95,
            },
            'Leverage 3x': {
                'leverage': 3,
                'trades_mult': 2.5,
                'ratio_mult': 2.0,
                'wr_mult': 0.95,
            },
            'Leverage 5x': {
                'leverage': 5,
                'trades_mult': 2.5,
                'ratio_mult': 2.0,
                'wr_mult': 0.95,
            },
        }
        
        results = {}
        
        for scenario_name, config in scenarios.items():
            capital = 100
            monthly_rois = []
            
            for month in range(1, 13):
                trades = int(trades_per_month * config['trades_mult'])
                wr_adjusted = wr * config['wr_mult']
                wins = int(trades * wr_adjusted)
                losses = trades - wins
                
                avg_win_adj = avg_win * config['ratio_mult']
                avg_loss_adj = avg_loss
                
                monthly_pnl = (wins * avg_win_adj - losses * avg_loss_adj)
                monthly_pnl_leverage = monthly_pnl * config['leverage']
                
                monthly_roi = (monthly_pnl_leverage / capital) * 100
                capital += monthly_pnl_leverage
                monthly_rois.append(monthly_roi)
            
            results[scenario_name] = {
                'avg_monthly_roi': statistics.mean(monthly_rois),
                'final_capital': capital,
                'total_roi': ((capital - 100) / 100) * 100,
            }
        
        return results

# ═══════════════════════════════════════════════════════════════
# REPORTES
# ═══════════════════════════════════════════════════════════════

def print_analysis(analyzer: TradeAnalyzer):
    """Imprimir análisis completo"""
    stats = analyzer.stats
    
    print("\n" + "="*70)
    print("📊 ANÁLISIS DE TRADES HISTÓRICOS")
    print("="*70)
    
    if not stats:
        print("❌ No hay datos")
        return
    
    print(f"Total Trades:      {stats['total_trades']}")
    print(f"Wins:              {stats['wins']}")
    print(f"Losses:            {stats['losses']}")
    print(f"Win Rate:          {stats['wr']:.1f}%")
    print(f"Total PnL:         ${stats['total_pnl']:.2f}")
    print(f"Avg Win:           ${stats['avg_win']:.4f}")
    print(f"Avg Loss:          ${stats['avg_loss']:.4f}")
    print(f"Profit Factor:     {stats['pf']:.2f}")
    print(f"Sharpe Ratio:      {stats['sharpe']:.2f}")
    
    # Top pares
    print("\n" + "─"*70)
    print("🏆 TOP 5 PARES")
    pair_stats = analyzer.get_stats_by_pair()
    sorted_pairs = sorted(pair_stats.items(), key=lambda x: x[1]['wr'], reverse=True)
    
    for pair, data in sorted_pairs[:5]:
        print(f"  {pair:12s} WR:{data['wr']:5.1f}% PnL:${data['pnl']:+7.2f} T:{data['trades']:3d}")

def print_projection(projector: Projector):
    """Imprimir proyecciones"""
    projection = projector.project_monthly(12)
    
    print("\n" + "="*70)
    print("📈 PROYECCIÓN A 12 MESES (Baseline)")
    print("="*70)
    
    for r in projection['projection']:
        print(f"Mes {r['month']:2d}: {r['roi']:+6.2f}% | "
              f"Capital: ${r['capital']:7.2f} | Trades: {r['trades']}")
    
    print("─"*70)
    print(f"Avg Monthly ROI: {projection['avg_monthly_roi']:+.2f}%")
    print(f"Final Capital:   ${projection['final_capital']:.2f}")
    print(f"Total ROI:       {projection['total_roi']:+.2f}%")

def print_scenarios(projector: Projector):
    """Imprimir comparativa de escenarios"""
    improvements = projector.project_with_improvements()
    
    print("\n" + "="*70)
    print("🚀 COMPARATIVA: PROYECCIÓN DE MEJORAS")
    print("="*70)
    print(f"{'Escenario':<25} {'Avg Monthly':<15} {'Total 12m':<15}")
    print("─"*70)
    
    for scenario, stats in improvements.items():
        avg_roi = stats['avg_monthly_roi']
        total_roi = stats['total_roi']
        print(f"{scenario:<25} {avg_roi:+7.2f}%         {total_roi:+8.2f}%")
    
    # Mejora vs actual
    actual = improvements.get('ACTUAL', {}).get('avg_monthly_roi', 0)
    best = max(improvements.values(), key=lambda x: x['avg_monthly_roi'])
    best_name = [k for k, v in improvements.items() if v == best][0]
    best_roi = best['avg_monthly_roi']
    
    print("\n" + "─"*70)
    print(f"🏆 MEJOR ESCENARIO: {best_name}")
    print(f"   Mejora vs Actual: +{((best_roi - actual) / abs(actual) * 100):.0f}%")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Backtester histórico')
    parser.add_argument('--data', type=str, default='trades.csv',
                       help='Archivo de datos (CSV o JSON)')
    args = parser.parse_args()
    
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "📊 BACKTESTER HISTÓRICO v1.0" + " "*23 + "║")
    print("║" + " "*20 + "Análisis de datos REALES" + " "*24 + "║")
    print("╚" + "="*68 + "╝")
    
    # Cargar datos
    print(f"\n🔄 Cargando datos de {args.data}...")
    loader = DataLoader()
    trades = loader.load_file(args.data)
    
    if not trades:
        print("❌ No se pudieron cargar datos")
        return
    
    # Analizar
    analyzer = TradeAnalyzer(trades)
    print_analysis(analyzer)
    
    # Proyectar
    projector = Projector(analyzer.stats)
    print_projection(projector)
    print_scenarios(projector)
    
    # Guardar
    output = {
        'timestamp': datetime.now().isoformat(),
        'stats': analyzer.stats,
        'projection': projector.project_monthly(12),
        'improvements': projector.project_with_improvements(),
    }
    
    output_file = 'backtest_historico.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✅ Resultados guardados en: {output_file}")

if __name__ == "__main__":
    main()
