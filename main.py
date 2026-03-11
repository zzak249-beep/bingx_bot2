"""
main.py — SMC Bot BingX v1.0
Estrategia: Fair Value Gaps + Equal Highs/Lows + ICT Killzones + Pivotes Diarios
  • Partial TP: 50% en TP1 + SL a breakeven
  • Trailing stop activo tras TP1
  • Time-based exit: >8h sin resolver → cerrar
  • Anti-hedge: carga posiciones de BingX al arranque
  • Gestión de riesgo: % del balance por trade
"""

import sys, os, time, traceback
from datetime import datetime, date, timezone
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    stream=sys.stdout, force=True,
)
log = logging.getLogger("main")
log.info("=== ARRANQUE SMC BOT v1.0 ===")

try:
    import config, exchange, analizar, memoria
except Exception as e:
    log.error(f"ERROR importando módulos: {e}\n{traceback.format_exc()}")
    sys.exit(1)

try:
    from config_pares import PARES as PARES_FIJOS
except Exception:
    PARES_FIJOS = []

log.info(f"Módulos OK | {config.VERSION}")

# ── Validar configuración ──
errores_config = config.validar()
for err in errores_config:
    log.warning(f"CONFIG: {err}")


# ═══════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════

class Estado:
    def __init__(self):
        self.posiciones   = {}     # par → dict posición
        self.pnl_hoy      = 0.0
        self.dia_actual   = str(date.today())
        self.wins = self.losses = 0

    def reset_diario(self):
        hoy = str(date.today())
        if hoy != self.dia_actual:
            self.dia_actual = hoy
            self.pnl_hoy    = 0.0
            log.info(f"Reset diario — {hoy}")

    def registrar_cierre(self, pnl: float):
        self.pnl_hoy += pnl
        if pnl > 0: self.wins  += 1
        else:       self.losses += 1

    def max_perdida_alcanzada(self) -> bool:
        if config.MAX_PERDIDA_DIA <= 0:
            return False
        return self.pnl_hoy <= -config.MAX_PERDIDA_DIA

estado = Estado()


# ═══════════════════════════════════════════════════════
# PARES
# ═══════════════════════════════════════════════════════

PARES_DEFAULT = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
    "XRP-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT",
    "DOT-USDT", "ARB-USDT", "OP-USDT",   "NEAR-USDT",
    "LTC-USDT", "ATOM-USDT","DOGE-USDT", "SUI-USDT",
    "INJ-USDT", "TIA-USDT", "APT-USDT",  "MATIC-USDT",
]

def preparar_pares(pares_raw: list) -> list:
    bloqueados   = set(config.PARES_BLOQUEADOS)
    prioritarios = config.PARES_PRIORITARIOS
    limpios = [p for p in pares_raw if p not in bloqueados]
    top     = [p for p in prioritarios if p in set(limpios)]
    resto   = [p for p in limpios if p not in set(top)]
    log.info(f"Pares: {len(pares_raw)} → {len(bloqueados)} bloqueados "
             f"→ {len(top)} prioritarios + {len(resto)} resto = {len(top+resto)} activos")
    return top + resto


# ═══════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════

def _notif(msg: str):
    try:
        import requests
        tok = config.TELEGRAM_TOKEN.strip()
        cid = config.TELEGRAM_CHAT_ID.strip()
        if not tok or not cid:
            return
        requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Telegram: {e}")

