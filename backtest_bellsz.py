"""
backtest_bellsz.py — Backtest Liquidez Lateral [Bellsz] v2.0
=============================================================
- 400 pares de Binance Futures (descarga automática)
- 60 dias de datos reales
- Descarga paralela (8 workers) para mayor velocidad
- Grid search: TP 1.5x-3.0x, Score 4-7
- Reporte por par, por sesion y por timeframe de purga
- Resultados: backtest_bellsz_results.json

Uso:
  python backtest_bellsz.py

Tarda ~15-25 min (400 pares × 60 dias × 4 timeframes)
"""

import sys, os, time, json, threading
from datetime import datetime, timezone
from statistics import mean
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    os.system("pip install requests -q")
    import requests

BINANCE_URL      = "https://api.binance.com/api/v3/klines"
BINANCE_EXCH_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
DIAS         = 60
TRADE_USDT   = 10
LEVERAGE     = 10
LIQ_LOOKBACK = 50
EMA_FAST     = 9
EMA_SLOW     = 21
RSI_BUY_MAX  = 70
RSI_SELL_MIN = 30
LIQ_MARGEN   = 0.1   # igual que margen_pip=0.1 en Pine Script (se divide /100 en detectar_purga)
MAX_PARES    = 100
WORKERS_DL   = 8      # hilos de descarga simultánea
WORKERS_BT   = 4      # hilos de backtest

# Grid search
TP_MULTS = [1.5, 2.0, 2.5, 3.0]
SCORES   = [4, 5, 6, 7]

# Pares manuales que siempre incluimos aunque no salgan en el top 400
PARES_FORZADOS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT",
    "AVAXUSDT","DOGEUSDT","LINKUSDT","UNIUSDT","AAVEUSDT","INJUSDT",
    "DOTUSDT","ATOMUSDT","NEARUSDT","APTUSDT","SUIUSDT","ARBUSDT",
    "OPUSDT","TONUSDT","TRXUSDT","PEPEUSDT","WIFUSDT","LTCUSDT",
    "BCHUSDT","FILUSDT","IMXUSDT","STXUSDT","ORDIUSDT","MATICUSDT",
]

_print_lock = threading.Lock()

def log(msg):
    with _print_lock:
        print(msg, flush=True)


# ══════════════════════════════════════════════════════════════
# PASO 1 — OBTENER 400 PARES DE BINANCE FUTURES
# ══════════════════════════════════════════════════════════════

def obtener_pares_binance(max_n=400) -> list:
    """
    Obtiene los N pares USDT de Binance Futures ordenados por volumen 24h.
    Usa el endpoint público — sin API key necesaria.
    """
    log("\n[PASO 1] Obteniendo pares de Binance Futures...")
    try:
        # Ticker 24h con volumen (endpoint público, sin auth)
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            timeout=20
        )
        tickers = r.json()
        if not isinstance(tickers, list):
            raise ValueError(f"Respuesta inesperada: {tickers}")

        # Filtrar solo pares USDT perpetuos
        usdt = [
            t for t in tickers
            if isinstance(t, dict)
            and t.get("symbol", "").endswith("USDT")
            and "_" not in t.get("symbol", "")  # excluir trimestrales
        ]

        # Ordenar por volumen quote (quoteVolume) descendente
        usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)

        # Tomar top N
        pares = [t["symbol"] for t in usdt[:max_n]]

        # Asegurar que los forzados están incluidos
        for p in PARES_FORZADOS:
            if p not in pares:
                pares.append(p)

        log(f"  ✓ {len(pares)} pares obtenidos (top por volumen 24h)")
        log(f"  Top 10: {', '.join(pares[:10])}")
        return pares[:max_n]

    except Exception as e:
        log(f"  ⚠️  Error obteniendo pares: {e}")
        log("  → Usando lista de respaldo...")
        return PARES_FORZADOS


# ══════════════════════════════════════════════════════════════
# PASO 2 — DESCARGA PARALELA DE DATOS
# ══════════════════════════════════════════════════════════════

