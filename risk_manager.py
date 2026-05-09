"""
Gestión de riesgo: calcula tamaño de posición basado en % de capital.
Regla: arriesgar max_risk_pct del balance en cada trade.
"""

import logging

log = logging.getLogger("RiskManager")


class RiskManager:
    def __init__(self, max_risk_pct: float = 1.0, rr_ratio: float = 3.0):
        """
        max_risk_pct: % del balance a arriesgar por trade (ej: 1.0 = 1%)
        rr_ratio: ratio riesgo/recompensa (3 = 1:3)
        """
        self.max_risk_pct = max_risk_pct / 100
        self.rr_ratio     = rr_ratio

    def calc_qty(self, balance: float, entry: float, sl: float, min_qty: float = 0.001) -> float:
        """
        Calcula cantidad de contratos a abrir.
        qty = (balance * risk_pct) / |entry - sl|
        """
        risk_usd = balance * self.max_risk_pct
        sl_dist  = abs(entry - sl)

        if sl_dist < 1e-8:
            log.warning("SL demasiado cercano al entry, no se abre posición")
            return 0.0

        qty = risk_usd / sl_dist
        qty = max(round(qty, 3), min_qty)
        log.info(f"RiskMgr → balance={balance:.2f} risk={risk_usd:.2f} sl_dist={sl_dist:.4f} qty={qty}")
        return qty

    def check_max_drawdown(self, equity: float, peak_equity: float, max_dd_pct: float = 10.0) -> bool:
        """Retorna True si se supera el drawdown máximo permitido."""
        dd = (peak_equity - equity) / peak_equity * 100
        if dd >= max_dd_pct:
            log.warning(f"⚠️ Drawdown {dd:.1f}% supera límite {max_dd_pct}%")
            return True
        return False
