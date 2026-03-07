#!/usr/bin/env python3
"""
🤖 BOT TRADING v3.0 - OPTIMIZADO MÁXIMA RENTABILIDAD
Estrategia: BB+RSI con TP:SL 3:1 + Learner + Selector dinámico
"""

import time
import traceback
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
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
    log.info("✅ Todos los módulos importados")
except ImportError as e:
    log.error(f"❌ Error importando módulo: {e}")
    raise

# ═══════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════

VERSION       = config.VERSION
HEARTBEAT_N   = 6   # Heartbeat cada N ciclos
STATE_DIR     = Path("bot_state")
STATE_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════
# SELECTOR Y LEARNER
# ═══════════════════════════════════════════════════════

_selector = None
_learner  = None

def _init_selector():
    global _selector
    if not config.SELECTOR_ENABLED:
        return
    try:
        from selector import PairSelector
        _selector = PairSelector()
        active = _selector.update_active_pairs(config.SYMBOLS, n_top=config.SELECTOR_TOP_N)
        log.info(f"✅ Selector activo: {len(active)} pares seleccionados")
    except Exception as e:
        log.warning(f"⚠️  Selector no disponible: {e}")

def _init_learner():
    global _learner
    if not config.LEARNER_ENABLED:
        return
    try:
        from learner import Learner
        _learner = Learner()
        summary = _learner.get_summary()
        log.info(f"✅ Learner activo: {summary['total_trades']} trades analizados")
        if summary.get("top_pairs"):
            log.info(f"   TOP pares: {', '.join(summary['top_pairs'][:5])}")
    except Exception as e:
        log.warning(f"⚠️  Learner no disponible: {e}")

def _get_active_symbols() -> list:
    """Retorna lista de símbolos activos (filtrados por selector si disponible)."""
    symbols = [s for s in config.SYMBOLS if s not in config.BLACKLIST]

    if _selector and config.SELECTOR_ENABLED:
        try:
            active = _selector.state.get("active_pairs", [])
            if active:
                # Operar solo pares en la lista activa
                symbols = [s for s in symbols if s in active]
        except Exception:
            pass

    return symbols


# ═══════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═══════════════════════════════════════════════════════

def diagnose_connections() -> dict:
    diag = {"bingx_api": False, "telegram": False, "data_feed": False, "balance": 0}

    # BingX
    try:
        balance = api.get_balance()
        diag["bingx_api"] = balance >= 0
        diag["balance"] = balance
        log.info(f"  ✅ BingX API — Balance: ${balance:.2f}")
    except Exception as e:
        log.error(f"  ❌ BingX API: {e}")

    # Telegram
    try:
        if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
            diag["telegram"] = True
            log.info("  ✅ Telegram configurado")
        else:
            log.warning("  ⚠️  Telegram no configurado (opcional)")
    except Exception as e:
        log.warning(f"  ⚠️  Telegram: {e}")

    # Data feed
    try:
        test_sym = config.SYMBOLS[0] if config.SYMBOLS else "LINK-USDT"
        df = data_feed.get_df(test_sym, interval="1h", limit=50)
        if not df.empty:
            diag["data_feed"] = True
            log.info(f"  ✅ Data feed — {len(df)} velas de {test_sym}")
        else:
            log.error(f"  ❌ Data feed vacío para {test_sym}")
    except Exception as e:
        log.error(f"  ❌ Data feed: {e}")

    return diag


# ═══════════════════════════════════════════════════════
# CICLO PRINCIPAL
# ═══════════════════════════════════════════════════════

