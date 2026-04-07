# CORRECCIONES ESPECÍFICAS - F-STRING ERRORS

## 🎯 CAMBIO 1: Línea ~558 - Función aurolo_signal()

### ❌ CÓDIGO ORIGINAL (INCORRECTO):
```python
result['descripcion'] = (
    f"P1({p1_icon})EMA{AUROLO_EMA_LEN} | "
    f"P2({p2_icon})WT={round(wt_now,1)} | "
    f"P3({p3_icon})ADX={round(adx_now,1)} DI+={round(dip_now,1)}"
)
```

### ✅ CÓDIGO CORREGIDO:
```python
# FIX: Pre-construct the description string to avoid f-string backslash issue
desc_parts = [
    f"P1({p1_icon})EMA{AUROLO_EMA_LEN}",
    f"P2({p2_icon})WT={round(wt_now,1)}",
    f"P3({p3_icon})ADX={round(adx_now,1)} DI+={round(dip_now,1)}"
]
result['descripcion'] = " | ".join(desc_parts)
```

## 🎯 CAMBIO 2: Línea ~750 - Learning._reporte()

### ❌ CÓDIGO ORIGINAL (INCORRECTO):
```python
pts_txt = ""
for p in sorted(self.by_pts):
    d = self.by_pts[p]; tot = d['w']+d['l']
    if tot > 0:
        wr_pts = int(d['w']/tot*100)
        pts_txt += f"  {p}/3 pts: WR={wr_pts}% PnL=${d['pnl']:.2f} ({tot}t)\n"

msg = (
    f"<b>🧠 APRENDIZAJE — {n} trades</b>\n"
    f"...\n"
    f"<b>📊 Por puntos Aurolo:</b>\n{pts_txt or '  Sin datos\n'}"
    ...
)
```

### ✅ CÓDIGO CORREGIDO:
```python
# Build pts_txt without f-string issues
pts_lines = []
for p in sorted(self.by_pts):
    d = self.by_pts[p]; tot = d['w']+d['l']
    if tot > 0:
        wr_pts = int(d['w']/tot*100)
        pts_lines.append(f"  {p}/3 pts: WR={wr_pts}% PnL=${d['pnl']:.2f} ({tot}t)")
pts_txt = "\n".join(pts_lines) if pts_lines else "  Sin datos"

# Build reas_txt
reas_lines = []
for r, d in sorted(self.by_reason.items(), key=lambda x: x[1]['pnl'], reverse=True):
    reas_lines.append(f"  {r}: ${d['pnl']:+.2f} ({d['n']}x)")
reas_txt = "\n".join(reas_lines) if reas_lines else "  Sin datos"

msg = (
    f"<b>🧠 APRENDIZAJE — {n} trades</b>\n"
    f"WR: {int(wr)}% | PnL: ${pnl:+.4f} | Score mín: {int(self.opt_score)}\n"
    f"Blacklist: {len(self.blacklist)} | Cap: {int(self._score_cap())}\n\n"
    f"<b>📊 Por puntos Aurolo:</b>\n{pts_txt}\n"
    f"<b>🚪 Cierres:</b>\n{reas_txt}\n"
)
```

## 🎯 CAMBIO 3: Línea ~1200 - _open() telegram message

### ❌ CÓDIGO ORIGINAL (INCORRECTO):
```python
self._tg(
    f"<b>🟢 LONG [{label}]</b> — <b>{sym}</b>\n"
    f"Score: {int(sig['score'])} | RR: {sig['rr']:.2f}:1\n\n"
    f"<b>🔍 Aurolo {pts}/3:</b>\n"
    f"{p1} P1 EMA{AUROLO_EMA_LEN}: ${sig['ema55']:.4f}\n"
    f"{p2} P2 WT: {sig['aurolo_wt']:.1f}"
    f"{'(OS✅)' if sig['aurolo_wt'] <= WT_OS2 else ''}\n"  # PROBLEMA AQUÍ
    ...
)
```

