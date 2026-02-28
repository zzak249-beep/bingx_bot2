# 🚀 SATY ELITE v13 — Full Strategy Edition

Bot de trading algorítmico para **BingX Perpetual Futures** con 12 trades simultáneos, 24/7, universo completo de pares USDT — ahora con **4 estrategias Pine Script integradas**.

```
╔══════════════════════════════════════════════════════════════╗
║         SATY ELITE v13 — FULL STRATEGY EDITION              ║
║         BingX Perpetual Futures · 12 Trades · 24/7         ║
╠══════════════════════════════════════════════════════════════╣
║  4 Pine Scripts integrados:                                 ║
║  · UTBot (HPotter) — ATR Trailing Stop                      ║
║  · Instrument-Z (OscillateMatrix) — WaveTrend TCI           ║
║  · Bj Bot (3Commas) — R:R dinámico con swing pivots         ║
║  · BB+RSI (rouxam) — Bollinger Bands + RSI filter           ║
╚══════════════════════════════════════════════════════════════╝

✅ Todo verificado y listo para Railway
✅ Código probado y funcionando
✅ Documentación completa incluida
```

---

## 📚 ÍNDICE DE DOCUMENTACIÓN

### 🚀 INICIO RÁPIDO
- **[QUICK_START.md](QUICK_START.md)** ← Empieza aquí (5 minutos)
- **[RESUMEN_EJECUTIVO.md](RESUMEN_EJECUTIVO.md)** ← Guía completa paso a paso

### ⚙️ CONFIGURACIÓN
- **[railway_variables.txt](railway_variables.txt)** ← Variables para copiar/pegar
- **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)** ← Instrucciones detalladas Railway

### 🎯 ESTRATEGIAS
- **[ESTRATEGIAS_AVANZADAS.md](ESTRATEGIAS_AVANZADAS.md)** ← Configuraciones por perfil

### ❓ AYUDA
- **[FAQ.md](FAQ.md)** ← Preguntas frecuentes
- **[verify.sh](verify.sh)** ← Script de verificación automática

---

## ⚡ DEPLOY EN 3 PASOS

### 1️⃣ Obtener credenciales (10 min)
- API Key de BingX (con permisos Read + Trade)
- Token de bot de Telegram (@BotFather)
- Chat ID de Telegram (@userinfobot)

### 2️⃣ Subir a GitHub (2 min)
```bash
git init
git add .
git commit -m "SATY ELITE v13 - initial deploy"
git remote add origin https://github.com/TU_USUARIO/saty-bot.git
git push -u origin main
```
⚠️ **IMPORTANTE:** Repo debe ser **PRIVADO**

### 3️⃣ Deploy en Railway (3 min)
1. https://railway.app → New Project → Deploy from GitHub
2. Conecta tu repo
3. Variables → RAW Editor → pega las 4 variables obligatorias
4. ✅ Bot desplegado

---

## 📋 VARIABLES OBLIGATORIAS