def descargar_tf(sym, interval, dias, reintentos=2):
    """Descarga un timeframe para un símbolo. Retorna lista de velas o []."""
    end   = int(time.time() * 1000)
    start = end - dias * 86_400_000
    todas = []
    for intento in range(reintentos + 1):
        try:
            todas = []
            s = start
            while s < end:
                r = requests.get(BINANCE_URL, params={
                    "symbol": sym, "interval": interval,
                    "startTime": s, "endTime": end, "limit": 1000
                }, timeout=15)
                d = r.json()
                if not isinstance(d, list) or not d:
                    break
                for c in d:
                    todas.append({
                        "ts":    int(c[0]),
                        "open":  float(c[1]),
                        "high":  float(c[2]),
                        "low":   float(c[3]),
                        "close": float(c[4]),
                        "volume":float(c[5]),
                    })
                s = int(d[-1][0]) + 1
                if len(d) < 1000:
                    break
                time.sleep(0.05)  # respetar rate limit Binance
            if todas:
                todas.sort(key=lambda x: x["ts"])
                return todas
        except Exception:
            if intento < reintentos:
                time.sleep(1)
    return []


_descarga_ok   = 0
_descarga_fail = 0
_descarga_lock = threading.Lock()


def descargar_par(sym):
    """Descarga 5m + 1h + 4h + 1d para un símbolo. Retorna (sym, datos) o (sym, None)."""
    global _descarga_ok, _descarga_fail
    try:
        c5  = descargar_tf(sym, "5m",  DIAS)
        c1h = descargar_tf(sym, "1h",  DIAS + 5)
        c4h = descargar_tf(sym, "4h",  DIAS + 5)
        c1d = descargar_tf(sym, "1d",  DIAS + 10)

        if len(c5) < 500:   # mínimo ~3 días de velas 5m
            with _descarga_lock:
                _descarga_fail += 1
            return sym, None

        with _descarga_lock:
            _descarga_ok += 1
            if _descarga_ok % 20 == 0:
                log(f"  ↳ {_descarga_ok} pares descargados...")

        return sym, {"5m": c5, "1h": c1h, "4h": c4h, "1d": c1d}
    except Exception as e:
        with _descarga_lock:
            _descarga_fail += 1
        return sym, None


def descargar_todos(pares):
    log(f"\n[PASO 2] Descargando datos de {len(pares)} pares ({DIAS} días)...")
    log(f"  Usando {WORKERS_DL} hilos paralelos — esto tarda ~15 min...\n")

    datos = {}
    con_error = []

    with ThreadPoolExecutor(max_workers=WORKERS_DL) as ex:
        futuros = {ex.submit(descargar_par, p): p for p in pares}
        for fut in as_completed(futuros):
            sym, d = fut.result()
            if d:
                datos[sym] = d
            else:
                con_error.append(sym)

    log(f"\n  ✓ {len(datos)} pares con datos OK")
    log(f"  ✗ {len(con_error)} pares sin datos (no listados en Binance Spot o sin histórico)")
    if con_error[:5]:
        log(f"  Ejemplos fallidos: {', '.join(con_error[:5])}")
    return datos


# ══════════════════════════════════════════════════════════════
# INDICADORES
# ══════════════════════════════════════════════════════════════

def ema(prices, n):
    if len(prices) < n:
        return None
    k = 2 / (n + 1)
    v = sum(prices[:n]) / n
    for x in prices[n:]:
        v = x * k + v * (1 - k)
    return v


def rsi_calc(prices, n=14):
    if len(prices) < n + 1:
        return 50.0
    d  = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(x, 0)      for x in d[:n]) / n
    al = sum(abs(min(x, 0)) for x in d[:n]) / n
    for x in d[n:]:
        ag = (ag * (n-1) + max(x, 0))      / n
        al = (al * (n-1) + abs(min(x, 0))) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr_calc(candles, n=14):
    if len(candles) < n + 1:
        return 0.0
    trs = [max(candles[i]["high"] - candles[i]["low"],
               abs(candles[i]["high"] - candles[i-1]["close"]),
               abs(candles[i]["low"]  - candles[i-1]["close"]))
           for i in range(1, len(candles))]
    return sum(trs[-n:]) / n if len(trs) >= n else (sum(trs)/len(trs) if trs else 0.0)


