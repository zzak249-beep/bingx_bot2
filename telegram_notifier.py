import os
import requests
import threading

# ══════════════════════════════════════════════════════
# telegram_notifier.py v13.0 — FIX: lee env vars en
# cada llamada (no en import), más robusto en Railway
# ══════════════════════════════════════════════════════

_offset = 0


def _token() -> str:
    # Lee SIEMPRE en tiempo de ejecución, no en import
    return os.getenv("TELEGRAM_TOKEN", "")


def _chat() -> str:
    return str(os.getenv("TELEGRAM_CHAT_ID", ""))


def _send(text: str) -> bool:
    token = _token()
    chat  = _chat()

    if not token or not chat or token == "TU_BOT_TOKEN_AQUI":
        print(f"[TG-NO-CONFIG] {text[:120]}")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":    chat,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=15)
        data = r.json()
        if not data.get("ok"):
            # Reintenta sin parse_mode si hay error de HTML
            r2 = requests.post(url, json={
                "chat_id": chat,
                "text":    text.replace("<b>","").replace("</b>","")
                               .replace("<code>","").replace("</code>",""),
            }, timeout=15)
            return r2.status_code == 200
        return True
    except Exception as e:
        print(f"[TG-ERROR] {e}")
        return False


# ── Notificaciones ─────────────────────────────────────

def notify_start(version, symbols, mode, balance):
    e = "🟢" if mode == "live" else "🟡"
    funds = f"💰 Balance: ${balance:.2f}" if balance > 0 else "⚠️ Sin fondos — solo señales"
    _send(
        f"{e} BOT INICIADO {version}\n"
        f"Modo: {mode.upper()}\n"
        f"{funds}\n"
        f"Pares activos: {len(symbols)}\n"
        f"✅ Trailing SL dinámico\n"
        f"✅ Multi-TF 4h\n"
        f"✅ Circuit breaker\n"
        f"✅ Sizing ATR\n"
        f"✅ Re-entry\n"
        f"✅ Filtro volumen\n"
        f"Comandos: /status /pause /resume /positions /balance /close"
    )


def notify_signal(sym, side, score, rsi, price, sl, tp, trend, executed, balance, bias_4h="?"):
    arrow  = "📈 LONG" if side == "long" else "📉 SHORT"
    status = "✅ ORDEN ABIERTA" if executed else "🔔 SEÑAL (sin fondos — no ejecutada)"
    _send(
        f"{status} {arrow}\n"
        f"Par: {sym}\n"
        f"Precio entrada: {price:.6g}\n"
        f"SL: {sl:.6g}  |  TP: {tp:.6g}\n"
        f"RSI: {rsi:.1f}  Score: {score}\n"
        f"Tendencia 1h: {trend}  |  Bias 4h: {bias_4h}\n"
        f"Balance: ${balance:.2f}"
    )


def notify_close(sym, side, entry, exit_p, pnl, reason, balance):
    emoji = "✅ WIN" if pnl >= 0 else "❌ LOSS"
    _send(
        f"{emoji} CIERRE {side.upper()} — {sym}\n"
        f"Entrada: {entry:.6g}  →  Salida: {exit_p:.6g}\n"
        f"PnL: ${pnl:+.4f}  ({reason})\n"
        f"Balance: ${balance:.2f}"
    )


def notify_partial_tp(sym, side, price, balance):
    _send(
        f"🎯 PARTIAL TP — {sym} {side.upper()}\n"
        f"Precio: {price:.6g}\n"
        f"SL movido a breakeven\n"
        f"Balance: ${balance:.2f}"
    )


def notify_no_funds(sym, side, score, rsi, price, sl, tp):
    arrow = "📈 LONG" if side == "long" else "📉 SHORT"
    _send(
        f"💡 SEÑAL SIN FONDOS {arrow}\n"
        f"Par: {sym}\n"
        f"Precio: {price:.6g}  SL: {sl:.6g}  TP: {tp:.6g}\n"
        f"RSI: {rsi:.1f}  Score: {score}"
    )


def notify_circuit_breaker(reason: str):
    _send(
        f"🚨 CIRCUIT BREAKER ACTIVADO\n"
        f"{reason}\n"
        f"Usa /resume para reactivar"
    )


def notify_reentry(sym, side, score):
    arrow = "📈" if side == "long" else "📉"
    _send(f"🔁 RE-ENTRY {arrow} {sym}  Score: {score}")


def notify_error(msg: str):
    _send(f"🚨 ERROR\n{str(msg)[:400]}")


def notify_heartbeat(version, cycle, balance, open_pos, mode, stats: dict):
    e = "🟢" if mode == "live" else "🟡"
    _send(
        f"{e} HEARTBEAT {version}  ciclo #{cycle}\n"
        f"Balance: ${balance:.2f}\n"
        f"Posiciones abiertas: {open_pos}\n"
        f"Drawdown: {stats.get('drawdown_pct', 0):.1f}%\n"
        f"Pérdidas consecutivas: {stats.get('consecutive_losses', 0)}\n"
        f"PnL hoy: ${stats.get('daily_pnl', 0):+.4f}  ({stats.get('daily_pnl_pct', 0):+.2f}%)"
    )


