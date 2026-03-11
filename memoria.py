"""
memoria.py — Aprendizaje avanzado
El bot aprende de cada trade:
  - Qué pares son rentables
  - En qué killzone funciona mejor
  - Qué combinación de señales tiene mejor win rate
  - Ajusta scores dinámicamente
  - Blacklist automático por pérdidas consecutivas
"""

import json, time, logging, os
from datetime import datetime, date

log = logging.getLogger("memoria")
MEMORY_FILE = "memoria.json"

_data = {
    "pares":       {},   # par → stats
    "killzones":   {},   # kz  → stats
    "patrones":    {},   # motivos_key → stats
    "compounding": {     # capital compuesto
        "base":       10.0,   # USDT base por trade
        "ganancias":  0.0,    # ganancias acumuladas reinvertibles
        "total_invertido": 0.0,
        "total_ganado":    0.0,
    },
    "trades":      [],   # historial
    "actualizado": "",
}

def _cargar():
    global _data
    if not os.path.exists(MEMORY_FILE):
        return
    try:
        with open(MEMORY_FILE) as f:
            loaded = json.load(f)
        # Merge conservando estructura
        for k in _data:
            if k in loaded:
                _data[k] = loaded[k]
        log.info(
            f"[MEMORIA] Cargada: {len(_data['pares'])} pares | "
            f"{len(_data['trades'])} trades | "
            f"Capital base: ${_data['compounding']['base']:.2f} | "
            f"Ganancias reinvertibles: ${_data['compounding']['ganancias']:.2f}"
        )
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
            "consec_losses": 0,   # pérdidas consecutivas
            "mejor_kz": "",       # killzone con mejor resultado
        }
    return _data["pares"][par]

def _get_kz(kz: str) -> dict:
    if kz not in _data["killzones"]:
        _data["killzones"][kz] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["killzones"][kz]

def _get_patron(motivos: list) -> dict:
    key = "+".join(sorted(motivos))
    if key not in _data["patrones"]:
        _data["patrones"][key] = {"wins": 0, "losses": 0, "pnl": 0.0}
    return _data["patrones"][key]

_cargar()


# ══════════════════════════════════════════════════════════════
# COMPOUNDING — $10 fijos + reinversión de ganancias
# ══════════════════════════════════════════════════════════════

