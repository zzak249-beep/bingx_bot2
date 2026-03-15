"""
memoria.py v4.2 — Aprendizaje + Compounding + Eliminación permanente

✅ APRENDE: WR por par/KZ/patrón → ajusta score dinámicamente
✅ REINVIERTE: +$1/trade cada $30 ganados netos (base $10, max $50)
✅ ELIMINA: WR≤15% en 10+ trades | 6 pérd. consecutivas | 2 errores API
"""

import json, time, logging, os, shutil
from datetime import datetime

log = logging.getLogger("memoria")

_DIR = os.getenv("MEMORY_DIR", "").strip()
if _DIR:
    os.makedirs(_DIR, exist_ok=True)

MEMORY_FILE    = os.path.join(_DIR, "memoria.json")    if _DIR else "memoria.json"
MEMORY_BKUP    = MEMORY_FILE.replace(".json", "_bkup.json")
MEMORY_TMP     = MEMORY_FILE.replace(".json", "_tmp.json")
BLACKLIST_FILE = os.path.join(_DIR, "blacklist.json")  if _DIR else "blacklist.json"

_data = {
    "pares":       {},
    "killzones":   {},
    "patrones":    {},
    "compounding": {
        "nivel":         10.0,
        "ganancias":     0.0,
        "total_ganado":  0.0,
        "total_perdido": 0.0,
        "racha_wins":    0,
        "racha_losses":  0,
    },
    "trades":      [],
    "actualizado": "",
}

_blacklist: set = set()


# ══════════════════════════════════════════════════════════════
# PERSISTENCIA
# ══════════════════════════════════════════════════════════════

def _cargar():
    global _data, _blacklist
    if os.path.exists(BLACKLIST_FILE):
        try:
            _blacklist = set(json.load(open(BLACKLIST_FILE)))
            log.info(f"[MEM] 🚫 {len(_blacklist)} pares en blacklist permanente")
        except Exception as e:
            log.warning(f"[MEM] blacklist error: {e}")

    for path in [MEMORY_FILE, MEMORY_BKUP]:
        if not os.path.exists(path):
            continue
        try:
            loaded = json.load(open(path))
            for k in _data:
                if k in loaded:
                    _data[k] = loaded[k]
            c = _data["compounding"]
            log.info(f"[MEM] {len(_data['pares'])} pares | {len(_data['trades'])} trades | "
                     f"${c['nivel']:.2f}/trade | Pool: ${c['ganancias']:.2f}")
            return
        except Exception as e:
            log.warning(f"[MEM] Error cargando {path}: {e}")
    log.info("[MEM] Memoria nueva")


def _guardar():
    try:
        _data["actualizado"] = datetime.now().isoformat()
        with open(MEMORY_TMP, "w") as f:
            json.dump(_data, f, indent=2)
        if os.path.exists(MEMORY_FILE):
            shutil.copy2(MEMORY_FILE, MEMORY_BKUP)
        os.replace(MEMORY_TMP, MEMORY_FILE)
    except Exception as e:
        log.warning(f"[MEM] Error guardando: {e}")


def _guardar_blacklist():
    try:
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(list(_blacklist), f, indent=2)
    except Exception as e:
        log.warning(f"[MEM] Error blacklist: {e}")


def _par(p: str) -> dict:
    if p not in _data["pares"]:
        _data["pares"][p] = {
            "wins": 0, "losses": 0, "pnl": 0.0,
            "blocked_until": 0.0, "consec_losses": 0,
            "consec_wins": 0, "errores_api": 0,
        }
    return _data["pares"][p]


def _kz(kz: str) -> dict:
    if kz not in _data["killzones"]:
        _data["killzones"][kz] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["killzones"][kz]


def _patron(motivos: list) -> dict:
    key = "+".join(sorted(motivos or []))
    if key not in _data["patrones"]:
        _data["patrones"][key] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["patrones"][key]


_cargar()


# ══════════════════════════════════════════════════════════════
# BLACKLIST PERMANENTE
# ══════════════════════════════════════════════════════════════

def esta_eliminado(par: str) -> bool:
    return par in _blacklist


def eliminar_par(par: str, razon: str) -> bool:
    if par in _blacklist:
        return False
    _blacklist.add(par)
    _guardar_blacklist()
    if par in _data["pares"]:
        _data["pares"][par]["eliminado_razon"] = razon
    log.warning(f"[ELIMINADO] 🚫 {par} — {razon}")
    return True


def filtrar_pares(pares: list) -> list:
    """Filtra lista de pares quitando los de blacklist. Usar en scanner."""
    antes    = len(pares)
    filtrado = [p for p in pares if p not in _blacklist]
    if antes - len(filtrado) > 0:
        log.debug(f"[MEM] Filtrados {antes - len(filtrado)} pares de blacklist")
    return filtrado


# ══════════════════════════════════════════════════════════════
# COMPOUNDING — reinversión automática
# ══════════════════════════════════════════════════════════════