def htf_tendencia(htf_candles, ts_ref):
    hist = [c for c in htf_candles if c["ts"] <= ts_ref]
    if len(hist) < 30:
        return "NEUTRAL"
    cl = [c["close"] for c in hist[-60:]]
    ef = ema(cl, EMA_FAST)
    es = ema(cl, EMA_SLOW)
    if ef and es:
        if ef > es * 1.001: return "BULL"
        if ef < es * 0.999: return "BEAR"
    return "NEUTRAL"


def get_niveles(htf_candles, ts_ref, lookback=50):
    """
    Replica exactamente: ta.highest(high, lookback) con lookahead_off
    Toma las últimas N velas HTF CERRADAS antes del ts_ref.
    La vela actual del HTF (que aún no ha cerrado) se excluye con ts < ts_ref.
    Esto es lo mismo que hace el Pine Script con lookahead_off.
    """
    # Solo velas HTF que han cerrado ANTES del timestamp actual
    hist = [c for c in htf_candles if c["ts"] < ts_ref]
    if len(hist) < 5:
        return 0.0, 0.0
    # Tomar las últimas N velas cerradas
    rec = hist[-lookback:] if len(hist) >= lookback else hist
    return max(c["high"] for c in rec), min(c["low"] for c in rec)


def detectar_purga(candle, bsl, ssl, margen=0.003):
    """
    Replica exactamente la detección de purga del Pine Script:
      purga_alcista = low <= ssl * (1 + margen/100) and close > ssl
      purga_bajista = high >= bsl * (1 - margen/100) and close < bsl
    """
    if bsl <= 0 or ssl <= 0:
        return False, False
    m  = margen / 100  # margen_pip/100 como en Pine Script
    pa = candle["low"]  <= ssl * (1 + m) and candle["close"] > ssl
    pb = candle["high"] >= bsl * (1 - m) and candle["close"] < bsl
    return pa, pb


def swing_sl(candles, lado, n=10):
    if len(candles) < n + 2:
        return 0.0
    rec = candles[-(n+1):-1]
    if lado == "LONG":
        return min(c["low"]  for c in rec) * 0.997
    return     max(c["high"] for c in rec) * 1.003


