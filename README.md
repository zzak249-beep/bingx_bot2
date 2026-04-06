# 🤖 MLP Tactical Bridge Bot

Bot de trading automático para BingX (Futuros Perpetuos) basado en la estrategia
**Triple Confirmación**: Tendencial (EMA55) + WaveTrend + ADX.

---

## 📋 Requisitos previos

1. **Cuenta BingX** con futuros perpetuos habilitados
2. **Bot de Telegram** creado con @BotFather
3. **Cuenta Railway** (railway.app) — plan Hobby ~$5/mes

---

## 🚀 Deploy en Railway (paso a paso)

### 1. Subir código a GitHub

```bash
git init
git add .
git commit -m "MLP Tactical Bridge Bot"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### 2. Crear proyecto en Railway

1. Ve a [railway.app](https://railway.app) → **New Project**
2. Elige **Deploy from GitHub repo**
3. Selecciona tu repositorio
4. Railway detectará el `Dockerfile` automáticamente

### 3. Configurar Variables de Entorno en Railway

En tu proyecto → **Variables** → añade cada una:

| Variable | Valor |
|----------|-------|
| `BINGX_API_KEY` | Tu API Key de BingX |
| `BINGX_SECRET_KEY` | Tu Secret Key de BingX |
| `TELEGRAM_TOKEN` | Token de tu bot de Telegram |
| `TELEGRAM_CHAT_ID` | Tu Chat ID de Telegram |
| `SYMBOL` | `BTC-USDT` (o el par que quieras) |
| `TIMEFRAME` | `1h` |
| `TRADE_AMOUNT` | `10` (USDT por trade) |
| `LEVERAGE` | `5` |
| `MIN_SIGNAL` | `2` |
| `USE_LIVE` | `false` ← **empieza aquí** |

### 4. Verificar que funciona

- Revisa los logs en Railway → **Deployments → View Logs**
- Deberías recibir en Telegram: `🤖 Bot iniciado (DEMO)`
- Si ves señales en los logs → funciona correctamente

### 5. Activar modo real

Solo cuando estés seguro → cambia en Railway Variables:
```
USE_LIVE=true
```

---

## 🔑 Obtener API Keys de BingX

1. Entra a [BingX](https://bingx.com) → tu perfil → **API Management**
2. Crea nueva API Key
3. Permisos: ✅ **Trade** ✅ **Read** ❌ **Withdraw** (no necesario)
4. Guarda el API Key y Secret Key (el secret solo se muestra una vez)
5. Añade la IP de Railway a la whitelist (o deja en blanco para todas)

---

## 🤖 Obtener Token de Telegram

1. Habla con [@BotFather](https://t.me/BotFather) en Telegram
2. Envía `/newbot` y sigue los pasos
3. Copia el **token** que te da
4. Para obtener tu **Chat ID**: habla con [@userinfobot](https://t.me/userinfobot)

---

## 📊 Cómo funciona la estrategia

### Triple Confirmación (0-3 puntos)

| Punto | Indicador | Condición LONG | Condición SHORT |
|-------|-----------|----------------|-----------------|
| 1️⃣ | EMA 55 (Tendencial) | Precio cerca/encima de EMA | Precio cerca/debajo de EMA |
| 2️⃣ | WaveTrend | Cruce en sobreventa | Cruce en sobrecompra |
| 3️⃣ | ADX/DMI | ADX cae + DI+ > DI- | ADX cae + DI- > DI+ |

- **3/3** = Señal perfecta ✅
- **2/3** = Señal válida (mínimo recomendado)
- **1/3** = No opera

### SL y TP automáticos
- **SL**: 1.5x el rango ATR de las últimas 20 velas
- **TP**: R:R mínimo de 1.8 (TP siempre mayor que SL)

---

## ⚙️ Variables de configuración

| Variable | Descripción | Valores |
|----------|-------------|---------|
| `SYMBOL` | Par a operar | `BTC-USDT`, `ETH-USDT`, `RUNE-USDT`... |
| `TIMEFRAME` | Temporalidad | `5m`, `15m`, `1h`, `4h`, `1d` |
| `TRADE_AMOUNT` | USDT por operación | `10`, `20`, `50`... |
| `LEVERAGE` | Apalancamiento | `1`-`20` (recomendado ≤10) |
| `MIN_SIGNAL` | Puntos mínimos para operar | `2` o `3` |
| `USE_LIVE` | Modo real vs demo | `true` / `false` |

---

## ⚠️ Advertencias importantes

- **Empieza siempre con `USE_LIVE=false`** para verificar señales
- **Nunca pongas `WITHDRAW` permissions** en tu API Key
- **Usa un capital que puedas permitirte perder**
- El bot no garantiza ganancias — es una herramienta de automatización
- Monitorea los logs en Railway regularmente

---

## 📱 Mensajes que recibirás en Telegram

- `🤖 Bot iniciado` — Al arrancar
- `🎯 SEÑAL 3/3 — LONG` — Nueva señal detectada
- `✅ Orden ejecutada` — Orden enviada a BingX
- `⚠️ Error en ciclo` — Si hay algún fallo