```env
BINGX_API_KEY=tu_api_key_aqui
BINGX_API_SECRET=tu_secret_aqui
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

**Variables opcionales** tienen valores por defecto optimizados.
Ver [railway_variables.txt](railway_variables.txt) para todas las opciones.

---

## 🎯 NOVEDADES v13 — 4 PINE SCRIPTS INTEGRADOS

### 🤖 1. UTBot (HPotter / Yo_adriiiiaan)
- **ATR Trailing Stop** calculado con Key Value × ATR
- Actúa como 2ª capa de protección tras TP1
- Genera punto **13/16** del score (señal buy/sell)
- Variables: `UTBOT_KEY_VALUE`, `UTBOT_ATR_PERIOD`

### 🌊 2. Instrument-Z (OscillateMatrix) — WaveTrend
- **TCI WaveTrend** oscillator con cruces en zonas OB/OS
- Trade Expiration: cierre automático tras N barras
- Mínimo profit para salidas por señal
- Genera punto **14/16** del score
- Variables: `WT_CHAN_LEN`, `WT_AVG_LEN`, `WT_OB`, `WT_OS`, `TRADE_EXPIRE_BARS`, `MIN_PROFIT_PCT`

### 📐 3. Bj Bot (3Commas framework)
- **R:R dinámico**: targets calculados desde swing pivots
- `TP1 = entrada + 50% del camino a TP2`
- `TP2 = entrada + RnR × riesgo`
- `SL  = swing_low/high − ATR × RISK_MULT`
- R:R trail trigger: activa trailing agresivo al llegar a X% del TP2
- Genera punto **15/16** del score (MA cross)
- Variables: `RNR`, `RISK_MULT`, `RR_EXIT`, `SWING_LB`

### 📊 4. BB+RSI (rouxam / DCA 3commas)
- **Bollinger Bands** con filtro RSI para evitar falsas señales
- Buy: precio bajo banda inferior + RSI < umbral
- Sell: precio sobre banda superior + RSI > umbral
- Integrado con squeeze filter (sin señales en contracción)
- Genera punto **16/16** del score
- Variables: `BB_PERIOD`, `BB_STD`, `BB_RSI_OB`

---

## 📊 SISTEMA DE SCORE — 16 PUNTOS

| # | Indicador | LONG | SHORT |
|---|-----------|------|-------|
| 1 | EMA trend | close > EMA48, EMA8 > EMA21 | close < EMA48, EMA8 < EMA21 |
| 2 | Oscilador | Cruza al alza | Cruza a la baja |
| 3 | HTF1 (15m) | Bias alcista | Bias bajista |
| 4 | HTF2 (1h) | Macro alcista | Macro bajista |
| 5 | ADX | DI+ > DI- | DI- > DI+ |
| 6 | RSI zona | 42-78 | 22-58 |
| 7 | Volumen | Buy vol + spike | Sell vol + spike |
| 8 | Vela | Bull candle > EMA21 | Bear candle < EMA21 |
| 9 | MACD | Bull / cross up | Bear / cross down |
| 10 | SMI momentum | Cross up / bull | Cross down / bear |
| 11 | SMI extremo | OS / salida OS | OB / salida OB |
| 12 | Patrón | Bull engulf / div | Bear engulf / div |
| 13 | **UTBot** | **Buy signal** | **Sell signal** |
| 14 | **WaveTrend** | **Cross up / OS** | **Cross down / OB** |
| 15 | **MA Cross** | **EMA8 cruza EMA21↑** | **EMA8 cruza EMA21↓** |
| 16 | **BB+RSI** | **Precio < BB lower** | **Precio > BB upper** |

**Score mínimo recomendado: 5/16**

---

## 📁 ESTRUCTURA DEL PROYECTO

```
saty-elite-v13/
├── bot.py                      ← Código principal v13 (verificado ✓)
├── requirements.txt            ← Dependencias Python
├── Procfile                    ← Config Railway
├── railway.toml                ← Config Railway
├── runtime.txt                 ← Python 3.11.9
│
├── QUICK_START.md              ← Inicio rápido (5 min)
├── RESUMEN_EJECUTIVO.md        ← Guía completa
├── RAILWAY_SETUP.md            ← Setup Railway detallado
├── railway_variables.txt       ← Variables copiar/pegar
├── ESTRATEGIAS_AVANZADAS.md    ← Configuraciones avanzadas
├── FAQ.md                      ← Preguntas frecuentes
└── verify.sh                   ← Script verificación
```

---

## 💰 COSTOS

| Servicio | Costo |
|----------|-------|
| **Railway** | $5/mes (Hobby Plan, recomendado) |
| **BingX** | 0.02-0.04% por trade (~$5-15/mes) |
| **Total** | ~$10-20/mes |

---

## 📊 PERFILES RECOMENDADOS

### 💚 Principiante ($50-200)
```
FIXED_USDT=5
MAX_OPEN_TRADES=8
MIN_SCORE=7
```

### 💙 Intermedio ($200-1000)
```
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=5
```

### 💜 Avanzado ($1000+)
```
FIXED_USDT=25
MAX_OPEN_TRADES=15
MIN_SCORE=5
```

Ver [ESTRATEGIAS_AVANZADAS.md](ESTRATEGIAS_AVANZADAS.md) para más perfiles.

---

## 📱 ALERTAS TELEGRAM — v13

| Alerta | Descripción |
|--------|-------------|
| ⚡ **ENTRADA** | Score /16 + SMI + WaveTrend + UTBot stop |
| 🟡 **TP1 + BE** | Primera ganancia, SL → break-even |
| 📐 **R:R TRAIL** | Trailing activado por Bj Bot (rrExit) |
| 🤖 **UTBOT STOP** | Cierre por ATR trailing UTBot |
| 🏁 **AGOTAMIENTO** | 9 señales de agotamiento (incluye WT + UTBot) |
| ⏳ **EXPIRADO** | Trade cerrado por TRADE_EXPIRE_BARS |
| 📊 **RESUMEN** | Cada 20 ciclos con top señales |
| 💓 **HEARTBEAT** | Cada hora con balance |

---

## ✅ CAMBIOS vs v12

| Característica | v12 | v13 |
|----------------|-----|-----|
| Score máximo | 12 | **16** |
| Indicadores | SMI + clásicos | **+ UTBot + WT + BB + R:R** |
| Targets TP/SL | ATR fijo | **Swing pivot + R:R ratio** |
| Trailing | 3 fases | **3 fases + R:R trigger + UTBot** |
| Agotamiento | 7 señales | **9 señales** |
| Trade expiry | No | **Sí (TRADE_EXPIRE_BARS)** |
| Min profit exit | No | **Sí (MIN_PROFIT_PCT)** |

---

## ⚠️ ADVERTENCIAS IMPORTANTES

- **DINERO REAL**: Empieza con $50-100
- **REPO PRIVADO**: Nunca hagas público el repositorio
- **SIN GARANTÍAS**: El trading conlleva riesgo de pérdida total
- **API KEYS**: NUNCA actives "Withdraw" en los permisos
- **MONITORIZA**: Revisa Telegram y logs diariamente

---

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║            ✅ TODO VERIFICADO Y LISTO                        ║
║                                                              ║
║   UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI            ║
║                                                              ║
║            🚀 ¡ÉXITO EN TU TRADING!                          ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```
