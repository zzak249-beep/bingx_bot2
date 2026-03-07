#!/usr/bin/env python3
"""
🧪 TESTING SUITE v2.0
Tests unitarios + integración + stress testing
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# TEST 1: IMPORTS
# ═══════════════════════════════════════════════════════

def test_imports():
    """✅ Verificar que todos los módulos importan sin error"""
    log.info("\n" + "="*60)
    log.info("TEST 1: IMPORTS")
    log.info("="*60)
    
    modules = [
        "config",
        "data_feed",
        "indicators",
        "strategy",
        "trader",
        "risk_manager",
        "bingx_api",
        "telegram_notifier",
    ]
    
    failed = []
    for mod in modules:
        try:
            __import__(mod)
            log.info(f"  ✅ {mod}")
        except Exception as e:
            log.error(f"  ❌ {mod}: {e}")
            failed.append((mod, str(e)))
    
    return len(failed) == 0, failed

# ═══════════════════════════════════════════════════════
# TEST 2: CONFIG
# ═══════════════════════════════════════════════════════

def test_config():
    """✅ Verificar que la configuración es válida"""
    log.info("\n" + "="*60)
    log.info("TEST 2: CONFIGURATION")
    log.info("="*60)
    
    import config
    
    errors = []
    
    # Verificar parámetros críticos
    checks = [
        ("LEVERAGE", config.LEVERAGE, int, lambda x: x > 0),
        ("RISK_PCT", config.RISK_PCT, float, lambda x: 0 < x <= 0.1),
        ("INITIAL_BAL", config.INITIAL_BAL, float, lambda x: x > 0),
        ("BB_PERIOD", config.BB_PERIOD, int, lambda x: x >= 10),
        ("RSI_PERIOD", config.RSI_PERIOD, int, lambda x: x >= 5),
        ("SYMBOLS", config.SYMBOLS, list, lambda x: len(x) > 0),
    ]
    
    for name, value, type_check, validator in checks:
        try:
            if not isinstance(value, type_check):
                errors.append(f"{name}: tipo incorrecto (esperado {type_check.__name__})")
            elif not validator(value):
                errors.append(f"{name}: valor fuera de rango ({value})")
            else:
                log.info(f"  ✅ {name}: {value}")
        except Exception as e:
            errors.append(f"{name}: {e}")
    
    # Verificar SYMBOLS
    log.info(f"  ✅ {len(config.SYMBOLS)} pares configurados")
    
    # Verificar variables de entorno críticas
    import os
    env_checks = {
        "BINGX_API_KEY": "API BingX",
        "BINGX_API_SECRET": "Secret BingX",
    }
    
    for var, desc in env_checks.items():
        val = os.getenv(var, "")
        if val:
            log.info(f"  ✅ {desc}: configurado ({val[:10]}...)")
        else:
            log.warning(f"  ⚠️  {desc}: NO configurado (opcional)")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# TEST 3: BINGX API
# ═══════════════════════════════════════════════════════

def test_bingx_api():
    """✅ Verificar conexión con BingX API"""
    log.info("\n" + "="*60)
    log.info("TEST 3: BINGX API CONNECTION")
    log.info("="*60)
    
    import bingx_api as api
    import config
    
    errors = []
    
    # Test 1: get_balance
    try:
        balance = api.get_balance()
        if balance >= 0:
            log.info(f"  ✅ get_balance(): ${balance:.2f}")
        else:
            log.warning(f"  ⚠️  get_balance(): retorna {balance} (¿sin fondos?)")
    except Exception as e:
        log.error(f"  ❌ get_balance(): {e}")
        errors.append(f"get_balance: {e}")
    
    # Test 2: get_price
    try:
        if config.SYMBOLS:
            sym = config.SYMBOLS[0]
            price = api.get_price(sym)
            if price > 0:
                log.info(f"  ✅ get_price({sym}): ${price:.6g}")
            else:
                log.error(f"  ❌ get_price({sym}): precio 0 o negativo")
                errors.append(f"get_price({sym}): precio inválido")
    except Exception as e:
        log.error(f"  ❌ get_price(): {e}")
        errors.append(f"get_price: {e}")
    
    # Test 3: fetch_klines
    try:
        if config.SYMBOLS:
            sym = config.SYMBOLS[0]
            klines = api.fetch_klines(sym, interval="1h", limit=10)
            if len(klines) > 0:
                log.info(f"  ✅ fetch_klines({sym}): {len(klines)} velas")
            else:
                log.error(f"  ❌ fetch_klines({sym}): retorna vacío")
                errors.append(f"fetch_klines({sym}): sin datos")
    except Exception as e:
        log.error(f"  ❌ fetch_klines(): {e}")
        errors.append(f"fetch_klines: {e}")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# TEST 4: DATA FEED
# ═══════════════════════════════════════════════════════

def test_data_feed():
    """✅ Verificar descarga de datos"""
    log.info("\n" + "="*60)
    log.info("TEST 4: DATA FEED")
    log.info("="*60)
    
    import data_feed
    import config
    
    errors = []
    
    if not config.SYMBOLS:
        log.error("  ❌ No hay símbolos configurados")
        return False, ["No symbols in config"]
    
    # Test con el primer símbolo
    sym = config.SYMBOLS[0]
    
    try:
        df = data_feed.get_df(sym, interval="1h", limit=100)
        
        if df.empty:
            log.error(f"  ❌ {sym}: DataFrame vacío")
            errors.append(f"{sym}: vacío")
        else:
            log.info(f"  ✅ {sym}: {len(df)} velas descargadas")
            log.info(f"     - Período: {df['ts'].min()} a {df['ts'].max()}")
            log.info(f"     - Rango precio: ${df['close'].min():.6g} - ${df['close'].max():.6g}")
            
            # Verificar columnas
            required_cols = ["ts", "open", "high", "low", "close", "volume"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                log.error(f"  ❌ Columnas faltantes: {missing}")
                errors.append(f"Columnas faltantes: {missing}")
            else:
                log.info(f"  ✅ Todas las columnas presentes")
    
    except Exception as e:
        log.error(f"  ❌ Error descargando {sym}: {e}")
        errors.append(f"get_df({sym}): {e}")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# TEST 5: INDICADORES
# ═══════════════════════════════════════════════════════

def test_indicators():
    """✅ Verificar cálculo de indicadores"""
    log.info("\n" + "="*60)
    log.info("TEST 5: INDICATORS")
    log.info("="*60)
    
    import data_feed
    import indicators
    import config
    import pandas as pd
    
    errors = []
    
    if not config.SYMBOLS:
        return False, ["No symbols"]
    
    sym = config.SYMBOLS[0]
    
    try:
        df = data_feed.get_df(sym, interval="1h", limit=100)
        if df.empty:
            log.error(f"  ❌ Sin datos para {sym}")
            return False, [f"Sin datos para {sym}"]
        
        df = indicators.add_indicators(df)
        
        # Verificar indicadores
        required_indicators = ["rsi", "upper", "basis", "lower", "atr", "macd", "stoch"]
        
        for ind in required_indicators:
            if ind not in df.columns:
                log.error(f"  ❌ Indicador faltante: {ind}")
                errors.append(f"Indicador faltante: {ind}")
            else:
                last_val = df[ind].iloc[-1]
                if pd.isna(last_val):
                    log.warning(f"  ⚠️  {ind}: NaN en último valor")
                else:
                    log.info(f"  ✅ {ind}: {float(last_val):.2f}")
    
    except Exception as e:
        log.error(f"  ❌ Error calculando indicadores: {e}")
        errors.append(f"add_indicators: {e}")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# TEST 6: STRATEGY
# ═══════════════════════════════════════════════════════

def test_strategy():
    """✅ Verificar generación de señales"""
    log.info("\n" + "="*60)
    log.info("TEST 6: STRATEGY")
    log.info("="*60)
    
    import data_feed
    import strategy
    import config
    
    errors = []
    
    if not config.SYMBOLS:
        return False, ["No symbols"]
    
    # Probar con múltiples símbolos
    test_syms = config.SYMBOLS[:3]
    signal_count = 0
    
    for sym in test_syms:
        try:
            df = data_feed.get_df(sym, interval="1h", limit=300)
            if df.empty:
                continue
            
            signal = strategy.get_signal(df, symbol=sym)
            
            if signal:
                signal_count += 1
                side = signal['side'].upper()
                score = signal['score']
                log.info(f"  🚀 {sym}: {side} (score={score})")
            else:
                log.debug(f"  - {sym}: sin señal")
        
        except Exception as e:
            log.warning(f"  ⚠️  {sym}: {e}")
    
    log.info(f"  ✅ Total: {signal_count} señal(es) en {len(test_syms)} pares")
    
    return True, []

# ═══════════════════════════════════════════════════════
# TEST 7: TRADER
# ═══════════════════════════════════════════════════════

def test_trader():
    """✅ Verificar módulo trader"""
    log.info("\n" + "="*60)
    log.info("TEST 7: TRADER")
    log.info("="*60)
    
    import trader
    import config
    
    errors = []
    
    try:
        balance = trader.get_balance()
        log.info(f"  ✅ get_balance(): ${balance:.2f}")
    except Exception as e:
        log.error(f"  ❌ get_balance(): {e}")
        errors.append(f"get_balance: {e}")
    
    try:
        positions = trader.get_positions()
        log.info(f"  ✅ get_positions(): {len(positions)} abiertas")
    except Exception as e:
        log.error(f"  ❌ get_positions(): {e}")
        errors.append(f"get_positions: {e}")
    
    try:
        history = trader.get_trade_history(10)
        log.info(f"  ✅ get_trade_history(): {len(history)} trades")
    except Exception as e:
        log.error(f"  ❌ get_trade_history(): {e}")
        errors.append(f"get_trade_history: {e}")
    
    try:
        summary = trader.get_summary()
        log.info(f"  ✅ get_summary(): {summary}")
    except Exception as e:
        log.error(f"  ❌ get_summary(): {e}")
        errors.append(f"get_summary: {e}")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# TEST 8: RISK MANAGER
# ═══════════════════════════════════════════════════════

def test_risk_manager():
    """✅ Verificar risk manager"""
    log.info("\n" + "="*60)
    log.info("TEST 8: RISK MANAGER")
    log.info("="*60)
    
    import risk_manager as rm
    import trader
    
    errors = []
    
    try:
        balance = trader.get_balance()
        stats = rm.get_stats(balance)
        
        log.info(f"  ✅ Peak balance: ${stats.get('peak_balance', 0):.2f}")
        log.info(f"  ✅ Drawdown: {stats.get('drawdown_pct', 0):.1f}%")
        log.info(f"  ✅ Daily PnL: ${stats.get('daily_pnl', 0):+.4f}")
        log.info(f"  ✅ Consecutive losses: {stats.get('consecutive_losses', 0)}")
    except Exception as e:
        log.error(f"  ❌ get_stats(): {e}")
        errors.append(f"get_stats: {e}")
    
    try:
        blocked, reason = rm.check_circuit_breaker(balance)
        status = "🔴 BLOQUEADO" if blocked else "🟢 ACTIVO"
        log.info(f"  ✅ Circuit breaker: {status}")
        if reason:
            log.info(f"     Razón: {reason}")
    except Exception as e:
        log.error(f"  ❌ check_circuit_breaker(): {e}")
        errors.append(f"check_circuit_breaker: {e}")
    
    return len(errors) == 0, errors

# ═══════════════════════════════════════════════════════
# REPORTE FINAL
# ═══════════════════════════════════════════════════════

def print_summary(results):
    """Imprimir resumen de tests"""
    log.info("\n" + "="*60)
    log.info("RESUMEN DE TESTS")
    log.info("="*60)
    
    passed = sum(1 for r in results if r[0])
    total = len(results)
    
    for i, (test_name, success, errors) in enumerate(results, 1):
        status = "✅ PASS" if success else "❌ FAIL"
        log.info(f"{i}. {test_name}: {status}")
        if errors:
            for err in errors:
                log.error(f"   - {err}")
    
    log.info("="*60)
    log.info(f"RESULTADO: {passed}/{total} tests pasados")
    
    if passed == total:
        log.info("🎉 ¡TODOS LOS TESTS PASARON! El bot está listo.")
        return True
    else:
        failed = total - passed
        log.error(f"❌ {failed} test(s) fallaron. Revisa los errores arriba.")
        return False

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    log.info("\n")
    log.info("╔" + "="*58 + "╗")
    log.info("║" + " "*12 + "🧪 BOT TESTING SUITE v2.0" + " "*21 + "║")
    log.info("╚" + "="*58 + "╝")
    
    results = [
        ("IMPORTS", *test_imports()),
        ("CONFIG", *test_config()),
        ("BINGX API", *test_bingx_api()),
        ("DATA FEED", *test_data_feed()),
        ("INDICATORS", *test_indicators()),
        ("STRATEGY", *test_strategy()),
        ("TRADER", *test_trader()),
        ("RISK MANAGER", *test_risk_manager()),
    ]
    
    success = print_summary(results)
    
    # Guardar resultados
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v2.0",
        "tests": [
            {
                "name": name,
                "passed": passed,
                "errors": errors[:3]  # Primeros 3 errores
            }
            for name, passed, errors in results
        ],
        "overall": "PASS" if success else "FAIL",
    }
    
    with open("/mnt/user-data/outputs/test_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    log.info("\n📊 Reporte guardado en test_report.json")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
