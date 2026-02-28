# 🚀 CONFIGURACIÓN COMPLETA RAILWAY — SATY ELITE v13

## ✅ VARIABLES OBLIGATORIAS (Railway → Variables)

Estas 4 variables son **OBLIGATORIAS** para que el bot funcione:

```
BINGX_API_KEY=tu_api_key_aqui
BINGX_API_SECRET=tu_api_secret_aqui
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=-1001234567890
```

### 📝 Cómo obtener cada variable:

#### 1. BINGX_API_KEY y BINGX_API_SECRET
1. Ve a https://bingx.com → Login → Perfil → **API Management**
2. Crear nueva API Key con permisos:
   - ✅ **Read** (leer balance y posiciones)
   - ✅ **Trade** (abrir/cerrar órdenes)
   - ❌ **Withdraw** (NO activar nunca)
3. Guarda API Key y Secret

#### 2. TELEGRAM_BOT_TOKEN
1. Telegram → busca **@BotFather** → `/newbot` → copia el TOKEN

#### 3. TELEGRAM_CHAT_ID
- **Chat personal**: Busca **@userinfobot**, escríbele y copia tu ID
- **Grupo** (recomendado): Crea grupo → añade tu bot + @userinfobot → copia el ID (empieza con `-100...`)

---

## ⚙️ VARIABLES DE CAPITAL Y TRADING

```
FIXED_USDT=8         # USDT por trade (default: 8)
MAX_OPEN_TRADES=12   # Máximo trades simultáneos (default: 12)
MIN_SCORE=5          # Score mínimo 0-16 (default: 5)
```

---

## 🎯 VARIABLES DE FILTROS

```
MIN_VOLUME_USDT=100000  # Volumen mínimo 24h (default: 100K)
TOP_N_SYMBOLS=300       # Pares a escanear (default: 300)
MAX_SPREAD_PCT=1.0      # Spread máximo % (default: 1.0)
BTC_FILTER=true         # Filtro tendencia BTC (default: true)
BLACKLIST=              # Pares excluidos, separados por coma
```

---

## 🛡️ VARIABLES DE PROTECCIÓN

```
MAX_DRAWDOWN=15         # Circuit breaker % total (default: 15)
DAILY_LOSS_LIMIT=8      # Pérdida diaria máxima % (default: 8)
COOLDOWN_MIN=20         # Pausa post-cierre en minutos (default: 20)
```

---

## ⏱️ TIMEFRAMES

```
TIMEFRAME=5m            # Timeframe principal (default: 5m)
HTF1=15m                # Confirmación media (default: 15m)
HTF2=1h                 # Tendencia macro (default: 1h)
POLL_SECONDS=60         # Segundos entre ciclos (default: 60)
```

---

## 📊 VARIABLES NUEVAS v13 — INDICADORES

### 🤖 UTBot (HPotter — ATR Trailing Stop)
```
UTBOT_KEY_VALUE=10     # Sensibilidad (menor = más señales) [7-20]
UTBOT_ATR_PERIOD=10    # Periodo ATR interno del UTBot [5-14]
```
- Score punto 13/16
- Actúa como trailing stop adicional en profit

### 🌊 WaveTrend (Instrument-Z)
```
WT_CHAN_LEN=9          # Channel Length EMA (default: 9)
WT_AVG_LEN=12          # Average Length EMA (default: 12)
WT_OB=60               # Nivel sobrecompra (default: 60)
WT_OS=-60              # Nivel sobreventa (default: -60)
TRADE_EXPIRE_BARS=0    # Cerrar trade tras N barras (0=OFF)
MIN_PROFIT_PCT=0.0     # Profit mínimo % para salir por señal
```
- Score punto 14/16
- `TRADE_EXPIRE_BARS=100` con timeframe 5m ≈ cierra en ~8 horas

### 📐 Bj Bot — Risk to Reward
```
RNR=2.0                # Ratio Reward:Risk (TP2 = RNR × SL-dist)
RISK_MULT=1.0          # Multiplicador ATR buffer en SL [0.5-2.0]
RR_EXIT=0.5            # % del TP2 para activar trailing (0=inmediato)
SWING_LB=10            # Lookback swing pivots en barras [5-20]
```
- Score punto 15/16 (MA cross EMA8/EMA21)
- Reemplaza los targets fijos de versiones anteriores

### 📊 Bollinger Bands + RSI
```
BB_PERIOD=20           # Periodo BB (default: 20)
BB_STD=2.0             # Desviaciones estándar (default: 2.0)
BB_RSI_OB=65           # RSI máximo para señal LONG (default: 65)
```
- Score punto 16/16
- Sin señal en squeeze (BB dentro de Keltner)

### 🔷 SMI (ya existente)
```
SMI_K_LEN=10           SMI_D_LEN=3
SMI_EMA_LEN=10         SMI_SMOOTH=5
SMI_OB=40              SMI_OS=-40
```
- Puntos 10 y 11 del score

---

## 🎯 CONFIGURACIONES RECOMENDADAS POR CAPITAL

