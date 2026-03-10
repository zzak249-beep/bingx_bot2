"""
╔══════════════════════════════════════════════════════════════════╗
║   BingX FUTURES — VWAP + EMA9 Bot v1.0                          ║
║   Estrategia:                                                    ║
║   • VWAP + Bandas de desviación estándar (±1σ, ±2σ)            ║
║   • EMA 9 como filtro de tendencia y confirmación               ║
║   • LONG: precio toca banda inferior VWAP + EMA9 apunta arriba ║
║   • SHORT: precio toca banda superior VWAP + EMA9 apunta abajo ║
║   • TP extendido: 4×ATR (deja correr las ganancias)            ║
║   • Partial TP 50% en 2×ATR + SL a breakeven                   ║
║   • Trailing stop activo tras TP1                               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, traceback, hmac, hashlib, json
import numpy as np
import requests
from datetime import datetime, date, timezone
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    stream=sys.stdout, force=True,
)
log = logging.getLogger("vwap_bot")

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════

API_KEY    = os.getenv("BINGX_API_KEY",    "")
API_SECRET = os.getenv("BINGX_SECRET_KEY", os.getenv("BINGX_API_SECRET", ""))
TG_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TG_CHAT    = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL   = "https://open-api.bingx.com"

MODO_DEMO      = os.getenv("MODO_DEMO",  "false").lower() == "true"
LEVERAGE       = int(os.getenv("LEVERAGE",       "7"))
MARGEN_USDT    = float(os.getenv("MARGEN_USDT",  "8"))
MAX_POS        = int(os.getenv("MAX_POS",         "3"))
LOOP_SECONDS   = int(os.getenv("LOOP_SECONDS",    "60"))

# VWAP
VWAP_PERIODO   = int(os.getenv("VWAP_PERIODO",   "20"))   # velas para VWAP
VWAP_STD1      = float(os.getenv("VWAP_STD1",    "1.0"))  # banda interna
VWAP_STD2      = float(os.getenv("VWAP_STD2",    "2.0"))  # banda externa

# EMA
EMA_PERIODO    = int(os.getenv("EMA_PERIODO",    "9"))

# ATR / SL / TP
ATR_PERIODO    = int(os.getenv("ATR_PERIODO",    "14"))
SL_ATR_MULT    = float(os.getenv("SL_ATR_MULT",  "1.5"))
TP_ATR_MULT    = float(os.getenv("TP_ATR_MULT",  "4.0"))  # TP extendido
TP1_ATR_MULT   = float(os.getenv("TP1_ATR_MULT", "2.0"))  # Partial TP

# FILTROS
VOLUMEN_MIN    = float(os.getenv("VOLUMEN_MIN",   "500000"))
SPREAD_MAX     = float(os.getenv("SPREAD_MAX",    "1.5"))
SCORE_MIN      = int(os.getenv("SCORE_MIN",       "60"))

# TRAILING
TRAIL_ACTIVAR  = float(os.getenv("TRAIL_ACTIVAR", "2.0"))  # activa en 2×ATR
TRAIL_DIST     = float(os.getenv("TRAIL_DIST",    "1.0"))

# TIME EXIT
TIME_EXIT_H    = int(os.getenv("TIME_EXIT_H",    "10"))

VERSION = "BingX-VWAP+EMA9-v1.0"

PARES = [
    "BERA-USDT", "PI-USDT",   "OP-USDT",    "NEAR-USDT",
    "ARB-USDT",  "LINK-USDT", "GRASS-USDT", "MYX-USDT",
    "KAITO-USDT","ONDO-USDT", "POPCAT-USDT","LTC-USDT",
    "AVAX-USDT", "INJ-USDT",  "SOL-USDT",   "DOT-USDT",
]


# ═══════════════════════════════════════════════════════
# EXCHANGE — BingX Futures
# ═══════════════════════════════════════════════════════

def _sign(params: dict) -> str:
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()

def _get(path, params=None):
    p = params or {}
    p["timestamp"] = int(time.time() * 1000)
    sig = _sign(p)
    url = f"{BASE_URL}{path}?{'&'.join(f'{k}={v}' for k,v in p.items())}&signature={sig}"
    try:
        r = requests.get(url, headers={"X-BX-APIKEY": API_KEY}, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"GET {path}: {e}")
        return {}

def _post(path, params=None):
    p = params or {}
    p["timestamp"] = int(time.time() * 1000)
    sig = _sign(p)
    url = f"{BASE_URL}{path}?{'&'.join(f'{k}={v}' for k,v in p.items())}&signature={sig}"
    try:
        r = requests.post(url, headers={"X-BX-APIKEY": API_KEY}, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"POST {path}: {e}")
        return {}

def get_balance() -> float:
    if MODO_DEMO:
        return 100.0
    d = _get("/openApi/swap/v2/user/balance", {"currency": "USDT"})
    try:
        data = d.get("data", {})
        if isinstance(data, list): data = data[0]
        bal = data.get("balance", data.get("availableMargin", 0))
        return float(bal)
    except:
        return 0.0

def get_klines(par, intervalo="15m", limit=100):
    d = requests.get(
        f"{BASE_URL}/openApi/swap/v3/quote/klines",
        params={"symbol": par, "interval": intervalo, "limit": limit},
        timeout=10
    )
    data = d.json().get("data", [])
    return data if isinstance(data, list) else []

def parsear_klines(klines):
    hi, lo, cl, vo = [], [], [], []
    for k in klines:
        try:
            if isinstance(k, dict):
                h = float(k.get("high",  k.get("h", 0)))
                l = float(k.get("low",   k.get("l", 0)))
                c = float(k.get("close", k.get("c", 0)))
                v = float(k.get("volume",k.get("v", 0)))
            elif isinstance(k, (list, tuple)) and len(k) >= 6:
                h, l, c, v = float(k[2]), float(k[3]), float(k[4]), float(k[5])
            else:
                continue
            if h > 0 and l > 0 and c > 0:
                hi.append(h); lo.append(l); cl.append(c); vo.append(v)
        except:
            continue
    return {"highs": hi, "lows": lo, "closes": cl, "volumes": vo}

def get_precio(par) -> float:
    try:
        d = requests.get(
            f"{BASE_URL}/openApi/swap/v2/quote/ticker",
            params={"symbol": par}, timeout=8
        ).json().get("data", {})
        if isinstance(d, list): d = d[0]
        return float(d.get("lastPrice", d.get("last", 0)))
    except:
        return 0.0

def get_volumen_24h(par) -> float:
    try:
        d = requests.get(
            f"{BASE_URL}/openApi/swap/v2/quote/ticker",
            params={"symbol": par}, timeout=8
        ).json().get("data", {})
        if isinstance(d, list): d = d[0]
        return float(d.get("quoteVolume", 0))
    except:
        return 0.0

def abrir_orden(par, lado, qty):
    if MODO_DEMO:
        log.info(f"[DEMO] {lado} {par} qty={qty:.4f}")
        return {"orderId": "DEMO", "price": get_precio(par)}
    accion = "BUY" if lado == "LONG" else "SELL"
    p = {
        "symbol":     par,
        "side":       accion,
        "positionSide": lado,
        "type":       "MARKET",
        "quantity":   qty,
        "leverage":   LEVERAGE,
    }
    return _post("/openApi/swap/v2/trade/order", p)

def cerrar_orden(par, lado, qty):
    if MODO_DEMO:
        log.info(f"[DEMO] CERRAR {lado} {par} qty={qty:.4f}")
        return {"orderId": "DEMO"}
    accion = "SELL" if lado == "LONG" else "BUY"
    p = {
        "symbol":       par,
        "side":         accion,
        "positionSide": lado,
        "type":         "MARKET",
        "quantity":     qty,
    }
    return _post("/openApi/swap/v2/trade/order", p)

def set_leverage(par):
    if MODO_DEMO:
        return
    _post("/openApi/swap/v2/trade/leverage", {
        "symbol":   par,
        "side":     "LONG",
        "leverage": LEVERAGE,
    })
    _post("/openApi/swap/v2/trade/leverage", {
        "symbol":   par,
        "side":     "SHORT",
        "leverage": LEVERAGE,
    })


# ═══════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════

def calc_ema(closes, periodo=9):
    if len(closes) < periodo:
        return closes[-1] if closes else 0.0
    k   = 2.0 / (periodo + 1)
    ema = sum(closes[:periodo]) / periodo
    for c in closes[periodo:]:
        ema = c * k + ema * (1 - k)
    return ema

def calc_ema_serie(closes, periodo=9):
    """Devuelve lista con EMA para cada vela"""
    if len(closes) < periodo:
        return [closes[-1]] * len(closes)
    k    = 2.0 / (periodo + 1)
    emas = [sum(closes[:periodo]) / periodo]
    for c in closes[periodo:]:
        emas.append(c * k + emas[-1] * (1 - k))
    # Rellenar inicio con primer valor
    pad = [emas[0]] * (periodo - 1)
    return pad + emas

def calc_vwap_bandas(highs, lows, closes, volumes, periodo=20, std1=1.0, std2=2.0):
    """
    VWAP con bandas de desviación estándar
    Usa las últimas `periodo` velas
    """
    vacio = {"vwap": 0, "sup1": 0, "sup2": 0, "inf1": 0, "inf2": 0, "pos": 0.5}
    n = periodo
    if len(closes) < n:
        return vacio

    hi  = np.array(highs[-n:],   dtype=float)
    lo  = np.array(lows[-n:],    dtype=float)
    cl  = np.array(closes[-n:],  dtype=float)
    vo  = np.array(volumes[-n:], dtype=float)

    tp  = (hi + lo + cl) / 3.0   # typical price
    vol_total = np.sum(vo)
    if vol_total <= 0:
        return vacio

    vwap = float(np.sum(tp * vo) / vol_total)

    # Desviación estándar ponderada por volumen
    var  = float(np.sum(vo * (tp - vwap) ** 2) / vol_total)
    std  = float(np.sqrt(var)) if var > 0 else float(np.std(tp))

    sup1 = vwap + std1 * std
    sup2 = vwap + std2 * std
    inf1 = vwap - std1 * std
    inf2 = vwap - std2 * std

    precio = closes[-1]
    rango  = sup2 - inf2
    pos    = float((precio - inf2) / rango) if rango > 0 else 0.5

    return {
        "vwap": vwap, "sup1": sup1, "sup2": sup2,
        "inf1": inf1, "inf2": inf2, "pos": pos,
        "std":  std,
    }

def calc_atr(highs, lows, closes, periodo=14):
    if len(closes) < 2:
        return closes[-1] * 0.02 if closes else 0.01
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]))
        for i in range(1, len(closes))
    ]
    if not trs:
        return closes[-1] * 0.02
    atr = float(np.mean(trs[:periodo]))
    for i in range(periodo, len(trs)):
        atr = (atr * (periodo - 1) + trs[i]) / periodo
    return atr


# ═══════════════════════════════════════════════════════
# SEÑALES — VWAP + EMA9
# ═══════════════════════════════════════════════════════

def analizar_par(par):
    resultado = {
        "par": par, "señal": False, "lado": None,
        "precio": 0.0, "sl": 0.0, "tp": 0.0, "tp1": 0.0,
        "atr": 0.0, "rr": 0.0, "score": 0, "motivo": "",
        "vwap": 0.0, "ema9": 0.0,
    }

    klines = get_klines(par, "15m", 120)
    if len(klines) < 50:
        resultado["motivo"] = f"klines insuficientes ({len(klines)})"
        return resultado

    data   = parsear_klines(klines)
    closes = data["closes"]
    highs  = data["highs"]
    lows   = data["lows"]
    vols   = data["volumes"]

    if len(closes) < 30:
        resultado["motivo"] = "datos insuficientes"
        return resultado

    precio = closes[-1]
    if precio <= 0:
        resultado["motivo"] = "precio = 0"
        return resultado

    resultado["precio"] = precio

    # ── Indicadores ──────────────────────────────────
    vwap_d  = calc_vwap_bandas(highs, lows, closes, vols, VWAP_PERIODO, VWAP_STD1, VWAP_STD2)
    atr     = calc_atr(highs, lows, closes, ATR_PERIODO)
    ema9    = calc_ema(closes, EMA_PERIODO)

    # EMA serie para ver tendencia (últimas 3 velas)
    ema_s   = calc_ema_serie(closes, EMA_PERIODO)
    ema_sube = ema_s[-1] > ema_s[-3] if len(ema_s) >= 3 else True
    ema_baja = ema_s[-1] < ema_s[-3] if len(ema_s) >= 3 else True

    resultado["vwap"] = vwap_d["vwap"]
    resultado["ema9"] = ema9
    resultado["atr"]  = atr

    # ── Filtros calidad ───────────────────────────────
    volumen = get_volumen_24h(par)
    if volumen < VOLUMEN_MIN:
        resultado["motivo"] = f"vol bajo ${volumen:,.0f}"
        return resultado

    if atr <= 0:
        resultado["motivo"] = "ATR = 0"
        return resultado

    sl_dist  = atr * SL_ATR_MULT
    tp_dist  = atr * TP_ATR_MULT
    tp1_dist = atr * TP1_ATR_MULT
    rr       = tp_dist / sl_dist if sl_dist > 0 else 0

    if rr < 1.5:
        resultado["motivo"] = f"R:R={rr:.2f} insuficiente"
        return resultado

    # ── LONG ─────────────────────────────────────────
    # Precio toca o cruza banda inferior + EMA9 tendencia alcista
    toca_inf1 = precio <= vwap_d["inf1"] * 1.003
    toca_inf2 = precio <= vwap_d["inf2"] * 1.005
    precio_bajo_ema = precio < ema9          # precio por debajo de EMA (rebote potencial)
    ema_alcista     = ema_sube

    if toca_inf1 and ema_alcista:
        score = 50
        if toca_inf2:           score += 20   # en banda 2σ: señal más fuerte
        if precio_bajo_ema:     score += 10   # precio debajo de EMA9
        if vwap_d["pos"] < 0.2: score += 10  # muy cerca del fondo
        if rr >= 2.5:           score += 10  # buen R:R
        score = min(100, score)

        if score >= SCORE_MIN:
            resultado.update({
                "señal": True, "lado": "LONG",
                "sl":    precio - sl_dist,
                "tp":    precio + tp_dist,
                "tp1":   precio + tp1_dist,
                "rr":    round(rr, 2), "score": score,
                "motivo": (
                    f"LONG VWAP inf{'2' if toca_inf2 else '1'}="
                    f"{vwap_d['inf2' if toca_inf2 else 'inf1']:.4f} "
                    f"EMA9={ema9:.4f} R:R={rr:.2f} score={score}"
                )
            })
            return resultado
        else:
            resultado["motivo"] = f"LONG score {score} < {SCORE_MIN}"
            return resultado

    # ── SHORT ─────────────────────────────────────────
    # Precio toca o cruza banda superior + EMA9 tendencia bajista
    toca_sup1 = precio >= vwap_d["sup1"] * 0.997
    toca_sup2 = precio >= vwap_d["sup2"] * 0.995
    precio_sobre_ema = precio > ema9
    ema_bajista      = ema_baja

    if toca_sup1 and ema_bajista:
        score = 50
        if toca_sup2:           score += 20
        if precio_sobre_ema:    score += 10
        if vwap_d["pos"] > 0.8: score += 10
        if rr >= 2.5:           score += 10
        score = min(100, score)

        if score >= SCORE_MIN:
            resultado.update({
                "señal": True, "lado": "SHORT",
                "sl":    precio + sl_dist,
                "tp":    precio - tp_dist,
                "tp1":   precio - tp1_dist,
                "rr":    round(rr, 2), "score": score,
                "motivo": (
                    f"SHORT VWAP sup{'2' if toca_sup2 else '1'}="
                    f"{vwap_d['sup2' if toca_sup2 else 'sup1']:.4f} "
                    f"EMA9={ema9:.4f} R:R={rr:.2f} score={score}"
                )
            })
            return resultado
        else:
            resultado["motivo"] = f"SHORT score {score} < {SCORE_MIN}"
            return resultado

    # Sin señal
    resultado["motivo"] = (
        f"VWAP pos={vwap_d['pos']:.2f} "
        f"EMA9={'↑' if ema_sube else '↓'} "
        f"precio={precio:.4f} "
        f"inf1={vwap_d['inf1']:.4f} sup1={vwap_d['sup1']:.4f}"
    )
    return resultado


def escanear(pares):
    señales = []
    for par in pares:
        try:
            r = analizar_par(par)
            if r["señal"]:
                señales.append(r)
                log.info(f"  ✓ {r['lado']:5s} {par}: {r['motivo']}")
            else:
                log.debug(f"  ✗ {par}: {r['motivo']}")
        except Exception as e:
            log.error(f"  [ERR] {par}: {e}")
    señales.sort(key=lambda x: x["score"], reverse=True)
    return señales


# ═══════════════════════════════════════════════════════
# ESTADO
# ═══════════════════════════════════════════════════════

class Estado:
    def __init__(self):
        self.posiciones = {}
        self.pnl_hoy    = 0.0
        self.wins = self.losses = 0
        self.dia_actual = str(date.today())

    def reset_diario(self):
        hoy = str(date.today())
        if hoy != self.dia_actual:
            self.dia_actual = hoy
            self.pnl_hoy    = 0.0
            log.info(f"Reset diario — {hoy}")

    def registrar_cierre(self, pnl):
        self.pnl_hoy += pnl
        if pnl > 0: self.wins   += 1
        else:        self.losses += 1

estado = Estado()


# ═══════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════

def _tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log.error(f"TG: {e}")

def tg_senal(r, balance, ejecutado):
    lado = "🟢 LONG" if r["lado"] == "LONG" else "🔴 SHORT"
    ex   = "✅ Ejecutado" if ejecutado else "⚠️ No ejecutado"
    _tg(
        f"{lado} — `{r['par']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Entrada : `{r['precio']:.6f}`\n"
        f"🔶 TP1 50% : `{r['tp1']:.6f}` (2×ATR)\n"
        f"✅ TP2     : `{r['tp']:.6f}` (4×ATR)\n"
        f"🛑 SL      : `{r['sl']:.6f}`\n"
        f"📐 R:R     : `{r['rr']:.2f}x`\n"
        f"🏅 Score   : `{r['score']}/100`\n"
        f"📊 VWAP    : `{r['vwap']:.6f}`\n"
        f"📈 EMA9    : `{r['ema9']:.6f}`\n"
        f"💰 Balance : `${balance:.2f} USDT`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{ex}"
    )

def tg_cierre(par, lado, entrada, salida, pnl, razon):
    ico = "✅" if pnl >= 0 else "❌"
    _tg(
        f"{ico} *CIERRE {lado} ({razon})* — `{par}`\n"
        f"`{entrada:.6f}` → `{salida:.6f}`\n"
        f"PnL: `${pnl:+.4f} USDT`"
    )


# ═══════════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════════

def actualizar_trailing(par, pos, precio):
    lado     = pos["lado"]
    atr      = pos.get("atr", 0)
    entrada  = pos["entrada"]
    if atr <= 0:
        return

    if lado == "LONG":
        if precio - entrada < atr * TRAIL_ACTIVAR:
            return
        nuevo = precio - atr * TRAIL_DIST
        if nuevo > pos.get("sl_trail", pos["sl"]):
            pos["sl_trail"] = nuevo
            log.debug(f"[TRAIL] {par} LONG SL → {nuevo:.6f}")
    else:
        if entrada - precio < atr * TRAIL_ACTIVAR:
            return
        nuevo = precio + atr * TRAIL_DIST
        if nuevo < pos.get("sl_trail", pos["sl"]):
            pos["sl_trail"] = nuevo
            log.debug(f"[TRAIL] {par} SHORT SL → {nuevo:.6f}")


# ═══════════════════════════════════════════════════════
# GESTIÓN DE POSICIONES
# ═══════════════════════════════════════════════════════

def gestionar_posiciones(balance):
    for par in list(estado.posiciones.keys()):
        pos    = estado.posiciones[par]
        lado   = pos["lado"]
        precio = get_precio(par)
        if precio <= 0:
            continue

        atr     = pos.get("atr", 0)
        entrada = pos["entrada"]
        qty     = pos["qty"]
        sl_ef   = pos.get("sl_trail", pos["sl"])

        # Tiempo de vida
        try:
            ts = datetime.fromisoformat(pos["ts"])
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
            horas = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        except:
            horas = 0

        actualizar_trailing(par, pos, precio)

        # Verificar SL
        sl_hit = (precio <= sl_ef) if lado == "LONG" else (precio >= sl_ef)
        # Verificar TP1 (partial)
        tp1_hit = (
            not pos.get("tp1_done") and (
                (precio >= pos["tp1"]) if lado == "LONG"
                else (precio <= pos["tp1"])
            )
        )
        # Verificar TP2 (total)
        tp2_hit = (
            (precio >= pos["tp"]) if lado == "LONG"
            else (precio <= pos["tp"])
        )
        # Time exit
        time_hit = horas >= TIME_EXIT_H

        # ── Partial TP1 ──────────────────────────────
        if tp1_hit and not pos.get("tp1_done"):
            qty_tp1 = round(qty * 0.5, 8)
            cerrar_orden(par, lado, qty_tp1)
            pnl = qty_tp1 * ((precio - entrada) if lado == "LONG" else (entrada - precio))
            estado.registrar_cierre(pnl)
            # SL a breakeven
            be = entrada * 1.0005 if lado == "LONG" else entrada * 0.9995
            pos["sl"]       = be
            pos["sl_trail"] = be
            pos["qty"]      = round(qty - qty_tp1, 8)
            pos["tp1_done"] = True
            log.info(f"🔶 TP1 PARCIAL {par} +${pnl:.4f} | SL → breakeven {be:.6f}")
            tg_cierre(par, lado, entrada, precio, pnl, "TP1 50%")
            continue

        # ── Cierre total ─────────────────────────────
        razon = None
        if sl_hit:   razon = "SL"
        elif tp2_hit: razon = "TP2"
        elif time_hit: razon = f"TIME {horas:.1f}h"

        if razon:
            cerrar_orden(par, lado, pos["qty"])
            pnl = pos["qty"] * ((precio - entrada) if lado == "LONG" else (entrada - precio))
            estado.registrar_cierre(pnl)
            log.info(f"{'✅' if pnl>0 else '❌'} CIERRE {lado} {par} [{razon}] PnL=${pnl:+.4f}")
            tg_cierre(par, lado, entrada, precio, pnl, razon)
            del estado.posiciones[par]


# ═══════════════════════════════════════════════════════
# EJECUTAR SEÑAL
# ═══════════════════════════════════════════════════════

def ejecutar_senal(r, balance) -> bool:
    par   = r["par"]
    lado  = r["lado"]
    precio = r["precio"]

    qty = round((MARGEN_USDT * LEVERAGE) / precio, 4)
    if qty <= 0:
        log.warning(f"qty=0 para {par}")
        return False

    set_leverage(par)
    res = abrir_orden(par, lado, qty)

    if not MODO_DEMO:
        codigo = res.get("code", -1)
        if codigo != 0:
            log.error(f"Error abriendo {par}: {res}")
            return False

    entrada_real = float(res.get("price", precio) or precio)
    if entrada_real <= 0:
        entrada_real = precio

    atr = r["atr"]
    sl  = (entrada_real - atr * SL_ATR_MULT)  if lado == "LONG" else (entrada_real + atr * SL_ATR_MULT)
    tp  = (entrada_real + atr * TP_ATR_MULT)  if lado == "LONG" else (entrada_real - atr * TP_ATR_MULT)
    tp1 = (entrada_real + atr * TP1_ATR_MULT) if lado == "LONG" else (entrada_real - atr * TP1_ATR_MULT)

    estado.posiciones[par] = {
        "lado":     lado,
        "entrada":  entrada_real,
        "qty":      qty,
        "sl":       sl,
        "tp":       tp,
        "tp1":      tp1,
        "sl_trail": sl,
        "atr":      atr,
        "tp1_done": False,
        "ts":       datetime.now(timezone.utc).isoformat(),
    }

    log.info(
        f"✅ {lado} {par} entrada={entrada_real:.6f} "
        f"SL={sl:.6f} TP1={tp1:.6f} TP2={tp:.6f} "
        f"R:R={r['rr']:.2f} score={r['score']}"
    )
    return True


# ═══════════════════════════════════════════════════════
# REPORTE
# ═══════════════════════════════════════════════════════

def enviar_reporte(balance):
    pos_txt = ""
    for par, pos in estado.posiciones.items():
        p  = get_precio(par)
        pnl_est = pos["qty"] * (
            (p - pos["entrada"]) if pos["lado"] == "LONG"
            else (pos["entrada"] - p)
        )
        fase = "🔶→TP2" if pos.get("tp1_done") else "▶️→TP1"
        ico  = "🟢" if pos["lado"] == "LONG" else "🔴"
        pos_txt += f"  {ico} `{par}` e:`{pos['entrada']:.4f}` est:${pnl_est:+.2f} {fase}\n"

    if not pos_txt:
        pos_txt = "  _(sin posiciones)_\n"

    w, l = estado.wins, estado.losses
    wr   = f"{w/(w+l)*100:.1f}%" if (w+l) > 0 else "N/A"

    _tg(
        f"📊 *Reporte — {VERSION}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance  : `${balance:.2f} USDT`\n"
        f"📈 Sesión   : `{w}W/{l}L` WR:`{wr}`\n"
        f"📉 PnL hoy  : `${estado.pnl_hoy:+.2f}` USDT\n"
        f"⚙️ TP: `4×ATR` | SL: `1.5×ATR` | Lev: `{LEVERAGE}x`\n"
        f"📋 Posiciones:\n{pos_txt}"
    )


# ═══════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info(f"{VERSION}")
    log.info(f"VWAP período:{VWAP_PERIODO} | EMA:{EMA_PERIODO} | LEV:{LEVERAGE}x")
    log.info(f"SL:{SL_ATR_MULT}×ATR | TP1:{TP1_ATR_MULT}×ATR | TP2:{TP_ATR_MULT}×ATR")
    log.info(f"MAX_POS:{MAX_POS} | MARGEN:${MARGEN_USDT} | SCORE≥{SCORE_MIN}")
    log.info(f"MODO: {'DEMO 🔵' if MODO_DEMO else 'LIVE 🔴'}")
    log.info("=" * 60)

    balance = get_balance()
    log.info(f"Balance: ${balance:.2f} USDT")

    _tg(
        f"🤖 *{VERSION}* arrancado\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance : `${balance:.2f} USDT`\n"
        f"📊 Pares   : `{len(PARES)}`\n"
        f"📈 VWAP    : `{VWAP_PERIODO}` velas | σ1=`{VWAP_STD1}` σ2=`{VWAP_STD2}`\n"
        f"📉 EMA9    : tendencia y confirmación\n"
        f"🎯 TP      : `4×ATR` extendido\n"
        f"🔶 Partial : `50% en 2×ATR` + SL→BE\n"
        f"🎯 Trailing: activo desde `2×ATR`\n"
        f"⏱ Time exit: `{TIME_EXIT_H}h`\n"
        f"{'🔵 DEMO' if MODO_DEMO else '🟢 LIVE — DINERO REAL'}"
    )

    ciclo        = 0
    last_reporte = time.time()

    while True:
        try:
            ciclo += 1
            estado.reset_diario()
            balance = get_balance()

            log.info(
                f"Ciclo {ciclo} | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | "
                f"Bal:${balance:.2f} | Pos:{len(estado.posiciones)} | "
                f"PnL:${estado.pnl_hoy:+.2f}"
            )

            # 1. Gestionar posiciones abiertas
            if estado.posiciones:
                gestionar_posiciones(balance)
                balance = get_balance()

            # 2. Buscar señales nuevas
            if len(estado.posiciones) < MAX_POS:
                log.info(f"Escaneando {len(PARES)} pares...")
                señales = escanear(PARES)

                if señales:
                    log.info(f"✓ {len(señales)} señal(es) detectadas")
                    for s in señales:
                        log.info(
                            f"  {s['lado']:5s} {s['par']:18s} "
                            f"score={s['score']} R:R={s['rr']:.2f}"
                        )
                else:
                    log.info("Sin señales este ciclo")

                for s in señales:
                    if len(estado.posiciones) >= MAX_POS:
                        break
                    if s["par"] in estado.posiciones:
                        continue
                    ejecutado = ejecutar_senal(s, balance)
                    tg_senal(s, balance, ejecutado)
                    if ejecutado:
                        balance = get_balance()
                        time.sleep(2)

            # 3. Reporte horario
            if time.time() - last_reporte >= 3600:
                enviar_reporte(balance)
                last_reporte = time.time()

        except KeyboardInterrupt:
            log.info("Detenido manualmente")
            _tg("🛑 *Bot VWAP+EMA9 detenido manualmente.*")
            break
        except Exception as e:
            log.error(f"ERROR CICLO {ciclo}: {e}")
            log.error(traceback.format_exc())
            try:
                _tg(f"🚨 *Error ciclo {ciclo}*\n`{str(e)[:200]}`")
            except:
                pass

        log.info(f"Próximo ciclo en {LOOP_SECONDS}s")
        log.info("-" * 55)
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()
