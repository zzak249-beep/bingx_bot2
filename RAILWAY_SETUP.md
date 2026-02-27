# 🚀 CONFIGURACIÓN COMPLETA RAILWAY - SATY ELITE v11

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
1. Ve a https://bingx.com
2. Inicia sesión → Perfil → **API Management**
3. Crear nueva API Key con permisos:
   - ✅ **Read** (leer balance y posiciones)
   - ✅ **Trade** (abrir/cerrar órdenes)
   - ❌ **Withdraw** (NO activar nunca)
4. Guarda ambas claves (API Key y Secret)

#### 2. TELEGRAM_BOT_TOKEN
1. Abre Telegram → busca **@BotFather**
2. Escribe `/newbot`
3. Sigue las instrucciones
4. Copia el TOKEN que te da (formato: `123456789:ABC...`)

#### 3. TELEGRAM_CHAT_ID
**Opción A - Chat personal:**
1. Busca **@userinfobot** en Telegram
2. Escríbele cualquier mensaje
3. Te responderá con tu Chat ID

**Opción B - Grupo (recomendado):**
1. Crea un grupo en Telegram
2. Añade tu bot al grupo
3. Busca **@userinfobot**
4. Añade @userinfobot al grupo
5. El bot te mostrará el ID del grupo (empieza con `-100...`)
6. Elimina @userinfobot del grupo

---

## ⚙️ VARIABLES OPCIONALES (Configuración Avanzada)

Estas variables tienen valores por defecto optimizados. Solo cámbialas si sabes lo que haces:

### 💰 Gestión de Capital
```
FIXED_USDT=8
# USDT por trade (default: 8)
# Ejemplo: Con $100, puedes tener ~12 trades de $8 cada uno

MAX_OPEN_TRADES=12
# Máximo de trades simultáneos (default: 12)
# Con $100 balance → 12 trades = $8 por trade
# Con $200 balance → 12 trades = $16 por trade (ajusta FIXED_USDT)
```

### 🎯 Filtros de Entrada
```
MIN_SCORE=4
# Score mínimo para entrar (0-12, default: 4)
# Menor = más trades pero menor calidad
# Mayor = menos trades pero mayor calidad

MIN_VOLUME_USDT=100000
# Volumen mínimo 24h en USDT (default: 100000 = 100K)
# 100K = incluye altcoins pequeños y nuevos
# 1000000 = solo pares con alto volumen

TOP_N_SYMBOLS=300
# Número de pares a escanear (default: 300)
# 300 = universo completo BingX
# 50 = solo los 50 con más volumen

MAX_SPREAD_PCT=1.0
# Spread máximo aceptado en % (default: 1.0)
# 1.0 = acepta pares menos líquidos
# 0.3 = solo pares muy líquidos (menos oportunidades)
```

### 🛡️ Protecciones
```
MAX_DRAWDOWN=15
# Circuit breaker en % (default: 15)
# Si pérdida total alcanza 15%, para de operar
# Ejemplo: Con $100, para si pierdes $15

DAILY_LOSS_LIMIT=8
# Pérdida diaria máxima en % (default: 8)
# Si en un día pierdes 8% del balance, para hasta mañana
# Ejemplo: Con $100, para si pierdes $8 en un día

COOLDOWN_MIN=20
# Minutos de pausa tras cerrar un trade en un par (default: 20)
# Evita entrar/salir repetidamente del mismo par
```

### 📊 Filtros Macro
```
BTC_FILTER=true
# Filtro macro BTC (default: true)
# true = Si BTC bajista → no abre LONGs | Si BTC alcista → no abre SHORTs
# false = ignora tendencia BTC (más trades, más riesgo)

BLACKLIST=
# Pares excluidos separados por coma (default: vacío)
# Ejemplo: BLACKLIST=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT
# Útil para excluir pares que no quieres tradear
```

### ⏱️ Timeframes
```
TIMEFRAME=5m
# Timeframe principal para análisis (default: 5m)

HTF1=15m
# Timeframe medio para confirmación (default: 15m)

HTF2=1h
# Timeframe macro para tendencia (default: 1h)

POLL_SECONDS=60
# Segundos entre cada ciclo de escaneo (default: 60)
# Menor = más frecuencia, más consumo de API
# Mayor = menos frecuencia, menos oportunidades
```

---

## 🎯 CONFIGURACIONES RECOMENDADAS POR CAPITAL

