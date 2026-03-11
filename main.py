"""
main.py — SMC Bot BingX v3.1 [CORREGIDO + MEJORADO]
Mejoras vs v3.0:
  ✅ Mensaje de arranque con resumen de todos los fixes
  ✅ Anti-hedge mejorado: verifica posición contraria en mismo par
  ✅ Manejo de señales con score ajustado por memoria
  ✅ Sincronización de posiciones más robusta
  ✅ Reporte de ciclo más informativo
  ✅ Comando /status mejorado via Telegram webhook (próxima versión)
"""

import sys, os, time, traceback
from datetime import datetime, date, timezone
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s — %(message)s",
    stream=sys.stdout,
    force=True,
)
# Subir a DEBUG para ver logs de no-señal
if os.getenv("LOG_LEVEL", "").upper() == "DEBUG":
    logging.getLogger().setLevel(logging.DEBUG)

log = logging.getLogger("main")
log.info("=== ARRANQUE SMC BOT v3.1 ===")

try:
    import config, exchange, analizar, memoria, scanner_pares
except Exception as e:
    log.error(f"ERROR importando módulos: {e}\n{traceback.format_exc()}")
    sys.exit(1)

log.info(f"Módulos OK | {config.VERSION}")
errores_config = config.validar()
for err in errores_config:
    log.warning(f"⚠️  CONFIG: {err}")


# ═══════════════════════════════════════════════════════
# GRUPOS DE CORRELACIÓN
# ═══════════════════════════════════════════════════════

GRUPOS_CORRELACION = [
    {"BTC-USDT", "ETH-USDT"},
    {"SOL-USDT", "AVAX-USDT", "APT-USDT", "SUI-USDT"},
    {"ARB-USDT", "OP-USDT"},
    {"DOGE-USDT", "SHIB-USDT", "PEPE-USDT", "WIF-USDT"},
    {"LINK-USDT", "BAND-USDT"},
    {"BNB-USDT", "TRX-USDT"},
]

def hay_correlacion(par: str, lado: str, posiciones: dict) -> bool:
    if not config.CORRELACION_ACTIVO:
        return False
    for grupo in GRUPOS_CORRELACION:
        if par not in grupo:
            continue
        for par_abierto, pos in posiciones.items():
            if par_abierto in grupo and par_abierto != par:
                if pos["lado"] == lado:
                    log.info(f"[CORR] {par} {lado} bloqueado — {par_abierto} ya abierto en mismo grupo/lado")
                    return True
    return False


def hay_hedge(par: str, lado: str, posiciones: dict) -> bool:
    """Bloquea si ya hay una posición contraria abierta en el mismo par."""
    if par in posiciones:
        pos_actual = posiciones[par]
        if pos_actual["lado"] != lado:
            log.info(f"[ANTI-HEDGE] {par} {lado} bloqueado — ya hay {pos_actual['lado']} abierto")
            return True
    return False


# ═══════════════════════════════════════════════════════
# ESTADO
# ═══════════════════════════════════════════════════════

class Estado:
    def __init__(self):
        self.posiciones = {}
        self.pnl_hoy    = 0.0
        self.dia_actual = str(date.today())
        self.wins       = 0
        self.losses     = 0

    def reset_diario(self):
        hoy = str(date.today())
        if hoy != self.dia_actual:
            self.dia_actual = hoy
            self.pnl_hoy    = 0.0
            log.info(f"[RESET DIARIO] {hoy} — PnL reseteado")

    def registrar_cierre(self, pnl: float):
        self.pnl_hoy += pnl
        if pnl > 0:
            self.wins   += 1
        else:
            self.losses += 1

    def max_perdida_alcanzada(self) -> bool:
        return config.MAX_PERDIDA_DIA > 0 and self.pnl_hoy <= -config.MAX_PERDIDA_DIA


estado = Estado()


# ═══════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════

def _notif(msg: str):
    try:
        import requests as rq
        tok = config.TELEGRAM_TOKEN.strip()
        cid = config.TELEGRAM_CHAT_ID.strip()
        if not tok or not cid:
            return
        rq.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Telegram: {e}")