def _notif_entrada(s: dict, balance: float, ejecutado: bool):
    lado  = "🟢 LONG" if s["lado"] == "LONG" else "🔴 SHORT"
    ex    = "✅ *Ejecutado*" if ejecutado else "⚠️ *No ejecutado*"
    star  = "⭐ " if s["par"] in config.PARES_PRIORITARIOS else ""
    motiv = " + ".join(s.get("motivos", []))
    kz    = s.get("kz", "")
    _notif(
        f"{lado} — {star}`{s['par']}` [{kz}]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Entrada : `{s['precio']:.6f}`\n"
        f"🔶 TP1     : `{s['tp1']:.6f}` (50%)\n"
        f"✅ TP2     : `{s['tp']:.6f}`\n"
        f"🛑 SL      : `{s['sl']:.6f}`\n"
        f"📊 R:R     : `{s['rr']:.2f}x`\n"
        f"🏅 Score   : `{s['score']}/8`\n"
        f"📉 RSI     : `{s['rsi']:.1f}`\n"
        f"🧩 Señales : `{motiv}`\n"
        f"💰 Balance : `${balance:.2f} USDT`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{ex}"
    )

def _notif_cierre(par: str, lado: str, entrada: float, salida: float, pnl: float, razon: str = ""):
    ico   = "✅" if pnl >= 0 else "❌"
    r_txt = f" ({razon})" if razon else ""
    _notif(
        f"{ico} *CIERRE {lado}{r_txt}* — `{par}`\n"
        f"`{entrada:.6f}` → `{salida:.6f}`\n"
        f"PnL: `${pnl:+.4f} USDT`"
    )


# ═══════════════════════════════════════════════════════
# CARGAR POSICIONES DESDE BINGX AL ARRANQUE  ← FIX CRÍTICO
# ═══════════════════════════════════════════════════════

