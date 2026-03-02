"""
╔══════════════════════════════════════════════════════════════════╗
║          CLOSE ALL — Cierre de emergencia de posiciones          ║
║                  Compatible con SATY ELITE v19                   ║
╚══════════════════════════════════════════════════════════════════╝

Uso:
    python close_all.py

Variables de entorno necesarias (las mismas que el bot principal):
    BINGX_API_KEY
    BINGX_API_SECRET
    TELEGRAM_BOT_TOKEN   (opcional, para notificación)
    TELEGRAM_CHAT_ID     (opcional, para notificación)
    HEDGE_MODE           (default: true, igual que el bot)
"""

import os
import time
import logging
from datetime import datetime, timezone

import ccxt
import requests

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("close_all")

# ── Config ────────────────────────────────────────────────
API_KEY    = os.environ.get("BINGX_API_KEY",    "")
API_SECRET = os.environ.get("BINGX_API_SECRET", "")
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID",   "")
HEDGE_MODE = os.environ.get("HEDGE_MODE", "true").lower() == "true"


# ── Telegram ──────────────────────────────────────────────
def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.warning(f"TG: {e}")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Exchange ───────────────────────────────────────────────
def build_exchange() -> ccxt.Exchange:
    ex = ccxt.bingx({
        "apiKey":          API_KEY,
        "secret":          API_SECRET,
        "options":         {"defaultType": "swap"},
        "enableRateLimit": True,
    })
    ex.load_markets()
    return ex


# ── Lógica principal ───────────────────────────────────────
def close_all():
    log.info("=" * 55)
    log.info("  CLOSE ALL — iniciando cierre de todas las posiciones")
    log.info("=" * 55)

    if not API_KEY or not API_SECRET:
        log.error("Faltan BINGX_API_KEY y/o BINGX_API_SECRET")
        return

    # Conectar
    log.info("Conectando al exchange...")
    ex = build_exchange()
    log.info("Exchange conectado ✓")

    # Obtener todas las posiciones abiertas
    log.info("Obteniendo posiciones abiertas...")
    try:
        positions = ex.fetch_positions()
    except Exception as e:
        log.error(f"fetch_positions: {e}")
        tg(f"❌ <b>CLOSE ALL ERROR:</b> no se pudieron obtener posiciones\n{e}")
        return

    # Filtrar solo las que tienen contratos abiertos
    open_pos = [
        p for p in positions
        if abs(float(p.get("contracts", 0) or 0)) > 0
    ]

    if not open_pos:
        log.info("✅ No hay posiciones abiertas.")
        tg(f"✅ <b>CLOSE ALL</b> — No había posiciones abiertas.\n⏰ {utcnow()}")
        return

    log.info(f"Encontradas {len(open_pos)} posiciones abiertas:")
    for p in open_pos:
        log.info(
            f"  {p['symbol']} | {p.get('side','?')} | "
            f"contratos: {p.get('contracts')} | "
            f"PnL: {p.get('unrealizedPnl', '?')}"
        )

    # Cancelar todas las órdenes pendientes primero
    log.info("Cancelando órdenes pendientes (SL/TP)...")
    cancelled = 0
    for p in open_pos:
        symbol = p["symbol"]
        try:
            ex.cancel_all_orders(symbol)
            log.info(f"  [{symbol}] órdenes canceladas ✓")
            cancelled += 1
        except Exception as e:
            log.warning(f"  [{symbol}] cancel_all_orders: {e}")
    log.info(f"Órdenes canceladas para {cancelled}/{len(open_pos)} símbolos")

    time.sleep(1)  # Pequeña pausa antes de cerrar

    # Cerrar cada posición con orden de mercado
    log.info("Cerrando posiciones con órdenes de mercado...")
    results = []
    total_pnl = 0.0

    for p in open_pos:
        symbol    = p["symbol"]
        contracts = abs(float(p.get("contracts", 0)))
        side      = p.get("side", "").lower()      # "long" o "short"
        entry     = float(p.get("entryPrice", 0) or 0)
        mark      = float(p.get("markPrice",  0) or 0)
        upnl      = float(p.get("unrealizedPnl", 0) or 0)

        if contracts <= 0:
            continue

        # Lado de cierre (opuesto a la posición)
        close_side = "sell" if side == "long" else "buy"

        # Params para Hedge Mode
        params = {}
        if HEDGE_MODE:
            params["positionSide"] = "LONG" if side == "long" else "SHORT"
        params["reduceOnly"] = True

        log.info(
            f"  [{symbol}] cerrando {side.upper()} "
            f"{contracts} contratos @ ~{mark:.6g} "
            f"(PnL no realizado: ${upnl:+.3f})"
        )

        try:
            order = ex.create_order(
                symbol, "market", close_side, contracts, params=params
            )
            fill_price = float(order.get("average") or mark)
            log.info(f"  [{symbol}] ✅ cerrado @ {fill_price:.6g}")
            results.append({
                "symbol": symbol,
                "side":   side,
                "contracts": contracts,
                "entry": entry,
                "exit":  fill_price,
                "upnl":  upnl,
                "ok":    True,
            })
            total_pnl += upnl

        except Exception as e:
            log.error(f"  [{symbol}] ❌ ERROR al cerrar: {e}")
            results.append({
                "symbol": symbol,
                "side":   side,
                "contracts": contracts,
                "error": str(e),
                "ok":    False,
            })

        time.sleep(0.5)  # Rate limit

    # Resumen
    log.info("=" * 55)
    log.info(f"RESUMEN — {len(results)} posiciones procesadas")
    ok_count  = sum(1 for r in results if r["ok"])
    err_count = sum(1 for r in results if not r["ok"])
    log.info(f"  ✅ Cerradas:  {ok_count}")
    log.info(f"  ❌ Errores:   {err_count}")
    log.info(f"  💹 PnL total aprox: ${total_pnl:+.3f}")
    log.info("=" * 55)

    # Mensaje Telegram
    lines = [
        f"🛑 <b>CLOSE ALL — COMPLETADO</b>",
        f"══════════════════════════",
        f"📊 Posiciones procesadas: {len(results)}",
        f"✅ Cerradas exitosamente: {ok_count}",
        f"❌ Con error: {err_count}",
        f"══════════════════════════",
    ]

    for r in results:
        if r["ok"]:
            lines.append(
                f"{'🟢' if r['side']=='long' else '🔴'} {r['symbol']} "
                f"{r['side'].upper()} {r['contracts']} ctrs "
                f"| PnL: ${r['upnl']:+.3f}"
            )
        else:
            lines.append(f"⚠️ {r['symbol']} — ERROR: {r.get('error','?')[:60]}")

    lines += [
        f"══════════════════════════",
        f"💹 PnL total aprox: ${total_pnl:+.3f}",
        f"⏰ {utcnow()}",
    ]

    tg("\n".join(lines))
    log.info("Notificación Telegram enviada.")


if __name__ == "__main__":
    close_all()