def hora_utc(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour


# ══════════════════════════════════════════════════════════════
# SEÑAL BELLSZ COMPLETA
# ══════════════════════════════════════════════════════════════

def senal_bellsz(c5, c1h, c4h, c1d, min_score=5):
    if len(c5) < 80:
        return None

    c      = c5[-1]
    ts     = c["ts"]
    precio = c["close"]

    at = atr_calc(c5[-20:])
    if at <= 0 or at / precio * 100 < 0.03:
        return None

    cl = [x["close"] for x in c5[-100:]]

    # Capa 2 — EMA
    er = ema(cl, EMA_FAST)
    el = ema(cl, EMA_SLOW)
    if er is None or el is None:
        return None
    bull_ema = er > el * 1.001
    bear_ema = er < el * 0.999

    # Capa 3 — RSI
    rv   = rsi_calc(cl[-50:])
    rsi_serie = [rsi_calc(cl[:i+1]) or 50 for i in range(max(0, len(cl)-8), len(cl))]
    rsi_ema3  = ema(rsi_serie, min(3, len(rsi_serie))) if len(rsi_serie) >= 3 else rv
    rsi_mb = rsi_ema3 is not None and rv > rsi_ema3
    rsi_ms = rsi_ema3 is not None and rv < rsi_ema3
    rsi_l  = RSI_SELL_MIN < rv < RSI_BUY_MAX
    rsi_s  = RSI_SELL_MIN < rv < RSI_BUY_MAX

    # HTF tendencia
    htf_1h = htf_tendencia(c1h, ts)
    htf_4h = htf_tendencia(c4h, ts)

    # Capa 1 — PURGAS (calcular ANTES de usarlas en base_l/base_s)
    bsl_h1, ssl_h1 = get_niveles(c1h, ts, LIQ_LOOKBACK)
    bsl_h4, ssl_h4 = get_niveles(c4h, ts, LIQ_LOOKBACK)
    bsl_d,  ssl_d  = get_niveles(c1d, ts, min(LIQ_LOOKBACK, 30))

    pa_h1, pb_h1 = detectar_purga(c, bsl_h1, ssl_h1, LIQ_MARGEN)
    pa_h4, pb_h4 = detectar_purga(c, bsl_h4, ssl_h4, LIQ_MARGEN)
    pa_d,  pb_d  = detectar_purga(c, bsl_d,  ssl_d,  LIQ_MARGEN)

    purga_l = pa_h1 or pa_h4 or pa_d
    purga_s = pb_h1 or pb_h4 or pb_d

    if not purga_l and not purga_s:
        return None

    # Condición base: purga + (EMA o RSI)
    base_l = purga_l and (bull_ema or rsi_l)
    base_s = purga_s and (bear_ema or rsi_s)

    trend_ok_l = (htf_1h != "BEAR")
    trend_ok_s = (htf_1h != "BULL")

    # Scoring
    sl = ss = 0
    if pa_h1: sl += 1
    if pa_h4: sl += 2
    if pa_d:  sl += 3
    if pb_h1: ss += 1
    if pb_h4: ss += 2
    if pb_d:  ss += 3
    if bull_ema: sl += 1
    if bear_ema: ss += 1
    if rsi_l and rsi_mb: sl += 2
    if rsi_s and rsi_ms: ss += 2
    if htf_1h == "BULL": sl += 1
    if htf_1h == "BEAR": ss += 1
    if htf_4h == "BULL": sl += 1
    if htf_4h == "BEAR": ss += 1

    lado = score = None
    if base_s and ss >= min_score and trend_ok_s:
        if ss > sl: lado, score = "SHORT", ss
    if base_l and sl >= min_score and trend_ok_l:
        if lado is None or sl >= ss: lado, score = "LONG", sl

    if lado is None:
        return None

    sl_p = swing_sl(c5, lado)
    if sl_p <= 0:
        return None
    dist = abs(precio - sl_p)
    if dist <= 0:
        return None

    purga_lvl = []
    if lado == "LONG":
        if pa_h1: purga_lvl.append("H1")
        if pa_h4: purga_lvl.append("H4")
        if pa_d:  purga_lvl.append("D")
    else:
        if pb_h1: purga_lvl.append("H1")
        if pb_h4: purga_lvl.append("H4")
        if pb_d:  purga_lvl.append("D")

    h = hora_utc(ts)
    kz = ("ASIA"   if 0  <= h < 4  else
          "LONDON" if 8  <= h < 12 else
          "NY"     if 13 <= h < 16 else "FUERA")

    return {
        "lado": lado, "precio": precio, "sl": sl_p,
        "dist": dist, "atr": at, "score": score,
        "rsi": rv, "htf": htf_1h, "htf4h": htf_4h,
        "purga_nivel": "+".join(purga_lvl),
        "kz": kz,
    }


# ══════════════════════════════════════════════════════════════
# SIMULADOR POR PAR
# ══════════════════════════════════════════════════════════════

def simular_par(sym, datos, tp_mult, min_score):
    d   = datos[sym]
    c5  = d["5m"]
    c1h = d["1h"]
    c4h = d["4h"]
    c1d = d["1d"]

    trades = []
    pos    = None
    cd     = 0

    for idx in range(80, len(c5)):
        c     = c5[idx]
        h_val = c["high"]
        l_val = c["low"]

        if pos:
            sl   = pos["sl"]
            tp   = pos["tp"]
            lado = pos["lado"]
            at   = pos["atr"]
            pos["age"] = pos.get("age", 0) + 1

            # Break-even automático al avanzar 1 ATR
            if not pos.get("be"):
                if ((lado == "LONG"  and h_val >= pos["entrada"] + at) or
                    (lado == "SHORT" and l_val <= pos["entrada"] - at)):
                    pos["sl"] = pos["entrada"]
                    pos["be"] = True

            razon = sal = None
            if pos["age"] >= 96:  # 8h en 5m
                razon, sal = "TIME", c["close"]
            elif lado == "LONG":
                if l_val <= sl:   razon, sal = "SL", sl
                elif h_val >= tp: razon, sal = "TP", tp
            else:
                if h_val >= sl:   razon, sal = "SL", sl
                elif l_val <= tp: razon, sal = "TP", tp

            if razon:
                ent = pos["entrada"]
                qty = (TRADE_USDT * LEVERAGE) / ent
                pnl = qty * ((sal - ent) if lado == "LONG" else (ent - sal))
                trades.append({
                    "pnl":    round(pnl, 4),
                    "razon":  razon,
                    "lado":   lado,
                    "score":  pos["score"],
                    "purga":  pos.get("purga_nivel", ""),
                    "kz":     pos.get("kz", ""),
                    "sym":    sym,
                })
                pos = None
                cd  = 5

        if pos is None and cd <= 0:
            sig = senal_bellsz(c5[:idx+1], c1h, c4h, c1d, min_score)
            if sig:
                ent   = sig["precio"]
                dist  = sig["dist"]
                lado  = sig["lado"]
                tp_p  = (ent + dist * tp_mult) if lado == "LONG" else (ent - dist * tp_mult)
                pos   = {
                    "lado":        lado,
                    "entrada":     ent,
                    "sl":          sig["sl"],
                    "tp":          tp_p,
                    "atr":         sig["atr"],
                    "score":       sig["score"],
                    "purga_nivel": sig["purga_nivel"],
                    "kz":          sig["kz"],
                    "age":         0,
                    "be":          False,
                }
        cd = max(0, cd - 1)

    # Cerrar posición abierta al final
    if pos:
        sal = c5[-1]["close"]
        ent = pos["entrada"]
        qty = (TRADE_USDT * LEVERAGE) / ent
        pnl = qty * ((sal - ent) if pos["lado"] == "LONG" else (ent - sal))
        trades.append({
            "pnl":   round(pnl, 4),
            "razon": "FIN",
            "lado":  pos["lado"],
            "score": pos["score"],
            "purga": pos.get("purga_nivel", ""),
            "kz":    pos.get("kz", ""),
            "sym":   sym,
        })

    return trades


# ══════════════════════════════════════════════════════════════
# BACKTEST COMPLETO (paralelo)
# ══════════════════════════════════════════════════════════════

def run_backtest(datos, tp_mult, min_score):
    """Corre el backtest sobre todos los pares en paralelo."""
    all_trades = []

    def bt_par(sym):
        try:
            return simular_par(sym, datos, tp_mult, min_score)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=WORKERS_BT) as ex:
        futuros = {ex.submit(bt_par, sym): sym for sym in datos}
        for fut in as_completed(futuros):
            all_trades.extend(fut.result())

    return all_trades


