"""
memoria.py — Aprendizaje + Compounding v4.1

BUGS CORREGIDOS:
  ✅ FIX#1 — Crea el directorio /data si no existe (Railway Volume)
  ✅ FIX#2 — Guardado atómico: escribe en .tmp → renombra (nunca corrompe)
  ✅ FIX#3 — Carga también el backup si el principal está corrompido
  ✅ FIX#4 — _guardar() no crashea nunca — errores logueados y silenciados
"""

import json, time, logging, os, shutil
from datetime import datetime, date

log         = logging.getLogger("memoria")

# ── Ruta del archivo ──────────────────────────────────────────
_MEMORY_DIR = os.getenv("MEMORY_DIR", "").strip()

if _MEMORY_DIR:
    # Crear el directorio si no existe (fix crítico para Railway Volume)
    try:
        os.makedirs(_MEMORY_DIR, exist_ok=True)
        log.info(f"[MEMORIA] Directorio: {_MEMORY_DIR}")
    except Exception as e:
        log.warning(f"[MEMORIA] No se pudo crear {_MEMORY_DIR}: {e} — usando directorio actual")
        _MEMORY_DIR = ""

MEMORY_FILE = os.path.join(_MEMORY_DIR, "memoria.json") if _MEMORY_DIR else "memoria.json"
MEMORY_BKUP = MEMORY_FILE.replace(".json", "_backup.json")
MEMORY_TMP  = MEMORY_FILE.replace(".json", "_tmp.json")

# ── Estructura inicial ────────────────────────────────────────
_data = {
    "pares":       {},
    "killzones":   {},
    "patrones":    {},
    "compounding": {
        "base":            10.0,
        "ganancias":       0.0,
        "total_invertido": 0.0,
        "total_ganado":    0.0,
    },
    "trades":      [],
    "actualizado": "",
}


def _cargar():
    global _data
    # Intentar cargar el principal, luego el backup
    for filepath in [MEMORY_FILE, MEMORY_BKUP]:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath) as f:
                loaded = json.load(f)
            for k in _data:
                if k in loaded:
                    _data[k] = loaded[k]
            log.info(
                f"[MEMORIA] Cargada desde {os.path.basename(filepath)}: "
                f"{len(_data['pares'])} pares | "
                f"{len(_data['trades'])} trades | "
                f"Capital: ${_data['compounding']['base']:.2f} | "
                f"Ganancias: ${_data['compounding']['ganancias']:.2f}"
            )
            return
        except Exception as e:
            log.warning(f"[MEMORIA] Error cargando {filepath}: {e}")
    log.info(f"[MEMORIA] Archivo nuevo en: {MEMORY_FILE}")


def _guardar():
    """
    Guardado atómico:
    1. Escribe en archivo .tmp
    2. Copia el actual como .backup
    3. Renombra .tmp → principal
    Nunca deja el archivo en estado corrupto.
    """
    try:
        _data["actualizado"] = datetime.now().isoformat()
        # Paso 1: escribir en temporal
        with open(MEMORY_TMP, "w") as f:
            json.dump(_data, f, indent=2)
        # Paso 2: backup del anterior
        if os.path.exists(MEMORY_FILE):
            try:
                shutil.copy2(MEMORY_FILE, MEMORY_BKUP)
            except Exception:
                pass
        # Paso 3: renombrar tmp → principal (atómico en Linux)
        os.replace(MEMORY_TMP, MEMORY_FILE)
    except Exception as e:
        log.warning(f"[MEMORIA] Error guardando: {e}")
        # Limpiar tmp si quedó a medias
        try:
            if os.path.exists(MEMORY_TMP):
                os.remove(MEMORY_TMP)
        except Exception:
            pass