def get_trade_amount() -> float:
    """
    $10 base + $1 por cada $30 ganados netos.
    Racha ≥3 pérdidas → tamaño reducido al 75%.
    Máximo $50.
    """
    c     = _data["compounding"]
    base  = 10.0
    extra = (c["ganancias"] // 30) * 1.0
    nivel = min(base + extra, 50.0)
    if c["racha_losses"] >= 3:
        nivel = max(base, round(nivel * 0.75, 2))
    nivel = round(nivel, 2)
    c["nivel"] = nivel
    return nivel


def _update_compounding(pnl: float):
    c = _data["compounding"]
    if pnl >= 0:
        c["total_ganado"] += pnl
        c["racha_wins"]   += 1
        c["racha_losses"]  = 0
        c["ganancias"]     = round(c["ganancias"] + pnl, 4)
        nuevo = min(10.0 + (c["ganancias"] // 30), 50.0)
        if nuevo > c["nivel"]:
            log.info(f"[COMPOUND] 📈 ${c['nivel']:.2f} → ${nuevo:.2f}/trade "
                     f"(pool: ${c['ganancias']:.2f})")
        c["nivel"] = nuevo
    else:
        c["total_perdido"] += abs(pnl)
        c["racha_losses"]  += 1
        c["racha_wins"]     = 0
        c["ganancias"]      = max(0.0, round(c["ganancias"] + pnl, 4))
        if c["racha_losses"] >= 3:
            log.warning(f"[COMPOUND] ⚠️ {c['racha_losses']} pérdidas seguidas — "
                        f"reduciendo a ${get_trade_amount():.2f}")


# ══════════════════════════════════════════════════════════════
# REGISTRAR RESULTADO
# ══════════════════════════════════════════════════════════════

def registrar_resultado(par: str, pnl: float, lado: str,
                        kz: str = "", motivos: list = None):
    d   = _par(par)
    kd  = _kz(kz) if kz else None
    pd  = _patron(motivos)

    d["pnl"] = round(d["pnl"] + pnl, 4)

    if pnl >= 0:
        d["wins"]          += 1
        d["consec_wins"]   += 1
        d["consec_losses"]  = 0
        d["errores_api"]    = max(0, d["errores_api"] - 1)
        if kd: kd["wins"] += 1; kd["pnl"] = round(kd["pnl"] + pnl, 4)
        pd["wins"] += 1;        pd["pnl"] = round(pd["pnl"] + pnl, 4)
    else:
        d["losses"]        += 1
        d["consec_losses"] += 1
        d["consec_wins"]    = 0
        if kd: kd["losses"] += 1; kd["pnl"] = round(kd["pnl"] + pnl, 4)
        pd["losses"] += 1;         pd["pnl"] = round(pd["pnl"] + pnl, 4)

        total = d["wins"] + d["losses"]

        # ── Bloqueos temporales ──
        if d["consec_losses"] >= 3:
            d["blocked_until"] = time.time() + 7200
            log.warning(f"[MEM] {par} bloqueado 2h ({d['consec_losses']} pérd. consecutivas)")

        if total >= 6 and d["losses"] / total >= 0.75:
            d["blocked_until"] = time.time() + 14400
            log.warning(f"[MEM] {par} bloqueado 4h (WR={d['wins']/total*100:.0f}%)")

        # ── Eliminación permanente ──
        if total >= 10 and d["wins"] / total <= 0.15:
            eliminar_par(par, f"WR={d['wins']/total*100:.0f}% en {total} trades")

        if d["consec_losses"] >= 6:
            eliminar_par(par, f"{d['consec_losses']} pérdidas consecutivas")

        if total >= 8 and d["pnl"] <= -3.0:
            eliminar_par(par, f"PnL={d['pnl']:.2f}$ en {total} trades")

    _update_compounding(pnl)

    _data["trades"].append({
        "par": par, "lado": lado,
        "pnl": round(pnl, 4), "kz": kz,
        "motivos": motivos or [],
        "size": get_trade_amount(),
        "ts":   datetime.now().isoformat(),
    })
    if len(_data["trades"]) > 2000:
        _data["trades"] = _data["trades"][-2000:]

    _guardar()
    c = _data["compounding"]
    log.info(f"[MEM] {par} W:{d['wins']} L:{d['losses']} "
             f"PnL:{d['pnl']:+.2f} | Pool:${c['ganancias']:.2f} | "
             f"Próx:${get_trade_amount():.2f}")


# ══════════════════════════════════════════════════════════════
# ERROR API → 2 fallos = eliminación permanente
# ══════════════════════════════════════════════════════════════

def registrar_error_api(par: str):
    d = _par(par)
    d["errores_api"] += 1
    if d["errores_api"] >= 2:
        eliminar_par(par, f"{d['errores_api']} errores API — par no soportado")
    else:
        d["blocked_until"] = time.time() + 3600
        log.warning(f"[MEM] {par} bloqueado 1h (1er error API)")
    _guardar()


# ══════════════════════════════════════════════════════════════
# BLOQUEO
# ══════════════════════════════════════════════════════════════

def esta_bloqueado(par: str) -> bool:
    if esta_eliminado(par):
        return True
    d = _par(par)
    if time.time() < d.get("blocked_until", 0):
        return True
    d["blocked_until"] = 0.0
    return False


# ══════════════════════════════════════════════════════════════
# AJUSTE DE SCORE (aprendizaje)
# ══════════════════════════════════════════════════════════════

def ajustar_score(par: str, score: int, kz: str = "", motivos: list = None) -> int:
    ajuste = 0
    d      = _par(par)
    total  = d["wins"] + d["losses"]

    if total >= 5:
        wr = d["wins"] / total
        if   wr >= 0.70: ajuste += 2
        elif wr >= 0.60: ajuste += 1
        elif wr <= 0.25: ajuste -= 2
        elif wr <= 0.35: ajuste -= 1

    if kz:
        kd  = _kz(kz)
        kzt = kd["wins"] + kd["losses"]
        if kzt >= 5:
            kwr = kd["wins"] / kzt
            if   kwr >= 0.65: ajuste += 1
            elif kwr <= 0.35: ajuste -= 1

    if motivos:
        pd  = _patron(motivos)
        pt  = pd["wins"] + pd["losses"]
        if pt >= 5:
            pwr = pd["wins"] / pt
            if   pwr >= 0.65: ajuste += 1
            elif pwr <= 0.35: ajuste -= 1

    final = score + ajuste
    if ajuste != 0:
        log.debug(f"[MEM] {par} score {score}→{final} ({ajuste:+d})")
    return final


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def get_pares_bloqueados() -> list:
    return [p for p, d in _data["pares"].items()
            if time.time() < d.get("blocked_until", 0) and p not in _blacklist]


def get_top_pares(n: int = 10) -> list:
    """Devuelve los n mejores pares por PnL neto (activos, no eliminados)."""
    activos = [
        (p, d) for p, d in _data["pares"].items()
        if p not in _blacklist and d["wins"] + d["losses"] >= 2
    ]
    top = sorted(activos, key=lambda x: x[1]["pnl"], reverse=True)[:n]
    return [p for p, _ in top]


def registrar_ganancia_compounding(pnl: float):
    """Actualiza el pool de compounding sin registrar un trade completo.
    Usar para partial TP parciales donde el trade sigue abierto."""
    _update_compounding(pnl)
    _guardar()


def registrar_inversion(amount: float):
    """Registra una inversión realizada (trazabilidad). No bloquea ni aprende."""
    log.debug(f"[MEM] Inversión registrada: ${amount:.2f}")


def desbloquear(par: str):
    d = _par(par)
    d["blocked_until"]  = 0.0
    d["consec_losses"]  = 0
    _guardar()
    log.info(f"[MEM] {par} desbloqueado manualmente")


# ══════════════════════════════════════════════════════════════
# RESUMEN TELEGRAM
# ══════════════════════════════════════════════════════════════

def resumen() -> str:
    pares  = _data["pares"]
    c      = _data["compounding"]
    tw     = sum(d["wins"]   for d in pares.values())
    tl     = sum(d["losses"] for d in pares.values())
    tt     = tw + tl
    wr     = f"{tw/tt*100:.1f}%" if tt else "N/A"
    neto   = round(c["total_ganado"] - c["total_perdido"], 4)

    activos = [(p, d) for p, d in pares.items()
               if p not in _blacklist and d["wins"] + d["losses"] >= 2]
    mejores = sorted(activos, key=lambda x: x[1]["pnl"], reverse=True)[:3]
    peores  = sorted(activos, key=lambda x: x[1]["pnl"])[:3]

    top = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in mejores)
    bot = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in peores if d["pnl"] < 0)

    best_kz = max(_data["killzones"].items(),
                  key=lambda x: x[1]["pnl"], default=("N/A", {}))

    bloq = get_pares_bloqueados()

    return (
        f"🧠 *SMC Bot — Memoria v4.2*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Trades: `{tt}` (✅{tw} / ❌{tl}) WR: `{wr}`\n"
        f"💵 PnL neto: `${neto:+.4f}` USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Trade actual: `${c['nivel']:.2f}` × 10x\n"
        f"📈 Pool ganancias: `${c['ganancias']:.2f}` USDT\n"
        f"🎯 Siguiente subida al operar: `${min(c['nivel']+1, 50):.2f}` en +$30\n"
        f"🔄 Racha: `+{c['racha_wins']}W` / `-{c['racha_losses']}L`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Mejores: `{top or 'N/A'}`\n"
        f"💀 Peores:  `{bot or 'N/A'}`\n"
        f"🕐 Mejor KZ: `{best_kz[0]}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏸️ Bloqueados: `{len(bloq)}`\n"
        f"🚫 Eliminados: `{len(_blacklist)}`\n"
        f"📋 Pares analizados: `{len(pares)}`\n"
    )
