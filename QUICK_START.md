# 🚀 QUICK START — 5 MINUTOS AL AIRE
## SATY ELITE v13 · UTBot · WaveTrend · Bj Bot · BB+RSI

## Necesitas tener listo:

1. ✅ API Key de BingX (con permisos Read + Trade)
2. ✅ Token de bot de Telegram (@BotFather)
3. ✅ Tu Chat ID de Telegram (@userinfobot)
4. ✅ Cuenta en GitHub
5. ✅ Cuenta en Railway.app

---

## Paso 1: Subir a GitHub (2 min)

```bash
git init
git add .
git commit -m "SATY ELITE v13 - initial deploy"

# Crear repo PRIVADO en github.com/new
git remote add origin https://github.com/TU_USUARIO/saty-bot.git
git branch -M main
git push -u origin main
```

⚠️ **El repo DEBE ser PRIVADO**

---

## Paso 2: Railway Deploy (2 min)

1. Ve a https://railway.app
2. New Project → Deploy from GitHub
3. Conecta GitHub → Selecciona tu repo
4. Añade estas 4 variables (Variables → RAW Editor):

```
BINGX_API_KEY=tu_key_aqui
BINGX_API_SECRET=tu_secret_aqui
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

5. Click "Update Variables"

---

## Paso 3: Verificar (1 min)

Railway → Deployments → Ver logs:

```
SATY ELITE v13 — FULL STRATEGY EDITION · 24/7
UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI
Exchange conectado ✓
Balance: $XXX.XX USDT
━━━ SCAN #1 ... | 300 pares | 0/12 trades ━━━
```

Telegram → Recibirás el mensaje de arranque con todos los indicadores activos.

---

## 🎯 LISTO — Bot operando 24/7 con 16 puntos de score

**Variables opcionales nuevas en v13** (tienen defaults optimizados):

| Variable | Default | Descripción |
|----------|---------|-------------|
| `UTBOT_KEY_VALUE` | 10 | Sensibilidad UTBot (↓ = más señales) |
| `WT_CHAN_LEN` | 9 | WaveTrend channel length |
| `RNR` | 2.0 | Risk to Reward ratio (TP2 = 2× riesgo) |
| `BB_PERIOD` | 20 | Período Bollinger Bands |
| `MIN_SCORE` | 5 | Score mínimo de 16 para entrar |
| `TRADE_EXPIRE_BARS` | 0 | Barras máx por trade (0=OFF) |

Ver `railway_variables.txt` para **todas** las variables.

**Costos**: Railway Hobby Plan $5/mes (recomendado)

**⚠️ IMPORTANTE**:
- Repo debe ser **PRIVADO**
- Nunca actives "Withdraw" en API de BingX
- Empieza con capital pequeño ($50-100)
- En v13 el score es sobre **16** (no 12 como en versiones anteriores)

---

Ver `RESUMEN_EJECUTIVO.md` para guía completa paso a paso.