### Capital pequeño ($50-$200) — Conservador
```
FIXED_USDT=5
MAX_OPEN_TRADES=8
MIN_SCORE=8
MAX_DRAWDOWN=12
DAILY_LOSS_LIMIT=6
MIN_VOLUME_USDT=500000
TOP_N_SYMBOLS=100
MAX_SPREAD_PCT=0.5
BTC_FILTER=true
RNR=2.0
UTBOT_KEY_VALUE=14
```

### Capital medio ($200-$1000) — Balanceado
```
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=5
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=8
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=true
RNR=2.0
UTBOT_KEY_VALUE=10
```

### Capital grande ($1000+) — Agresivo
```
FIXED_USDT=25
MAX_OPEN_TRADES=15
MIN_SCORE=5
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=10
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=false
RNR=2.5
UTBOT_KEY_VALUE=8
```

---

## 📦 PASOS PARA CONFIGURAR EN RAILWAY

### 1. Subir a GitHub (REPO PRIVADO)
```bash
git init
git add .
git commit -m "SATY ELITE v13 - initial deploy"
git remote add origin https://github.com/TU_USUARIO/saty-elite-v13.git
git branch -M main
git push -u origin main
```
⚠️ El repo DEBE ser **PRIVADO**

### 2. Crear proyecto en Railway
1. https://railway.app → **New Project** → **Deploy from GitHub repo**
2. Conecta GitHub → selecciona el repo
3. Railway detectará `Procfile` automáticamente

### 3. Añadir variables de entorno
1. Railway → **Variables** → **RAW Editor**
2. Pega el contenido de `railway_variables.txt` con tus datos
3. Click **Update Variables**

### 4. Verificar deployment
```
SATY ELITE v13 — FULL STRATEGY EDITION · 24/7
UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI
Exchange conectado ✓
Modo cuenta: HEDGE
Balance: $XXX.XX USDT
━━━ SCAN #1 ... | 300 pares | 0/12 trades ━━━
```

En Telegram recibirás el mensaje de arranque con todos los parámetros activos.

---

## 🔧 TROUBLESHOOTING

| Error | Causa | Solución |
|-------|-------|----------|
| `DRY-RUN: sin claves API` | Variables faltantes | Añade BINGX_API_KEY y BINGX_API_SECRET |
| `No se pudo conectar` | Claves incorrectas | Verifica permisos Read + Trade en BingX |
| Sin alertas Telegram | TOKEN o CHAT_ID mal | Verifica con @BotFather y @userinfobot |
| `Circuit breaker` | Pérdida > MAX_DRAWDOWN | Normal. Reinicia en Railway o reduce FIXED_USDT |
| 0 trades en 6h | MIN_SCORE muy alto | Reduce MIN_SCORE de 8 a 6 o 5 |
| `Insufficient balance` | Capital insuficiente | Reduce FIXED_USDT o MAX_OPEN_TRADES |

---

## 📱 ALERTAS TELEGRAM v13

| Icono | Alerta | Descripción |
|-------|--------|-------------|
| 🟢/🔴 | **ENTRADA** | Score/16, SMI, WaveTrend, UTBot stop, R:R targets |
| 🟡 | **TP1 + BE** | Primera ganancia, SL movido a break-even |
| 📐 | **R:R TRAIL** | Trailing agresivo activado (Bj Bot rrExit) |
| 🤖 | **UTBOT STOP** | Cierre por ATR trailing del UTBot |
| 🏁 | **AGOTAMIENTO** | 9 señales (MACD+ADX+Vol+Div+OSC+RSI+SMI+WT+UTBot) |
| ⏳ | **EXPIRADO** | Trade cerrado por TRADE_EXPIRE_BARS |
| ✅/❌ | **CERRADO** | Resumen con PnL, barras, estadísticas |
| 📡 | **RESUMEN** | Cada 20 ciclos: top señales + posiciones |
| 💓 | **HEARTBEAT** | Cada hora: balance + trades abiertos |
| 🔔 | **RSI EXTREMO** | Alerta RSI + SMI + WaveTrend en zonas extremas |

---

## 📊 COSTOS RAILWAY

- **Free Tier**: ~500 horas/mes (suficiente para probar)
- **Hobby Plan**: $5/mes (recomendado, sin límite de horas)

---

## 🔄 ACTUALIZAR EL BOT

```bash
git add .
git commit -m "v13: descripción del cambio"
git push
# Railway redesplegará automáticamente en ~2 minutos
```

---

## ⚠️ ADVERTENCIAS FINALES

1. **DINERO REAL**: Opera con fondos reales, empieza con $50-100
2. **EMPIEZA CON MIN_SCORE ALTO**: Usa 7-8 las primeras semanas
3. **REPO PRIVADO**: Nunca hagas público el repo
4. **SIN GARANTÍAS**: El trading conlleva riesgo de pérdida total
5. **MONITORIZA**: Revisa logs y Telegram diariamente
6. **AJUSTA GRADUALMENTE**: Cambia 1-2 variables, observa 3-5 días