def _notif_entrada(s: dict, trade_usdt: float, ejecutado: bool):
    lado  = "🟢 LONG" if s["lado"] == "LONG" else "🔴 SHORT"
    ex    = "✅ *Ejecutado*" if ejecutado else "⚠️ *No ejecutado*"
    motiv = " + ".join(s.get("motivos", []))

    extras = ""
    if s.get("ob_bull") or s.get("ob_bear"):
        extras += "📦 `Order Block`\n"
    if s.get("choch_bull") or s.get("choch_bear"):
        extras += "🔄 `Change of Character`\n"
    elif s.get("bos_bull") or s.get("bos_bear"):
        extras += "🔨 `Break of Structure`\n"
    if s.get("htf") in ("BULL", "BEAR"):
        extras += f"📈 MTF 1h: `{s['htf']}`\n"
    if s.get("vela_conf"):
        extras += "🕯️ `Vela confirmadora`\n"
    if s.get("asia_valido"):
        extras += "🌙 `Rango Asia activo`\n"

    _notif(
        f"{lado} — `{s['par']}` [{s.get('kz', '')}]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Entrada : `{s['precio']:.6f}`\n"
        f"🔶 TP1     : `{s['tp1']:.6f}` (50%)\n"
        f"✅ TP2     : `{s['tp']:.6f}`\n"
        f"🛑 SL      : `{s['sl']:.6f}`\n"
        f"📊 R:R     : `{s['rr']:.2f}x`\n"
        f"🏅 Score   : `{s['score']}/12`\n"
        f"📉 RSI     : `{s['rsi']:.1f}`\n"
        f"🧩 Señales : `{motiv}`\n"
        f"{extras}"
        f"💵 Trade   : `${trade_usdt:.2f}` × {config.LEVERAGE}x\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{ex}"
    )


def _notif_cierre(par, lado, entrada, salida, pnl, razon="", trade_usdt=0):
    ico  = "✅" if pnl >= 0 else "❌"
    comp = memoria._data["compounding"]
    _notif(
        f"{ico} *CIERRE {lado}* ({razon}) — `{par}`\n"
        f"`{entrada:.6f}` → `{salida:.6f}`\n"
        f"PnL: `${pnl:+.4f} USDT`\n"
        f"💰 Pool reinversión: `${comp['ganancias']:.2f}`\n"
        f"📈 Próx trade: `${memoria.get_trade_amount():.2f} USDT`"
    )


# ═══════════════════════════════════════════════════════
# CARGAR POSICIONES AL ARRANQUE
# ═══════════════════════════════════════════════════════

def cargar_posiciones_desde_bingx():
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
                continue
            lado   = "LONG" if amt > 0 else "SHORT"
            entry  = float(p.get("entryPrice", 0) or 0)
            qty    = abs(amt)
            if entry <= 0 or qty <= 0:
                continue
            estado.posiciones[par] = {
                "lado":        lado,
                "entrada":     entry,
                "qty":         qty,
                "sl":          float(p.get("stopLoss",    0) or 0),
                "tp":          float(p.get("takeProfit",  0) or 0),
                "tp1":         0.0,
                "atr":         0.0,
                "sl_trailing": float(p.get("stopLoss",    0) or 0),
                "tp1_hit":     False,
                "ts":          datetime.now(timezone.utc).isoformat(),
                "recuperada":  True,
                "trade_usdt":  config.TRADE_USDT_BASE,
            }
            cargadas += 1
            log.info(f"[ARRANQUE] ✅ {lado} {par} entry={entry:.6f} qty={qty}")

        if cargadas:
            _notif(
                f"♻️ *Bot reiniciado — {cargadas} posición(es) recuperada(s)*\n"
                + "\n".join(
                    f"  {'🟢' if v['lado']=='LONG' else '🔴'} `{k}` {v['lado']} @ `{v['entrada']:.6f}`"
                    for k, v in estado.posiciones.items()
                    if v.get("recuperada")
                )
            )
    except Exception as e:
        log.error(f"[ARRANQUE] {e}")


# ═══════════════════════════════════════════════════════
# SINCRONIZACIÓN
# ═══════════════════════════════════════════════════════

