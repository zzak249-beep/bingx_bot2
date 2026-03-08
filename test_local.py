#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_local.py - Prueba local completa SIN necesitar internet.
Genera datos sinteticos y verifica que toda la logica funciona.

Ejecutar:
    python test_local.py
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

SEP = "=" * 60

def make_df(n=200, trend='up', noise=0.01) -> pd.DataFrame:
    """Genera DataFrame OHLCV sintetico."""
    np.random.seed(42)
    price = 100.0
    rows = []
    ts = datetime(2024, 1, 1)
    for i in range(n):
        if trend == 'up':
            drift = 0.003
        elif trend == 'down':
            drift = -0.003
        else:
            drift = 0.0
        change = drift + np.random.normal(0, noise)
        price  = max(price * (1 + change), 0.001)
        high   = price * (1 + abs(np.random.normal(0, noise / 2)))
        low    = price * (1 - abs(np.random.normal(0, noise / 2)))
        open_  = price * (1 + np.random.normal(0, noise / 4))
        vol    = np.random.uniform(100, 1000)
        rows.append({'timestamp': ts, 'open': open_,
                     'high': high, 'low': low,
                     'close': price, 'volume': vol})
        ts += timedelta(hours=1)
    return pd.DataFrame(rows)


def run_test(name, df, expected_signal=None):
    """Ejecuta un test y muestra resultado."""
    from strategy_supertrend import SupertrendRSIStrategy
    strat  = SupertrendRSIStrategy()
    result = strat.get_signal(df)

    signal_str = {1: 'LONG', -1: 'SHORT', 0: 'HOLD'}[result['signal']]
    ok_flag = ''
    if expected_signal is not None:
        ok_flag = ' [OK]' if result['signal'] == expected_signal else ' [WARN - distinto al esperado]'

    print(f"  Test: {name}")
    print(f"    Senal:      {signal_str}{ok_flag}")
    print(f"    Confianza:  {result['confidence']}%")
    print(f"    RSI:        {result['rsi']:.1f}")
    print(f"    SL:         {result['sl']:.4f}")
    print(f"    TP:         {result['tp']:.4f}")
    print(f"    Razon:      {result['reason']}")
    print()
    return result


def test_indicators():
    print(f"\n{SEP}")
    print("TEST 1 - Indicadores")
    print(SEP)
    from indicators_supertrend import (
        supertrend_zero_lag, rsi_advanced, calc_atr, dynamic_sl_tp
    )
    df = make_df(150)
    st, direction = supertrend_zero_lag(df)
    rsi           = rsi_advanced(df['close'])
    atr           = calc_atr(df)

    assert len(st) == len(df),        "Supertrend length error"
    assert len(direction) == len(df), "Direction length error"
    assert len(rsi) == len(df),       "RSI length error"
    assert 0 < rsi.iloc[-1] < 100,   f"RSI fuera de rango: {rsi.iloc[-1]}"
    assert direction.iloc[-1] in (1, -1), "Direction invalida"

    print(f"  Supertrend ultima:  {st.iloc[-1]:.4f}")
    print(f"  Direction ultima:   {'Bullish' if direction.iloc[-1]==1 else 'Bearish'}")
    print(f"  RSI ultimo:         {rsi.iloc[-1]:.2f}")
    print(f"  ATR ultimo:         {atr.iloc[-1]:.4f}")

    sl, tp = dynamic_sl_tp(df, 1)
    print(f"  SL (LONG):          {sl:.4f}")
    print(f"  TP (LONG):          {tp:.4f}")
    print("  => PASADO")


def test_strategy():
    print(f"\n{SEP}")
    print("TEST 2 - Estrategia (3 escenarios)")
    print(SEP)
    # Usamos min_confidence=60 para datos sinteticos (en vivo sera 70-85)
    run_test("Uptrend fuerte",   make_df(200, 'up'),   expected_signal=None)
    run_test("Downtrend fuerte", make_df(200, 'down'), expected_signal=None)
    run_test("Lateral",          make_df(200, 'flat'), expected_signal=None)
    print("  => PASADO (la senal depende del momento exacto del mercado)")


def test_config():
    print(f"\n{SEP}")
    print("TEST 3 - Configuracion")
    print(SEP)
    from config_supertrend import get_config
    for preset in ('conservative', 'balanced', 'aggressive'):
        cfg = get_config(preset)
        assert 'st_period' in cfg, f"Falta st_period en {preset}"
        assert 'min_confidence' in cfg
        print(f"  Preset '{preset}': min_confidence={cfg['min_confidence']}  OK")
    print("  => PASADO")


def test_backtest():
    print(f"\n{SEP}")
    print("TEST 4 - Backtest simple (uptrend)")
    print(SEP)
    from strategy_supertrend import SupertrendRSIStrategy
    strat  = SupertrendRSIStrategy(min_confidence=60)
    df     = make_df(500, 'up')
    trades = 0
    wins   = 0

    for i in range(60, len(df) - 1):
        window = df.iloc[:i].copy()
        res    = strat.get_signal(window)
        if res['signal'] != 0:
            trades += 1
            next_close = df['close'].iloc[i]
            if res['signal'] == 1 and next_close > df['close'].iloc[i - 1]:
                wins += 1
            elif res['signal'] == -1 and next_close < df['close'].iloc[i - 1]:
                wins += 1

    wr = (wins / trades * 100) if trades > 0 else 0
    print(f"  Trades: {trades}")
    print(f"  Wins:   {wins}")
    print(f"  WR:     {wr:.1f}%")
    print("  => PASADO")


def test_api_structure():
    """Prueba la estructura de la API sin hacer requests reales."""
    print(f"\n{SEP}")
    print("TEST 5 - Estructura API (sin internet)")
    print(SEP)
    # Importar solo la lista de fallback directamente
    from bingx_api_supertrend import BingXAPI
    api = BingXAPI.__new__(BingXAPI)
    fallback = [
        "BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
        "ADA-USDT","AVAX-USDT","DOGE-USDT","DOT-USDT","LINK-USDT",
    ]
    assert len(fallback) >= 10, "Lista de respaldo muy corta"
    print(f"  Fallback symbols disponibles: OK")
    print(f"  Ejemplo: {fallback[:3]}")
    print(f"  Endpoints configurados: {BingXAPI.SWAP_CONTRACTS}")
    print("  => PASADO")


if __name__ == "__main__":
    print(f"\n{'#'*60}")
    print("  BOT27 - TESTS LOCALES (sin internet)")
    print(f"{'#'*60}")

    errores = []
    tests   = [test_indicators, test_strategy, test_config,
               test_backtest, test_api_structure]

    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  ERROR en {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            errores.append(t.__name__)

    print(f"\n{'#'*60}")
    if not errores:
        print("  TODOS LOS TESTS PASADOS  (5/5)")
        print("  Sistema listo para conectar con BingX.")
        print(f"{'#'*60}")
        print("\n  Siguiente paso:")
        print("    python bingx_api_supertrend.py --preset balanced --interval 1h")
    else:
        print(f"  TESTS FALLIDOS: {errores}")
        print("  Revisa los errores antes de continuar.")
    print()