def send_test():
    """Envía un mensaje de prueba. Llama con: python -c 'import telegram_notifier; telegram_notifier.send_test()'"""
    ok = _send("🔧 TEST — Bot conectado correctamente ✅")
    if ok:
        print("[TG] ✅ Mensaje de prueba enviado correctamente")
    else:
        print("[TG] ❌ FALLO — Revisa TELEGRAM_TOKEN y TELEGRAM_CHAT_ID")
        print(f"     TOKEN configurado: {'Sí' if _token() else 'NO ← AQUÍ EL PROBLEMA'}")
        print(f"     CHAT_ID configurado: {'Sí' if _chat() else 'NO ← AQUÍ EL PROBLEMA'}")


# ── Comandos bidireccionales ───────────────────────────

def _handle_command(text: str):
    try:
        import trader
        import risk_manager as rm

        cmd = text.strip().lower().split()[0]

        if cmd == "/status":
            bal   = trader.get_balance()
            pos   = trader.get_positions()
            summ  = trader.get_summary()
            stats = rm.get_stats(bal)
            _send(
                f"📊 STATUS\n"
                f"Balance: ${bal:.2f}\n"
                f"Posiciones abiertas: {len(pos)}\n"
                f"Drawdown: {stats['drawdown_pct']:.1f}%\n"
                f"Pérd. consecutivas: {stats['consecutive_losses']}\n"
                f"Trades totales: {summ.get('total',0)}\n"
                f"WR: {summ.get('wr',0)}%  PF: {summ.get('pf',0)}\n"
                f"PnL total: ${summ.get('pnl',0):+.4f}\n"
                f"PnL hoy: ${stats['daily_pnl']:+.4f}\n"
                f"Pausado: {'Sí — ' + stats['pause_reason'] if stats['paused'] else 'No'}"
            )

        elif cmd == "/balance":
            bal = trader.get_balance()
            _send(f"💰 Balance: ${bal:.2f}")

        elif cmd == "/positions":
            pos = trader.get_positions()
            if not pos:
                _send("📭 Sin posiciones abiertas")
            else:
                lines = ["📋 POSICIONES ABIERTAS"]
                for sym, p in pos.items():
                    pnl_dir = "🟢" if p['side'] == 'long' else "🔴"
                    lines.append(
                        f"{pnl_dir} {sym} {p['side'].upper()}\n"
                        f"   Entrada: {p['entry']:.6g}  SL: {p['sl']:.6g}  TP: {p['tp']:.6g}"
                    )
                _send("\n".join(lines))

        elif cmd == "/pause":
            rm.pause("manual via Telegram")
            _send("⏸️ Bot pausado. Usa /resume para reactivar.")

        elif cmd == "/resume":
            rm.resume()
            _send("▶️ Bot reactivado.")

        elif cmd == "/close":
            parts = text.strip().split()
            if len(parts) < 2:
                _send("Uso: /close SYMBOL\nEjemplo: /close LINK-USDT")
                return
            sym = parts[1].upper()
            pos = trader.get_positions()
            if sym not in pos:
                _send(f"No hay posición abierta para {sym}")
            else:
                import bingx_api as api
                p     = pos[sym]
                price = api.get_price(sym) if os.getenv("TRADE_MODE","paper") == "live" else p["entry"]
                trader._execute_close(sym, p, price, "MANUAL")
                _send(f"✅ Posición {sym} cerrada manualmente")

        elif cmd == "/help":
            _send(
                "📖 COMANDOS DISPONIBLES\n\n"
                "/status — resumen completo\n"
                "/balance — balance actual\n"
                "/positions — posiciones abiertas\n"
                "/pause — pausar el bot\n"
                "/resume — reactivar el bot\n"
                "/close SYMBOL — cerrar posición\n"
                "/help — esta ayuda"
            )
        else:
            _send(f"Comando no reconocido: {cmd}\nUsa /help")

    except Exception as e:
        _send(f"Error en comando: {e}")


def _poll_loop():
    global _offset
    while True:
        try:
            token = _token()
            chat  = _chat()
            if not token or not chat:
                import time; time.sleep(30); continue

            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": _offset, "timeout": 30},
                timeout=35,
            )
            if r.status_code != 200:
                import time; time.sleep(5); continue

            for upd in r.json().get("result", []):
                _offset = upd["update_id"] + 1
                msg  = upd.get("message", {})
                text = msg.get("text", "")
                cid  = str(msg.get("chat", {}).get("id", ""))
                if text.startswith("/") and cid == chat:
                    _handle_command(text)

        except Exception:
            import time; time.sleep(5)


def start_command_listener():
    if not _token():
        print("  [TG] ⚠️  TELEGRAM_TOKEN no configurado — sin comandos ni notificaciones")
        print("  [TG]    → Añade TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en Railway > Settings > Variables")
        return
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    print(f"  [TG] ✅ Listener de comandos activo (chat_id: {_chat()})")