def _get_par(par: str) -> dict:
    if par not in _data["pares"]:
        _data["pares"][par] = {
            "wins": 0, "losses": 0, "pnl": 0.0,
            "blocked_until": 0.0,
            "consec_losses": 0,
            "errores_api":   0,
            "mejor_kz":      "",
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
# COMPOUNDING — $10 base + reinversión progresiva
# ══════════════════════════════════════════════════════════════

def get_trade_amount() -> float:
    comp  = _data["compounding"]
    base  = comp["base"]
    extra = (comp["ganancias"] // 50) * 1.0   # +$1 por cada $50 ganados
    total = min(base + extra, 50.0)
    return round(total, 2)


def registrar_inversion(usdt: float):
    _data["compounding"]["total_invertido"] += usdt
    _guardar()


def registrar_ganancia_compounding(pnl: float):
    comp = _data["compounding"]
    comp["total_ganado"] += pnl
    comp["ganancias"]     = max(0.0, comp["ganancias"] + pnl)
    _guardar()


# ══════════════════════════════════════════════════════════════
# REGISTRAR RESULTADO
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
        if kd: kd["wins"] += 1; kd["pnl"] += pnl
        pd["wins"] += 1; pd["pnl"] += pnl
    else:
        d["losses"]        += 1
        d["consec_losses"] += 1
        if kd: kd["losses"] += 1; kd["pnl"] += pnl
        pd["losses"] += 1; pd["pnl"] += pnl

        # Blacklist por pérdidas consecutivas
        if d["consec_losses"] >= 3:
            d["blocked_until"] = time.time() + 7200
            log.warning(f"[MEMORIA] {par} bloqueado 2h ({d['consec_losses']} pérd. consecutivas)")

        # Blacklist por tasa ≥75% con ≥5 trades
        total = d["wins"] + d["losses"]
        if total >= 5 and d["losses"] / total >= 0.75:
            d["blocked_until"] = time.time() + 14400
            log.warning(f"[MEMORIA] {par} bloqueado 4h (75%+ tasa pérdida)")

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
    if len(_data["trades"]) > 1000:
        _data["trades"] = _data["trades"][-1000:]

    _guardar()

    comp = _data["compounding"]
    log.info(
        f"[MEMORIA] {par} W:{d['wins']} L:{d['losses']} PnL:{d['pnl']:+.4f} | "
        f"Pool: ${comp['ganancias']:.2f} | "
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


def registrar_error_api(par: str):
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

    score_final = score + ajuste
    if ajuste != 0:
        log.debug(f"[MEMORIA] {par} score {score}→{score_final} (ajuste:{ajuste:+d})")
    return score_final


# ══════════════════════════════════════════════════════════════
# TOP PARES
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
    return [
        par for par, d in _data["pares"].items()
        if time.time() < d.get("blocked_until", 0)
    ]


# ══════════════════════════════════════════════════════════════
# RESUMEN TELEGRAM
# ══════════════════════════════════════════════════════════════

def resumen() -> str:
    pares   = _data["pares"]
    comp    = _data["compounding"]
    total_w = sum(p["wins"]   for p in pares.values())
    total_l = sum(p["losses"] for p in pares.values())
    total_t = total_w + total_l
    wr      = f"{total_w/total_t*100:.1f}%" if total_t > 0 else "N/A"

    mejores = sorted(pares.items(), key=lambda x: x[1]["pnl"], reverse=True)[:3]
    peores  = sorted(pares.items(), key=lambda x: x[1]["pnl"])[:3]
    top_txt = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in mejores if total_t > 0)
    bot_txt = " | ".join(f"{p}:{d['pnl']:+.2f}" for p, d in peores  if d["pnl"] < 0)

    bloq    = get_pares_bloqueados()

    best_kz = best_kz_pnl = ""
    best_p  = -999
    for kz, kd in _data["killzones"].items():
        if kd["pnl"] > best_p:
            best_kz  = kz
            best_p   = kd["pnl"]
            best_kz_pnl = f"+${kd['pnl']:.2f}"

    return (
        f"🧠 *Memoria SMC Bot v4*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Trades: `{total_t}` (✅{total_w}/❌{total_l}) WR:`{wr}`\n"
        f"PnL total: `${comp['total_ganado']:+.4f}` USDT\n"
        f"💰 Trade base: `${comp['base']:.2f}` | "
        f"Próx: `${get_trade_amount():.2f}` | "
        f"Pool: `${comp['ganancias']:.2f}`\n"
        f"📈 Mejores: `{top_txt or 'N/A'}`\n"
        f"📉 Peores:  `{bot_txt or 'N/A'}`\n"
        f"🕐 Mejor KZ: `{best_kz or 'N/A'}` {best_kz_pnl}\n"
        f"🚫 Bloqueados: `{len(bloq)}`\n"
        f"📊 Pares: `{len(pares)}`\n"
        f"💾 Archivo: `{MEMORY_FILE}`"
    )
