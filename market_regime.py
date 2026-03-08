"""
market_regime.py - Detector de regimen de mercado
Clasifica cada par en: TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE
Y selecciona la estrategia optima para cada regimen.
"""

import pandas as pd
import numpy as np
from enum import Enum


class Regime(str, Enum):
    TRENDING_UP   = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING       = "RANGING"       # Lateral - usa BB reversion
    VOLATILE      = "VOLATILE"      # Alta volatilidad - reduce size


class MarketRegimeDetector:
    """
    Detecta el regimen de mercado usando:
    - ADX (fuerza de tendencia)
    - Bollinger Band Width (volatilidad)
    - EMA slope (direccion)
    - ATR relativo (volatilidad normalizada)
    """

    def __init__(self,
                 adx_period: int = 14,
                 adx_trend_threshold: float = 25.0,
                 adx_strong_threshold: float = 40.0,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 atr_volatile_mult: float = 2.5):
        self.adx_period           = adx_period
        self.adx_trend_threshold  = adx_trend_threshold
        self.adx_strong_threshold = adx_strong_threshold
        self.bb_period            = bb_period
        self.bb_std               = bb_std
        self.atr_volatile_mult    = atr_volatile_mult

    # ------------------------------------------------------------------

    def calc_adx(self, df: pd.DataFrame) -> pd.Series:
        high  = df['high']
        low   = df['low']
        close = df['close']
        n     = self.adx_period

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        dm_plus  = (high - high.shift(1)).clip(lower=0)
        dm_minus = (low.shift(1) - low).clip(lower=0)
        mask     = dm_plus < dm_minus
        dm_plus[mask]  = 0
        mask2    = dm_minus < dm_plus
        dm_minus[mask2] = 0

        atr14    = tr.ewm(span=n, adjust=False).mean()
        di_plus  = 100 * dm_plus.ewm(span=n, adjust=False).mean()  / atr14.replace(0, np.nan)
        di_minus = 100 * dm_minus.ewm(span=n, adjust=False).mean() / atr14.replace(0, np.nan)
        dx       = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan))
        adx      = dx.ewm(span=n, adjust=False).mean()
        return adx.fillna(0)

    def calc_bb_width(self, df: pd.DataFrame) -> pd.Series:
        mid  = df['close'].rolling(self.bb_period).mean()
        std  = df['close'].rolling(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        width = (upper - lower) / mid.replace(0, np.nan)
        return width.fillna(0)

    def calc_atr_pct(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']; low = df['low']; close = df['close']
        tr   = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr  = tr.ewm(span=period, adjust=False).mean()
        return (atr / close.replace(0, np.nan)).fillna(0)

    def calc_ema_slope(self, df: pd.DataFrame, period: int = 20) -> float:
        ema   = df['close'].ewm(span=period, adjust=False).mean()
        slope = (ema.iloc[-1] - ema.iloc[-period]) / ema.iloc[-period]
        return float(slope)

    # ------------------------------------------------------------------

    def detect(self, df: pd.DataFrame) -> dict:
        """
        Analiza el DataFrame y retorna:
        {
          'regime': Regime,
          'adx': float,
          'bb_width': float,
          'atr_pct': float,
          'ema_slope': float,
          'confidence': float,   # 0-1
        }
        """
        if len(df) < max(self.adx_period * 2, self.bb_period * 2):
            return {'regime': Regime.RANGING, 'adx': 0, 'bb_width': 0,
                    'atr_pct': 0, 'ema_slope': 0, 'confidence': 0}

        adx       = float(self.calc_adx(df).iloc[-1])
        bb_width  = float(self.calc_bb_width(df).iloc[-1])
        atr_pct   = float(self.calc_atr_pct(df).iloc[-1])
        ema_slope = self.calc_ema_slope(df)

        # ATR medio historico (para comparar si es "muy volatil")
        atr_mean  = float(self.calc_atr_pct(df).rolling(50).mean().iloc[-1])
        atr_ratio = atr_pct / atr_mean if atr_mean > 0 else 1.0

        # --- Clasificacion ---
        if atr_ratio > self.atr_volatile_mult:
            regime     = Regime.VOLATILE
            confidence = min(atr_ratio / self.atr_volatile_mult, 1.0)

        elif adx >= self.adx_trend_threshold:
            if ema_slope > 0:
                regime = Regime.TRENDING_UP
            else:
                regime = Regime.TRENDING_DOWN
            confidence = min((adx - self.adx_trend_threshold) /
                             (self.adx_strong_threshold - self.adx_trend_threshold), 1.0)

        else:
            regime     = Regime.RANGING
            confidence = 1.0 - (adx / self.adx_trend_threshold)

        return {
            'regime':     regime,
            'adx':        round(adx, 2),
            'bb_width':   round(bb_width, 4),
            'atr_pct':    round(atr_pct, 4),
            'ema_slope':  round(ema_slope, 6),
            'confidence': round(confidence, 2),
        }


# ------------------------------------------------------------------
# ESTRATEGIA PARA MERCADO LATERAL (Bollinger Band Mean Reversion)
# ------------------------------------------------------------------

class RangingStrategy:
    """
    Estrategia para mercado lateral.
    Entra en reversiones cuando el precio toca las bandas de Bollinger
    y el RSI confirma sobrecompra/sobreventa.
    """

    def __init__(self, bb_period=20, bb_std=2.0,
                 rsi_period=14, rsi_ob=70, rsi_os=30):
        self.bb_period  = bb_period
        self.bb_std     = bb_std
        self.rsi_period = rsi_period
        self.rsi_ob     = rsi_ob
        self.rsi_os     = rsi_os

    def get_signal(self, df: pd.DataFrame) -> dict:
        if len(df) < self.bb_period * 2:
            return {'signal': 0, 'confidence': 0, 'rsi': 50,
                    'sl': 0, 'tp': 0, 'reason': 'Datos insuficientes'}

        close  = df['close']
        mid    = close.rolling(self.bb_period).mean()
        std    = close.rolling(self.bb_period).std()
        upper  = mid + self.bb_std * std
        lower  = mid - self.bb_std * std

        # RSI simple
        delta     = close.diff()
        gain      = delta.clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        loss      = (-delta).clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        rs        = gain / loss.replace(0, np.inf)
        rsi       = 100 - (100 / (1 + rs))

        price     = float(close.iloc[-1])
        curr_rsi  = float(rsi.iloc[-1])
        curr_up   = float(upper.iloc[-1])
        curr_low  = float(lower.iloc[-1])
        curr_mid  = float(mid.iloc[-1])

        band_width = (curr_up - curr_low) / curr_mid if curr_mid > 0 else 0

        signal     = 0
        confidence = 0
        reason     = "Sin senal BB"

        # LONG: precio en banda inferior + RSI oversold
        if price <= curr_low and curr_rsi <= self.rsi_os:
            signal     = 1
            confidence = 70
            reason     = "BB inferior + RSI oversold"
            if curr_rsi < self.rsi_os - 5:
                confidence += 10
            sl = price - (curr_up - curr_low) * 0.2
            tp = curr_mid

        # SHORT: precio en banda superior + RSI overbought
        elif price >= curr_up and curr_rsi >= self.rsi_ob:
            signal     = -1
            confidence = 70
            reason     = "BB superior + RSI overbought"
            if curr_rsi > self.rsi_ob + 5:
                confidence += 10
            sl = price + (curr_up - curr_low) * 0.2
            tp = curr_mid

        else:
            sl = tp = price

        return {
            'signal':     signal,
            'confidence': confidence,
            'rsi':        round(curr_rsi, 2),
            'sl':         round(sl, 8),
            'tp':         round(tp, 8),
            'reason':     reason,
            'band_width': round(band_width, 4),
        }