def sincronizar_posiciones():
    if not estado.posiciones or config.MODO_DEMO:
        return
    try:
        pos_reales = exchange.get_posiciones_abiertas()
        reales     = set()
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
                salida, razon = precio, "BINGX"
                pnl = qty * ((precio - entry) if lado == "LONG" else (entry - precio))

            estado.registrar_cierre(pnl)
            memoria.registrar_resultado(
                par, pnl, lado,
                kz=pos.get("kz", ""),
                motivos=pos.get("motivos", []),
            )
            del estado.posiciones[par]
            _notif_cierre(par, lado, entry, salida, pnl, f"BingX-{razon}")
            log.info(f"[SYNC] {par} cerrado ({razon}) PnL≈{pnl:+.4f}")

    except Exception as e:
        log.error(f"[SYNC] {e}")


# ═══════════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════════

def actualizar_trailing(par, pos, precio):
    if not config.TRAILING_ACTIVO:
        return
    atr  = pos.get("atr", 0)
    lado = pos["lado"]
    if atr <= 0:
        return
    if lado == "LONG":
        if precio - pos["entrada"] < atr * config.TRAILING_ACTIVAR:
            return
        nuevo = precio - atr * config.TRAILING_DISTANCIA
        if nuevo > pos.get("sl_trailing", pos["sl"]):
            pos["sl_trailing"] = nuevo
    else:
        if pos["entrada"] - precio < atr * config.TRAILING_ACTIVAR:
            return
        nuevo = precio + atr * config.TRAILING_DISTANCIA
        if nuevo < pos.get("sl_trailing", pos["sl"]):
            pos["sl_trailing"] = nuevo


# ═══════════════════════════════════════════════════════
# PARTIAL TP
# ═══════════════════════════════════════════════════════

def gestionar_partial_tp(par, pos, precio):
    if not config.PARTIAL_TP_ACTIVO or pos.get("tp1_hit"):
        return
    tp1  = pos.get("tp1", 0)
    lado = pos["lado"]
    if tp1 <= 0:
        return
    alcanzado = (precio >= tp1) if lado == "LONG" else (precio <= tp1)
    if not alcanzado:
        return

    qty_tp1 = round(pos["qty"] * 0.5, 6)
    if not config.MODO_DEMO:
        res         = exchange.cerrar_posicion(par, qty_tp1, lado)
        salida_real = (res or {}).get("precio_salida", precio) or precio
    else:
        salida_real = precio

    entrada = pos["entrada"]
    pnl_p   = qty_tp1 * (
        (salida_real - entrada) if lado == "LONG"
        else (entrada - salida_real)
    )
    estado.pnl_hoy += pnl_p
    memoria.registrar_ganancia_compounding(pnl_p)

    be             = entrada * 1.0005 if lado == "LONG" else entrada * 0.9995
    pos["sl"]      = pos["sl_trailing"] = be
    pos["qty"]     = round(pos["qty"] - qty_tp1, 6)
    pos["tp1_hit"] = True

    log.info(f"[TP1] {par} 50% @ {salida_real:.6f} PnL_p={pnl_p:+.4f} SL→BE={be:.6f}")
    _notif(
        f"🔶 *TP1* — `{par}` {lado}\n"
        f"50% @ `{salida_real:.6f}` | PnL: `${pnl_p:+.4f}`\n"
        f"🔄 SL → `{be:.6f}` (breakeven)\n"
        f"📈 Próx trade: `${memoria.get_trade_amount():.2f} USDT`"
    )


# ═══════════════════════════════════════════════════════
# TIME EXIT
# ═══════════════════════════════════════════════════════

def check_time_exit(par, pos) -> bool:
    ts_str = pos.get("ts", "")
    if not ts_str:
        return False
    try:
        ts    = datetime.fromisoformat(ts_str)
        ahora = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (ahora - ts).total_seconds() / 3600 >= config.TIME_EXIT_HORAS:
            log.warning(f"[TIME_EXIT] {par} lleva más de {config.TIME_EXIT_HORAS}h")
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════
# GESTIONAR POSICIONES
# ═══════════════════════════════════════════════════════

