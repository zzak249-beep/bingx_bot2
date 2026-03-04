import time
import traceback
from datetime import datetime, timezone
from config import (SYMBOLS, VERSION, POLL_INTERVAL, TRADE_MODE, DASHBOARD_ENABLED)
import data_feed
import strategy
import trader
import risk_manager as rm
import telegram_notifier as tg

# ══════════════════════════════════════════════════════
# main.py — Loop principal v12.3
# Integra: circuit breaker, multi-TF, re-entry,
#          trailing dinámico, dashboard web, comandos TG
# ══════════════════════════════════════════════════════

HEARTBEAT_EVERY = 6   # ciclos (~6h con velas 1h)


def run_cycle(cycle: int):
    balance = trader.get_balance()
    rm.reset_daily_if_needed(balance)
    rm.update_peak(balance)

    # ── Circuit breaker global ─────────────────────────
    blocked, reason = rm.check_circuit_breaker(balance)
    if blocked:
        print(f"\n  ⛔ CIRCUIT BREAKER: {reason}")
        tg.notify_circuit_breaker(reason)
        return

    if rm.is_manually_paused():
        print(f"\n  ⏸  Bot pausado manualmente")
        return

    print(f"\n{'='*56}")
    print(f"  CICLO #{cycle}  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Balance: ${balance:.2f}  Modo: {TRADE_MODE.upper()}")
    print(f"{'='*56}")

    for sym in SYMBOLS:
        try:
            df = data_feed.get_df(sym, interval="1h", limit=300)
            if df.empty:
                print(f"  {sym}: sin datos")
                continue

            current_price = float(df["close"].iloc[-1])
            print(f"  {sym}  precio={current_price:.6g}", end="")

            # ── Gestionar posición abierta ─────────────
            if sym in trader.get_positions():
                trader.check_exits(sym, current_price)
                pos = trader.get_positions().get(sym)
                if pos:
                    sl = pos["sl"]
                    print(f"  → abierta ({pos['side']})  SL:{sl:.5g}")
                else:
                    print(f"  → cerrada en este ciclo")
                continue

            # ── Comprobar re-entry disponible ──────────
            reentry_info = trader.get_reentry_info(sym)

            # ── Buscar señal ───────────────────────────
            sig = strategy.get_signal(df, symbol=sym, reentry_info=reentry_info)

            if sig:
                is_reentry = sig.get("reentry", False)
                tag = " [RE-ENTRY]" if is_reentry else ""
                print(f"  → SEÑAL {sig['side'].upper()} score={sig['score']} rsi={sig['rsi']} 4h={sig['bias_4h']}{tag}")
                if is_reentry:
                    tg.notify_reentry(sym, sig["side"], sig["score"])
                opened = trader.open_trade(sym, sig, balance)
                if opened:
                    balance = trader.get_balance()
            else:
                print(f"  → sin señal")

        except Exception as e:
            msg = f"{sym}: {e}\n{traceback.format_exc()}"
            print(f"  ERROR {msg[:200]}")
            tg.notify_error(msg)

        time.sleep(0.4)

    # ── Heartbeat ──────────────────────────────────────
    if cycle % HEARTBEAT_EVERY == 0:
        open_pos = len(trader.get_positions())
        stats    = rm.get_stats(balance)
        tg.notify_heartbeat(VERSION, cycle, balance, open_pos, TRADE_MODE, stats)


def main():
    balance = trader.get_balance()
    print(f"\n{'='*56}")
    print(f"  BOT {VERSION}  —  {TRADE_MODE.upper()}")
    print(f"  Balance: ${balance:.2f}")
    print(f"  Pares: {len(SYMBOLS)}")
    print(f"  Nuevas funciones:")
    print(f"    ✅ Trailing SL dinámico desde apertura")
    print(f"    ✅ Multi-timeframe 4h confirmación")
    print(f"    ✅ Circuit breaker & drawdown guard")
    print(f"    ✅ Sizing dinámico por ATR")
    print(f"    ✅ Re-entry inteligente")
    print(f"    ✅ Filtro de volumen")
    print(f"    ✅ Scoring con momentum")
    print(f"    ✅ Comandos Telegram bidireccionales")
    print(f"    ✅ Dashboard web tiempo real")
    print(f"{'='*56}\n")

    # Iniciar dashboard web
    if DASHBOARD_ENABLED:
        try:
            from dashboard import start_dashboard
            start_dashboard()
        except Exception as e:
            print(f"  [WEB] Dashboard no disponible: {e}")

    # Iniciar listener de comandos Telegram
    tg.start_command_listener()

    tg.notify_start(VERSION, SYMBOLS, TRADE_MODE, balance)

    cycle = 1
    while True:
        try:
            run_cycle(cycle)
        except Exception as e:
            msg = f"Error fatal ciclo #{cycle}: {e}\n{traceback.format_exc()}"
            print(f"  FATAL: {msg[:300]}")
            tg.notify_error(msg)

        cycle += 1
        print(f"\n  Próximo ciclo en {POLL_INTERVAL//60}min...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
