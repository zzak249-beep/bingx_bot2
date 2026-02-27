# 🎯 ESTRATEGIAS Y CONFIGURACIONES AVANZADAS

## 📊 PERFILES DE TRADING

### 🛡️ PERFIL: Conservador (Capital $50-$200)
**Objetivo**: Protección de capital, crecimiento lento y constante

```env
FIXED_USDT=5
MAX_OPEN_TRADES=6
MIN_SCORE=6
MAX_DRAWDOWN=10
DAILY_LOSS_LIMIT=5
MIN_VOLUME_USDT=1000000
TOP_N_SYMBOLS=50
MAX_SPREAD_PCT=0.3
BTC_FILTER=true
COOLDOWN_MIN=30
```

**Características:**
- Solo 6 trades simultáneos
- Score muy alto (6+) = menos señales, más calidad
- Solo pares con volumen alto (>1M)
- Spread bajo = pares muy líquidos
- Cooldown largo (30min) = menos frecuencia
- **Win rate esperado**: 50-60%
- **Trades diarios**: 2-5

---

### ⚖️ PERFIL: Balanceado (Capital $200-$1000)
**Objetivo**: Balance entre riesgo y retorno

```env
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=4
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=8
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=true
COOLDOWN_MIN=20
```

**Características:**
- 12 trades simultáneos
- Score moderado (4+) = buena cantidad de señales
- Incluye altcoins pequeños (>100K vol)
- Spread normal
- **Win rate esperado**: 45-55%
- **Trades diarios**: 8-15

---

### ⚡ PERFIL: Agresivo (Capital $1000+)
**Objetivo**: Máximo crecimiento, acepta más riesgo

```env
FIXED_USDT=30
MAX_OPEN_TRADES=18
MIN_SCORE=3
MAX_DRAWDOWN=20
DAILY_LOSS_LIMIT=12
MIN_VOLUME_USDT=50000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=2.0
BTC_FILTER=false
COOLDOWN_MIN=10
```

**Características:**
- 18 trades simultáneos
- Score bajo (3+) = muchas señales
- Incluye pares muy pequeños (>50K vol)
- Sin filtro BTC = opera en ambas direcciones
- Cooldown corto = alta frecuencia
- **Win rate esperado**: 40-50%
- **Trades diarios**: 20-40

---

### 🎯 PERFIL: Scalper (Alta Frecuencia)
**Objetivo**: Muchos trades pequeños

```env
FIXED_USDT=8
MAX_OPEN_TRADES=15
MIN_SCORE=3
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=10
MIN_VOLUME_USDT=500000
TOP_N_SYMBOLS=200
MAX_SPREAD_PCT=0.5
BTC_FILTER=false
COOLDOWN_MIN=5
TIMEFRAME=1m
HTF1=5m
HTF2=15m
POLL_SECONDS=30
```

**Características:**
- Timeframe muy corto (1m)
- Cooldown muy corto (5min)
- Scan cada 30 segundos
- Sin filtro BTC
- **Win rate esperado**: 45-50%
- **Trades diarios**: 30-60

---

### 🌙 PERFIL: Swing Trader (Posiciones largas)
**Objetivo**: Trades de mayor duración, menor frecuencia

```env
FIXED_USDT=20
MAX_OPEN_TRADES=8
MIN_SCORE=7
MAX_DRAWDOWN=18
DAILY_LOSS_LIMIT=12
MIN_VOLUME_USDT=5000000
TOP_N_SYMBOLS=50
MAX_SPREAD_PCT=0.2
BTC_FILTER=true
COOLDOWN_MIN=60
TIMEFRAME=1h
HTF1=4h
HTF2=1d
POLL_SECONDS=300
```

**Características:**
- Timeframes largos (1h base)
- Score muy alto (7+)
- Solo top 50 pares
- Cooldown largo (1 hora)
- Scan cada 5 minutos
- **Win rate esperado**: 55-65%
- **Trades diarios**: 1-3

---

## 🎨 ESTRATEGIAS ESPECIALES

### 🌊 ESTRATEGIA: Solo Altcoins Nuevos
**Objetivo**: Capturar pumps de tokens recién listados

```env
FIXED_USDT=6
MAX_OPEN_TRADES=10
MIN_SCORE=4
MIN_VOLUME_USDT=50000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=2.0
BTC_FILTER=false
BLACKLIST=BTC/USDT:USDT,ETH/USDT:USDT,BNB/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT
```

**Características:**
- Excluye las top coins vía BLACKLIST
- Acepta volumen muy bajo (altcoins nuevos)
- Spread alto (pares menos líquidos)
- Sin filtro BTC
- **Más volátil, mayor riesgo/retorno**

---

### 🏔️ ESTRATEGIA: Solo Top 10 Coins
**Objetivo**: Máxima liquidez y estabilidad

```env
FIXED_USDT=15
MAX_OPEN_TRADES=8
MIN_SCORE=5
MIN_VOLUME_USDT=50000000
TOP_N_SYMBOLS=10
MAX_SPREAD_PCT=0.1
BTC_FILTER=true
COOLDOWN_MIN=40
```

**Características:**
- Solo pares con >50M volumen (BTC, ETH, etc)
- Spread muy bajo
- Cooldown largo
- **Menor volatilidad, más predecible**

---

### 🎲 ESTRATEGIA: Bull Market Only
**Objetivo**: Operar solo LONGs en mercado alcista

```env
FIXED_USDT=12
MAX_OPEN_TRADES=15
MIN_SCORE=4
BTC_FILTER=true
MIN_VOLUME_USDT=200000
TOP_N_SYMBOLS=300
```

