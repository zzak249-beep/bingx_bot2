"""
analizar_bellsz.py — Motor de señales Liquidez Lateral [Bellsz] v1.0
======================================================================

ESTRATEGIA NÚCLEO (3 capas):
  Capa 1 — LIQUIDEZ: Detecta BSL/SSL en H1, H4 y Diario
           Genera señal cuando el precio barre un nivel y cierra al otro lado (purga)
  Capa 2 — EMA: EMA9 / EMA21 confirman la dirección de la tendencia
  Capa 3 — RSI: momentum confirmado, no en zona extrema

SCORE (máx 10):
  Purga H1=1, Purga H4=2, Purga D=3  (capa 1)
  Cruce EMA=2, Tendencia EMA=1        (capa 2)
  RSI ok=1, RSI momentum=1           (capa 3)
  KZ=1, OB+FVG=1, CHoCH/BOS=1       (confluencia extra)

MEJORAS vs indicador original:
  + Order Blocks (OB) en zona de purga
  + Fair Value Gaps (FVG) como entrada refinada
  + CHoCH / BOS como 3ª confirmación estructural
  + Score de confluencia 1-10
  + Filtro de sesiones (Asia, Londres, NY)
  + Filtro de volatilidad ATR
  + ADX para evitar mercados laterales muertos
  + VWAP como zona de valor
  + Premium/Discount zones
"""

import logging
import time
from datetime import datetime, timezone
import concurrent.futures

import config
import exchange

log = logging.getLogger("analizar_bellsz")

_cooldown_ts:  dict = {}
_kz_stats:     dict = {}
_macro_btc:    dict = {"htf": "NEUTRAL", "ts": 0.0}


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def registrar_senal_ts(par: str):
    _cooldown_ts[par] = time.time()


def registrar_trade_kz(kz: str, ganado: bool):
    s = _kz_stats.setdefault(kz, {"trades": 0, "wins": 0})
    s["trades"] += 1
    s["wins"]   += int(ganado)


def _cooldown_ok(par: str) -> bool:
    ultimo = _cooldown_ts.get(par, 0)
    return (time.time() - ultimo) >= config.COOLDOWN_VELAS * 300


def actualizar_macro_btc():
    if time.time() - _macro_btc["ts"] < 900:
        return
    try:
        ch = exchange.get_candles("BTC-USDT", "4h", 50)
        if len(ch) < 50:
            return
        cl = [c["close"] for c in ch]
        ef = calc_ema(cl, 21)
        es = calc_ema(cl, 50)
        if ef and es:
            if   ef > es * 1.005: _macro_btc["htf"] = "BULL"
            elif ef < es * 0.995: _macro_btc["htf"] = "BEAR"
            else:                 _macro_btc["htf"] = "NEUTRAL"
        _macro_btc["ts"] = time.time()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# INDICADORES
# ══════════════════════════════════════════════════════════════

def calc_ema(prices: list, period: int):
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(prices: list, period: int = 14):
    if len(prices) < period + 1:
        return None
    d  = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(x, 0)      for x in d[:period]) / period
    al = sum(abs(min(x, 0)) for x in d[:period]) / period
    for x in d[period:]:
        ag = (ag * (period - 1) + max(x, 0))      / period
        al = (al * (period - 1) + abs(min(x, 0))) / period
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)


def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0.0
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1]))
           for i in range(1, len(highs))]
    return sum(trs[-period:]) / period if len(trs) >= period else (sum(trs) / len(trs) if trs else 0.0)


def calc_adx(highs, lows, closes, period=14) -> float:
    """ADX para confirmar tendencia. ADX < 20 = mercado lateral."""
    if len(highs) < period * 2:
        return 25.0
    try:
        trs = []
        plus_dm  = []
        minus_dm = []
        for i in range(1, len(highs)):
            tr   = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            up   = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            trs.append(tr)
            plus_dm.append(max(up,   0) if up   > down else 0)
            minus_dm.append(max(down, 0) if down > up   else 0)

        def smooth(data):
            s = sum(data[:period])
            for i in range(period, len(data)):
                s = s - s/period + data[i]
            return s

        atr14  = smooth(trs[-period*2:])
        pdi14  = smooth(plus_dm[-period*2:])
        mdi14  = smooth(minus_dm[-period*2:])
        if atr14 <= 0:
            return 25.0
        pdi = 100 * pdi14 / atr14
        mdi = 100 * mdi14 / atr14
        deno = pdi + mdi
        return abs(pdi - mdi) / deno * 100 if deno > 0 else 25.0
    except Exception:
        return 25.0


def calc_vwap(candles: list) -> float:
    hoy = datetime.now(timezone.utc).date()
    vc  = [c for c in candles
           if datetime.fromtimestamp(c["ts"] / 1000, tz=timezone.utc).date() == hoy]
    if not vc:
        vc = candles[-50:]
    tp_vol    = sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in vc)
    vol_total = sum(c["volume"] for c in vc)
    return tp_vol / vol_total if vol_total > 0 else candles[-1]["close"]


