#!/usr/bin/env python3
"""
🤖 BOT FUSIONADO v2.0 - Main mejorado
Combina BB+RSI Elite + Learning + Análisis
Con testing, logging y debugging integrado
"""

import time
import traceback
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════
# CONFIGURACIÓN DE LOGGING
# ═══════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════

try:
    import config
    import data_feed
    import indicators
    import strategy
    import trader
    import risk_manager as rm
    import telegram_notifier as tg
    import bingx_api as api
    log.info("✅ Todos los módulos importados correctamente")
except ImportError as e:
    log.error(f"❌ Error importando módulo: {e}")
    raise

# ═══════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════

VERSION = "v2.0-FUSION"
HEARTBEAT_EVERY = 6
STATE_DIR = Path("bot_state")
STATE_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════
# DIAGNÓSTICO DE CONEXIÓN
# ═══════════════════════════════════════════════════════

def diagnose_connections():
    """Verificar que todo está conectado correctamente"""
    log.info("🔍 Iniciando diagnóstico...")
    
    diagnostics = {
        "bingx_api": False,
        "telegram": False,
        "data_feed": False,
        "balance": 0,
    }
    
    # Test BingX
    try:
        balance = api.get_balance()
        diagnostics["bingx_api"] = balance >= 0
        diagnostics["balance"] = balance
        if balance >= 0:
            log.info(f"  ✅ BingX API OK - Balance: ${balance:.2f}")
        else:
            log.warning(f"  ⚠️  BingX retorna balance negativo: {balance}")
    except Exception as e:
        log.error(f"  ❌ BingX API FALLA: {e}")
    
    # Test Telegram
    try:
        token = config.TELEGRAM_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
        if token and chat_id:
            diagnostics["telegram"] = True
            log.info(f"  ✅ Telegram configurado (chat: {str(chat_id)[:10]}...)")
        else:
            log.warning("  ⚠️  Telegram no configurado (opcional)")
    except Exception as e:
        log.warning(f"  ⚠️  Telegram error: {e}")
    
    # Test data feed
    try:
        test_symbol = config.SYMBOLS[0] if config.SYMBOLS else "BTCUSDT"
        df = data_feed.get_df(test_symbol, interval="1h", limit=50)
        if not df.empty:
            diagnostics["data_feed"] = True
            log.info(f"  ✅ Data feed OK - {len(df)} velas descargadas de {test_symbol}")
        else:
            log.error(f"  ❌ Data feed vacío para {test_symbol}")
    except Exception as e:
        log.error(f"  ❌ Data feed FALLA: {e}")
    
    return diagnostics

# ═══════════════════════════════════════════════════════
# PROCESAMIENTO DE CICLO
# ═══════════════════════════════════════════════════════

