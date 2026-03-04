# 🤖 BB+RSI Elite Bot v12.3

Bot de trading automático para **BingX Perpetual Swap**.  
Estrategia: Bollinger Bands + RSI + MACD + Stoch RSI + Divergencias.

---

## 🆕 Novedades v12.3 vs v12.2

| Mejora | Detalle |
|---|---|
| 🧠 Trailing SL dinámico | Activo desde el primer tick, no solo tras partial TP |
| 📊 Dashboard web | Equity, posiciones y trades en tiempo real |
| 🛡️ Circuit breaker | Para si pérdida diaria >5% o drawdown >12% |
| 📐 Sizing ATR | Posición más pequeña en pares más volátiles |
| 🔁 Re-entry | Vuelve a entrar con score más alto tras SL |
| 🕐 Multi-timeframe 4h | Solo abre LONG si 4h no es bajista (y viceversa) |
| 📊 Filtro volumen | Ignora señales en velas de volumen muerto |
| ⚖️ Scoring momentum | Penaliza señales con demasiadas velas seguidas en contra |
| 📱 Comandos Telegram | /status /pause /resume /positions /close |

---

## 📁 Estructura de archivos

```
main.py              ← Entrypoint Railway (loop principal)
config.py            ← TODOS los parámetros
strategy.py          ← Señales + filtros MTF + volumen
trader.py            ← Ejecución, trailing, re-entry
risk_manager.py      ← Circuit breaker, drawdown, sizing ATR
dashboard.py         ← Dashboard web Flask
bingx_api.py         ← Wrapper REST BingX autenticado
data_feed.py         ← Descarga velas
indicators.py        ← Indicadores + scoring mejorado
telegram_notifier.py ← Notificaciones + comandos bidireccionales
backtest_final.py    ← Motor backtest (no cambia nunca)
```

---

## 🚀 Deploy en Railway

### 1. Subir a GitHub
```bash
git init && git add . && git commit -m "bot v12.3"
git remote add origin https://github.com/TU_USER/trading-bot.git
git push -u origin main
```

### 2. Railway: New Project → Deploy from GitHub

### 3. Variables de entorno (Settings → Variables)

| Variable | Valor |
|---|---|
| `BINGX_API_KEY` | API key BingX |
| `BINGX_API_SECRET` | API secret BingX |
| `TELEGRAM_TOKEN` | Token @BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat ID |
| `TRADE_MODE` | `paper` → `live` cuando estés listo |
| `PORT` | Railway lo pone solo (8080) |

### 4. Dashboard web
Railway expone automáticamente el puerto → verás la URL en el panel.  
También tienes `/api/status` y `/api/trades` como endpoints JSON.

---

## 📱 Comandos Telegram

Envía estos mensajes a tu bot:

```
/status     — resumen completo (balance, WR, PF, drawdown)
/balance    — balance en tiempo real
/positions  — posiciones abiertas con precios y SL
/pause      — pausar el bot (no abre nuevas operaciones)
/resume     — reactivar el bot
/close LINK-USDT  — cerrar posición manualmente
/help       — lista de comandos
```

---

## ⚙️ Parámetros clave (config.py)

```python
# Circuit breaker
MAX_DAILY_LOSS_PCT = 0.05   # para si pierde >5% hoy
MAX_DRAWDOWN_PCT   = 0.12   # para si drawdown >12%
MAX_CONCURRENT_POS = 4      # máximo 4 posiciones a la vez

# Trailing SL
TRAIL_FROM_START   = True   # trailing activo desde apertura
TRAIL_ATR_MULT_INIT  = 2.0  # distancia al trailing = 2x ATR
TRAIL_ATR_MULT_AFTER = 1.5  # más ajustado tras partial TP

# Re-entry
REENTRY_ENABLED   = True
REENTRY_COOLDOWN  = 2       # horas de espera
REENTRY_SCORE_MIN = 60      # score más exigente

# Filtros
VOLUME_FILTER     = True    # desactivar si da demasiados rechazos
MTF_ENABLED       = True    # desactivar para más señales
```

---

## ⚠️ Aviso de riesgo

Trading con apalancamiento implica riesgo de pérdida total.  
Usa `TRADE_MODE=paper` hasta validar en vivo.  
Este software es educativo.
