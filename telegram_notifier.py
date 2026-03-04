import requests
import threading
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

# ══════════════════════════════════════════════════════
# telegram_notifier.py — Notificaciones + comandos v12.3
# Añade: /status /pause /resume /balance /positions /close
# ══════════════════════════════════════════════════════

_URL    = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_offset = 0
_bot_ref = None   # referencia al objeto main para comandos


def set_bot_ref(bot):
    global _bot_ref
    _bot_ref = bot


def _send(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TG] {text}")
        return False
    try:
        r = requests.post(f"{_URL}/sendMessage", json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[TG] send error: {e}")
        return False


# ── Notificaciones ─────────────────────────────────────

def notify_start(version, symbols, mode, balance):
    e = "🟢" if mode == "live" else "🟡"
    no_funds = "\n⚠️ <b>Sin fondos — solo señales</b>" if balance <= 0 else f"\n💰 Balance: <code>${balance:.2f}</code>"
    _send(f"{e} <b>BOT INICIADO {version}</b>\n"
          f"Modo: <code>{mode.upper()}</code>{no_funds}\n"
          f"Pares: {len(symbols)} activos\n"
          f"✅ Trailing dinámico  ✅ Multi-TF 4h\n"
          f"✅ Circuit breaker    ✅ Sizing ATR\n"
          f"✅ Re-entry           ✅ Filtro volumen\n"
          f"Comandos: /status /pause /resume /positions /balance")


def notify_signal(sym, side, score, rsi, price, sl, tp, trend, executed, balance):
    arrow  = "📈 LONG" if side == "long" else "📉 SHORT"
    status = "✅ <b>ORDEN ABIERTA</b>" if executed else "🔔 <b>SEÑAL</b> (sin fondos)"
    _send(f"{status} {arrow}\n"
          f"Par: <b>{sym}</b>\n"
          f"Precio: <code>{price:.6g}</code>\n"
          f"SL: <code>{sl:.6g}</code>  TP: <code>{tp:.6g}</code>\n"
          f"RSI: <code>{rsi:.1f}</code>  Score: <code>{score}</code>  Tendencia: <code>{trend}</code>\n"
          f"Balance: <code>${balance:.2f}</code>")


def notify_close(sym, side, entry, exit_p, pnl, reason, balance):
    e = "✅" if pnl >= 0 else "❌"
    _send(f"{e} <b>CIERRE {side.upper()}</b> — {sym}\n"
          f"Entrada: <code>{entry:.6g}</code>  Salida: <code>{exit_p:.6g}</code>\n"
          f"PnL: <code>${pnl:+.4f}</code>  ({reason})\n"
          f"Balance: <code>${balance:.2f}</code>")


def notify_partial_tp(sym, side, price, balance):
    _send(f"🎯 <b>PARTIAL TP</b> — {sym} {side.upper()}\n"
          f"Precio: <code>{price:.6g}</code>  → SL a breakeven\n"
          f"Balance: <code>${balance:.2f}</code>")


def notify_no_funds(sym, side, score, rsi, price, sl, tp):
    arrow = "📈 LONG" if side == "long" else "📉 SHORT"
    _send(f"💡 <b>SEÑAL SIN FONDOS</b> {arrow}\n"
          f"Par: <b>{sym}</b>  Precio: <code>{price:.6g}</code>\n"
          f"SL: <code>{sl:.6g}</code>  TP: <code>{tp:.6g}</code>\n"
          f"RSI: <code>{rsi:.1f}</code>  Score: <code>{score}</code>")


def notify_circuit_breaker(reason: str):
    _send(f"🚨 <b>CIRCUIT BREAKER ACTIVADO</b>\n<code>{reason}</code>\nUsa /resume para reactivar")


def notify_error(msg: str):
    _send(f"🚨 <b>ERROR</b>\n<code>{msg[:400]}</code>")


def notify_heartbeat(version, cycle, balance, open_pos, mode, stats: dict):
    e = "🟢" if mode == "live" else "🟡"
    dd = stats.get("drawdown_pct", 0)
    cl = stats.get("consecutive_losses", 0)
    _send(f"{e} <b>HEARTBEAT {version}</b>  #{cycle}\n"
          f"Balance: <code>${balance:.2f}</code>  Posiciones: <code>{open_pos}</code>\n"
          f"Drawdown: <code>{dd:.1f}%</code>  Pérdidas consec.: <code>{cl}</code>\n"
          f"PnL hoy: <code>${stats.get('daily_pnl', 0):+.4f}</code>")


def notify_reentry(sym, side, score):
    arrow = "📈" if side == "long" else "📉"
    _send(f"🔁 <b>RE-ENTRY</b> {arrow} <b>{sym}</b>\n"
          f"Score: <code>{score}</code> (umbral elevado)")


# ── Comandos Telegram (polling) ────────────────────────

def _handle_command(text: str, chat_id: str):
    """Procesa comandos recibidos."""
    import trader
    import risk_manager as rm

    cmd = text.strip().lower().split()[0]

    if cmd == "/status":
        bal  = trader.get_balance()
        pos  = trader.get_positions()
        summ = trader.get_summary()
        stats = rm.get_stats(bal)
        lines = [f"📊 <b>STATUS</b>",
                 f"Balance: <code>${bal:.2f}</code>",
                 f"Posiciones abiertas: <code>{len(pos)}</code>",
                 f"Drawdown: <code>{stats['drawdown_pct']:.1f}%</code>",
                 f"Pérd. consec.: <code>{stats['consecutive_losses']}</code>",
                 f"Total trades: <code>{summ.get('total', 0)}</code>  WR: <code>{summ.get('wr', 0)}%</code>",
                 f"PnL total: <code>${summ.get('pnl', 0):+.4f}</code>  PF: <code>{summ.get('pf', 0)}</code>",
                 f"Pausado: <code>{'Sí — ' + stats['pause_reason'] if stats['paused'] else 'No'}</code>"]
        _send("\n".join(lines))

    elif cmd == "/balance":
        bal = trader.get_balance()
        _send(f"💰 Balance actual: <code>${bal:.2f}</code>")

    elif cmd == "/positions":
        pos = trader.get_positions()
        if not pos:
            _send("📭 Sin posiciones abiertas")
        else:
            lines = ["📋 <b>POSICIONES ABIERTAS</b>"]
            for sym, p in pos.items():
                lines.append(f"  • <b>{sym}</b> {p['side'].upper()}  entrada: <code>{p['entry']:.6g}</code>  SL: <code>{p['sl']:.6g}</code>")
            _send("\n".join(lines))

    elif cmd == "/pause":
        rm.pause("manual via Telegram")
        _send("⏸️ Bot pausado. Usa /resume para reactivar.")

    elif cmd == "/resume":
        rm.resume()
        _send("▶️ Bot reactivado.")

    elif cmd.startswith("/close"):
        parts = text.strip().split()
        if len(parts) < 2:
            _send("Uso: /close SYMBOL (ej: /close LINK-USDT)")
        else:
            sym = parts[1].upper()
            pos = trader.get_positions()
            if sym not in pos:
                _send(f"No hay posición abierta para {sym}")
            else:
                import bingx_api as api
                from config import TRADE_MODE
                p = pos[sym]
                price = api.get_price(sym) if TRADE_MODE == "live" else p["entry"]
                trader._execute_close(sym, p, price, "MANUAL")
                _send(f"✅ Posición {sym} cerrada manualmente")

    elif cmd == "/help":
        _send("📖 <b>COMANDOS</b>\n"
              "/status — resumen completo\n"
              "/balance — balance actual\n"
              "/positions — posiciones abiertas\n"
              "/pause — pausar el bot\n"
              "/resume — reactivar el bot\n"
              "/close SYMBOL — cerrar posición manualmente")
    else:
        _send(f"Comando no reconocido: {cmd}\nUsa /help")


def _poll_loop():
    global _offset
    while True:
        try:
            r = requests.get(f"{_URL}/getUpdates",
                             params={"offset": _offset, "timeout": 30},
                             timeout=35)
            if r.status_code != 200:
                continue
            updates = r.json().get("result", [])
            for upd in updates:
                _offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = msg.get("text", "")
                cid  = str(msg.get("chat", {}).get("id", ""))
                if text.startswith("/") and cid == str(TELEGRAM_CHAT_ID):
                    try:
                        _handle_command(text, cid)
                    except Exception as e:
                        _send(f"Error procesando comando: {e}")
        except Exception:
            import time; time.sleep(5)


def start_command_listener():
    """Inicia el listener de comandos en un hilo separado."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    print("  [TG] Listener de comandos activo")
