"""
backtest_bellsz.py — Backtest de la estrategia Liquidez Lateral [Bellsz]
=========================================================================
Descarga datos reales de Binance y simula las señales Bellsz completas:
  - Purgas BSL/SSL en H1, H4, Diario
  - Confirmación EMA 9/21 + RSI momentum
  - Score de confluencia
  - TP proporcional al dist_SL (probado en bt_v4)

Uso:
  python backtest_bellsz.py

Resultados: backtest_bellsz_results.json
"""

import sys, os, time, json
from datetime import datetime, timezone
from statistics import mean

try:
    import requests
except ImportError:
    os.system("pip install requests --break-system-packages -q")
    import requests

BINANCE_URL = "https://api.binance.com/api/v3/klines"

# ─── CONFIG ────────────────────────────────────────────────────────────────────
PARES = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
    "LINK-USDT", "NEAR-USDT", "AVAX-USDT", "ARB-USDT",
]
DIAS         = 30
TRADE_USDT   = 10
LEVERAGE     = 10
SCORE_MIN    = 5
LIQ_LOOKBACK = 50
EMA_FAST     = 9
EMA_SLOW     = 21
RSI_PERIOD   = 14
RSI_BUY_MAX  = 70
RSI_SELL_MIN = 30
LIQ_MARGEN   = 0.001   # 0.1%

# Grid search
TP_MULTS  = [1.5, 2.0, 2.5, 3.0]
SL_MULTS  = [1.0, 1.5, 2.0]
SCORES    = [4, 5, 6]

print("=" * 60)
print("  BACKTEST — Liquidez Lateral [Bellsz]")
print("=" * 60)


# ─── DESCARGA ──────────────────────────────────────────────────────────────────

def descargar(sym, interval, dias):
    sym_b = sym.replace("-", "")
    end   = int(time.time() * 1000)
    start = end - dias * 86_400_000
    todas = []
    while start < end:
        try:
            r = requests.get(BINANCE_URL, params={
                "symbol": sym_b, "interval": interval,
                "startTime": start, "endTime": end, "limit": 1000
            }, timeout=20)
            d = r.json()
            if not isinstance(d, list) or not d:
                break
            for c in d:
                todas.append({
                    "ts": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                    "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])
                })
            start = int(d[-1][0]) + 1
            if len(d) < 1000:
                break
        except Exception as e:
            print(f"  ERR {sym} {interval}: {e}")
            break
    todas.sort(key=lambda x: x["ts"])
    return todas


print(f"\nDescargando {len(PARES)} pares × {DIAS} días...")
datos = {}
for par in PARES:
    try:
        c5  = descargar(par, "5m",  DIAS)
        c1h = descargar(par, "1h",  DIAS + 5)
        c4h = descargar(par, "4h",  DIAS + 5)
        c1d = descargar(par, "1d",  DIAS + 10)
        if len(c5) > 300:
            datos[par] = {"5m": c5, "1h": c1h, "4h": c4h, "1d": c1d}
            print(f"  ✓ {par:14s} 5m={len(c5)} 1h={len(c1h)} 4h={len(c4h)}")
    except Exception as e:
        print(f"  ✗ {par}: {e}")

if not datos:
    print("ERROR: sin datos")
    sys.exit(1)


# ─── INDICADORES ───────────────────────────────────────────────────────────────

def ema(prices, n):
    if len(prices) < n:
        return None
    k = 2 / (n + 1)
    v = sum(prices[:n]) / n
    for x in prices[n:]:
        v = x * k + v * (1 - k)
    return v


def rsi(prices, n=14):
    if len(prices) < n + 1:
        return 50.0
    d  = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(x, 0) for x in d[:n]) / n
    al = sum(abs(min(x, 0)) for x in d[:n]) / n
    for x in d[n:]:
        ag = (ag * (n-1) + max(x, 0)) / n
        al = (al * (n-1) + abs(min(x, 0))) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr(candles, n=14):
    if len(candles) < n + 1:
        return 0.0
    trs = [max(candles[i]["high"] - candles[i]["low"],
               abs(candles[i]["high"] - candles[i-1]["close"]),
               abs(candles[i]["low"]  - candles[i-1]["close"]))
           for i in range(1, len(candles))]
    return sum(trs[-n:]) / n if len(trs) >= n else (sum(trs) / len(trs) if trs else 0)


def get_htf_tendencia(htf_candles, ts_ref):
    """Tendencia HTF en el momento de la señal (sin look-ahead)."""
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