def gestionar_posiciones():
    for par, pos in list(estado.posiciones.items()):
        try:
            precio = exchange.get_precio(par)
            if precio <= 0:
                continue
            lado = pos["lado"]
            qty  = pos["qty"]

            if pos.get("recuperada") and pos.get("sl", 0) <= 0:
                actualizar_trailing(par, pos, precio)
                continue

            gestionar_partial_tp(par, pos, precio)

            if check_time_exit(par, pos):
                res         = exchange.cerrar_posicion(par, qty, lado)
                salida_real = (res or {}).get("precio_salida", precio) or precio
                pnl = qty * (
                    (salida_real - pos["entrada"]) if lado == "LONG"
                    else (pos["entrada"] - salida_real)
                )
                estado.registrar_cierre(pnl)
                memoria.registrar_resultado(par, pnl, lado,
                    kz=pos.get("kz", ""), motivos=pos.get("motivos", []))
                del estado.posiciones[par]
                _notif_cierre(par, lado, pos["entrada"], salida_real, pnl, "TIME")
                continue

            actualizar_trailing(par, pos, precio)
            sl_ef  = pos.get("sl_trailing", pos["sl"])
            tp     = pos["tp"]
            sl_hit = (precio <= sl_ef) if lado == "LONG" else (precio >= sl_ef)
            tp_hit = (precio >= tp)    if lado == "LONG" else (precio <= tp)

            razon = salida = None
            if sl_hit:
                razon  = "TRAIL-SL" if pos.get("tp1_hit") else "SL"
                salida = sl_ef
            elif tp_hit:
                razon  = "TP2"
                salida = tp

            if razon:
                res         = exchange.cerrar_posicion(par, qty, lado)
                salida_real = (res or {}).get("precio_salida", salida) or salida
                pnl = qty * (
                    (salida_real - pos["entrada"]) if lado == "LONG"
                    else (pos["entrada"] - salida_real)
                )
                estado.registrar_cierre(pnl)
                memoria.registrar_resultado(par, pnl, lado,
                    kz=pos.get("kz", ""), motivos=pos.get("motivos", []))
                del estado.posiciones[par]
                log.info(f"CIERRE {lado} {par} @ {salida_real:.6f} PnL={pnl:+.4f} ({razon})")
                _notif_cierre(par, lado, pos["entrada"], salida_real, pnl, razon,
                              pos.get("trade_usdt", config.TRADE_USDT_BASE))

        except Exception as e:
            log.error(f"gestionar {par}: {e}")
        time.sleep(0.3)


# ═══════════════════════════════════════════════════════
# EJECUTAR SEÑAL
# ═══════════════════════════════════════════════════════

