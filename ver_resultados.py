"""
ver_resultados.py — Lee backtest_bellsz_results.json y muestra el ranking completo
Ejecutar: python ver_resultados.py
"""
import json, os, sys

# Buscar el archivo JSON
fname = "backtest_bellsz_results.json"
if not os.path.exists(fname):
    # Buscar en la misma carpeta que este script
    base = os.path.dirname(os.path.abspath(__file__))
    fname = os.path.join(base, "backtest_bellsz_results.json")

if not os.path.exists(fname):
    print("ERROR: No se encontró backtest_bellsz_results.json")
    print("Asegúrate de ejecutar este script desde la misma carpeta que el JSON")
    sys.exit(1)

with open(fname, encoding="utf-8") as f:
    data = json.load(f)

print(f"\n{'═'*60}")
print(f"  RESULTADOS BACKTEST BELLSZ")
print(f"  Fecha     : {data.get('fecha','?')[:19]}")
print(f"  Pares     : {data.get('pares_total','?')}")
print(f"  Días      : {data.get('dias','?')}")
print(f"  Trade     : ${data.get('trade_usdt','?')} × {data.get('leverage','?')}x")
print(f"  Duración  : {data.get('duracion_min','?')} minutos")
print(f"{'═'*60}")

todos = [r for r in data.get("todos", []) if r.get("trades", 0) > 0]
todos.sort(key=lambda x: x.get("pnl", -999), reverse=True)

if not todos:
    print("\n  Sin resultados con trades > 0")
    print("  El margen de purga puede seguir siendo muy restrictivo.")
    sys.exit(0)

print(f"\n  RANKING COMPLETO ({len(todos)} combinaciones con trades):")
print(f"  {'#':>2}  {'TP':>6}  {'Score':>5}  {'PnL':>8}  {'WR':>6}  {'PF':>5}  {'R:R':>5}  {'Trades':>6}  {'MaxDD':>7}  {'Racha-':>7}")
print(f"  {'-'*75}")

for i, r in enumerate(todos, 1):
    ico = "✅" if r["pnl"] > 0 else "❌"
    print(
        f"  {i:>2}. {ico} "
        f"TP={r['tp_mult']}x  "
        f"S≥{r['min_score']}  "
        f"${r['pnl']:>+7.2f}  "
        f"{r.get('wr',0):>5.1f}%  "
        f"{r.get('pf',0):>4.2f}  "
        f"{r.get('rr',0):>4.2f}x  "
        f"{r['trades']:>6}  "
        f"${r.get('max_dd',0):>6.2f}  "
        f"{r.get('max_racha_neg',0):>7}"
    )

print(f"\n{'═'*60}")
best = todos[0]
print(f"  🏆 MEJOR CONFIGURACIÓN:")
print(f"     TP_DIST_MULT  = {best['tp_mult']}")
print(f"     SCORE_MIN     = {best['min_score']}")
print(f"     PnL total     = ${best['pnl']:+.2f} USDT")
print(f"     Win Rate      = {best.get('wr',0):.1f}%")
print(f"     Profit Factor = {best.get('pf',0):.2f}")
print(f"     R:R           = {best.get('rr',0):.2f}x")
print(f"     Trades        = {best['trades']}")
print(f"     Max Drawdown  = ${best.get('max_dd',0):.2f}")
print(f"     Racha neg max = {best.get('max_racha_neg',0)}")
print(f"{'═'*60}")

# Breakdown purgas del mejor
purga = best.get("purga_stats", {})
if purga:
    print(f"\n  PURGAS — qué nivel funciona mejor (config óptima):")
    for k, v in sorted(purga.items(), key=lambda x: -x[1]["pnl"]):
        wr_p = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
        print(f"    {k:12s}  T:{v['total']:3d}  WR:{wr_p:.0f}%  PnL:${v['pnl']:+.2f}")

# Breakdown sesiones del mejor
kz = best.get("kz_stats", {})
if kz:
    print(f"\n  SESIONES — cuándo opera mejor:")
    for k, v in sorted(kz.items(), key=lambda x: -x[1]["pnl"]):
        wr_k = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
        print(f"    {k:8s}  T:{v['total']:3d}  WR:{wr_k:.0f}%  PnL:${v['pnl']:+.2f}")

# Top pares del mejor
pares = best.get("par_stats", {})
if pares:
    print(f"\n  TOP 10 PARES más rentables:")
    for i, (p, v) in enumerate(list(pares.items())[:10], 1):
        wr_p = v["wins"]/v["total"]*100 if v["total"] > 0 else 0
        print(f"    {i:>2}. {p:14s}  T:{v['total']:3d}  WR:{wr_p:.0f}%  PnL:${v['pnl']:+.2f}")

print(f"\n  → Pon estos valores en Railway Variables:")
print(f"     TP_DIST_MULT={best['tp_mult']}")
print(f"     SCORE_MIN={best['min_score']}")
print(f"{'═'*60}\n")