def get_niveles_liquidez(htf_candles, ts_ref, lookback=50):
    hist = [c for c in htf_candles if c["ts"] <= ts_ref]
    if len(hist) < lookback:
        return 0.0, 0.0
    rec = hist[-lookback:]
    return max(c["high"] for c in rec), min(c["low"] for c in rec)


def detectar_purga_bt(candle, bsl, ssl, margen_pct=0.001):
    """Detecta si la vela actual purgó un nivel."""
    margen = candle["close"] * margen_pct / 100
    purga_alcista = ssl > 0 and candle["low"] <= ssl * (1 + margen) and candle["close"] > ssl
    purga_bajista = bsl > 0 and candle["high"] >= bsl * (1 - margen) and candle["close"] < bsl
    return purga_alcista, purga_bajista


def swing_sl(candles, lado, n=10):
    if len(candles) < n + 2:
        return 0.0
    rec = candles[-(n+1):-1]
    if lado == "LONG":
        return min(c["low"]  for c in rec) * 0.997
    return max(c["high"] for c in rec) * 1.003


# ─── MOTOR DE SEÑALES BELLSZ ───────────────────────────────────────────────────

def senal_bellsz(candles_5m, c1h, c4h, c1d, min_score=5):
    """Genera señal Bellsz completa con las 3 capas."""
    if len(candles_5m) < 80:
        return None

    c    = candles_5m[-1]
    ts   = c["ts"]
    precio = c["close"]

    at = atr(candles_5m[-20:])
    if at <= 0 or at / precio * 100 < 0.03:
        return None

    cl = [x["close"] for x in candles_5m[-100:]]

    # Capa 2 — EMA
    ema_r = ema(cl, EMA_FAST)
    ema_l = ema(cl, EMA_SLOW)
    if ema_r is None or ema_l is None:
        return None
    bull_ema = ema_r > ema_l * 1.001
    bear_ema = ema_r < ema_l * 0.999

    # Capa 3 — RSI
    rsi_v = rsi(cl[-50:])
    rsi_ema = ema([rsi(cl[:i+1]) or 50 for i in range(len(cl)-5, len(cl))], 3)
    rsi_mom_bull = rsi_ema is not None and rsi_v > rsi_ema
    rsi_mom_bear = rsi_ema is not None and rsi_v < rsi_ema
    rsi_ok_l = RSI_SELL_MIN < rsi_v < RSI_BUY_MAX and rsi_mom_bull
    rsi_ok_s = RSI_SELL_MIN < rsi_v < RSI_BUY_MAX and rsi_mom_bear

    # HTF tendencia
    htf_1h = get_htf_tendencia(c1h, ts)
    htf_4h = get_htf_tendencia(c4h, ts)

    trend_ok_l = bull_ema and (htf_1h != "BEAR")
    trend_ok_s = bear_ema and (htf_1h != "BULL")

    # Capa 1 — Niveles de liquidez HTF
    bsl_h1, ssl_h1 = get_niveles_liquidez(c1h, ts, LIQ_LOOKBACK)
    bsl_h4, ssl_h4 = get_niveles_liquidez(c4h, ts, LIQ_LOOKBACK)
    bsl_d,  ssl_d  = get_niveles_liquidez(c1d, ts, min(LIQ_LOOKBACK, 30))

    # Detectar purgas
    pa_h1, pb_h1 = detectar_purga_bt(c, bsl_h1, ssl_h1)
    pa_h4, pb_h4 = detectar_purga_bt(c, bsl_h4, ssl_h4)
    pa_d,  pb_d  = detectar_purga_bt(c, bsl_d,  ssl_d)

    purga_alcista = pa_h1 or pa_h4 or pa_d
    purga_bajista = pb_h1 or pb_h4 or pb_d

    if not purga_alcista and not purga_bajista:
        return None

    # SCORING
    sl_pts = ss_pts = 0
    sl_pts += 1 if pa_h1 else 0
    sl_pts += 2 if pa_h4 else 0
    sl_pts += 3 if pa_d  else 0
    ss_pts += 1 if pb_h1 else 0
    ss_pts += 2 if pb_h4 else 0
    ss_pts += 3 if pb_d  else 0

    # EMA y RSI añaden puntos
    if bull_ema: sl_pts += 1
    if bear_ema: ss_pts += 1
    if rsi_ok_l: sl_pts += 2
    if rsi_ok_s: ss_pts += 2
    if htf_1h == "BULL": sl_pts += 1
    if htf_1h == "BEAR": ss_pts += 1
    if htf_4h == "BULL": sl_pts += 1
    if htf_4h == "BEAR": ss_pts += 1

    # Condición base Bellsz: purga + EMA + RSI obligatorios
    base_l = purga_alcista and bull_ema and rsi_ok_l
    base_s = purga_bajista and bear_ema and rsi_ok_s

    lado = score = None
    if not config_import_ok:
        # Sin config.py, usar umbrales directos
        SCORE_MIN_BT = min_score
    else:
        SCORE_MIN_BT = min_score

    if base_s and ss_pts >= SCORE_MIN_BT and trend_ok_s:
        if ss_pts > sl_pts:
            lado, score = "SHORT", ss_pts
    if base_l and sl_pts >= SCORE_MIN_BT and trend_ok_l:
        if lado is None or sl_pts >= ss_pts:
            lado, score = "LONG", sl_pts

    if lado is None:
        return None

    # SL estructural
    sl_p = swing_sl(candles_5m, lado)
    if sl_p <= 0:
        return None
    dist = abs(precio - sl_p)
    if dist <= 0:
        return None

    purga_nivel = []
    if lado == "LONG":
        if pa_h1: purga_nivel.append("H1")
        if pa_h4: purga_nivel.append("H4")
        if pa_d:  purga_nivel.append("D")
    else:
        if pb_h1: purga_nivel.append("H1")
        if pb_h4: purga_nivel.append("H4")
        if pb_d:  purga_nivel.append("D")

    return {
        "lado": lado, "precio": precio, "sl": sl_p,
        "dist": dist, "atr": at, "score": score,
        "rsi": rsi_v, "htf": htf_1h, "purga_nivel": "+".join(purga_nivel),
    }