def calc_macd(closes: list, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    macd_hist = []
    for i in range(slow, len(closes)):
        ef = calc_ema(closes[:i+1], fast)
        es = calc_ema(closes[:i+1], slow)
        if ef and es:
            macd_hist.append(ef - es)
    if len(macd_hist) < signal:
        return None, None, None
    macd_line   = macd_hist[-1]
    signal_line = calc_ema(macd_hist, signal)
    histogram   = macd_line - (signal_line or 0)
    return macd_line, signal_line, histogram


# ══════════════════════════════════════════════════════════════
# CAPA 1 — NIVELES DE LIQUIDEZ HTF (núcleo Bellsz)
# ══════════════════════════════════════════════════════════════

def get_niveles_liquidez(par: str) -> dict:
    """
    Obtiene BSL (máximo) y SSL (mínimo) de los últimos N periodos
    en H1, H4 y Diario. Estos son los niveles de liquidez institucional.
    """
    resultado = {
        "bsl_h1": 0.0, "ssl_h1": 0.0,
        "bsl_h4": 0.0, "ssl_h4": 0.0,
        "bsl_d":  0.0, "ssl_d":  0.0,
        "ok": False
    }
    try:
        lb = config.LIQ_LOOKBACK

        if config.LIQ_MOSTRAR_H1:
            c_h1 = exchange.get_candles(par, config.HTF_H1_TF, lb + 5)
            if len(c_h1) >= lb:
                resultado["bsl_h1"] = max(c["high"] for c in c_h1[-lb:])
                resultado["ssl_h1"] = min(c["low"]  for c in c_h1[-lb:])

        if config.LIQ_MOSTRAR_H4:
            c_h4 = exchange.get_candles(par, config.HTF_H4_TF, lb + 5)
            if len(c_h4) >= lb:
                resultado["bsl_h4"] = max(c["high"] for c in c_h4[-lb:])
                resultado["ssl_h4"] = min(c["low"]  for c in c_h4[-lb:])

        if config.LIQ_MOSTRAR_D:
            c_d = exchange.get_candles(par, config.HTF_D_TF, min(lb, 30) + 5)
            if len(c_d) >= 5:
                resultado["bsl_d"] = max(c["high"] for c in c_d[-min(lb, 30):])
                resultado["ssl_d"] = min(c["low"]  for c in c_d[-min(lb, 30):])

        resultado["ok"] = True
    except Exception as e:
        log.debug(f"[LIQ] {par} error: {e}")
    return resultado


def detectar_purga(candles: list, niveles: dict, precio: float) -> dict:
    """
    Detecta si el precio barrió un nivel de liquidez y cerró al otro lado.

    PURGA ALCISTA (señal LONG):
      - El precio tocó el SSL (mínimos de liquidez vendedora)
      - Pero cerró POR ENCIMA del SSL → trampa bajista, revertirá al alza

    PURGA BAJISTA (señal SHORT):
      - El precio tocó el BSL (máximos de liquidez compradora)
      - Pero cerró POR DEBAJO del BSL → trampa alcista, revertirá a la baja
    """
    if len(candles) < 3:
        return {"purga_alcista": False, "purga_bajista": False,
                "purga_nivel": "", "purga_peso": 0}

    c = candles[-1]
    # LIQ_MARGEN = 0.001 significa 0.1% → multiplicar directo, sin /100
    margen = precio * config.LIQ_MARGEN

    purga_alcista = False
    purga_bajista = False
    purga_nivel   = ""
    purga_peso    = 0

    # ── PURGAS ALCISTAS (compra) ──────────────────────────────
    purga_nivel_l = ""
    purga_nivel_s = ""

    # H1 ssl
    ssl_h1 = niveles.get("ssl_h1", 0)
    if ssl_h1 > 0 and c["low"] <= ssl_h1 + margen and c["close"] > ssl_h1:
        purga_alcista = True
        purga_nivel_l += "SSL_H1 "
        purga_peso   += 1

    # H4 ssl — más peso
    ssl_h4 = niveles.get("ssl_h4", 0)
    if ssl_h4 > 0 and c["low"] <= ssl_h4 + margen and c["close"] > ssl_h4:
        purga_alcista = True
        purga_nivel_l += "SSL_H4 "
        purga_peso   += 2

    # Diario ssl — máximo peso
    ssl_d = niveles.get("ssl_d", 0)
    if ssl_d > 0 and c["low"] <= ssl_d + margen and c["close"] > ssl_d:
        purga_alcista = True
        purga_nivel_l += "SSL_D "
        purga_peso   += 3

    # ── PURGAS BAJISTAS (venta) ───────────────────────────────
    bsl_h1 = niveles.get("bsl_h1", 0)
    if bsl_h1 > 0 and c["high"] >= bsl_h1 - margen and c["close"] < bsl_h1:
        purga_bajista = True
        purga_nivel_s += "BSL_H1 "
        purga_peso   += 1

    bsl_h4 = niveles.get("bsl_h4", 0)
    if bsl_h4 > 0 and c["high"] >= bsl_h4 - margen and c["close"] < bsl_h4:
        purga_bajista = True
        purga_nivel_s += "BSL_H4 "
        purga_peso   += 2

    bsl_d = niveles.get("bsl_d", 0)
    if bsl_d > 0 and c["high"] >= bsl_d - margen and c["close"] < bsl_d:
        purga_bajista = True
        purga_nivel_s += "BSL_D "
        purga_peso   += 3

    # Nivel combinado para log/notif — el más relevante gana
    if purga_alcista and purga_bajista:
        # Doble purga — usar la de más peso para el log
        purga_nivel = purga_nivel_l.strip() if purga_peso >= 2 else purga_nivel_s.strip()
    elif purga_alcista:
        purga_nivel = purga_nivel_l.strip()
    else:
        purga_nivel = purga_nivel_s.strip()

    return {
        "purga_alcista":  purga_alcista,
        "purga_bajista":  purga_bajista,
        "purga_nivel":    purga_nivel,
        "purga_nivel_l":  purga_nivel_l.strip(),
        "purga_nivel_s":  purga_nivel_s.strip(),
        "purga_peso":     purga_peso,
    }


# ══════════════════════════════════════════════════════════════
# CAPA 2 — EMA CONFIRMACIÓN DE TENDENCIA
# ══════════════════════════════════════════════════════════════

def confirmar_ema(closes: list) -> dict:
    """
    EMA 9 / EMA 21 como filtro de tendencia.
    LONG: EMA rápida > EMA lenta (o cruce alcista reciente)
    SHORT: EMA rápida < EMA lenta (o cruce bajista reciente)
    """
    ema_r = calc_ema(closes, config.EMA_FAST)
    ema_l = calc_ema(closes, config.EMA_SLOW)

    if ema_r is None or ema_l is None:
        return {"bull": False, "bear": False, "cruce_bull": False,
                "cruce_bear": False, "ema_r": 0, "ema_l": 0}

    # Cruce reciente (últimas 3 velas)
    prev_closes = closes[:-1]
    ema_r_prev  = calc_ema(prev_closes, config.EMA_FAST) if len(prev_closes) >= config.EMA_FAST else None
    ema_l_prev  = calc_ema(prev_closes, config.EMA_SLOW) if len(prev_closes) >= config.EMA_SLOW else None

    cruce_bull = (ema_r_prev is not None and ema_l_prev is not None
                  and ema_r_prev <= ema_l_prev and ema_r > ema_l)
    cruce_bear = (ema_r_prev is not None and ema_l_prev is not None
                  and ema_r_prev >= ema_l_prev and ema_r < ema_l)

    return {
        "bull":       ema_r > ema_l * 1.001,
        "bear":       ema_r < ema_l * 0.999,
        "cruce_bull": cruce_bull,
        "cruce_bear": cruce_bear,
        "ema_r":      ema_r,
        "ema_l":      ema_l,
    }


# ══════════════════════════════════════════════════════════════
# CAPA 3 — RSI CONFIRMACIÓN DE MOMENTUM
# ══════════════════════════════════════════════════════════════

def confirmar_rsi(closes: list) -> dict:
    """
    RSI confirma que hay momentum y el precio no está en zona extrema.
    """
    rsi_val  = calc_rsi(closes, config.RSI_PERIOD)
    rsi_ema3 = calc_ema([calc_rsi(closes[:i+1]) or 50
                         for i in range(len(closes)-5, len(closes))], 3)

    if rsi_val is None:
        return {"ok_long": False, "ok_short": False, "momentum_bull": False,
                "momentum_bear": False, "valor": 50.0}

    ok_long  = rsi_val < config.RSI_BUY_MAX  and rsi_val > config.RSI_SELL_MIN
    ok_short = rsi_val > config.RSI_SELL_MIN and rsi_val < config.RSI_BUY_MAX

    momentum_bull = rsi_ema3 is not None and rsi_val > rsi_ema3
    momentum_bear = rsi_ema3 is not None and rsi_val < rsi_ema3

    # ok_long/ok_short son INDEPENDIENTES del momentum
    # El momentum suma puntos extra en el score, pero no bloquea la señal base
    return {
        "ok_long":       ok_long,
        "ok_short":      ok_short,
        "momentum_bull": momentum_bull,
        "momentum_bear": momentum_bear,
        "valor":         rsi_val,
    }


# ══════════════════════════════════════════════════════════════
# CONFLUENCIAS EXTRA (Order Blocks, FVG, BOS, CHoCH, Sweep)
# ══════════════════════════════════════════════════════════════

def detectar_order_blocks(candles: list) -> dict:
    lb = min(config.OB_LOOKBACK, len(candles) - 3)
    bull_ob = bear_ob = False
    bull_top = bull_bot = bear_top = bear_bot = 0.0

    for i in range(len(candles)-3, max(len(candles)-lb-3, 1), -1):
        c = candles
        if not bull_ob and c[i]["close"] < c[i]["open"]:
            if (i+2 < len(c) and c[i+1]["close"] > c[i+1]["open"]
                    and c[i+2]["close"] > c[i+2]["open"]
                    and c[i+2]["high"] > c[i]["high"]):
                bull_ob  = True
                bull_top = max(c[i]["open"], c[i]["close"])
                bull_bot = c[i]["low"]
        if not bear_ob and c[i]["close"] > c[i]["open"]:
            if (i+2 < len(c) and c[i+1]["close"] < c[i+1]["open"]
                    and c[i+2]["close"] < c[i+2]["open"]
                    and c[i+2]["low"] < c[i]["low"]):
                bear_ob  = True
                bear_top = c[i]["high"]
                bear_bot = min(c[i]["open"], c[i]["close"])
        if bull_ob and bear_ob:
            break

    precio = candles[-1]["close"]
    iob_b = bull_ob and bull_bot <= precio <= bull_top * 1.005
    iob_r = bear_ob and bear_bot * 0.995 <= precio <= bear_top

    return {
        "bull_ob": bull_ob, "bull_ob_top": bull_top, "bull_ob_bottom": bull_bot,
        "bear_ob": bear_ob, "bear_ob_top": bear_top, "bear_ob_bottom": bear_bot,
        "iob_bull": iob_b,  "iob_bear": iob_r,
    }


def detectar_fvg(candles: list) -> dict:
    r = {"bull_fvg": False, "bear_fvg": False, "fvg_top": 0.0,
         "fvg_bottom": 0.0, "fvg_rellenado": True, "en_zona": False}
    if len(candles) < 5:
        return r
    precio = candles[-1]["close"]
    for i in range(len(candles)-1, max(len(candles)-20, 2), -1):
        c = candles
        if c[i]["low"] > c[i-2]["high"]:
            r.update({"bull_fvg": True, "fvg_top": c[i]["low"],
                      "fvg_bottom": c[i-2]["high"],
                      "fvg_rellenado": precio < c[i-2]["high"],
                      "en_zona": c[i-2]["high"] <= precio <= c[i]["low"]})
            return r
        if c[i]["high"] < c[i-2]["low"]:
            r.update({"bear_fvg": True, "fvg_top": c[i-2]["low"],
                      "fvg_bottom": c[i]["high"],
                      "fvg_rellenado": precio > c[i-2]["low"],
                      "en_zona": c[i]["high"] <= precio <= c[i-2]["low"]})
            return r
    return r


def detectar_bos_choch(candles: list) -> dict:
    r = {"bos_bull": False, "bos_bear": False, "choch_bull": False, "choch_bear": False}
    if len(candles) < 20:
        return r
    rec = candles[-20:]
    ph = max(c["high"] for c in rec[:-1])
    pl = min(c["low"]  for c in rec[:-1])
    ultimo = candles[-1]
    if ultimo["close"] > ph:
        r["bos_bull"]   = True
    if ultimo["close"] < pl:
        r["bos_bear"]   = True
    if len(candles) >= 40:
        prev = candles[-40:-20]
        ph_p = max(c["high"] for c in prev)
        pl_p = min(c["low"]  for c in prev)
        if ultimo["close"] > ph_p and not r["bos_bull"]:
            r["choch_bull"] = True
        if ultimo["close"] < pl_p and not r["bos_bear"]:
            r["choch_bear"] = True
    return r


def detectar_sweep(candles: list) -> dict:
    lb = min(config.SWEEP_LOOKBACK, len(candles) - 2)
    if lb < 5:
        return {"sweep_bull": False, "sweep_bear": False}
    rec    = candles[-(lb+1):-1]
    ultimo = candles[-1]
    max_rec = max(c["high"] for c in rec)
    min_rec = min(c["low"]  for c in rec)
    return {
        "sweep_bull": ultimo["low"] < min_rec and ultimo["close"] > min_rec,
        "sweep_bear": ultimo["high"] > max_rec and ultimo["close"] < max_rec,
    }


def detectar_patron_vela(candles: list) -> dict:
    if len(candles) < 3:
        return {"patron": None, "lado": None, "confianza": 0}
    c = candles[-1]
    cuerpo  = abs(c["close"] - c["open"])
    rango   = c["high"] - c["low"]
    if rango <= 0:
        return {"patron": None, "lado": None, "confianza": 0}
    ratio_cuerpo = cuerpo / rango
    mecha_baja   = (min(c["close"], c["open"]) - c["low"])  / rango
    mecha_alta   = (c["high"] - max(c["close"], c["open"])) / rango

    if mecha_baja > config.PINBAR_RATIO and ratio_cuerpo < 0.35:
        return {"patron": "PIN_BAR_BULL", "lado": "LONG", "confianza": 2}
    if mecha_alta > config.PINBAR_RATIO and ratio_cuerpo < 0.35:
        return {"patron": "PIN_BAR_BEAR", "lado": "SHORT", "confianza": 2}

    p = candles[-2]
    if (p["close"] < p["open"] and c["close"] > c["open"]
            and c["open"] < p["close"] and c["close"] > p["open"]):
        return {"patron": "ENGULFING_BULL", "lado": "LONG", "confianza": 2}
    if (p["close"] > p["open"] and c["close"] < c["open"]
            and c["open"] > p["close"] and c["close"] < p["open"]):
        return {"patron": "ENGULFING_BEAR", "lado": "SHORT", "confianza": 2}

    return {"patron": None, "lado": None, "confianza": 0}


def premium_discount_zone(candles: list) -> dict:
    r = {"premium": False, "discount": False, "zona_pct": 50.0}
    if len(candles) < 10:
        return r
    lb    = min(config.PREMIUM_DISCOUNT_LB, len(candles))
    rec   = candles[-lb:]
    max_h = max(c["high"] for c in rec)
    min_l = min(c["low"]  for c in rec)
    rng   = max_h - min_l
    if rng <= 0:
        return r
    precio = candles[-1]["close"]
    zona   = (precio - min_l) / rng * 100
    return {"premium": zona >= 60, "discount": zona <= 40, "zona_pct": round(zona, 1)}


def en_killzone() -> dict:
    ahora = datetime.now(timezone.utc)
    tim   = ahora.hour * 60 + ahora.minute
    asia   = config.KZ_ASIA_START   <= tim < config.KZ_ASIA_END
    london = config.KZ_LONDON_START <= tim < config.KZ_LONDON_END
    ny     = config.KZ_NY_START     <= tim < config.KZ_NY_END
    return {
        "in_asia": asia, "in_london": london, "in_ny": ny,
        "in_kz":   asia or london or ny,
        "nombre":  "ASIA" if asia else ("LONDON" if london else ("NY" if ny else "FUERA")),
    }


def tendencia_htf(par: str, tf: str = None, n: int = None) -> str:
    tf = tf or config.MTF_TIMEFRAME
    n  = n  or config.MTF_CANDLES
    if not config.MTF_ACTIVO:
        return "NEUTRAL"
    try:
        ch = exchange.get_candles(par, tf, n)
        if len(ch) < 50:
            return "NEUTRAL"
        cl = [c["close"] for c in ch]
        ef = calc_ema(cl, config.EMA_FAST)
        es = calc_ema(cl, config.EMA_SLOW)
        if ef is None or es is None:
            return "NEUTRAL"
        if ef > es * 1.001: return "BULL"
        if ef < es * 0.999: return "BEAR"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def tendencia_4h(par: str) -> str:
    if not config.MTF_4H_ACTIVO:
        return "NEUTRAL"
    return tendencia_htf(par, "4h", 50)


def es_trending(candles: list, n: int = 20) -> bool:
    """Choppiness index — True si hay tendencia (no lateral muerto)."""
    if len(candles) < n + 1:
        return True
    w = candles[-(n+1):]
    s = sum(max(w[i]["high"] - w[i]["low"],
                abs(w[i]["high"] - w[i-1]["close"]),
                abs(w[i]["low"]  - w[i-1]["close"]))
            for i in range(1, len(w)))
    rng = max(c["high"] for c in w) - min(c["low"] for c in w)
    return (s / rng / n * 100) < 61.8 if rng > 0 else False


def volumen_ok(candles: list) -> bool:
    if len(candles) < 21:
        return True
    vols = [c["volume"] for c in candles[-21:-1]]
    avg  = sum(vols) / len(vols) if vols else 0
    return avg <= 0 or candles[-1]["volume"] / avg >= 0.40


def get_rango_asia(candles: list) -> dict:
    r = {"high": 0.0, "low": 0.0, "valido": False}
    if not config.ASIA_RANGE_ACTIVO or len(candles) < 20:
        return r
    ahora  = datetime.now(timezone.utc)
    asia_s = config.KZ_ASIA_START
    asia_e = config.KZ_ASIA_END
    velas_asia = [c for c in candles[-50:]
                  if asia_s <= (datetime.fromtimestamp(c["ts"]/1000, tz=timezone.utc).hour * 60
                                + datetime.fromtimestamp(c["ts"]/1000, tz=timezone.utc).minute) < asia_e]
    if len(velas_asia) >= 3:
        r = {"high": max(c["high"] for c in velas_asia),
             "low":  min(c["low"]  for c in velas_asia),
             "valido": True}
    return r


# ══════════════════════════════════════════════════════════════
# SL ESTRUCTURAL Y TP PROPORCIONAL
# ══════════════════════════════════════════════════════════════

def _swing_low(candles: list, n: int = 10) -> float:
    if len(candles) < n + 2:
        return 0.0
    return min(c["low"] for c in candles[-(n+1):-1])


def _swing_high(candles: list, n: int = 10) -> float:
    if len(candles) < n + 2:
        return 0.0
    return max(c["high"] for c in candles[-(n+1):-1])


def _calcular_sl_estructural(candles: list, ob: dict, lado: str, atr: float, precio: float) -> float:
    if lado == "LONG":
        swing   = _swing_low(candles, 15)
        sl_ob   = ob["bull_ob_bottom"] * 0.997 if ob["bull_ob"] else 0
        sl_sw   = swing * 0.997 if swing > 0 else 0
        sl_atr  = precio - atr * config.SL_ATR_MULT
        cands   = [x for x in [sl_ob, sl_sw] if 0 < x < precio]
        sl_estr = max(cands) if cands else sl_atr
        sl_min  = precio - atr * 0.5
        return min(sl_estr, sl_min)
    else:
        swing   = _swing_high(candles, 15)
        sl_ob   = ob["bear_ob_top"] * 1.003 if ob["bear_ob"] else 0
        sl_sw   = swing * 1.003 if swing > 0 else 0
        sl_atr  = precio + atr * config.SL_ATR_MULT
        cands   = [x for x in [sl_ob, sl_sw] if x > precio]
        sl_estr = min(cands) if cands else sl_atr
        sl_max  = precio + atr * 0.5
        return max(sl_estr, sl_max)


def _calcular_tp(precio: float, sl: float, lado: str) -> tuple:
    """
    TP proporcional al riesgo real (basado en bt_v4 — PROBADO).
    TP = dist_SL x TP_DIST_MULT (3.0 → R:R 1:3)
    TP1 = dist_SL x TP1_DIST_MULT (1.5 → salida parcial)
    """
    dist     = abs(precio - sl)
    tp_mult  = config.TP_DIST_MULT   # 3.0
    tp1_mult = config.TP1_DIST_MULT  # 1.5

    if lado == "LONG":
        return precio + dist * tp_mult, precio + dist * tp1_mult
    else:
        return precio - dist * tp_mult, precio - dist * tp1_mult


# ══════════════════════════════════════════════════════════════
# SEÑAL PRINCIPAL — LIQUIDEZ LATERAL [Bellsz]
# ══════════════════════════════════════════════════════════════

def analizar_par(par: str):
    """
    Señal Bellsz: 3 capas + confluencias adicionales.
    Retorna dict con todos los campos que espera main.py, o None.
    """
    try:
        candles = exchange.get_candles(par, config.TIMEFRAME, config.CANDLES_LIMIT)
        if len(candles) < 80:
            return None

        if not _cooldown_ok(par):
            return None

        if not es_trending(candles, 20):
            return None

        if not volumen_ok(candles):
            return None

        cl     = [c["close"] for c in candles]
        hi     = [c["high"]  for c in candles]
        lo     = [c["low"]   for c in candles]
        precio = cl[-1]
        if precio <= 0:
            return None

        atr = calc_atr(hi, lo, cl, config.ATR_PERIOD)
        if atr <= 0 or atr / precio * 100 < 0.03:
            return None

        # ══════════════════════════════════════════════════════
        # CAPA 1 — LIQUIDEZ (purga de BSL/SSL)
        # ══════════════════════════════════════════════════════
        # Inyectar margen adaptativo en config temporal para esta llamada
        _atr_pct = atr / precio  # p.ej 0.003 = 0.3%
        _margen_orig = config.LIQ_MARGEN
        # Usar el mayor entre el margen config y 0.5× ATR%
        # Así en coins muy volátiles (ATR 1%) el margen se adapta
        config.LIQ_MARGEN = max(config.LIQ_MARGEN, _atr_pct * 0.5)
        niveles = get_niveles_liquidez(par)
        purga   = detectar_purga(candles, niveles, precio)
        config.LIQ_MARGEN = _margen_orig  # restaurar

        # ── ADX: evitar mercados completamente planos ──────────
        adx = calc_adx(hi, lo, cl)
        if adx < 12:
            log.debug(f"[SKIP] {par} ADX={adx:.1f} — demasiado lateral")
            return None

        # Sin purga = sin señal (núcleo de Bellsz)
        if not purga["purga_alcista"] and not purga["purga_bajista"]:
            return None

        # ══════════════════════════════════════════════════════
        # CAPA 2 — EMA
        # ══════════════════════════════════════════════════════
        ema_conf = confirmar_ema(cl)

        # ══════════════════════════════════════════════════════
        # CAPA 3 — RSI
        # ══════════════════════════════════════════════════════
        rsi_conf = confirmar_rsi(cl)

        # ══════════════════════════════════════════════════════
        # CONFLUENCIAS EXTRA
        # ══════════════════════════════════════════════════════
        ob      = detectar_order_blocks(candles)
        fvg     = detectar_fvg(candles)
        bos     = detectar_bos_choch(candles)
        sweep   = detectar_sweep(candles)
        pat     = detectar_patron_vela(candles)
        pd_zone = premium_discount_zone(candles)
        kz      = en_killzone()
        asia    = get_rango_asia(candles)
        htf     = tendencia_htf(par)
        htf_4h  = tendencia_4h(par)
        vwap    = calc_vwap(candles)
        _, _, macd_hist = calc_macd(cl)

        sobre_vwap = precio > vwap * (1 + config.VWAP_PCT / 100)
        bajo_vwap  = precio < vwap * (1 - config.VWAP_PCT / 100)

        ob_fvg_b = (ob["iob_bull"] and fvg["bull_fvg"] and
                    ob["bull_ob_bottom"] <= fvg.get("fvg_bottom", 0) <= ob["bull_ob_top"])
        ob_fvg_r = (ob["iob_bear"] and fvg["bear_fvg"] and
                    ob["bear_ob_bottom"] <= fvg.get("fvg_top", 0) <= ob["bear_ob_top"])

        desplazamiento = False
        if config.DISPLACEMENT_ACTIVO and len(candles) >= 3:
            avg_body   = sum(abs(c["close"] - c["open"]) for c in candles[-3:-1]) / 2
            curr_body  = abs(candles[-1]["close"] - candles[-1]["open"])
            desplazamiento = curr_body > avg_body * 1.5

        # ══════════════════════════════════════════════════════
        # SCORING BELLSZ (máx ~15)
        # ══════════════════════════════════════════════════════
        sl_pts = ss_pts = 0
        ml: list = []
        ms: list = []

        def add(cond, pts, lbl, side):
            nonlocal sl_pts, ss_pts
            if cond:
                if side in ("L", "B"): sl_pts += pts; ml.append(lbl)
                if side in ("S", "B"): ss_pts += pts; ms.append(lbl)

        # Capa 1 — purgas (núcleo Bellsz)
        pnl = purga.get("purga_nivel_l", "")
        pns = purga.get("purga_nivel_s", "")
        add(purga["purga_alcista"] and "H1" in pnl, 1, "PURGA_SSL_H1", "L")
        add(purga["purga_alcista"] and "H4" in pnl, 2, "PURGA_SSL_H4", "L")
        add(purga["purga_alcista"] and "_D"  in pnl, 3, "PURGA_SSL_D",  "L")
        add(purga["purga_bajista"] and "H1" in pns, 1, "PURGA_BSL_H1", "S")
        add(purga["purga_bajista"] and "H4" in pns, 2, "PURGA_BSL_H4", "S")
        add(purga["purga_bajista"] and "_D"  in pns, 3, "PURGA_BSL_D",  "S")

        # Capa 2 — EMA
        add(ema_conf["cruce_bull"],                      2, "CRUCE_EMA_BULL", "L")
        add(ema_conf["cruce_bear"],                      2, "CRUCE_EMA_BEAR", "S")
        add(ema_conf["bull"] and not ema_conf["cruce_bull"], 1, "EMA_BULL", "L")
        add(ema_conf["bear"] and not ema_conf["cruce_bear"], 1, "EMA_BEAR", "S")

        # Capa 3 — RSI
        add(rsi_conf["ok_long"],       1, f"RSI{rsi_conf['valor']:.0f}",  "L")
        add(rsi_conf["ok_short"],      1, f"RSI{rsi_conf['valor']:.0f}",  "S")
        add(rsi_conf["momentum_bull"], 1, "RSI_BULL",  "L")
        add(rsi_conf["momentum_bear"], 1, "RSI_BEAR",  "S")

        # Confluencias extra
        add(ob["iob_bull"],            2, "OB+",     "L")
        add(ob["iob_bear"],            2, "OB-",     "S")
        add(ob_fvg_b,                  1, "OB+FVG",  "L")
        add(ob_fvg_r,                  1, "OB+FVG",  "S")
        add(fvg["bull_fvg"] and not fvg["fvg_rellenado"], 2, "FVG", "L")
        add(fvg["bear_fvg"] and not fvg["fvg_rellenado"], 2, "FVG", "S")
        add(sweep["sweep_bull"],        2, "SWEEP",   "L")
        add(sweep["sweep_bear"],        2, "SWEEP",   "S")
        add(bos["choch_bull"],          2, "CHoCH",   "L")
        add(bos["choch_bear"],          2, "CHoCH",   "S")
        add(bos["bos_bull"] and not bos["choch_bull"], 1, "BOS", "L")
        add(bos["bos_bear"] and not bos["choch_bear"], 1, "BOS", "S")
        add(htf == "BULL",              1, "MTF1H",   "L")
        add(htf == "BEAR",              1, "MTF1H",   "S")
        add(htf_4h == "BULL",           1, "MTF4H",   "L")
        add(htf_4h == "BEAR",           1, "MTF4H",   "S")
        add(pd_zone["discount"],        1, "DISC",    "L")
        add(pd_zone["premium"],         1, "PREM",    "S")
        add(bajo_vwap and config.VWAP_ACTIVO, 1, "VWAP_B", "L")
        add(sobre_vwap and config.VWAP_ACTIVO, 1, "VWAP_H", "S")
        add(kz["in_kz"],                1, f"KZ_{kz['nombre']}", "B")
        add(desplazamiento,             1, "DISP",    "B")
        add(macd_hist and macd_hist > 0, 1, "MACD",  "L")
        add(macd_hist and macd_hist < 0, 1, "MACD",  "S")
        if pat.get("patron"):
            add(pat["lado"] == "LONG",  pat["confianza"], pat["patron"], "L")
            add(pat["lado"] == "SHORT", pat["confianza"], pat["patron"], "S")

        # ══════════════════════════════════════════════════════
        # CONDICIÓN BASE: purga es OBLIGATORIA (núcleo Bellsz)
        # + al menos 1 confirmación de capa 2 o 3
        # ══════════════════════════════════════════════════════
        base_l = (purga["purga_alcista"] and
                  (ema_conf["bull"] or ema_conf["cruce_bull"]) and
                  (rsi_conf["ok_long"] or rsi_conf["momentum_bull"]))

        base_s = (purga["purga_bajista"] and
                  (ema_conf["bear"] or ema_conf["cruce_bear"]) and
                  (rsi_conf["ok_short"] or rsi_conf["momentum_bear"]))

        # HTF flexible: solo BULL/BEAR explícito bloquea la dirección contraria
        trend_ok_l = ema_conf["bull"] and (htf != "BEAR")
        trend_ok_s = ema_conf["bear"] and (htf != "BULL")

        lado = score = None
        motivos: list = []

        if not config.SOLO_LONG:
            if base_s and ss_pts >= config.SCORE_MIN and trend_ok_s:
                if ss_pts > sl_pts:
                    lado, score, motivos = "SHORT", ss_pts, ms

        if base_l and sl_pts >= config.SCORE_MIN and trend_ok_l:
            if lado is None or sl_pts >= ss_pts:
                lado, score, motivos = "LONG", sl_pts, ml

        if lado is None:
            if sl_pts >= 3 or ss_pts >= 3:
                log.info(
                    f"[NO-SENAL] {par} L:{sl_pts}({','.join(ml[:5])}) "
                    f"S:{ss_pts}({','.join(ms[:5])}) "
                    f"purga_L={purga['purga_alcista']}({purga.get('purga_nivel_l','')}) "
                    f"purga_S={purga['purga_bajista']}({purga.get('purga_nivel_s','')}) "
                    f"ema_bull={ema_conf['bull']} ema_bear={ema_conf['bear']} "
                    f"rsi={rsi_conf['valor']:.1f} htf={htf}"
                )
            return None

        # ══════════════════════════════════════════════════════
        # SL estructural + TP proporcional
        # ══════════════════════════════════════════════════════
        sl_p = _calcular_sl_estructural(candles, ob, lado, atr, precio)
        tp_p, tp1_p = _calcular_tp(precio, sl_p, lado)

        dist = abs(precio - sl_p)
        if dist <= 0:
            return None

        rr = abs(tp_p - precio) / dist
        if rr < config.MIN_RR:
            log.debug(f"[NO-SENAL] {par} R:R={rr:.2f} < {config.MIN_RR}")
            return None

        # Macro BTC veto solo para score bajo
        macro = _macro_btc["htf"]
        if score < 6 and macro != "NEUTRAL":
            if lado == "LONG"  and macro == "BEAR": return None
            if lado == "SHORT" and macro == "BULL": return None

        registrar_senal_ts(par)

        vol_avg   = sum(c["volume"] for c in candles[-21:-1]) / 20
        vol_ratio = round(candles[-1]["volume"] / (vol_avg + 1e-9), 2)

        return {
            # Campos estándar que espera main.py
            "par":           par,
            "lado":          lado,
            "precio":        precio,
            "sl":            round(sl_p, 8),
            "tp":            round(tp_p, 8),
            "tp1":           round(tp1_p, 8),
            "tp2":           round(tp_p, 8),
            "atr":           round(atr, 8),
            "dist_sl":       round(dist, 8),
            "score":         score,
            "rsi":           rsi_conf["valor"],
            "rr":            round(rr, 2),
            "motivos":       motivos,
            "kz":            kz["nombre"],
            "htf":           htf,
            "htf_4h":        htf_4h,
            "vwap":          round(vwap, 8),
            "sobre_vwap":    sobre_vwap,
            "fvg_top":       fvg.get("fvg_top", 0),
            "fvg_bottom":    fvg.get("fvg_bottom", 0),
            "fvg_rellenado": fvg.get("fvg_rellenado", True),
            "ob_bull":       ob["bull_ob"],
            "ob_bear":       ob["bear_ob"],
            "ob_fvg_bull":   ob_fvg_b,
            "ob_fvg_bear":   ob_fvg_r,
            "ob_mitigado":   not ob["bull_ob"] and not ob["bear_ob"],
            "bos_bull":      bos["bos_bull"],
            "bos_bear":      bos["bos_bear"],
            "choch_bull":    bos["choch_bull"],
            "choch_bear":    bos["choch_bear"],
            "sweep_bull":    sweep["sweep_bull"],
            "sweep_bear":    sweep["sweep_bear"],
            "patron":        pat.get("patron"),
            "vela_conf":     pat.get("patron") is not None,
            "premium":       pd_zone["premium"],
            "discount":      pd_zone["discount"],
            "zona_pct":      pd_zone["zona_pct"],
            "displacement":  desplazamiento,
            "inducement":    False,
            "pivotes":       None,
            "macd_hist":     round(macd_hist, 8) if macd_hist else 0,
            "vol_ratio":     vol_ratio,
            "asia_valido":   asia["valido"],
            "mercado_lateral": False,
            # Campos específicos Bellsz
            "purga_nivel":   purga["purga_nivel"],
            "purga_peso":    purga["purga_peso"],
            "bsl_h1": round(niveles["bsl_h1"], 8), "ssl_h1": round(niveles["ssl_h1"], 8),
            "bsl_h4": round(niveles["bsl_h4"], 8), "ssl_h4": round(niveles["ssl_h4"], 8),
            "bsl_d":  round(niveles["bsl_d"], 8),  "ssl_d":  round(niveles["ssl_d"], 8),
            "ema_r":  round(ema_conf["ema_r"], 8),
            "ema_l":  round(ema_conf["ema_l"], 8),
            "adx":    round(adx, 1),
        }

    except Exception as e:
        log.error(f"analizar_par {par}: {e}")
        return None


def analizar_todos(pares: list, workers: int = 4) -> list:
    senales = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = {ex.submit(analizar_par, p): p for p in pares}
        for fut in concurrent.futures.as_completed(futuros):
            try:
                r = fut.result()
                if r:
                    senales.append(r)
            except Exception as e:
                log.error(f"thread analizar: {e}")
    senales.sort(key=lambda x: x["score"], reverse=True)
    return senales