def run_cycle(cycle: int):
    """Ejecuta un ciclo completo de trading"""
    try:
        balance = trader.get_balance()
        rm.reset_daily_if_needed(balance)
        rm.update_peak(balance)
        
        # Circuit breaker
        blocked, reason = rm.check_circuit_breaker(balance)
        if blocked:
            log.warning(f"⛔ CIRCUIT BREAKER ACTIVADO: {reason}")
            tg.notify_circuit_breaker(reason)
            return 0, 0
        
        # Pausa manual
        if rm.is_manually_paused():
            log.info("⏸️  Bot pausado manualmente (/resume para reactivar)")
            return 0, 0
        
        # Header de ciclo
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        log.info("=" * 60)
        log.info(f"CICLO #{cycle}  |  {now_str}  |  Balance: ${balance:.2f}")
        log.info("=" * 60)
        
        signals_found = 0
        trades_opened = 0
        
        # Procesar cada símbolo
        for sym in config.SYMBOLS:
            try:
                # Descargar datos
                df = data_feed.get_df(sym, interval="1h", limit=300)
                if df.empty:
                    log.debug(f"{sym}: sin datos disponibles")
                    continue
                
                current_price = float(df["close"].iloc[-1])
                
                # Gestionar posición abierta
                if sym in trader.get_positions():
                    pos = trader.get_positions()[sym]
                    trader.check_exits(sym, current_price)
                    if sym in trader.get_positions():
                        log.debug(f"{sym}: 🔓 posición abierta {pos['side'].upper()}")
                    else:
                        log.info(f"{sym}: 🔒 posición cerrada en este ciclo")
                    continue
                
                # Buscar señal
                reentry_info = trader.get_reentry_info(sym)
                signal = strategy.get_signal(df, symbol=sym, reentry_info=reentry_info)
                
                if signal:
                    signals_found += 1
                    tag = " [RE-ENTRY]" if signal.get("reentry") else ""
                    log.info(
                        f"{sym}: 🚀 SEÑAL {signal['side'].upper()} | "
                        f"score={signal['score']} | rsi={signal['rsi']} | "
                        f"4h={signal['bias_4h']}{tag}"
                    )
                    
                    if signal.get("reentry"):
                        tg.notify_reentry(sym, signal["side"], signal["score"])
                    
                    opened = trader.open_trade(sym, signal, balance)
                    if opened:
                        trades_opened += 1
                        balance = trader.get_balance()
                
                time.sleep(0.3)
            
            except Exception as e:
                log.error(f"{sym}: ERROR - {str(e)[:200]}", exc_info=False)
                tg.notify_error(f"{sym}: {str(e)[:150]}")
        
        # Heartbeat cada N ciclos
        if cycle % HEARTBEAT_EVERY == 0:
            stats = rm.get_stats(balance)
            log.info(f"💓 HEARTBEAT: {signals_found} señales | {trades_opened} trades abiertos")
            tg.notify_heartbeat(VERSION, cycle, balance, len(trader.get_positions()), 
                               config.TRADE_MODE, stats)
        
        log.info(f"✅ Ciclo #{cycle} completado - {signals_found} señal(es) | {trades_opened} trade(s) abierto(s)\n")
        
        return signals_found, trades_opened
    
    except Exception as e:
        log.error(f"ERROR FATAL en ciclo #{cycle}: {str(e)}", exc_info=True)
        tg.notify_error(f"Ciclo #{cycle}: {str(e)[:200]}")
        return 0, 0

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    """Función principal con diagnóstico e inicialización"""
    
    log.info("=" * 60)
    log.info(f"🤖 BOT FUSIONADO {VERSION}")
    log.info(f"📊 Modo: {config.TRADE_MODE.upper()}")
    log.info(f"📈 Pares: {len(config.SYMBOLS)}")
    log.info(f"⏱️  Intervalo: {config.POLL_INTERVAL // 60} min")
    log.info("=" * 60)
    
    # Diagnóstico
    log.info("\n🔍 DIAGNÓSTICO DE SISTEMA:")
    diag = diagnose_connections()
    
    if not diag["bingx_api"]:
        log.error("❌ ERROR CRÍTICO: No hay conexión a BingX API")
        log.error("   Verifica:")
        log.error("   1. BINGX_API_KEY en variables")
        log.error("   2. BINGX_API_SECRET en variables")
        log.error("   3. API key tiene permiso 'Read' en BingX")
        raise RuntimeError("BingX API no disponible")
    
    if not diag["data_feed"]:
        log.error("❌ ERROR CRÍTICO: No hay datos de BingX")
        log.error("   Verifica que los símbolos en config.SYMBOLS existen")
        raise RuntimeError("Data feed no disponible")
    
    log.info("\n📋 FILTROS ACTIVOS:")
    log.info(f"  RSI LONG < {config.RSI_LONG} | RSI SHORT > {config.RSI_SHORT}")
    log.info(f"  Score mínimo: {config.SCORE_MIN} | R:R mínimo: {config.MIN_RR}")
    log.info(f"  MTF 4h: {'✅' if config.MTF_ENABLED else '❌'}")
    log.info(f"  Volumen: {'✅' if config.VOLUME_FILTER else '❌'}")
    log.info(f"  Re-entry: {'✅' if config.REENTRY_ENABLED else '❌'}")
    log.info(f"  Trailing desde apertura: {'✅' if config.TRAIL_FROM_START else '❌'}")
    
    # Dashboard
    if config.DASHBOARD_ENABLED:
        try:
            from dashboard import start_dashboard
            start_dashboard()
            log.info(f"\n📊 Dashboard en puerto {config.DASHBOARD_PORT}")
        except Exception as e:
            log.warning(f"⚠️  Dashboard no disponible: {e}")
    
    # Telegram
    try:
        tg.start_command_listener()
        tg.notify_start(VERSION, config.SYMBOLS, config.TRADE_MODE, diag["balance"])
        log.info("✅ Telegram listener activo")
    except Exception as e:
        log.warning(f"⚠️  Telegram no disponible: {e}")
    
    log.info(f"\n{'='*60}")
    log.info("🚀 BOT INICIADO - Esperando ciclos...")
    log.info(f"{'='*60}\n")
    
    # Loop principal
    cycle = 1
    stats_log = []
    
    while True:
        try:
            signals, trades = run_cycle(cycle)
            
            # Guardar estadísticas
            stats_log.append({
                "cycle": cycle,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signals": signals,
                "trades": trades,
                "balance": trader.get_balance(),
            })
            
            # Guardar cada 10 ciclos
            if cycle % 10 == 0:
                try:
                    with open(STATE_DIR / "stats.json", "w") as f:
                        json.dump(stats_log[-100:], f, indent=2)
                except Exception as e:
                    log.warning(f"No se guardaron stats: {e}")
            
            cycle += 1
            next_in_sec = config.POLL_INTERVAL
            log.info(f"⏰ Próximo ciclo en {next_in_sec//60}min ({config.POLL_INTERVAL}s)")
            time.sleep(next_in_sec)
        
        except KeyboardInterrupt:
            log.info("\n⏹️  Bot detenido por usuario (Ctrl+C)")
            break
        except Exception as e:
            log.error(f"ERROR FATAL: {str(e)}", exc_info=True)
            tg.notify_error(f"Error fatal: {str(e)[:150]}")
            time.sleep(60)
            cycle += 1

if __name__ == "__main__":
    main()