def cargar_posiciones_desde_bingx():
    """
    Lee posiciones reales de BingX y las registra en estado.posiciones.
    Evita abrir el lado contrario tras un reinicio (hedging accidental).
    """
    if config.MODO_DEMO:
        log.info("[ARRANQUE] DEMO — posiciones reseteadas")
        return

    try:
        pos_reales = exchange.get_posiciones_abiertas()
        if not pos_reales:
            log.info("[ARRANQUE] Sin posiciones abiertas en BingX")
            return

        cargadas = 0
        for p in pos_reales:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue

            symbol = p.get("symbol", "")
            par    = symbol if "-" in symbol else symbol.replace("USDT", "-USDT")

            if par in estado.posiciones:
                log.warning(f"[ARRANQUE] {par} ya en estado — ignorando duplicado")
                continue

            lado   = "LONG" if amt > 0 else "SHORT"
            entry  = float(p.get("entryPrice", p.get("avgPrice", 0)) or 0)
            qty    = abs(amt)

            if entry <= 0 or qty <= 0:
                continue

            estado.posiciones[par] = {
                "lado":        lado,
                "entrada":     entry,
                "qty":         qty,
                "sl":          float(p.get("stopLoss", 0) or 0),
                "tp":          float(p.get("takeProfit", 0) or 0),
                "tp1":         0.0,
                "atr":         0.0,
                "sl_trailing": float(p.get("stopLoss", 0) or 0),
                "tp1_hit":     False,
                "ts":          datetime.now(timezone.utc).isoformat(),
                "recuperada":  True,
            }
            cargadas += 1
            log.info(f"[ARRANQUE] ✅ {lado} {par} entry={entry:.6f} qty={qty}")

        if cargadas:
            msg = (
                f"♻️ *SMC Bot reiniciado — {cargadas} posición(es) recuperada(s)*\n"
                + "\n".join(
                    f"  {'🟢' if v['lado']=='LONG' else '🔴'} `{k}` "
                    f"{v['lado']} @ `{v['entrada']:.6f}`"
                    for k, v in estado.posiciones.items()
                    if v.get("recuperada")
                )
            )
            log.warning(msg.replace("*", "").replace("`", ""))
            _notif(msg)

    except Exception as e:
        log.error(f"[ARRANQUE] Error: {e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════
# SINCRONIZACIÓN CONTINUA CON BINGX
# ═══════════════════════════════════════════════════════

def sincronizar_posiciones():
    if not estado.posiciones or config.MODO_DEMO:
        return
    try:
        pos_reales = exchange.get_posiciones_abiertas()
        reales = set()
        for p in pos_reales:
            s = p.get("symbol", "")
            reales.add(s)
            reales.add(s.replace("-", ""))
            if "USDT" in s and "-" not in s:
                reales.add(s.replace("USDT", "-USDT"))

        cerradas = [
            par for par in estado.posiciones
            if par not in reales and par.replace("-", "") not in reales
        ]

        for par in cerradas:
            pos    = estado.posiciones[par]
            lado   = pos["lado"]
            entry  = pos["entrada"]
            qty    = pos["qty"]
            sl_ef  = pos.get("sl_trailing", pos["sl"])
            tp     = pos["tp"]
            precio = exchange.get_precio(par)

            if sl_ef > 0 and tp > 0:
                if lado == "LONG":
                    salida, razon = (tp, "TP") if precio >= tp * 0.98 else (sl_ef, "SL")
                    pnl = qty * (salida - entry)
                else:
                    salida, razon = (tp, "TP") if precio <= tp * 1.02 else (sl_ef, "SL")
                    pnl = qty * (entry - salida)
            else:
                salida = precio
                razon  = "BINGX"
                pnl    = qty * ((precio - entry) if lado == "LONG" else (entry - precio))

            estado.registrar_cierre(pnl)
            memoria.registrar_resultado(par, pnl, lado)
            del estado.posiciones[par]
            log.info(f"[SYNC] {par} cerrado ({razon}) PnL≈{pnl:+.4f}")
            _notif_cierre(par, lado, entry, salida, pnl, f"BingX-{razon}")

    except Exception as e:
        log.error(f"[SYNC] {e}")


# ═══════════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════════

def actualizar_trailing(par: str, pos: dict, precio: float):
    if not config.TRAILING_ACTIVO:
        return
    atr     = pos.get("atr", 0)
    lado    = pos["lado"]
    entrada = pos["entrada"]
    if atr <= 0:
        return

    activar   = config.TRAILING_ACTIVAR
    distancia = config.TRAILING_DISTANCIA

    if lado == "LONG":
        if precio - entrada < atr * activar:
            return
        nuevo = precio - atr * distancia
        if nuevo > pos.get("sl_trailing", pos["sl"]):
            pos["sl_trailing"] = nuevo
    else:
        if entrada - precio < atr * activar:
            return
        nuevo = precio + atr * distancia
        if nuevo < pos.get("sl_trailing", pos["sl"]):
            pos["sl_trailing"] = nuevo


# ═══════════════════════════════════════════════════════
# PARTIAL TP
# ═══════════════════════════════════════════════════════

def gestionar_partial_tp(par: str, pos: dict, precio: float):
    if not config.PARTIAL_TP_ACTIVO or pos.get("tp1_hit"):
        return
    tp1  = pos.get("tp1", 0)
    lado = pos["lado"]
    if tp1 <= 0:
        return

    alcanzado = (precio >= tp1) if lado == "LONG" else (precio <= tp1)
    if not alcanzado:
        return

    qty     = pos["qty"]
    qty_tp1 = round(qty * 0.5, 6)

    if not config.MODO_DEMO:
        res         = exchange.cerrar_posicion(par, qty_tp1, lado)
        salida_real = (res or {}).get("precio_salida", precio) or precio
    else:
        salida_real = precio

    entrada = pos["entrada"]
    pnl_p   = qty_tp1 * ((salida_real - entrada) if lado == "LONG"
                          else (entrada - salida_real))
    estado.pnl_hoy += pnl_p

    be = entrada * 1.0005 if lado == "LONG" else entrada * 0.9995
    pos["sl"]          = be
    pos["sl_trailing"] = be
    pos["qty"]         = round(qty - qty_tp1, 6)
    pos["tp1_hit"]     = True

    log.info(f"[TP1] {par} 50% @ {salida_real:.6f} PnL_p={pnl_p:+.4f} SL→BE={be:.6f}")
    _notif(
        f"🔶 *TP1 ALCANZADO* — `{par}` {lado}\n"
        f"50% cerrado @ `{salida_real:.6f}`\n"
        f"PnL parcial: `${pnl_p:+.4f}` USDT\n"
        f"🔄 SL → breakeven `{be:.6f}`\n"
        f"▶️ Resto a TP2: `{pos['tp']:.6f}`"
    )


# ═══════════════════════════════════════════════════════
# TIME EXIT
# ═══════════════════════════════════════════════════════

def check_time_exit(par: str, pos: dict) -> bool:
    ts_str = pos.get("ts", "")
    if not ts_str:
        return False
    try:
        ts    = datetime.fromisoformat(ts_str)
        ahora = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        horas = (ahora - ts).total_seconds() / 3600
        if horas >= config.TIME_EXIT_HORAS:
            log.warning(f"[TIME_EXIT] {par} lleva {horas:.1f}h — cerrando")
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════
# GESTIONAR POSICIONES ABIERTAS
# ═══════════════════════════════════════════════════════

def gestionar_posiciones(balance: float):
    for par, pos in list(estado.posiciones.items()):
        try:
            precio = exchange.get_precio(par)
            if precio <= 0:
                continue
            lado = pos["lado"]
            qty  = pos["qty"]

            # Posiciones recuperadas sin SL/TP: sólo trailing, no cerrar por SL=0
            if pos.get("recuperada") and pos.get("sl", 0) <= 0:
                actualizar_trailing(par, pos, precio)
                continue

            # 1. Partial TP
            gestionar_partial_tp(par, pos, precio)

            # 2. Time exit
            if check_time_exit(par, pos):
                res         = exchange.cerrar_posicion(par, qty, lado)
                salida_real = (res or {}).get("precio_salida", precio) or precio
                pnl = qty * ((salida_real - pos["entrada"]) if lado == "LONG"
                             else (pos["entrada"] - salida_real))
                estado.registrar_cierre(pnl)
                memoria.registrar_resultado(par, pnl, lado)
                del estado.posiciones[par]
                _notif_cierre(par, lado, pos["entrada"], salida_real, pnl, "TIME")
                continue

            # 3. Trailing stop
            actualizar_trailing(par, pos, precio)
            sl_ef = pos.get("sl_trailing", pos["sl"])
            tp    = pos["tp"]

            sl_hit = (precio <= sl_ef) if lado == "LONG" else (precio >= sl_ef)
            tp_hit = (precio >= tp)    if lado == "LONG" else (precio <= tp)

            razon = salida = None
            if sl_hit:
                razon  = "TRAIL-SL" if pos.get("tp1_hit") else "SL"
                salida = sl_ef
            elif tp_hit:
                razon, salida = "TP2", tp

            if razon:
                res         = exchange.cerrar_posicion(par, qty, lado)
                salida_real = (res or {}).get("precio_salida", salida) or salida
                pnl = qty * ((salida_real - pos["entrada"]) if lado == "LONG"
                             else (pos["entrada"] - salida_real))
                estado.registrar_cierre(pnl)
                memoria.registrar_resultado(par, pnl, lado)
                del estado.posiciones[par]
                log.info(f"CIERRE {lado} {par} @ {salida_real:.6f} PnL={pnl:+.4f} ({razon})")
                _notif_cierre(par, lado, pos["entrada"], salida_real, pnl, razon)

        except Exception as e:
            log.error(f"gestionar {par}: {e}")
        time.sleep(0.5)


# ═══════════════════════════════════════════════════════
# EJECUTAR SEÑAL
# ═══════════════════════════════════════════════════════

def ejecutar_senal(s: dict, balance: float) -> bool:
    par   = s["par"]
    lado  = s["lado"]
    precio= s["precio"]

    # ── Anti-hedge: verificar posición existente ──
    if par in estado.posiciones:
        pos_existente = estado.posiciones[par]
        log.warning(f"[BLOQUEO] {par} ya tiene {pos_existente['lado']} abierto "
                    f"— señal {lado} DESCARTADA")
        return False

    if memoria.esta_bloqueado(par):
        log.info(f"[MEMORIA] {par} bloqueado"); return False
    if len(estado.posiciones) >= config.MAX_POSICIONES:
        return False
    if estado.max_perdida_alcanzada():
        log.warning(f"Máx pérdida diaria alcanzada (${estado.pnl_hoy:.2f})"); return False
    if balance < 5.0 and not config.MODO_DEMO:
        log.warning(f"Balance insuficiente: ${balance:.2f}"); return False

    qty = exchange.calcular_cantidad(par, balance, precio)
    if qty <= 0:
        return False

    if lado == "LONG":
        res = exchange.abrir_long(par, qty, precio, s["sl"], s["tp"])
    else:
        res = exchange.abrir_short(par, qty, precio, s["sl"], s["tp"])

    if not res or "error" in res:
        err = (res or {}).get("error", "vacío")
        log.error(f"Orden fallida {lado} {par}: {err}")
        memoria.registrar_error_api(par)
        _notif(f"🚨 *Orden fallida {lado} `{par}`*\n❌ `{err}`")
        return False

    # Precio real de ejecución
    entrada_real = float(res.get("fill_price", 0) or 0)
    if entrada_real <= 0:
        entrada_real = exchange.get_precio(par)
    if entrada_real <= 0:
        entrada_real = precio

    # Recalcular SL/TP/TP1 desde precio real
    atr = s.get("atr", 0)
    if atr > 0:
        sl_r  = (entrada_real - atr * config.SL_ATR_MULT)     if lado == "LONG" \
                else (entrada_real + atr * config.SL_ATR_MULT)
        tp_r  = (entrada_real + atr * config.TP_ATR_MULT)     if lado == "LONG" \
                else (entrada_real - atr * config.TP_ATR_MULT)
        tp1_r = (entrada_real + atr * config.PARTIAL_TP1_MULT) if lado == "LONG" \
                else (entrada_real - atr * config.PARTIAL_TP1_MULT)
    else:
        ratio = entrada_real / precio if precio > 0 else 1.0
        sl_r  = s["sl"]  * ratio
        tp_r  = s["tp"]  * ratio
        tp1_r = s["tp1"] * ratio

    qty_real = float(res.get("executedQty", qty) or qty)

    estado.posiciones[par] = {
        "lado":        lado,
        "entrada":     entrada_real,
        "qty":         qty_real,
        "sl":          sl_r,
        "tp":          tp_r,
        "tp1":         tp1_r,
        "atr":         atr,
        "sl_trailing": sl_r,
        "tp1_hit":     False,
        "ts":          datetime.now(timezone.utc).isoformat(),
        "recuperada":  False,
        "score":       s["score"],
        "motivos":     s.get("motivos", []),
    }

    slip = abs(entrada_real - precio) / precio * 100 if precio > 0 else 0
    slip_tag = f" ⚠️SLIP:{slip:.1f}%" if slip > 0.5 else ""
    log.info(
        f"✅ {lado} {par} fill:{entrada_real:.6f}{slip_tag} "
        f"SL:{sl_r:.6f} TP1:{tp1_r:.6f} TP2:{tp_r:.6f} "
        f"score:{s['score']} [{', '.join(s.get('motivos',[]))}]"
    )
    return True


# ═══════════════════════════════════════════════════════
# REPORTE HORARIO
# ═══════════════════════════════════════════════════════

def enviar_reporte(balance: float):
    prior   = set(config.PARES_PRIORITARIOS)
    pos_txt = ""
    for par, pos in estado.posiciones.items():
        p_actual = exchange.get_precio(par)
        pnl_est  = pos["qty"] * (
            (p_actual - pos["entrada"]) if pos["lado"] == "LONG"
            else (pos["entrada"] - p_actual)
        )
        fase  = "🔶→TP2" if pos.get("tp1_hit") else "▶️→TP1"
        ico   = "🟢" if pos["lado"] == "LONG" else "🔴"
        star  = "⭐" if par in prior else ""
        rec   = "♻️" if pos.get("recuperada") else ""
        ts_str= pos.get("ts", "")
        horas = ""
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
                horas = f" {h:.1f}h"
            except Exception:
                pass
        pos_txt += (f"  {ico}{star}{rec} `{par}` e:`{pos['entrada']:.5f}` "
                    f"est:${pnl_est:+.2f} {fase}{horas}\n")

    if not pos_txt:
        pos_txt = "  _(sin posiciones)_\n"

    w, l = estado.wins, estado.losses
    wr   = f"{w/(w+l)*100:.1f}%" if (w+l) > 0 else "N/A"
    kz   = analizar.en_killzone()

    _notif(
        f"📊 *Reporte — {config.VERSION}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance   : `${balance:.2f} USDT`\n"
        f"📈 Sesión    : `{w}W/{l}L` WR:`{wr}`\n"
        f"PnL hoy      : `${estado.pnl_hoy:+.4f}` USDT\n"
        f"🕐 Killzone  : `{kz['nombre']}`\n"
        f"🏅 Score≥`{config.SCORE_MIN}` | Lev:`{config.LEVERAGE}x`\n"
        f"🔶 Partial TP | ⏱ Time exit `{config.TIME_EXIT_HORAS}h`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Posiciones:\n{pos_txt}"
    )


# ═══════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════

def main():
    log.info("=" * 65)
    log.info(f"  {config.VERSION}")
    log.info(f"  SCORE≥{config.SCORE_MIN} | LEV:{config.LEVERAGE}x "
             f"| MAX_POS:{config.MAX_POSICIONES} | TF:{config.TIMEFRAME}")
    log.info(f"  TP:{config.TP_ATR_MULT}×ATR | SL:{config.SL_ATR_MULT}×ATR "
             f"| PARTIAL_TP1:{config.PARTIAL_TP1_MULT}×ATR")
    log.info(f"  TRAILING:{config.TRAILING_ACTIVO} | "
             f"TIME_EXIT:{config.TIME_EXIT_HORAS}h | "
             f"RIESGO:{config.RIESGO_PCT}%/trade")
    log.info(f"  SOLO_LONG:{config.SOLO_LONG} | DEMO:{config.MODO_DEMO}")
    log.info("=" * 65)

    balance = exchange.get_balance()
    log.info(f"Balance inicial: ${balance:.2f} USDT")

    if balance <= 0 and not config.MODO_DEMO:
        log.error("Balance = $0 — verifica BINGX_API_KEY y BINGX_SECRET_KEY en Railway")
        _notif("🚨 *Balance = $0.00*\nVerifica `BINGX_API_KEY` y `BINGX_SECRET_KEY`.")

    # ── CRÍTICO: cargar posiciones abiertas antes del primer ciclo ──
    cargar_posiciones_desde_bingx()

    # ── Pares ──
    pares_raw = PARES_FIJOS or PARES_DEFAULT
    pares     = preparar_pares(pares_raw)
    prior     = config.PARES_PRIORITARIOS
    bloq      = config.PARES_BLOQUEADOS

    _notif(
        f"🤖 *{config.VERSION}* arrancado\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance   : `${balance:.2f} USDT`\n"
        f"📊 Pares     : `{len(pares)}` activos\n"
        f"⭐ Prioritarios: `{len(prior)}` | 🚫 Bloqueados: `{len(bloq)}`\n"
        f"🏅 Score≥`{config.SCORE_MIN}` | Lev:`{config.LEVERAGE}x` | "
        f"Max:`{config.MAX_POSICIONES}` pos\n"
        f"🕐 TF:`{config.TIMEFRAME}` | Riesgo:`{config.RIESGO_PCT}%`/trade\n"
        f"🔶 Partial TP (50%@TP1→SL breakeven)\n"
        f"🎯 Trailing stop | ⏱ Time exit `{config.TIME_EXIT_HORAS}h`\n"
        f"🔄 Anti-hedge: activo\n"
        f"🧠 Memoria: activa\n"
        f"{'🔇 *DEMO*' if config.MODO_DEMO else '🟢 *LIVE — DINERO REAL*'}"
    )

    ciclo        = 0
    last_reporte = time.time()

    while True:
        try:
            ciclo += 1
            estado.reset_diario()
            balance = exchange.get_balance()

            kz = analizar.en_killzone()
            log.info(
                f"Ciclo {ciclo} | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | "
                f"Bal:${balance:.2f} | Pos:{len(estado.posiciones)} | "
                f"PnL:${estado.pnl_hoy:+.4f} | KZ:{kz['nombre']}"
            )

            # Verificar pérdida máxima diaria
            if estado.max_perdida_alcanzada():
                log.warning(f"🛑 Máx pérdida diaria alcanzada (${estado.pnl_hoy:.2f}) — pausa hasta mañana")
                _notif(f"🛑 *Máx pérdida diaria* `${estado.pnl_hoy:.2f}` — bot en pausa")
                time.sleep(config.LOOP_SECONDS * 10)
                continue

            # 1. Sincronizar con BingX
            sincronizar_posiciones()

            # 2. Gestionar posiciones abiertas
            if estado.posiciones:
                gestionar_posiciones(balance)
                balance = exchange.get_balance()

            # 3. Buscar nuevas señales
            if len(estado.posiciones) < config.MAX_POSICIONES:
                log.info(f"Escaneando {len(pares)} pares (score≥{config.SCORE_MIN}, KZ:{kz['nombre']})...")
                senales = analizar.analizar_todos(pares)

                if senales:
                    log.info(f"✓ {len(senales)} señal(es) encontrada(s):")
                    for s in senales:
                        star  = "⭐" if s["par"] in prior else " "
                        log.info(
                            f"  {star}{s['lado']:5s} {s['par']:15s} "
                            f"score={s['score']} RSI={s['rsi']:.1f} "
                            f"R:R={s['rr']:.2f} KZ={s['kz']} "
                            f"[{'+'.join(s.get('motivos',[]))}]"
                        )
                else:
                    log.info("Sin señales este ciclo")

                for s in senales:
                    if len(estado.posiciones) >= config.MAX_POSICIONES:
                        break
                    if s["par"] in estado.posiciones:
                        continue

                    # Ajustar score con historial
                    s["score"] = memoria.ajustar_score(s["par"], s["score"])
                    if s["score"] < config.SCORE_MIN:
                        log.info(f"[MEMORIA] {s['par']} score ajustado={s['score']} < {config.SCORE_MIN}")
                        continue

                    ejecutado = ejecutar_senal(s, balance)
                    _notif_entrada(s, balance, ejecutado)
                    if ejecutado:
                        balance = exchange.get_balance()
                        time.sleep(2)

            # 4. Reporte horario
            if time.time() - last_reporte >= 3600:
                enviar_reporte(balance)
                _notif(memoria.resumen())
                last_reporte = time.time()

        except KeyboardInterrupt:
            log.info("Detenido manualmente")
            _notif("🛑 *SMC Bot detenido manualmente.*")
            break
        except Exception as e:
            log.error(f"ERROR CICLO {ciclo}: {e}")
            log.error(traceback.format_exc())
            try:
                _notif(f"🚨 *Error ciclo {ciclo}*\n`{str(e)[:200]}`")
            except Exception:
                pass

        log.info(f"Próximo ciclo en {config.LOOP_SECONDS}s — "
                 f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        log.info("-" * 60)
        time.sleep(config.LOOP_SECONDS)


if __name__ == "__main__":
    main()