def ejecutar_senal(s: dict) -> bool:
    par  = s["par"]
    lado = s["lado"]

    if par in estado.posiciones:
        log.warning(f"[BLOQUEO] {par} ya tiene {estado.posiciones[par]['lado']}")
        return False
    if hay_hedge(par, lado, estado.posiciones):
        return False
    if hay_correlacion(par, lado, estado.posiciones):
        return False
    if memoria.esta_bloqueado(par):
        return False
    if len(estado.posiciones) >= config.MAX_POSICIONES:
        log.debug(f"[BLOQUEO] Máx posiciones {config.MAX_POSICIONES} alcanzadas")
        return False
    if estado.max_perdida_alcanzada():
        log.warning("[BLOQUEO] Máx pérdida diaria alcanzada")
        return False

    balance = exchange.get_balance()
    if balance < 5.0 and not config.MODO_DEMO:
        log.warning(f"Balance insuficiente: ${balance:.2f}")
        return False

    trade_usdt = memoria.get_trade_amount()
    qty        = exchange.calcular_cantidad(par, trade_usdt, s["precio"])
    if qty <= 0:
        log.warning(f"[{par}] Cantidad calculada = 0")
        return False

    margen_necesario = trade_usdt * 1.1
    if balance < margen_necesario and not config.MODO_DEMO:
        log.warning(f"[{par}] Margen insuficiente: ${balance:.2f} < ${margen_necesario:.2f}")
        return False

    if lado == "LONG":
        res = exchange.abrir_long(par, qty, s["precio"], s["sl"], s["tp"])
    else:
        res = exchange.abrir_short(par, qty, s["precio"], s["sl"], s["tp"])

    if not res or "error" in res:
        err = (res or {}).get("error", "respuesta vacía")
        log.error(f"Orden fallida {lado} {par}: {err}")
        memoria.registrar_error_api(par)
        _notif(f"🚨 *Orden fallida {lado} `{par}`*\n❌ `{err}`")
        return False

    entrada_real = float(res.get("fill_price", 0) or 0)
    if entrada_real <= 0:
        entrada_real = exchange.get_precio(par) or s["precio"]

    atr    = s.get("atr", 0)
    precio = s["precio"]
    if atr > 0:
        sl_r  = (entrada_real - atr * config.SL_ATR_MULT)  if lado == "LONG" else (entrada_real + atr * config.SL_ATR_MULT)
        tp_r  = (entrada_real + atr * config.TP_ATR_MULT)  if lado == "LONG" else (entrada_real - atr * config.TP_ATR_MULT)
        tp1_r = (entrada_real + atr * config.PARTIAL_TP1_MULT) if lado == "LONG" else (entrada_real - atr * config.PARTIAL_TP1_MULT)
    else:
        ratio = entrada_real / precio if precio > 0 else 1.0
        sl_r  = s["sl"]  * ratio
        tp_r  = s["tp"]  * ratio
        tp1_r = s["tp1"] * ratio

    qty_real = float(res.get("executedQty", qty) or qty)
    memoria.registrar_inversion(trade_usdt)

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
        "kz":          s.get("kz", ""),
        "trade_usdt":  trade_usdt,
    }

    slip = abs(entrada_real - precio) / precio * 100 if precio > 0 else 0
    log.info(
        f"✅ {lado} {par} fill:{entrada_real:.6f} "
        f"{'⚠️ SLIP:'+str(round(slip,1))+'%' if slip > 0.5 else ''} "
        f"trade:${trade_usdt:.2f} SL:{sl_r:.6f} TP2:{tp_r:.6f} "
        f"score:{s['score']}/12 HTF:{s.get('htf','?')} "
        f"OB:{s.get('ob_bull') or s.get('ob_bear')} "
        f"BOS:{s.get('bos_bull') or s.get('bos_bear')}"
    )
    return True


# ═══════════════════════════════════════════════════════
# REPORTE HORARIO
# ═══════════════════════════════════════════════════════

def enviar_reporte(balance: float):
    pos_txt = ""
    for par, pos in estado.posiciones.items():
        p_actual = exchange.get_precio(par)
        if p_actual > 0:
            pnl_est = pos["qty"] * (
                (p_actual - pos["entrada"]) if pos["lado"] == "LONG"
                else (pos["entrada"] - p_actual)
            )
        else:
            pnl_est = 0
        fase = "🔶→TP2" if pos.get("tp1_hit") else "▶️→TP1"
        ico  = "🟢" if pos["lado"] == "LONG" else "🔴"
        pos_txt += f"  {ico} `{par}` est:${pnl_est:+.2f} {fase} [{pos.get('score','?')}/12]\n"
    if not pos_txt:
        pos_txt = "  _(sin posiciones)_\n"

    w, l = estado.wins, estado.losses
    wr   = f"{w/(w+l)*100:.1f}%" if (w + l) > 0 else "N/A"
    comp = memoria._data["compounding"]
    kz   = analizar.en_killzone()

    _notif(
        f"📊 *Reporte — {config.VERSION}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance    : `${balance:.2f} USDT`\n"
        f"📈 Sesión     : `{w}W / {l}L` WR:`{wr}`\n"
        f"PnL hoy       : `${estado.pnl_hoy:+.4f}` USDT\n"
        f"🕐 Killzone   : `{kz['nombre']}`\n"
        f"💵 Trade size : `${memoria.get_trade_amount():.2f}`\n"
        f"💹 Pool reinv.: `${comp['ganancias']:.2f}` USDT\n"
        f"📊 Total PnL  : `${comp['total_ganado']:+.4f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Posiciones:\n{pos_txt}"
    )


# ═══════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════