def run_cycle(cycle: int) -> tuple:
    """Ejecuta un ciclo completo de trading."""
    try:
        balance = trader.get_balance()
        rm.reset_daily_if_needed(balance)
        rm.update_peak(balance)

        # Circuit breaker
        blocked, reason = rm.check_circuit_breaker(balance)
        if blocked:
            log.warning(f"⛔ CIRCUIT BREAKER: {reason}")
            tg.notify_circuit_breaker(reason)
            return 0, 0

        if rm.is_manually_paused():
            log.info("⏸️  Bot pausado (/resume para reactivar)")
            return 0, 0

        # Header
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log.info("=" * 65)
        log.info(f"CICLO #{cycle}  |  {now_str}  |  Balance: ${balance:.2f}")
        log.info("=" * 65)

        signals_found = 0
        trades_opened = 0

        # Símbolos activos (filtrados)
        active_symbols = _get_active_symbols()
        log.info(f"📋 Procesando {len(active_symbols)} pares activos")

        for sym in active_symbols:
            try:
                # Descargar datos
                df = data_feed.get_df(sym, interval=config.CANDLE_TF, limit=300)
                if df.empty:
                    continue

                current_price = float(df["close"].iloc[-1])

                # Gestionar posición abierta
                if sym in trader.get_positions():
                    trader.check_exits(sym, current_price)
                    continue

                # Buscar señal
                reentry_info = trader.get_reentry_info(sym)
                signal = strategy.get_signal(df, symbol=sym, reentry_info=reentry_info)

                if signal:
                    signals_found += 1
                    tag = " [RE-ENTRY]" if signal.get("reentry") else ""
                    log.info(
                        f"{sym}: 🚀 {signal['side'].upper()} | "
                        f"score={signal['score']} rsi={signal['rsi']} "
                        f"rr={((signal['tp']-signal['price'])/abs(signal['price']-signal['sl'])):.2f} "
                        f"4h={signal['bias_4h']}{tag}"
                    )

                    opened = trader.open_trade(sym, signal, balance)
                    if opened:
                        trades_opened += 1
                        balance = trader.get_balance()

                time.sleep(0.25)

            except Exception as e:
                log.error(f"{sym}: ERROR — {str(e)[:200]}")
                tg.notify_error(f"{sym}: {str(e)[:150]}")

        # Heartbeat
        if cycle % HEARTBEAT_N == 0:
            stats = rm.get_stats(balance)
            summary = trader.get_summary()
            log.info(
                f"💓 HEARTBEAT ciclo={cycle} señales={signals_found} "
                f"trades={trades_opened} wr={summary.get('wr', 0)}% "
                f"pf={summary.get('pf', 0)}"
            )
            tg.notify_heartbeat(VERSION, cycle, balance,
                                len(trader.get_positions()), config.TRADE_MODE, stats)

        # Actualizar learner cada 50 ciclos
        if cycle % 50 == 0 and _learner:
            try:
                _learner.update()
                log.info("🧠 Learner actualizado")
            except Exception:
                pass

        # Rotar selector cada SELECTOR_ROTATE_H horas
        rotate_cycles = config.SELECTOR_ROTATE_H * 3600 // config.POLL_INTERVAL
        if cycle % max(rotate_cycles, 1) == 0 and _selector:
            try:
                active = _selector.update_active_pairs(
                    config.SYMBOLS, n_top=config.SELECTOR_TOP_N
                )
                log.info(f"🔄 Selector rotado: {len(active)} pares activos")
            except Exception:
                pass

        log.info(f"✅ Ciclo #{cycle} — {signals_found} señal(es) | {trades_opened} trade(s)\n")
        return signals_found, trades_opened

    except Exception as e:
        log.error(f"ERROR FATAL ciclo #{cycle}: {str(e)}", exc_info=True)
        tg.notify_error(f"Ciclo #{cycle}: {str(e)[:200]}")
        return 0, 0


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    log.info("=" * 65)
    log.info(f"🤖 BOT TRADING {VERSION}")
    log.info(f"📊 Modo: {config.TRADE_MODE.upper()}")
    log.info(f"📈 Pares config: {len(config.SYMBOLS)}")
    log.info(f"⚡ Leverage: {config.LEVERAGE}x")
    log.info(f"🎯 TP:SL ratio: {config.TP_ATR_MULT}:{config.SL_ATR_MULT} ATR")
    log.info(f"⏱️  Intervalo: {config.POLL_INTERVAL // 60} min")
    log.info("=" * 65)

    # Diagnóstico
    log.info("\n🔍 DIAGNÓSTICO DE SISTEMA:")
    diag = diagnose_connections()

    if not diag["bingx_api"]:
        log.error("❌ BingX API no disponible. Verifica BINGX_API_KEY y BINGX_API_SECRET")
        raise RuntimeError("BingX API no disponible")

    if not diag["data_feed"]:
        log.error("❌ Data feed no disponible. Verifica los símbolos en SYMBOLS")
        raise RuntimeError("Data feed no disponible")

    # Inicializar módulos inteligentes
    log.info("\n🧠 INICIALIZANDO MÓDULOS:")
    _init_learner()
    _init_selector()

    active = _get_active_symbols()
    log.info(f"✅ {len(active)} pares activos tras filtros")

    # Configuración activa
    log.info("\n📋 CONFIGURACIÓN ACTIVA:")
    log.info(f"  TP: {config.TP_ATR_MULT}x ATR | SL: {config.SL_ATR_MULT}x ATR | Ratio: ~{config.TP_ATR_MULT/config.SL_ATR_MULT:.1f}:1")
    log.info(f"  Score MIN: {config.SCORE_MIN} | RSI LONG < {config.RSI_LONG} | RSI SHORT > {config.RSI_SHORT}")
    log.info(f"  Max posiciones: {config.MAX_POSITIONS} | Risk/trade: {config.RISK_PCT*100:.0f}%")
    log.info(f"  MTF 4h: {'✅' if config.MTF_ENABLED else '❌'} | Selector: {'✅' if config.SELECTOR_ENABLED else '❌'} | Learner: {'✅' if config.LEARNER_ENABLED else '❌'}")

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
        tg.notify_start(VERSION, active, config.TRADE_MODE, diag["balance"])
        log.info("✅ Telegram activo")
    except Exception as e:
        log.warning(f"⚠️  Telegram: {e}")

    log.info(f"\n{'='*65}")
    log.info("🚀 BOT INICIADO — Esperando ciclos...")
    log.info(f"{'='*65}\n")

    # Loop principal
    cycle     = 1
    stats_log = []

    while True:
        try:
            signals, trades = run_cycle(cycle)

            stats_log.append({
                "cycle":     cycle,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signals":   signals,
                "trades":    trades,
                "balance":   trader.get_balance(),
            })

            if cycle % 10 == 0:
                try:
                    with open(STATE_DIR / "stats.json", "w") as f:
                        json.dump(stats_log[-100:], f, indent=2)
                except Exception:
                    pass

            cycle += 1
            log.info(f"⏰ Próximo ciclo en {config.POLL_INTERVAL // 60}min")
            time.sleep(config.POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("\n⏹️  Bot detenido (Ctrl+C)")
            break
        except Exception as e:
            log.error(f"ERROR FATAL: {str(e)}", exc_info=True)
            tg.notify_error(f"Error fatal: {str(e)[:150]}")
            time.sleep(60)
            cycle += 1


if __name__ == "__main__":
    main()
