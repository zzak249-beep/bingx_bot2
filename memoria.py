"""
memoria.py — Aprendizaje y Compounding v4.0
  ✅ $10 base fijo — reinvierte ganancias progresivamente
  ✅ Blacklist automática por rachas negativas
  ✅ Ajuste de score dinámico por historial
  ✅ Backup automático antes de guardar
  ✅ Estadísticas por killzone + patrón
"""

import json, time, logging, os, shutil
from datetime import datetime

log = logging.getLogger("memoria")

_MEMORY_DIR = os.getenv("MEMORY_DIR", "").strip()
MEMORY_FILE = os.path.join(_MEMORY_DIR, "memoria.json") if _MEMORY_DIR else "memoria.json"
MEMORY_BKUP = MEMORY_FILE.replace(".json", "_backup.json")

_data = {
    "pares":       {},
    "killzones":   {},
    "patrones":    {},
    "compounding": {
        "base":            10.0,
        "ganancias":       0.0,
        "total_trades":    0,
        "total_ganado":    0.0,
        "wins":            0,
        "losses":          0,
    },
    "trades":      [],
    "actualizado": "",
}


def _cargar():
    global _data
    if not os.path.exists(MEMORY_FILE):
        log.info(f"[MEMORIA] Nuevo archivo: {MEMORY_FILE}")
        return
    try:
        with open(MEMORY_FILE) as f:
            loaded = json.load(f)
        for k in _data:
            if k in loaded:
                _data[k] = loaded[k]
        comp = _data["compounding"]
        log.info(
            f"[MEMORIA] ✅ Cargada | Trades:{comp['total_trades']} "
            f"W:{comp['wins']} L:{comp['losses']} | "
            f"PnL:${comp['total_ganado']:+.4f} | "
            f"Pool:${comp['ganancias']:.2f} | "
            f"Próx:${get_trade_amount():.2f}"
        )
    except Exception as e:
        log.warning(f"[MEMORIA] Error: {e} — cargando backup")
        _cargar_backup()


def _cargar_backup():
    if not os.path.exists(MEMORY_BKUP):
        return
    try:
        with open(MEMORY_BKUP) as f:
            loaded = json.load(f)
        for k in _data:
            if k in loaded:
                _data[k] = loaded[k]
        log.info("[MEMORIA] ✅ Backup cargado")
    except Exception as e:
        log.error(f"[MEMORIA] Error backup: {e}")


def _guardar():
    try:
        _data["actualizado"] = datetime.now().isoformat()
        if os.path.exists(MEMORY_FILE):
            shutil.copy2(MEMORY_FILE, MEMORY_BKUP)
        with open(MEMORY_FILE, "w") as f:
            json.dump(_data, f, indent=2)
    except Exception as e:
        log.warning(f"[MEMORIA] Error guardando: {e}")


def _get_par(par: str) -> dict:
    if par not in _data["pares"]:
        _data["pares"][par] = {
            "wins": 0, "losses": 0, "pnl": 0.0,
            "blocked_until": 0.0,
            "consec_losses": 0,
            "errores_api": 0,
        }
    return _data["pares"][par]


def _get_kz(kz: str) -> dict:
    if kz not in _data["killzones"]:
        _data["killzones"][kz] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["killzones"][kz]


def _get_patron(motivos: list) -> dict:
    key = "+".join(sorted(motivos)) if motivos else "NONE"
    if key not in _data["patrones"]:
        _data["patrones"][key] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["patrones"][key]


_cargar()


# ══════════════════════════════════════════════════════════════
# COMPOUNDING — $10 base + reinversión progresiva
# ══════════════════════════════════════════════════════════════