**Nota:** BTC_FILTER=true bloqueará SHORTs cuando BTC esté alcista
**Mejor momento:** Usar cuando BTC está en tendencia alcista clara

---

### 🐻 ESTRATEGIA: Bear Market Only
**Objetivo**: Operar solo SHORTs en mercado bajista

```env
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=4
BTC_FILTER=true
MIN_VOLUME_USDT=200000
TOP_N_SYMBOLS=300
```

**Nota:** BTC_FILTER=true bloqueará LONGs cuando BTC esté bajista
**Mejor momento:** Usar cuando BTC está en tendencia bajista clara

---

### 🌐 ESTRATEGIA: All-Weather (Sin Filtros)
**Objetivo**: Operar en cualquier condición de mercado

```env
FIXED_USDT=10
MAX_OPEN_TRADES=15
MIN_SCORE=4
BTC_FILTER=false
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
```

**Características:**
- Sin filtro BTC = opera LONGs y SHORTs siempre
- Universo amplio
- **Mayor cantidad de trades**

---

## 📈 AJUSTES POR OBJETIVOS

### 🎯 Objetivo: Máxima Tasa de Acierto
Prioridad: Ganar más del 60% de los trades

```env
MIN_SCORE=7
MIN_VOLUME_USDT=5000000
TOP_N_SYMBOLS=30
MAX_SPREAD_PCT=0.2
COOLDOWN_MIN=60
```

**Trade-off:** Menos trades totales

---

### 💰 Objetivo: Máximo Profit Factor
Prioridad: Ganancias >> Pérdidas

```env
MIN_SCORE=6
MAX_DRAWDOWN=12
DAILY_LOSS_LIMIT=6
MIN_VOLUME_USDT=1000000
```

**Trade-off:** Growth más lento

---

### 🚀 Objetivo: Máximo Retorno Mensual
Prioridad: Crecimiento agresivo

```env
FIXED_USDT=15
MAX_OPEN_TRADES=20
MIN_SCORE=3
BTC_FILTER=false
MIN_VOLUME_USDT=50000
COOLDOWN_MIN=5
```

**Trade-off:** Mayor riesgo y drawdown

---

### 🛡️ Objetivo: Mínimo Drawdown
Prioridad: Protección de capital

```env
MAX_DRAWDOWN=8
DAILY_LOSS_LIMIT=4
MIN_SCORE=7
MAX_OPEN_TRADES=6
FIXED_USDT=5
```

**Trade-off:** Crecimiento muy lento

---

## 🧪 OPTIMIZACIÓN POR PRUEBA Y ERROR

### Metodología:

1. **Semana 1-2**: Empezar con configuración Balanceada
   - Observar win rate
   - Observar profit factor
   - Anotar qué pares funcionan mejor

2. **Semana 3**: Ajustar MIN_SCORE
   - Si win rate < 40% → Subir MIN_SCORE a 5 o 6
   - Si win rate > 60% pero pocos trades → Bajar MIN_SCORE a 3

3. **Semana 4**: Ajustar MIN_VOLUME y TOP_N
   - Si muchos trades fallan por liquidez → Subir MIN_VOLUME
   - Si hay pocas señales → Aumentar TOP_N_SYMBOLS

4. **Semana 5**: Ajustar protecciones
   - Si drawdown cerca de límite → Reducir MAX_DRAWDOWN
   - Si muchos días con pérdidas → Reducir DAILY_LOSS_LIMIT

5. **Mes 2**: Optimizar capital
   - Si win rate estable > 50% → Aumentar FIXED_USDT gradualmente
   - Si drawdown controlado < 10% → Aumentar MAX_OPEN_TRADES

---

## 📊 INDICADORES DE ÉXITO

### Métricas a monitorizar en Telegram:

✅ **Win Rate > 45%** = Configuración saludable
✅ **Profit Factor > 1.5** = Ganancias 50% mayores que pérdidas
✅ **Drawdown < 10%** = Capital bien protegido
✅ **Trades/día > 5** = Suficiente actividad
✅ **Avg Win > Avg Loss** = Buena gestión de exits

⚠️ **Señales de alerta:**
- Win rate < 35% → Revisar MIN_SCORE (aumentar)
- Profit factor < 1.0 → Revisar estrategia de exits
- Drawdown > 15% → Reducir FIXED_USDT o MAX_OPEN_TRADES
- 0 trades en 6 horas → Revisar MIN_SCORE (reducir)

---

## 🔄 CAMBIAR DE ESTRATEGIA EN RAILWAY

1. Railway → Variables → RAW Editor
2. Cambia las variables que necesites
3. Click "Update Variables"
4. Railway redesplegará el bot en ~2 min
5. Verifica en logs que los nuevos valores están activos

---

## ⚠️ ADVERTENCIAS

- **NUNCA cambies todas las variables a la vez**
  → Cambia 1-2 variables, observa 3-5 días, ajusta

- **No te vuelvas agresivo después de una racha ganadora**
  → La volatilidad volverá

- **No seas excesivamente conservador después de pérdidas**
  → Las pérdidas son parte del trading

- **Documenta tus cambios**
  → Anota fecha + variables + resultado en una hoja

---

**Recuerda:** El mejor perfil es el que se adapta a tu:
- Capital disponible
- Tolerancia al riesgo
- Tiempo para monitorear
- Objetivos de retorno

🎯 **Empieza conservador, ajusta progresivamente**
