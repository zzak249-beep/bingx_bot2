"""
memoria.py — Memoria de trades y aprendizaje
Guarda historial de resultados por par y ajusta scores.
"""

import json, time, logging, os
from datetime import datetime

log = logging.getLogger("memoria")
MEMORY_FILE = "memoria.json"

# ── Estado en memoria ─────────────────────────────────────────
_data = {
    "pares": {},          # par → {wins, losses, pnl, blocked_until, errores_api}
    "trades": [],         # historial de trades cerrados
    "actualizado": "",
}

def _cargar():
    global _data
    if not os.path.exists(MEMORY_FILE):
        return
    try:
        with open(MEMORY_FILE) as f:
            _data = json.load(f)
        log.info(f"[MEMORIA] Cargada: {len(_data.get('pares', {}))} pares | "
                 f"{len(_data.get('trades', []))} trades")
    except Exception as e:
        log.warning(f"[MEMORIA] Error cargando: {e}")

def _guardar():
    try:
        _data["actualizado"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "w") as f:
            json.dump(_data, f, indent=2)
    except Exception as e:
        log.warning(f"[MEMORIA] Error guardando: {e}")

def _get_par(par: str) -> dict:
    if par not in _data["pares"]:
        _data["pares"][par] = {
            "wins": 0, "losses": 0, "pnl": 0.0,
            "blocked_until": 0.0, "errores_api": 0,
        }
    return _data["pares"][par]

# Cargar al importar
_cargar()


# ══════════════════════════════════════════════════════════════
# REGISTRAR RESULTADO
# ══════════════════════════════════════════════════════════════

def registrar_resultado(par: str, pnl: float, lado: str):
    d = _get_par(par)
    d["pnl"] += pnl
    if pnl > 0:
        d["wins"]   += 1
        d["errores_api"] = max(0, d["errores_api"] - 1)
    else:
        d["losses"] += 1
        # Si 3+ pérdidas consecutivas → bloquear 2h
        total = d["wins"] + d["losses"]
        if total >= 3 and d["losses"] / total >= 0.75:
            d["blocked_until"] = time.time() + 7200
            log.warning(f"[MEMORIA] {par} bloqueado 2h (75%+ pérdidas)")

    _data["trades"].append({
        "par": par, "lado": lado, "pnl": round(pnl, 4),
        "ts": datetime.now().isoformat(),
    })
    # Mantener sólo los últimos 500 trades
    if len(_data["trades"]) > 500:
        _data["trades"] = _data["trades"][-500:]

    _guardar()
    log.info(f"[MEMORIA] {par} W:{d['wins']} L:{d['losses']} PnL:{d['pnl']:+.4f}")


# ══════════════════════════════════════════════════════════════
# REGISTRAR ERROR API
# ══════════════════════════════════════════════════════════════

def registrar_error_api(par: str, codigo: int = 0):
    d = _get_par(par)
    d["errores_api"] += 1
    if d["errores_api"] >= 3:
        d["blocked_until"] = time.time() + 3600
        log.warning(f"[MEMORIA] {par} bloqueado 1h (3+ errores API)")
    _guardar()


# ══════════════════════════════════════════════════════════════
# COMPROBAR BLOQUEO
# ══════════════════════════════════════════════════════════════

def esta_bloqueado(par: str) -> bool:
    d = _get_par(par)
    if time.time() < d.get("blocked_until", 0):
        mins = (d["blocked_until"] - time.time()) / 60
        log.debug(f"[MEMORIA] {par} bloqueado {mins:.0f}min más")
        return True
    # Limpiar bloqueo expirado
    d["blocked_until"] = 0.0
    return False


# ══════════════════════════════════════════════════════════════
# AJUSTAR SCORE
# ══════════════════════════════════════════════════════════════

def ajustar_score(par: str, score: int) -> int:
    """Ajusta el score según historial: +1 si ≥60% wins, -1 si ≥60% losses."""
    d = _get_par(par)
    total = d["wins"] + d["losses"]
    if total < 3:
        return score
    wr = d["wins"] / total
    if wr >= 0.60:
        return score + 1
    if wr <= 0.35:
        return score - 1
    return score


# ══════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════

def resumen() -> str:
    pares = _data.get("pares", {})
    trades= _data.get("trades", [])
    total_pnl = sum(p["pnl"] for p in pares.values())
    total_w   = sum(p["wins"]   for p in pares.values())
    total_l   = sum(p["losses"] for p in pares.values())
    total_t   = total_w + total_l
    wr = f"{total_w/total_t*100:.1f}%" if total_t > 0 else "N/A"

    # Top 3 mejores pares
    mejores = sorted(pares.items(), key=lambda x: x[1]["pnl"], reverse=True)[:3]
    top_txt = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in mejores if d["pnl"] != 0)

    # Bloqueados
    bloq = [p for p, d in pares.items() if time.time() < d.get("blocked_until", 0)]

    return (
        f"🧠 *Memoria SMC Bot*\n"
        f"Trades totales: `{total_t}` (✅{total_w}/❌{total_l}) WR:`{wr}`\n"
        f"PnL acumulado: `${total_pnl:+.4f}` USDT\n"
        f"Top pares: `{top_txt or 'N/A'}`\n"
        f"Bloqueados: `{len(bloq)}`"
    )