def get_trade_amount() -> float:
    """
    Base: $10 fijo siempre.
    Cada $30 ganados netos → añade $1 al trade.
    Máximo: $50 por trade.
    Capital base NUNCA se toca.
    """
    from config import TRADE_USDT_BASE, TRADE_USDT_MAX, COMPOUND_STEP_USDT, COMPOUND_ADD_USDT
    comp  = _data["compounding"]
    extra = (comp["ganancias"] // COMPOUND_STEP_USDT) * COMPOUND_ADD_USDT
    total = min(TRADE_USDT_BASE + extra, TRADE_USDT_MAX)
    return round(total, 2)


def registrar_inversion(usdt: float):
    _data["compounding"]["total_trades"] += 1
    _guardar()


def registrar_ganancia_compounding(pnl: float):
    comp = _data["compounding"]
    comp["total_ganado"] += pnl
    comp["ganancias"]     = max(0.0, comp["ganancias"] + pnl)
    if pnl > 0:
        comp["wins"]   += 1
    else:
        comp["losses"] += 1
    _guardar()


# ══════════════════════════════════════════════════════════════
# REGISTRAR RESULTADO — aprende de cada trade
# ══════════════════════════════════════════════════════════════

def registrar_resultado(par: str, pnl: float, lado: str,
                        kz: str = "", motivos: list = None):
    d  = _get_par(par)
    kd = _get_kz(kz) if kz else None
    pd = _get_patron(motivos or [])

    d["pnl"] += pnl

    if pnl > 0:
        d["wins"]          += 1
        d["consec_losses"]  = 0
        d["errores_api"]    = max(0, d["errores_api"] - 1)
        if kd:
            kd["wins"] += 1; kd["pnl"] += pnl
        pd["wins"] += 1; pd["pnl"] += pnl
    else:
        d["losses"]        += 1
        d["consec_losses"] += 1
        if kd:
            kd["losses"] += 1; kd["pnl"] += pnl
        pd["losses"] += 1; pd["pnl"] += pnl

        # Blacklist automática por pérdidas
        if d["consec_losses"] >= 3:
            d["blocked_until"] = time.time() + 7200  # 2h
            log.warning(f"[APRENDE] ⛔ {par} bloqueado 2h ({d['consec_losses']} pérdidas seguidas)")
        total = d["wins"] + d["losses"]
        if total >= 6 and d["losses"] / total >= 0.75:
            d["blocked_until"] = time.time() + 14400  # 4h
            log.warning(f"[APRENDE] ⛔ {par} bloqueado 4h (WR={d['wins']/total:.0%})")

    registrar_ganancia_compounding(pnl)

    _data["trades"].append({
        "par":        par,
        "lado":       lado,
        "pnl":        round(pnl, 4),
        "kz":         kz,
        "motivos":    motivos or [],
        "trade_size": get_trade_amount(),
        "ts":         datetime.now().isoformat(),
    })
    if len(_data["trades"]) > 2000:
        _data["trades"] = _data["trades"][-2000:]

    _guardar()

    comp = _data["compounding"]
    log.info(
        f"[APRENDE] {par} W:{d['wins']} L:{d['losses']} PnL:{d['pnl']:+.4f} | "
        f"Total:${comp['total_ganado']:+.4f} | Pool:${comp['ganancias']:.2f} | "
        f"Próx:${get_trade_amount():.2f}"
    )


# ══════════════════════════════════════════════════════════════
# BLOQUEO Y DESBLOQUEO
# ══════════════════════════════════════════════════════════════

def esta_bloqueado(par: str) -> bool:
    d = _get_par(par)
    if time.time() < d.get("blocked_until", 0):
        mins = (d["blocked_until"] - time.time()) / 60
        log.debug(f"[APRENDE] {par} bloqueado {mins:.0f}min")
        return True
    d["blocked_until"] = 0.0
    return False


def registrar_error_api(par: str, codigo: int = 0):
    d = _get_par(par)
    d["errores_api"] += 1
    if d["errores_api"] >= 3:
        d["blocked_until"] = time.time() + 3600
        log.warning(f"[APRENDE] ⛔ {par} bloqueado 1h (API errors={d['errores_api']})")
    _guardar()


# ══════════════════════════════════════════════════════════════
# AJUSTE DE SCORE CON HISTORIAL
# ══════════════════════════════════════════════════════════════

def ajustar_score(par: str, score: int,
                  kz: str = "", motivos: list = None) -> int:
    """
    Aprende del historial:
      +2 si WR >= 70% (≥5 trades)
      +1 si WR >= 60%
      -1 si WR <= 35%
      -2 si WR <= 25%
      +1/-1 por killzone y patrón
    """
    ajuste = 0
    d      = _get_par(par)
    total  = d["wins"] + d["losses"]

    if total >= 5:
        wr = d["wins"] / total
        if   wr >= 0.70: ajuste += 2
        elif wr >= 0.60: ajuste += 1
        elif wr <= 0.25: ajuste -= 2
        elif wr <= 0.35: ajuste -= 1

    if kz:
        kd     = _get_kz(kz)
        kz_tot = kd["wins"] + kd["losses"]
        if kz_tot >= 5:
            kz_wr = kd["wins"] / kz_tot
            if   kz_wr >= 0.65: ajuste += 1
            elif kz_wr <= 0.35: ajuste -= 1

    if motivos:
        pd      = _get_patron(motivos)
        pat_tot = pd["wins"] + pd["losses"]
        if pat_tot >= 5:
            pat_wr = pd["wins"] / pat_tot
            if   pat_wr >= 0.65: ajuste += 1
            elif pat_wr <= 0.35: ajuste -= 1

    score_f = score + ajuste
    if ajuste != 0:
        log.debug(f"[APRENDE] {par} score {score}→{score_f} ({ajuste:+d})")
    return score_f


# ══════════════════════════════════════════════════════════════
# TOP PARES + RESUMEN
# ══════════════════════════════════════════════════════════════

def get_top_pares(n: int = 20) -> list:
    ranked = []
    for par, d in _data["pares"].items():
        total = d["wins"] + d["losses"]
        if total < 3:
            continue
        wr    = d["wins"] / total
        score = wr * max(d["pnl"], 0.001)
        ranked.append((par, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in ranked[:n]]


def get_pares_bloqueados() -> list:
    return [par for par, d in _data["pares"].items()
            if time.time() < d.get("blocked_until", 0)]


def resumen() -> str:
    pares   = _data["pares"]
    comp    = _data["compounding"]
    total_w = comp["wins"]
    total_l = comp["losses"]
    total_t = comp["total_trades"]
    wr      = f"{total_w/(total_w+total_l)*100:.1f}%" if (total_w+total_l) > 0 else "N/A"

    mejores = sorted(pares.items(), key=lambda x: x[1]["pnl"], reverse=True)[:3]
    peores  = sorted(pares.items(), key=lambda x: x[1]["pnl"])[:3]
    top_txt = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in mejores if d["pnl"] != 0)
    bot_txt = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in peores  if d["pnl"] < 0)

    best_kz, best_kz_pnl = "N/A", -9999
    for kz, kd in _data["killzones"].items():
        if kd["pnl"] > best_kz_pnl:
            best_kz, best_kz_pnl = kz, kd["pnl"]

    bloq = get_pares_bloqueados()

    return (
        f"🧠 *Memoria SMC Bot v4.0*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Trades: `{total_t}` (✅{total_w}/❌{total_l}) WR:`{wr}`\n"
        f"PnL total: `${comp['total_ganado']:+.4f}` USDT\n"
        f"💰 Base: `$10.00` siempre\n"
        f"💹 Pool reinversión: `${comp['ganancias']:.2f}`\n"
        f"📊 Próx trade: `${get_trade_amount():.2f}`\n"
        f"📈 Mejores: `{top_txt or 'N/A'}`\n"
        f"📉 Peores: `{bot_txt or 'N/A'}`\n"
        f"🕐 Mejor KZ: `{best_kz}` (+${best_kz_pnl:.2f})\n"
        f"🚫 Bloqueados: `{len(bloq)}` pares\n"
        f"📊 Pares totales: `{len(pares)}`\n"
        f"💾 Archivo: `{MEMORY_FILE}`"
    )