### Capital pequeño ($50 - $200)
```
FIXED_USDT=5
MAX_OPEN_TRADES=8
MIN_SCORE=5
MAX_DRAWDOWN=12
DAILY_LOSS_LIMIT=6
MIN_VOLUME_USDT=500000
TOP_N_SYMBOLS=100
MAX_SPREAD_PCT=0.5
BTC_FILTER=true
```

### Capital medio ($200 - $1000)
```
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=4
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=8
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=true
```

### Capital grande ($1000+)
```
FIXED_USDT=25
MAX_OPEN_TRADES=15
MIN_SCORE=4
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=10
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=false
```

---

## 📦 PASOS PARA CONFIGURAR EN RAILWAY

### 1. Subir a GitHub (REPO PRIVADO)
```bash
git init
git add .
git commit -m "SATY ELITE v11 - initial deploy"
git remote add origin https://github.com/TU_USUARIO/saty-elite-v11.git
git branch -M main
git push -u origin main
```

⚠️ **IMPORTANTE**: El repo DEBE ser **PRIVADO** porque contiene tus claves API

### 2. Crear proyecto en Railway
1. Ve a https://railway.app
2. Click en **New Project**
3. Selecciona **Deploy from GitHub repo**
4. Conecta tu cuenta GitHub
5. Selecciona el repo `saty-elite-v11`
6. Railway detectará automáticamente el `Procfile`

### 3. Añadir variables de entorno
1. En tu proyecto Railway → **Variables** (icono de llave)
2. Click en **+ New Variable**
3. Añade las 4 variables OBLIGATORIAS:
   ```
   BINGX_API_KEY
   BINGX_API_SECRET
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
   ```
4. (Opcional) Añade las variables de configuración que quieras cambiar

### 4. Verificar deployment
1. Railway → **Deployments** → ver logs en tiempo real
2. Deberías ver:
   ```
   SATY ELITE v11 — REAL MONEY · 12 TRADES · 24/7
   Exchange conectado ✓
   Modo cuenta: HEDGE
   Balance: $XXX.XX USDT
   ```
3. En Telegram recibirás mensaje de arranque

---

## 🔧 TROUBLESHOOTING

### Error: "DRY-RUN: sin claves API"
❌ No has añadido las variables BINGX_API_KEY o BINGX_API_SECRET
✅ Ve a Railway → Variables → añade ambas claves

### Error: "No se pudo conectar al exchange"
❌ Claves incorrectas o sin permisos
✅ Verifica en BingX que la API Key tenga permisos Read + Trade

### No recibo alertas en Telegram
❌ TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID incorrectos
✅ Verifica el token del bot y tu Chat ID con @userinfobot

### Bot se reinicia constantemente
❌ Error en el código o balance insuficiente
✅ Revisa los logs en Railway → Deployments

### "Circuit breaker activated"
✅ Normal - el bot se detiene si pérdida > MAX_DRAWDOWN
✅ Reinicia el servicio en Railway o espera a recuperar

---

## 📊 COSTOS RAILWAY

- **Free Tier**: ~500 horas/mes (suficiente para probar)
- **Hobby Plan**: $5/mes (recomendado, sin límite de horas)

El bot consume muy pocos recursos, el plan Hobby es suficiente.

---

## ⚠️ ADVERTENCIAS FINALES

1. **DINERO REAL**: Este bot opera con fondos reales
2. **EMPIEZA PEQUEÑO**: Prueba con $50-$100 primero
3. **MONITORIZA**: Revisa logs y Telegram diariamente
4. **SIN GARANTÍAS**: El trading conlleva riesgo de pérdida
5. **REPO PRIVADO**: Nunca hagas público el repo con tus claves

---

## 🔄 ACTUALIZAR EL BOT

Para actualizar el código:
```bash
git add .
git commit -m "update bot"
git push
```

Railway redesplegará automáticamente en ~2 minutos.

---

## 📱 COMANDOS ÚTILES

Una vez funcionando, recibirás en Telegram:
- ⚡ **Entrada**: Cada vez que abre un trade
- 🎯 **TP1**: Cuando alcanza 50% ganancia
- 🏆 **TP2**: Cuando alcanza ganancia final
- 🛑 **Stop Loss**: Cuando cierra por pérdida
- 📊 **Resumen**: Cada 20 ciclos (~20min)
- 💓 **Heartbeat**: Cada hora (balance actualizado)

---

🚀 **¡Listo! Con esto tu bot debería funcionar perfectamente en Railway.**
