"""
risk_manager.py - Gestion de riesgo avanzada
- Limite de perdida diaria (drawdown diario)
- Deteccion de correlacion entre pares abiertos
- Position sizing por volatilidad del par
- Trailing stop
"""
import logging
from datetime import datetime, date
from typing import List

log = logging.getLogger('bot27')


class RiskManager:
    def __init__(self,
                 max_daily_loss_pct: float = 5.0,
                 max_correlated_trades: int = 2,
                 max_total_risk_pct: float = 6.0):
        """
        max_daily_loss_pct:    Para el bot si pierde este % del balance en el dia
        max_correlated_trades: Max trades en pares correlacionados (BTC/ETH/BNB)
        max_total_risk_pct:    Risk total maximo en todos los trades abiertos
        """
        self.max_daily_loss_pct    = max_daily_loss_pct
        self.max_correlated_trades = max_correlated_trades
        self.max_total_risk_pct    = max_total_risk_pct

        self.daily_pnl    = 0.0
        self.daily_date   = date.today()
        self.trading_halted = False

        # Grupos de correlacion (pares que se mueven juntos)
        self.correlation_groups = [
            {'BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT'},  # Large caps
            {'XRP-USDT', 'ADA-USDT', 'DOT-USDT', 'ATOM-USDT'},  # Alt L1s
            {'DOGE-USDT', 'SHIB-USDT', 'PEPE-USDT', 'FLOKI-USDT'},  # Memecoins
            {'LINK-USDT', 'GRT-USDT', 'API3-USDT'},              # Oracles
        ]

    def reset_daily(self):
        """Resetea contadores diarios a medianoche."""
        today = date.today()
        if today != self.daily_date:
            log.info(f"Nuevo dia - reset PnL diario (era {self.daily_pnl:+.2f} USDT)")
            self.daily_pnl      = 0.0
            self.daily_date     = today
            self.trading_halted = False

    def record_pnl(self, pnl_usdt: float, balance: float):
        """Registra PnL y verifica limite diario."""
        self.reset_daily()
        self.daily_pnl += pnl_usdt

        daily_loss_pct = (self.daily_pnl / balance * 100) if balance > 0 else 0

        if daily_loss_pct <= -self.max_daily_loss_pct:
            self.trading_halted = True
            log.warning(f"LIMITE DIARIO ALCANZADO: {daily_loss_pct:.1f}% - Trading pausado hasta manana")
            return False
        return True

    def can_trade(self, symbol: str, open_trades: dict,
                  balance: float, risk_pct: float) -> tuple:
        """
        Verifica si se puede abrir un trade.
        Returns: (bool, razon)
        """
        self.reset_daily()

        if self.trading_halted:
            return False, "Trading pausado - limite diario alcanzado"

        # Verificar riesgo total
        total_risk = len(open_trades) * risk_pct
        if total_risk + risk_pct > self.max_total_risk_pct:
            return False, f"Riesgo total maximo ({self.max_total_risk_pct}%) alcanzado"

        # Verificar correlacion
        correlated_open = self._count_correlated(symbol, list(open_trades.keys()))
        if correlated_open >= self.max_correlated_trades:
            return False, f"Demasiados trades correlacionados ({correlated_open})"

        return True, "OK"

    def _count_correlated(self, symbol: str, open_symbols: List[str]) -> int:
        """Cuenta cuantos trades abiertos estan correlacionados con el simbolo."""
        for group in self.correlation_groups:
            if symbol in group:
                return sum(1 for s in open_symbols if s in group)
        return 0

    def calc_position_size(self, balance: float, price: float,
                            sl: float, risk_pct: float,
                            leverage: int, atr_pct: float = None) -> float:
        """
        Position sizing ajustado por volatilidad.
        Pares mas volatiles reciben menos capital automaticamente.
        """
        risk_usdt = balance * (risk_pct / 100)
        sl_pct    = max(abs(price - sl) / price, 0.005)

        # Ajuste por volatilidad: si ATR% es alto, reducir size
        vol_adj = 1.0
        if atr_pct is not None:
            if atr_pct > 0.05:    vol_adj = 0.5   # muy volatil -> 50%
            elif atr_pct > 0.03:  vol_adj = 0.75  # algo volatil -> 75%

        size     = (risk_usdt / sl_pct) * leverage * vol_adj
        max_size = balance * leverage * 0.12
        return round(max(min(size, max_size), 5.0), 2)

    def get_status(self) -> dict:
        return {
            'daily_pnl':       round(self.daily_pnl, 2),
            'trading_halted':  self.trading_halted,
            'date':            str(self.daily_date),
        }
