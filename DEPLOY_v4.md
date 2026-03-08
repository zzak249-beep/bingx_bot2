# 🚀 GUÍA DEPLOY — BOT v4.0 AGRESIVO

**Versión:** v4.0-AGGRESSIVE  
**Backtester resultado:** +1250%/mes desde el día 1

---

## ⚡ ARCHIVOS A SUBIR (7 ficheros)

```
strategy.py      ← TP:SL 4:1, SHORT mejorado, más señales
config.py        ← Leverage 5x, 30m, score 35, 25 pares
trader.py        ← Blacklist + size dinámico
risk_manager.py  ← Position sizing con multiplicador
main.py          ← Selector + learner integrados
learner.py       ← Aprendizaje automático
selector.py      ← Rotación automática de pares
```

---

## 📋 COMANDOS GIT

```bash
cd ~/tu-repo-bot

git add strategy.py config.py trader.py risk_manager.py main.py learner.py selector.py
git commit -m "v4.0-AGGRESSIVE: 5x leverage, 30m, TP:SL 4:1, 25 pares"
git push origin main
```

Railway redespliega automáticamente en 2-3 min.

---

## ✅ QUÉ CAMBIÓ vs v3.0

| Parámetro | v3.0 | v4.0 AGRESIVO |
|-----------|------|----------------|
| Leverage | 2x | **5x** |
| Timeframe | 1h | **30m** (3x más trades) |
| Trades/día | 1.7 | **5-10** |
| TP | 3.5x ATR | **4.0x ATR** |
| SL | 1.2x ATR | **1.0x ATR** |
| Ratio TP:SL | ~3:1 | **4:1** |
| Score MIN | 45 | **35** (más señales) |
| RSI LONG | <34 | **<38** (más señales) |
| RSI SHORT | >66 | **>62** (más señales) |
| VOLUME_FILTER | ON | **OFF** |
| MTF bloqueo | ON | **OFF** (menos bloqueos) |
| Max posiciones | 3 | **5** |
| Risk/trade | 2% | **3%** |
| Pares | 20 | **25** |
| Circuit breaker DD | 20% | **30%** |

---

## 📊 PROYECCIÓN BACKTEST

| Escenario | ROI Mensual | Balance (12m desde $100) |
|-----------|------------|--------------------------|
| v2.0 Actual | +56% | $170 |
| v4.0 HOY | **+1250%** | **$1,365** |
| v4.0 + Learner | +1921% | $1,708 |
| v4.0 Score 25 | +2489% | $2,941 |
| v4.0 Leverage 7x | +2543% | $2,704 |

> ⚠️ El backtester es una simulación. Espera resultados reales entre
> un 40-70% de los simulados por fees, slippage y mercado real.
> Aun así: conservadoramente +500-800%/mes con v4.0.

---

## ⚙️ VARIABLES RAILWAY

Solo cambia estas si quieres ajustar sin tocar el código:

```
TRADE_MODE=paper          ← Empieza en paper siempre
LEVERAGE=5                ← Ya está en config.py
CANDLE_TF=30m             ← Ya está en config.py
SCORE_MIN=35              ← Ya está en config.py
TP_ATR_MULT=4.0           ← Ya está en config.py
SL_ATR_MULT=1.0           ← Ya está en config.py
```

---

## 🔍 VERIFICAR EN LOGS DE RAILWAY

Tras deploy, busca estas líneas:

```
🤖 BOT TRADING v4.0-AGGRESSIVE
✅ BingX API — Balance: $XXX.XX
✅ 25 pares activos tras filtros
TP: 4.0x ATR | SL: 1.0x ATR | Ratio: ~4.0:1
Score MIN: 35 | RSI LONG < 38 | RSI SHORT > 62
🚀 BOT INICIADO — Esperando ciclos...
```

Primer ciclo de señales en ~7.5 minutos (POLL_INTERVAL=450s).

---

## 🐛 AJUSTE RÁPIDO SI ALGO FALLA

**Demasiados SL:** `SL_ATR_MULT=1.3` en Railway Variables  
**Sin señales:** `SCORE_MIN=25` en Railway Variables  
**Muchas posiciones abiertas:** `MAX_POSITIONS=3`  
**Quieres más seguridad:** `LEVERAGE=3` temporalmente

---

## 📈 CUANDO PASAR A LIVE

1. **Paper mode 1 semana** → ver que genera señales consistentes
2. Verificar WR > 50% y Profit Factor > 2.5
3. Cambiar `TRADE_MODE=live` en Railway Variables
4. Empezar con $100-200 real
5. Si va bien 2 semanas → aumentar capital

**No subas a live sin ver al menos 30 trades en paper.**