config_import_ok = True  # siempre True en backtest standalone


# ─── SIMULADOR ─────────────────────────────────────────────────────────────────

def simular(par, tp_mult, sl_mult_atr, min_score):
    d = datos[par]
    c5 = d["5m"]; c1h = d["1h"]; c4h = d["4h"]; c1d = d["1d"]
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
            age  = pos.get("age", 0) + 1
            pos["age"] = age

            # Break-even si avanzó 1 ATR
            if not pos.get("be_hit"):
                if (lado == "LONG"  and h_val >= pos["entrada"] + at) or \
                   (lado == "SHORT" and l_val <= pos["entrada"] - at):
                    pos["sl"]    = pos["entrada"]
                    pos["be_hit"] = True

            razon = sal = None
            if age >= 96:         razon, sal = "TIME", c["close"]
            elif lado == "LONG":
                if l_val <= sl:   razon, sal = "SL",   sl
                elif h_val >= tp: razon, sal = "TP",   tp
            else:
                if h_val >= sl:   razon, sal = "SL",   sl
                elif l_val <= tp: razon, sal = "TP",   tp

            if razon:
                ent = pos["entrada"]
                pnl = (TRADE_USDT * LEVERAGE / ent) * ((sal - ent) if lado == "LONG" else (ent - sal))
                trades.append({"pnl": round(pnl, 4), "razon": razon,
                                "lado": lado, "score": pos["score"],
                                "purga": pos.get("purga_nivel", "")})
                pos = None
                cd  = 5

        if pos is None and cd <= 0:
            sig = senal_bellsz(c5[:idx+1], c1h, c4h, c1d, min_score)
            if sig:
                dist = sig["dist"]
                ent  = sig["precio"]
                # SL: el estructural del signal
                sl_p = sig["sl"]
                # TP proporcional: dist × tp_mult
                if sig["lado"] == "LONG":
                    tp_p = ent + dist * tp_mult
                else:
                    tp_p = ent - dist * tp_mult
                pos = {
                    "lado": sig["lado"], "entrada": ent, "sl": sl_p,
                    "tp": tp_p, "atr": sig["atr"], "score": sig["score"],
                    "purga_nivel": sig["purga_nivel"], "age": 0, "be_hit": False,
                }
        cd = max(0, cd - 1)

    if pos:
        sal = c5[-1]["close"]
        ent = pos["entrada"]
        pnl = (TRADE_USDT * LEVERAGE / ent) * ((sal - ent) if pos["lado"] == "LONG" else (ent - sal))
        trades.append({"pnl": round(pnl, 4), "razon": "FIN", "lado": pos["lado"],
                       "score": pos["score"], "purga": pos.get("purga_nivel", "")})
    return trades


