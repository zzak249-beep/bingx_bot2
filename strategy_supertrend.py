"""
strategy_supertrend.py v2
- ATR calculado una sola vez (cache)
- Filtro de volumen
- Divergencias RSI como confirmacion extra
- Confianza mas granular
"""
import pandas as pd
from indicators_supertrend import (supertrend_zero_lag, rsi_advanced,
                                    dynamic_sl_tp, calc_atr,
                                    volume_filter, rsi_divergence)


class SupertrendRSIStrategy:
    def __init__(self, st_period=10, st_mult=3.0, rsi_period=14,
                 rsi_ob=65, rsi_os=35, min_confidence=70,
                 sl_mult=1.5, tp_mult=2.5):
        self.st_period      = st_period
        self.st_mult        = st_mult
        self.rsi_period     = rsi_period
        self.rsi_ob         = rsi_ob
        self.rsi_os         = rsi_os
        self.min_confidence = min_confidence
        self.sl_mult        = sl_mult
        self.tp_mult        = tp_mult

    def get_signal(self, df: pd.DataFrame) -> dict:
        min_bars = max(self.st_period * 3, self.rsi_period * 3, 40)
        if len(df) < min_bars:
            return {'signal':0,'confidence':0,'rsi':50.0,'sl':0.0,'tp':0.0,'reason':'Datos insuficientes','divergence':'none'}

        df = df.copy().reset_index(drop=True)

        # Calcular ATR una sola vez y reutilizar
        atr_cache = calc_atr(df, self.st_period)

        st, direction = supertrend_zero_lag(df, self.st_period, self.st_mult, atr_cache=atr_cache)
        rsi           = rsi_advanced(df['close'], self.rsi_period)
        divergence    = rsi_divergence(df, rsi)

        curr_dir  = int(direction.iloc[-1])
        prev_dir  = int(direction.iloc[-2])
        curr_rsi  = float(rsi.iloc[-1])
        prev_rsi  = float(rsi.iloc[-2])

        # Filtro de volumen - ignorar señal si volumen muy bajo
        if not volume_filter(df):
            return {'signal':0,'confidence':0,'rsi':round(curr_rsi,2),'sl':0.0,'tp':0.0,
                    'reason':'Volumen insuficiente','divergence':divergence}

        signal = confidence = 0
        reason = "Sin senal"

        if curr_dir == 1:  # LONG
            signal = 1; confidence = 60
            reason = "Supertrend alcista"
            if prev_dir == -1:
                confidence += 15; reason = "Cruce alcista ST"
            if curr_rsi < self.rsi_os:
                confidence += 15; reason += " + RSI oversold"
            elif curr_rsi < 50:
                confidence += 5
            if prev_rsi < curr_rsi:
                confidence += 5
            if divergence == 'bullish':
                confidence += 10; reason += " + divergencia alcista"

        elif curr_dir == -1:  # SHORT
            signal = -1; confidence = 60
            reason = "Supertrend bajista"
            if prev_dir == 1:
                confidence += 15; reason = "Cruce bajista ST"
            if curr_rsi > self.rsi_ob:
                confidence += 15; reason += " + RSI overbought"
            elif curr_rsi > 50:
                confidence += 5
            if prev_rsi > curr_rsi:
                confidence += 5
            if divergence == 'bearish':
                confidence += 10; reason += " + divergencia bajista"

        confidence = min(confidence, 100)

        if confidence < self.min_confidence:
            signal = 0
            reason = f"Confianza insuficiente ({confidence}% < {self.min_confidence}%)"

        sl, tp = dynamic_sl_tp(df, signal, sl_mult=self.sl_mult,
                               tp_mult=self.tp_mult, atr_cache=atr_cache)

        return {'signal':signal, 'confidence':confidence, 'rsi':round(curr_rsi,2),
                'sl':sl, 'tp':tp, 'reason':reason, 'divergence':divergence}