def calcular_stats(all_trades, nombre, tp_mult, min_score):
    fin    = [t for t in all_trades if t["razon"] in ("SL","TP","TIME","FIN")]
    if not fin:
        return {"nombre": nombre, "pnl": -999, "trades": 0}

    wins   = [t for t in fin if t["pnl"] > 0]
    losses = [t for t in fin if t["pnl"] <= 0]
    total  = sum(t["pnl"] for t in all_trades)
    wr     = len(wins) / len(fin) * 100
    aw     = mean([t["pnl"] for t in wins])   if wins   else 0
    al     = mean([t["pnl"] for t in losses]) if losses else 0
    pf_n   = sum(t["pnl"] for t in wins)
    pf_d   = abs(sum(t["pnl"] for t in losses))
    pf     = pf_n / pf_d if pf_d > 0 else 99.0
    rr     = abs(aw / al) if al != 0 else 0

    # Breakdown por razón
    por_r = {}
    for t in fin:
        por_r[t["razon"]] = por_r.get(t["razon"], 0) + 1

    # Breakdown por purga
    purga_stats = {}
    for t in fin:
        p = t.get("purga", "?") or "?"
        if p not in purga_stats:
            purga_stats[p] = {"total": 0, "wins": 0, "pnl": 0.0}
        purga_stats[p]["total"] += 1
        purga_stats[p]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            purga_stats[p]["wins"] += 1

    # Breakdown por sesión
    kz_stats = {}
    for t in fin:
        k = t.get("kz", "?") or "?"
        if k not in kz_stats:
            kz_stats[k] = {"total": 0, "wins": 0, "pnl": 0.0}
        kz_stats[k]["total"] += 1
        kz_stats[k]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            kz_stats[k]["wins"] += 1

    # Top 10 pares por PnL
    par_stats = {}
    for t in fin:
        p = t.get("sym", "?") or "?"
        if p not in par_stats:
            par_stats[p] = {"total": 0, "wins": 0, "pnl": 0.0}
        par_stats[p]["total"] += 1
        par_stats[p]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            par_stats[p]["wins"] += 1

    # Drawdown máximo y equity curve
    running = 0.0
    peak    = 0.0
    max_dd  = 0.0
    equity  = []
    for t in all_trades:
        running += t["pnl"]
        equity.append(round(running, 4))
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Racha de pérdidas consecutivas
    max_racha = racha = 0
    for t in fin:
        if t["pnl"] <= 0:
            racha += 1
            max_racha = max(max_racha, racha)
        else:
            racha = 0

    estado = "✅ RENTABLE" if total > 0 and wr > 45 else "❌"

    return {
        "nombre":       nombre,
        "pnl":          round(total, 2),
        "trades":       len(fin),
        "wr":           round(wr, 1),
        "pf":           round(pf, 2),
        "rr":           round(rr, 2),
        "avg_win":      round(aw, 3),
        "avg_loss":     round(al, 3),
        "max_dd":       round(max_dd, 2),
        "max_racha_neg":max_racha,
        "tp_mult":      tp_mult,
        "min_score":    min_score,
        "por_razon":    por_r,
        "purga_stats":  purga_stats,
        "kz_stats":     kz_stats,
        "par_stats":    dict(sorted(par_stats.items(), key=lambda x: -x[1]["pnl"])[:20]),
        "estado":       estado,
    }