def run_bt(tp_mult, sl_mult, min_score, nombre):
    all_t = []
    for par in datos:
        t = simular(par, tp_mult, sl_mult, min_score)
        all_t.extend(t)

    if not all_t:
        return {"nombre": nombre, "pnl": -999, "trades": 0}

    fin    = [t for t in all_t if t["razon"] in ("SL", "TP", "TIME", "FIN")]
    wins   = [t for t in fin if t["pnl"] > 0]
    losses = [t for t in fin if t["pnl"] <= 0]
    total  = sum(t["pnl"] for t in all_t)
    wr     = len(wins) / len(fin) * 100 if fin else 0
    aw     = mean([t["pnl"] for t in wins])   if wins   else 0
    al     = mean([t["pnl"] for t in losses]) if losses else 0
    pf_num = sum(t["pnl"] for t in wins)
    pf_den = abs(sum(t["pnl"] for t in losses))
    pf     = pf_num / pf_den if pf_den > 0 else 99
    rr     = abs(aw / al) if al != 0 else 0

    # Breakdown por razón
    por_r  = {}
    for t in all_t:
        por_r[t["razon"]] = por_r.get(t["razon"], 0) + 1

    # Breakdown por purga
    purga_breakdown = {}
    for t in fin:
        p = t.get("purga", "?")
        if p not in purga_breakdown:
            purga_breakdown[p] = {"total": 0, "wins": 0}
        purga_breakdown[p]["total"] += 1
        if t["pnl"] > 0:
            purga_breakdown[p]["wins"] += 1

    estado = "✅" if total > 0 and wr > 45 else "❌"

    print(f"\n{'='*56}")
    print(f"  {nombre}")
    print(f"{'='*56}")
    print(f"  Trades:{len(fin)}  WR:{wr:.1f}%  PnL:${total:+.2f}  PF:{pf:.2f}  R:R:{rr:.2f}  {estado}")
    print(f"  AvgW:${aw:.2f}  AvgL:${al:.2f}  {' '.join(f'{k}:{v}' for k,v in sorted(por_r.items()))}")
    print(f"  Purgas → {', '.join(f'{k}:{v[\"wins\"]}/{v[\"total\"]}' for k,v in purga_breakdown.items())}")

    return {
        "nombre": nombre, "pnl": round(total, 2), "trades": len(fin),
        "wr": round(wr, 1), "pf": round(pf, 2), "rr": round(rr, 2),
        "tp_mult": tp_mult, "sl_mult": sl_mult, "min_score": min_score,
        "por_razon": por_r, "purga_breakdown": purga_breakdown,
    }


# ─── GRID SEARCH ───────────────────────────────────────────────────────────────

print("\n" + "─" * 56)
print("  GRID SEARCH — Bellsz (purga + EMA + RSI)")
print("─" * 56)

results = []
for tp_m in TP_MULTS:
    for sc in SCORES:
        nombre = f"TP={tp_m}x  score={sc}"
        r = run_bt(tp_m, 1.5, sc, nombre)
        results.append(r)

results.sort(key=lambda x: x["pnl"], reverse=True)

print("\n\n" + "═" * 56)
print("  RANKING FINAL")
print("═" * 56)
for r in results[:10]:
    ico = "✅" if r["pnl"] > 0 else "❌"
    print(
        f"  {ico} {r['nombre']:30s} "
        f"PnL:${r['pnl']:+.2f}  WR:{r.get('wr',0):.1f}%  "
        f"PF:{r.get('pf',0):.2f}  T:{r['trades']}"
    )

if results:
    best = results[0]
    print(f"\n  🏆 MEJOR: {best['nombre']}")
    print(f"     PnL=${best['pnl']:+.2f} | WR={best.get('wr',0):.1f}% | PF={best.get('pf',0):.2f}")
    print(f"     → TP_DIST_MULT={best['tp_mult']} | SCORE_MIN={best['min_score']}")
    print("═" * 56)

# Guardar resultados
output = {
    "fecha": datetime.now(timezone.utc).isoformat(),
    "pares": PARES,
    "dias": DIAS,
    "mejor": results[0] if results else {},
    "ranking": results[:10],
}
try:
    with open("backtest_bellsz_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  💾 Guardado en backtest_bellsz_results.json")
except Exception as e:
    print(f"  ⚠️  No se pudo guardar: {e}")