def main():
    log.info("=" * 65)
    log.info(f"  {config.VERSION}")
    log.info(f"  TRADE: ${config.TRADE_USDT_BASE} base + compounding (máx ${config.TRADE_USDT_MAX})")
    log.info(f"  LEV:{config.LEVERAGE}x | MAX_POS:{config.MAX_POSICIONES} | TF:{config.TIMEFRAME} | MTF:{config.MTF_TIMEFRAME}")
    log.info(f"  SCORE≥{config.SCORE_MIN}/12 | PIVOT_PCT:{config.PIVOT_NEAR_PCT}% | MIN_RR:{config.MIN_RR}")
    log.info(f"  SOLO_LONG:{config.SOLO_LONG} | DEMO:{config.MODO_DEMO}")
    log.info(f"  MTF={config.MTF_ACTIVO} OB={config.OB_ACTIVO} BOS={config.BOS_ACTIVO}")
    log.info(f"  ASIA={config.ASIA_RANGE_ACTIVO} VELA={config.VELA_CONFIRMACION} CORR={config.CORRELACION_ACTIVO}")
    log.info(f"  MEMORY: {memoria.MEMORY_FILE}")
    log.info("=" * 65)

    balance = exchange.get_balance()
    log.info(f"Balance inicial: ${balance:.2f} USDT")

    if balance <= 0 and not config.MODO_DEMO:
        _notif("🚨 *Balance = $0*\nVerifica las API keys en Railway.")

    cargar_posiciones_desde_bingx()

    log.info("Cargando pares de BingX...")
    pares_todos  = scanner_pares.get_pares_cached(config.VOLUMEN_MIN_24H)
    bloq_config  = set(config.PARES_BLOQUEADOS)
    pares_todos  = [p for p in pares_todos if p not in bloq_config]
    prioritarios = [p for p in config.PARES_PRIORITARIOS if p in set(pares_todos)]
    top_memoria  = [p for p in memoria.get_top_pares(10) if p in set(pares_todos)]
    resto        = [p for p in pares_todos
                    if p not in set(prioritarios) and p not in set(top_memoria)]
    pares        = prioritarios + top_memoria + resto

    if config.MAX_PARES_SCAN > 0:
        pares = pares[:config.MAX_PARES_SCAN]

    log.info(f"Total pares a escanear: {len(pares)}")

    _notif(
        f"🤖 *{config.VERSION}*\narrancado\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance    : `${balance:.2f} USDT`\n"
        f"💵 Trade size : `${memoria.get_trade_amount():.2f} USDT` (base ${config.TRADE_USDT_BASE})\n"
        f"📊 Pares      : `{len(pares)}` (todos BingX >${config.VOLUMEN_MIN_24H/1e6:.0f}M vol)\n"
        f"🏅 Score≥`{config.SCORE_MIN}/12` | Lev:`{config.LEVERAGE}x` | Max:`{config.MAX_POSICIONES}` pos\n"
        f"📐 Pivot zone : `±{config.PIVOT_NEAR_PCT}%` | Min R:R `{config.MIN_RR}x`\n"
        f"🔄 Compounding: cada ${config.COMPOUND_STEP_USDT:.0f} ganados → +${config.COMPOUND_ADD_USDT:.0f}/trade\n"
        f"🧠 Aprendizaje: blacklist automático + score dinámico\n"
        f"🔁 Anti-hedge: activo\n"
        f"⏱️ Time exit: {config.TIME_EXIT_HORAS}h\n"
        f"{'🔇 *DEMO*' if config.MODO_DEMO else '🟢 *LIVE — DINERO REAL*'}"
    )

    ciclo           = 0
    last_reporte    = time.time()
    last_scan_pares = time.time()

    while True:
        try:
            ciclo += 1
            estado.reset_diario()
            balance = exchange.get_balance()
            kz      = analizar.en_killzone()

            log.info(
                f"Ciclo {ciclo} | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | "
                f"Bal:${balance:.2f} | Pos:{len(estado.posiciones)} | "
                f"PnL:${estado.pnl_hoy:+.4f} | KZ:{kz['nombre']} | "
                f"Score≥{config.SCORE_MIN} | Trade:${memoria.get_trade_amount():.2f}"
            )

            # Refrescar lista de pares cada hora
            if time.time() - last_scan_pares > 3600:
                nuevos   = scanner_pares.get_pares_cached(config.VOLUMEN_MIN_24H)
                nuevos   = [p for p in nuevos if p not in bloq_config]
                bloq_mem = set(memoria.get_pares_bloqueados())
                top_m    = [p for p in memoria.get_top_pares(10) if p in set(nuevos)]
                resto_n  = [p for p in nuevos if p not in set(top_m) and p not in bloq_mem]
                pares    = prioritarios + top_m + resto_n
                if config.MAX_PARES_SCAN > 0:
                    pares = pares[:config.MAX_PARES_SCAN]
                log.info(f"Pares actualizados: {len(pares)}")
                last_scan_pares = time.time()

            if estado.max_perdida_alcanzada():
                log.warning(f"🛑 Máx pérdida diaria (${estado.pnl_hoy:.2f})")
                _notif(
                    f"🛑 *Máx pérdida diaria* `${estado.pnl_hoy:.2f}`\n"
                    f"Bot en pausa hasta mañana"
                )
                time.sleep(config.LOOP_SECONDS * 30)
                continue

            sincronizar_posiciones()

            if estado.posiciones:
                gestionar_posiciones()
                balance = exchange.get_balance()

            if len(estado.posiciones) < config.MAX_POSICIONES:
                bloq_ahora = set(memoria.get_pares_bloqueados())
                pares_scan = [
                    p for p in pares
                    if p not in estado.posiciones and p not in bloq_ahora
                ]

                log.info(
                    f"Escaneando {len(pares_scan)} pares | "
                    f"KZ:{kz['nombre']} | Score≥{config.SCORE_MIN}/12"
                )
                senales = analizar.analizar_todos(pares_scan, workers=config.ANALISIS_WORKERS)

                if senales:
                    log.info(f"✓ {len(senales)} señal(es) encontradas:")
                    for s in senales[:10]:
                        log.info(
                            f"  {s['lado']:5s} {s['par']:15s} "
                            f"score={s['score']}/12 RSI={s['rsi']:.1f} "
                            f"R:R={s['rr']:.2f} KZ={s['kz']} HTF={s.get('htf','?')} "
                            f"OB={s.get('ob_bull') or s.get('ob_bear')} "
                            f"BOS={s.get('bos_bull') or s.get('bos_bear')}"
                        )
                else:
                    log.info("Sin señales este ciclo")

                for s in senales:
                    if len(estado.posiciones) >= config.MAX_POSICIONES:
                        break
                    if s["par"] in estado.posiciones:
                        continue

                    # Ajustar score con aprendizaje
                    s["score"] = memoria.ajustar_score(
                        s["par"], s["score"],
                        kz=s.get("kz", ""),
                        motivos=s.get("motivos", []),
                    )
                    if s["score"] < config.SCORE_MIN:
                        log.info(
                            f"[MEMORIA] {s['par']} score={s['score']} "
                            f"< {config.SCORE_MIN} (ajustado por historial)"
                        )
                        continue

                    ejecutado = ejecutar_senal(s)
                    _notif_entrada(s, memoria.get_trade_amount(), ejecutado)
                    if ejecutado:
                        balance = exchange.get_balance()
                        time.sleep(2)

            # Reporte horario
            if time.time() - last_reporte >= 3600:
                enviar_reporte(balance)
                _notif(memoria.resumen())
                last_reporte = time.time()

        except KeyboardInterrupt:
            log.info("Detenido manualmente (Ctrl+C)")
            _notif("🛑 *SMC Bot v3.1 detenido manualmente.*")
            break
        except Exception as e:
            log.error(f"ERROR CICLO {ciclo}: {e}\n{traceback.format_exc()}")
            try:
                _notif(f"🚨 *Error ciclo {ciclo}*\n`{str(e)[:200]}`")
            except Exception:
                pass

        log.info(f"Próximo ciclo en {config.LOOP_SECONDS}s")
        log.info("-" * 60)
        time.sleep(config.LOOP_SECONDS)


if __name__ == "__main__":
    main()