def get_trade_amount() -> float:
    """
    Siempre invierte $10 USDT base.
    Las ganancias acumuladas se reinvierten progresivamente:
      - Por cada $50 de ganancia → +$1 al trade size
    Esto garantiza crecimiento controlado sin arriesgar todo.
    """
    comp  = _data["compounding"]
    base  = comp["base"]          # siempre $10
    extra = (comp["ganancias"] // 50) * 1.0   # +$1 por cada $50 ganados
    total = min(base + extra, 50.0)            # máximo $50 por trade
    return round(total, 2)

def registrar_inversion(usdt: float):
    _data["compounding"]["total_invertido"] += usdt
    _guardar()

def registrar_ganancia_compounding(pnl: float):
    """Acumula ganancia neta para reinversión."""
    comp = _data["compounding"]
    comp["total_ganado"] += pnl
    if pnl > 0:
        # Solo las ganancias se reinvierten
        comp["ganancias"] = max(0, comp["ganancias"] + pnl)
    else:
        # Las pérdidas reducen el pool de reinversión pero no el base
        comp["ganancias"] = max(0, comp["ganancias"] + pnl)
    _guardar()


# ══════════════════════════════════════════════════════════════
# REGISTRAR RESULTADO
# ══════════════════════════════════════════════════════════════

def registrar_resultado(par: str, pnl: float, lado: str,
                        kz: str = "", motivos: list = None):
    d  = _get_par(par)
    kd = _get_kz(kz) if kz else None
    pd = _get_patron(motivos or [])

    d["pnl"]  += pnl
    kd_update  = kd is not None

    if pnl > 0:
        d["wins"]         += 1
        d["consec_losses"]  = 0
        d["errores_api"]    = max(0, d["errores_api"] - 1)
        if kd_update: kd["wins"] += 1; kd["pnl"] += pnl
        pd["wins"] += 1; pd["pnl"] += pnl
    else:
        d["losses"]        += 1
        d["consec_losses"] += 1
        if kd_update: kd["losses"] += 1; kd["pnl"] += pnl
        pd["losses"] += 1; pd["pnl"] += pnl

        # Blacklist por pérdidas consecutivas
        if d["consec_losses"] >= 3:
            d["blocked_until"] = time.time() + 7200  # 2h
            log.warning(f"[MEMORIA] {par} bloqueado 2h ({d['consec_losses']} pérdidas consecutivas)")

        # Blacklist por tasa de pérdida alta (≥5 trades, 75%+ pérdidas)
        total = d["wins"] + d["losses"]
        if total >= 5 and d["losses"] / total >= 0.75:
            d["blocked_until"] = time.time() + 14400  # 4h
            log.warning(f"[MEMORIA] {par} bloqueado 4h (75%+ tasa pérdida)")

    # Actualizar compounding
    registrar_ganancia_compounding(pnl)

    # Historial
    _data["trades"].append({
        "par": par, "lado": lado, "pnl": round(pnl, 4),
        "kz": kz, "motivos": motivos or [],
        "trade_size": get_trade_amount(),
        "ts": datetime.now().isoformat(),
    })
    if len(_data["trades"]) > 1000:
        _data["trades"] = _data["trades"][-1000:]

    _guardar()

    comp = _data["compounding"]
    log.info(
        f"[MEMORIA] {par} W:{d['wins']} L:{d['losses']} PnL:{d['pnl']:+.4f} | "
        f"Pool reinversión: ${comp['ganancias']:.2f} | "
        f"Próx trade: ${get_trade_amount():.2f}"
    )


# ══════════════════════════════════════════════════════════════
# BLOQUEO
# ══════════════════════════════════════════════════════════════

def esta_bloqueado(par: str) -> bool:
    d = _get_par(par)
    if time.time() < d.get("blocked_until", 0):
        mins = (d["blocked_until"] - time.time()) / 60
        log.debug(f"[MEMORIA] {par} bloqueado {mins:.0f}min más")
        return True
    d["blocked_until"] = 0.0
    return False

def registrar_error_api(par: str, codigo: int = 0):
    d = _get_par(par)
    d["errores_api"] += 1
    if d["errores_api"] >= 3:
        d["blocked_until"] = time.time() + 3600
        log.warning(f"[MEMORIA] {par} bloqueado 1h (3+ errores API)")
    _guardar()


# ══════════════════════════════════════════════════════════════
# AJUSTAR SCORE CON APRENDIZAJE
# ══════════════════════════════════════════════════════════════

def ajustar_score(par: str, score: int, kz: str = "", motivos: list = None) -> int:
    """
    Ajusta el score según lo aprendido:
    +2 si el par tiene ≥70% win rate con ≥5 trades
    +1 si el par tiene ≥60% win rate
    -1 si el par tiene ≤35% win rate
    -2 si el par tiene ≤25% win rate
    +1 si la killzone actual tiene buen historial
    +1 si el patrón de señales tiene buen historial
    """
    ajuste = 0

    # Por par
    d     = _get_par(par)
    total = d["wins"] + d["losses"]
    if total >= 5:
        wr = d["wins"] / total
        if   wr >= 0.70: ajuste += 2
        elif wr >= 0.60: ajuste += 1
        elif wr <= 0.25: ajuste -= 2
        elif wr <= 0.35: ajuste -= 1

    # Por killzone
    if kz:
        kd     = _get_kz(kz)
        kz_tot = kd["wins"] + kd["losses"]
        if kz_tot >= 5:
            kz_wr = kd["wins"] / kz_tot
            if   kz_wr >= 0.65: ajuste += 1
            elif kz_wr <= 0.35: ajuste -= 1

    # Por patrón de señales
    if motivos:
        pd      = _get_patron(motivos)
        pat_tot = pd["wins"] + pd["losses"]
        if pat_tot >= 5:
            pat_wr = pd["wins"] / pat_tot
            if   pat_wr >= 0.65: ajuste += 1
            elif pat_wr <= 0.35: ajuste -= 1

    score_final = score + ajuste
    if ajuste != 0:
        log.debug(f"[MEMORIA] {par} score {score} → {score_final} (ajuste:{ajuste:+d})")
    return score_final


# ══════════════════════════════════════════════════════════════
# TOP PARES (para priorizar el escaneo)
# ══════════════════════════════════════════════════════════════

def get_top_pares(n: int = 20) -> list:
    """Devuelve los N pares con mejor PnL y win rate."""
    pares = _data["pares"]
    ranked = []
    for par, d in pares.items():
        total = d["wins"] + d["losses"]
        if total < 3:
            continue
        wr    = d["wins"] / total
        score = wr * max(d["pnl"], 0.001)
        ranked.append((par, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in ranked[:n]]

def get_pares_bloqueados() -> list:
    return [
        par for par, d in _data["pares"].items()
        if time.time() < d.get("blocked_until", 0)
    ]


# ══════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════

def resumen() -> str:
    pares     = _data["pares"]
    comp      = _data["compounding"]
    trades    = _data["trades"]
    total_w   = sum(p["wins"]   for p in pares.values())
    total_l   = sum(p["losses"] for p in pares.values())
    total_t   = total_w + total_l
    wr        = f"{total_w/total_t*100:.1f}%" if total_t > 0 else "N/A"

    mejores   = sorted(pares.items(), key=lambda x: x[1]["pnl"], reverse=True)[:3]
    peores    = sorted(pares.items(), key=lambda x: x[1]["pnl"])[:3]
    top_txt   = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in mejores if total_t > 0)
    bot_txt   = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in peores  if d["pnl"] < 0)

    bloq      = get_pares_bloqueados()

    # Mejor killzone
    best_kz = ""
    best_kz_pnl = -999
    for kz, kd in _data["killzones"].items():
        if kd["pnl"] > best_kz_pnl:
            best_kz     = kz
            best_kz_pnl = kd["pnl"]

    return (
        f"🧠 *Memoria SMC Bot*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Trades: `{total_t}` (✅{total_w}/❌{total_l}) WR:`{wr}`\n"
        f"PnL total: `${comp['total_ganado']:+.4f}` USDT\n"
        f"💰 Trade base: `${comp['base']:.2f}` | "
        f"Próx: `${get_trade_amount():.2f}` | "
        f"Pool: `${comp['ganancias']:.2f}`\n"
        f"📈 Mejores: `{top_txt or 'N/A'}`\n"
        f"📉 Peores: `{bot_txt or 'N/A'}`\n"
        f"🕐 Mejor KZ: `{best_kz or 'N/A'}` (+${best_kz_pnl:.2f})\n"
        f"🚫 Bloqueados: `{len(bloq)}`\n"
        f"📊 Pares analizados: `{len(pares)}`"
    )