def imprimir_resultado(r):
    if r["trades"] == 0:
        return
    log(f"\n{'='*58}")
    log(f"  TP={r['tp_mult']}x  Score≥{r['min_score']}  —  {r['estado']}")
    log(f"{'='*58}")
    log(f"  Trades:{r['trades']}  WR:{r['wr']}%  PnL:${r['pnl']:+.2f}  PF:{r['pf']}  R:R:{r['rr']}x")
    log(f"  AvgW:${r['avg_win']:.3f}  AvgL:${r['avg_loss']:.3f}  MaxDD:${r['max_dd']:.2f}  RachaNeg:{r.get('max_racha_neg',0)}")

    por_r = r.get("por_razon", {})
    log(f"  Razones: {' '.join(f'{k}:{v}' for k,v in sorted(por_r.items()))}")

    purga = r.get("purga_stats", {})
    if purga:
        log("  Purgas:")
        for k, v in sorted(purga.items(), key=lambda x: -x[1]["pnl"]):
            wr_p = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
            log(f"    {k:12s} T:{v['total']:3d}  W:{v['wins']:3d}  WR:{wr_p:.0f}%  PnL:${v['pnl']:+.2f}")

    kz = r.get("kz_stats", {})
    if kz:
        log("  Sesiones:")
        for k, v in sorted(kz.items(), key=lambda x: -x[1]["pnl"]):
            wr_k = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
            log(f"    {k:8s} T:{v['total']:3d}  WR:{wr_k:.0f}%  PnL:${v['pnl']:+.2f}")

    pares = r.get("par_stats", {})
    if pares:
        log("  Top 5 pares:")
        for i, (p, v) in enumerate(list(pares.items())[:5], 1):
            wr_p = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
            log(f"    {i}. {p:12s} T:{v['total']:3d}  WR:{wr_p:.0f}%  PnL:${v['pnl']:+.2f}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    t_inicio = time.time()

    log("=" * 58)
    log("  BACKTEST — Liquidez Lateral [Bellsz] v2.0")
    log(f"  {MAX_PARES} pares | {DIAS} días | ${TRADE_USDT}×{LEVERAGE}x")
    log("=" * 58)

    # ── Obtener pares ──────────────────────────────────────────
    pares = obtener_pares_binance(MAX_PARES)
    log(f"  Total pares a descargar: {len(pares)}")

    # ── Descargar datos ────────────────────────────────────────
    datos = descargar_todos(pares)

    if not datos:
        log("ERROR: no se descargaron datos")
        sys.exit(1)

    log(f"\n  ✓ {len(datos)} pares con datos completos")
    t_dl = time.time()
    log(f"  Tiempo descarga: {(t_dl-t_inicio)/60:.1f} min")

    # ── Grid Search ────────────────────────────────────────────
    log(f"\n[PASO 3] Grid Search ({len(TP_MULTS)} TP × {len(SCORES)} scores = {len(TP_MULTS)*len(SCORES)} combinaciones)...")
    log(f"  Procesando {len(datos)} pares con {WORKERS_BT} hilos...\n")

    results = []
    total_combo = len(TP_MULTS) * len(SCORES)
    combo_n = 0

    for tp_m in TP_MULTS:
        for sc in SCORES:
            combo_n += 1
            nombre = f"TP={tp_m}x  Score≥{sc}"
            log(f"  [{combo_n}/{total_combo}] {nombre}...")

            all_t = run_backtest(datos, tp_m, sc)
            r     = calcular_stats(all_t, nombre, tp_m, sc)
            results.append(r)
            imprimir_resultado(r)

    # ── Ranking final ──────────────────────────────────────────
    # Filtrar combos sin trades antes de ordenar
    results = [r for r in results if r.get("trades", 0) > 0]
    results.sort(key=lambda x: x["pnl"], reverse=True)

    log("\n\n" + "═" * 58)
    log("  RANKING FINAL — TOP 10")
    log("═" * 58)
    for i, r in enumerate(results[:10], 1):
        ico = "✅" if r["pnl"] > 0 else "❌"
        log(
            f"  {i:2d}. {ico} TP={r['tp_mult']}x Score≥{r['min_score']}"
            f"  PnL:${r['pnl']:+.2f}"
            f"  WR:{r.get('wr',0):.1f}%"
            f"  PF:{r.get('pf',0):.2f}"
            f"  T:{r['trades']}"
            f"  DD:${r.get('max_dd',0):.2f}"
        )

    if results and results[0]["trades"] > 0:
        best = results[0]
        log(f"\n{'═'*58}")
        log(f"  🏆 MEJOR CONFIGURACIÓN:")
        log(f"     TP_DIST_MULT = {best['tp_mult']}")
        log(f"     SCORE_MIN    = {best['min_score']}")
        log(f"     PnL          = ${best['pnl']:+.2f}")
        log(f"     WR           = {best.get('wr',0):.1f}%")
        log(f"     Profit Factor= {best.get('pf',0):.2f}")
        log(f"     Max Drawdown = ${best.get('max_dd',0):.2f}")
        log(f"     Trades       = {best['trades']}")
        log(f"{'═'*58}")
        log(f"\n  → Usa estos valores en config.py antes de Railway:")
        log(f"     TP_DIST_MULT={best['tp_mult']}")
        log(f"     SCORE_MIN={best['min_score']}")

    # ── Guardar resultados ─────────────────────────────────────
    t_fin  = time.time()
    output = {
        "fecha":         datetime.now(timezone.utc).isoformat(),
        "pares_total":   len(datos),
        "dias":          DIAS,
        "trade_usdt":    TRADE_USDT,
        "leverage":      LEVERAGE,
        "duracion_min":  round((t_fin - t_inicio) / 60, 1),
        "mejor":         results[0] if results else {},
        "ranking_top10": results[:10],
        "todos":         results,
    }

    fname = "backtest_bellsz_results.json"
    try:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        log(f"\n  💾 Guardado en {fname}")
    except Exception as e:
        log(f"  ⚠️  No se pudo guardar: {e}")

    log(f"\n  ⏱️  Tiempo total: {(t_fin-t_inicio)/60:.1f} minutos")
    log("  Backtest completado.\n")


if __name__ == "__main__":
    main()