### ✅ CÓDIGO CORREGIDO:
```python
# FIX: Build telegram message without f-string backslashes
os_indicator = "(OS✅)" if sig['aurolo_wt'] <= WT_OS2 else ""

msg = (
    f"<b>🟢 LONG [{label}]</b> — <b>{sym}</b>\n"
    f"Score: {int(sig['score'])} | RR: {sig['rr']:.2f}:1\n\n"
    f"<b>🔍 Aurolo {pts}/3:</b>\n"
    f"{p1} P1 EMA{AUROLO_EMA_LEN}: ${sig['ema55']:.4f}\n"
    f"{p2} P2 WT: {sig['aurolo_wt']:.1f}{os_indicator}\n"
    f"{p3} P3 ADX: {sig['aurolo_adx']:.1f} | DI+:{sig['aurolo_dip']:.1f} DI-:{sig['aurolo_din']:.1f}\n\n"
    f"📍 Entrada:  ${fill_price:.6f}\n"
    f"{vwap_icon} VWAP:    ${sig['vwap']:.6f}\n"
    f"🎯 TP1 ({int(TP1_PCT)}%): ${tp1_price:.6f} (+{sl_pct_real*TP1_RATIO:.2f}%)\n"
    f"🎯 TP2 ({int(TP2_PCT)}%): ${tp2_price:.6f} (+{sl_pct_real*TP2_RATIO:.2f}%)\n"
    f"🏃 Runner ({int(100-TP1_PCT-TP2_PCT)}%): EMA25\n"
    f"🛑 SL: ${sl_price:.6f} (-{sl_pct_real:.2f}%)\n"
    f"1H: {'🟢' if sig['trend_1h']==1 else '⚪'} | BTC: {self._btc_1h:+.2f}%"
)
self._tg(msg)
```

## 🎯 CAMBIO 4: Línea ~1500 - _report() telegram message

### ❌ CÓDIGO ORIGINAL (INCORRECTO):
```python
pos = ""
for sym,t in self.trades.items():
    tk=self._ticker(sym); cur=tk['price'] if tk else t['entry']
    pct=(cur-t['entry'])/t['entry']*100
    tp_st = "TP1✅TP2✅" if t['tp2_hit'] else "TP1✅" if t['tp1_hit'] else "→TP1"
    pos += f"  📌 {sym}[{t['aurolo_pts']}/3]: {pct:+.2f}% {tp_st}\n"

self._tg(
    f"<b>📊 Reporte v5.6</b>\n"
    ...
    + (pos if pos else "  Sin posiciones\n")
)
```

### ✅ CÓDIGO CORREGIDO:
```python
# Build position lines
pos_lines = []
for sym,t in self.trades.items():
    tk=self._ticker(sym); cur=tk['price'] if tk else t['entry']
    pct=(cur-t['entry'])/t['entry']*100
    tp_st = "TP1✅TP2✅" if t['tp2_hit'] else "TP1✅" if t['tp1_hit'] else "→TP1"
    pos_lines.append(f"  📌 {sym}[{t['aurolo_pts']}/3]: {pct:+.2f}% {tp_st}")
pos = "\n".join(pos_lines) if pos_lines else "  Sin posiciones"

self._tg(
    f"<b>📊 Reporte v5.6.1</b>\n"
    f"PnL: ${self.stats['pnl']:+.4f} | WR: {wr:.0f}% | {total}t\n"
    f"Día: ${self._daily_pnl:+.4f} | Equity: ${ACCOUNT_EQUITY:.2f}\n"
    f"Score: {int(self.learn.opt_score)} (cap {int(self.learn._score_cap())}) | BTC: {self._btc_1h:+.2f}%\n"
    f"{pos}\n"
)
```

## 🔍 REGLA GENERAL

**NUNCA hagas esto:**
```python
# ❌ MAL - backslash en f-string
result = f"texto {variable}\n más texto"
result = f"texto {'(X)' if cond else ''}\n más"
```

**SIEMPRE haz esto:**
```python
# ✅ BIEN - construye fuera del f-string
lines = ["línea 1", "línea 2", "línea 3"]
result = "\n".join(lines)

# O asigna a variable
indicator = "(X)" if cond else ""
result = f"texto {variable} {indicator}"
```

## 📝 CHECKLIST DE VERIFICACIÓN

Después de aplicar los cambios:

1. ✅ Busca en tu código: `\n` dentro de f-strings
2. ✅ Busca: expresiones condicionales complejas en f-strings
3. ✅ Verifica que no haya `\t`, `\r` u otros escapes en f-strings
4. ✅ Prueba localmente: `python3 main.py`
5. ✅ Revisa que no haya errores de sintaxis

## 🚀 DEPLOYMENT

Una vez corregido:
```bash
python3 main.py  # Prueba local
# Si funciona:
git add main.py
git commit -m "Fix: f-string syntax errors"
git push origin main
```
