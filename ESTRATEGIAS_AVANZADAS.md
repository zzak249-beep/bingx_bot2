# 🎯 ESTRATEGIAS Y CONFIGURACIONES AVANZADAS — v13

> **Score máximo: 16 puntos** (UTBot + WaveTrend + Bj Bot R:R + BB+RSI + SMI + clásicos)
> El MIN_SCORE funciona sobre 16. Ajusta en consecuencia.

---

## 📊 PERFILES DE TRADING

### 🛡️ PERFIL: Conservador (Capital $50-$200)
**Objetivo**: Protección de capital, señales de muy alta calidad

```env
FIXED_USDT=5
MAX_OPEN_TRADES=6
MIN_SCORE=8
MAX_DRAWDOWN=10
DAILY_LOSS_LIMIT=5
MIN_VOLUME_USDT=1000000
TOP_N_SYMBOLS=50
MAX_SPREAD_PCT=0.3
BTC_FILTER=true
COOLDOWN_MIN=30
RNR=2.0
RISK_MULT=1.2
UTBOT_KEY_VALUE=14
TRADE_EXPIRE_BARS=0
```

**Características:**
- Score 8/16 = solo las señales donde confluyen todos los indicadores
- Solo pares >1M vol = máxima liquidez
- UTBot sensibilidad baja (14) = menos ruido
- R:R 2:1 con buffer amplio en SL
- **Win rate esperado**: 55-65%
- **Trades diarios**: 1-4

---

### ⚖️ PERFIL: Balanceado (Capital $200-$1000)
**Objetivo**: Balance entre calidad y frecuencia

```env
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=5
MAX_DRAWDOWN=15
DAILY_LOSS_LIMIT=8
MIN_VOLUME_USDT=100000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=1.0
BTC_FILTER=true
COOLDOWN_MIN=20
RNR=2.0
RISK_MULT=1.0
UTBOT_KEY_VALUE=10
RR_EXIT=0.5
```

**Características:**
- Score 5/16 = buen balance señales/calidad
- Universo completo (300 pares)
- UTBot sensibilidad media (10)
- R:R trail activo desde 50% del camino a TP2
- **Win rate esperado**: 48-58%
- **Trades diarios**: 6-14

---

### ⚡ PERFIL: Agresivo (Capital $1000+)
**Objetivo**: Máximo crecimiento, acepta más riesgo

```env
FIXED_USDT=30
MAX_OPEN_TRADES=18
MIN_SCORE=4
MAX_DRAWDOWN=20
DAILY_LOSS_LIMIT=12
MIN_VOLUME_USDT=50000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=2.0
BTC_FILTER=false
COOLDOWN_MIN=10
RNR=2.5
RISK_MULT=0.8
UTBOT_KEY_VALUE=7
RR_EXIT=0.3
```

**Características:**
- Score 4/16 = señales más frecuentes
- Sin filtro BTC = opera en ambas direcciones siempre
- UTBot muy sensible (7) = reacciona más rápido
- R:R trail desde 30% del TP2
- **Win rate esperado**: 42-52%
- **Trades diarios**: 20-40

---

### 🎯 PERFIL: Scalper (Alta Frecuencia)
**Objetivo**: Muchos trades cortos con expiración automática

```env
FIXED_USDT=8
MAX_OPEN_TRADES=15
MIN_SCORE=5
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
RNR=1.5
RISK_MULT=0.7
UTBOT_KEY_VALUE=7
UTBOT_ATR_PERIOD=7
WT_CHAN_LEN=7
WT_AVG_LEN=9
TRADE_EXPIRE_BARS=60
RR_EXIT=0.25
```

**Características:**
- Timeframe 1m, scan cada 30s
- Trade expira a 60 barras (1 hora en 1m)
- UTBot y WT más reactivos
- R:R corto (1.5:1) con trail temprano
- **Win rate esperado**: 45-52%
- **Trades diarios**: 30-70

---

### 🌙 PERFIL: Swing Trader
**Objetivo**: Trades de días, alta calidad

```env
FIXED_USDT=20
MAX_OPEN_TRADES=8
MIN_SCORE=9
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
RNR=3.0
RISK_MULT=1.5
UTBOT_KEY_VALUE=14
UTBOT_ATR_PERIOD=14
WT_CHAN_LEN=9
WT_AVG_LEN=12
WT_OB=53
WT_OS=-53
TRADE_EXPIRE_BARS=0
SMI_OB=45
SMI_OS=-45
```

**Características:**
- Score 9/16 = señales de máxima confluencia
- R:R 3:1 con buffer amplio
- Solo top 50 pares > 5M vol
- Scan cada 5 min
- **Win rate esperado**: 55-68%
- **Trades diarios**: 0-3

---

## 🎨 ESTRATEGIAS ESPECIALES

### 🌊 ESTRATEGIA: UTBot Puro (señal primaria)
**Objetivo**: Usar UTBot como señal principal, rest como filtros

```env
MIN_SCORE=5
UTBOT_KEY_VALUE=8
UTBOT_ATR_PERIOD=10
WT_OB=80
WT_OS=-80
SMI_OB=60
SMI_OS=-60
BB_RSI_OB=75
```
Sube los umbrales de WT, SMI y BB para que sean muy difíciles de activar → UTBot domina

---

### 🌊 ESTRATEGIA: WaveTrend Puro
**Objetivo**: WaveTrend como señal principal

```env
MIN_SCORE=5
WT_CHAN_LEN=7
WT_AVG_LEN=10
WT_OB=53
WT_OS=-53
UTBOT_KEY_VALUE=20
SMI_OB=60
SMI_OS=-60
```
UTBot con key muy alta = casi nunca señal → WaveTrend domina en punto 14

---

### 📐 ESTRATEGIA: R:R Máximo
**Objetivo**: Solo trades con R:R muy favorable

```env
RNR=4.0
RISK_MULT=0.8
RR_EXIT=0.7
MIN_SCORE=7
COOLDOWN_MIN=30
```
SL más cercano, TP2 muy lejano. Menos trades pero con excelente ratio.

---

### 🔔 ESTRATEGIA: Solo Altcoins Nuevos
**Objetivo**: Capturar pumps de tokens recién listados

```env
FIXED_USDT=6
MAX_OPEN_TRADES=10
MIN_SCORE=5
MIN_VOLUME_USDT=50000
TOP_N_SYMBOLS=300
MAX_SPREAD_PCT=2.0
BTC_FILTER=false
UTBOT_KEY_VALUE=7
WT_OB=50
WT_OS=-50
BLACKLIST=BTC/USDT:USDT,ETH/USDT:USDT,BNB/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT
```

---

### 🏔️ ESTRATEGIA: Solo Top 10 Coins
**Objetivo**: Máxima liquidez y estabilidad

```env
FIXED_USDT=15
MAX_OPEN_TRADES=8
MIN_SCORE=7
MIN_VOLUME_USDT=50000000
TOP_N_SYMBOLS=10
MAX_SPREAD_PCT=0.1
BTC_FILTER=true
COOLDOWN_MIN=40
UTBOT_KEY_VALUE=12
RNR=2.5
```

---

### ⏳ ESTRATEGIA: Trade Expiration (Instrument-Z style)
**Objetivo**: Salir de trades estancados automáticamente

```env
TRADE_EXPIRE_BARS=100
MIN_PROFIT_PCT=0.3
```
- En 5m: 100 barras ≈ 8.3 horas máximo por trade
- En 1h: 100 barras ≈ 4 días máximo
- `MIN_PROFIT_PCT=0.3` = solo cierra por señal si hay ≥0.3% de ganancia

---

## 📈 AJUSTES POR OBJETIVOS

### 🎯 Objetivo: Máxima Tasa de Acierto
```env
MIN_SCORE=9
MIN_VOLUME_USDT=5000000
TOP_N_SYMBOLS=30
MAX_SPREAD_PCT=0.2
COOLDOWN_MIN=60
UTBOT_KEY_VALUE=14
RNR=2.0
```

### 💰 Objetivo: Máximo Profit Factor
```env
MIN_SCORE=7
MAX_DRAWDOWN=12
DAILY_LOSS_LIMIT=6
MIN_VOLUME_USDT=1000000
RNR=3.0
RISK_MULT=1.0
MIN_PROFIT_PCT=0.5
```

### 🚀 Objetivo: Máximo Retorno Mensual
```env
FIXED_USDT=15
MAX_OPEN_TRADES=20
MIN_SCORE=4
BTC_FILTER=false
MIN_VOLUME_USDT=50000
COOLDOWN_MIN=5
UTBOT_KEY_VALUE=7
RNR=2.0
RR_EXIT=0.25
```

### 🛡️ Objetivo: Mínimo Drawdown
```env
MAX_DRAWDOWN=8
DAILY_LOSS_LIMIT=4
MIN_SCORE=9
MAX_OPEN_TRADES=6
FIXED_USDT=5
UTBOT_KEY_VALUE=14
RNR=1.5
RISK_MULT=1.5
```

---

## 🧪 OPTIMIZACIÓN POR PRUEBA Y ERROR

### Metodología v13:

1. **Semana 1-2**: Perfil Balanceado con MIN_SCORE=7
   - Observar qué puntos del score se activan más
   - Notar si UTBot (p.13) o WT (p.14) son frecuentes

2. **Semana 3**: Ajustar UTBot
   - Si poca señal UTBot → Bajar `UTBOT_KEY_VALUE` de 10 a 8
   - Si demasiado ruido UTBot → Subir a 14

3. **Semana 4**: Ajustar WaveTrend
   - Si WT señala tarde → Bajar `WT_OB`/`WT_OS` de 60 a 50
   - Si WT señala demasiado → Subir a 70

4. **Semana 5**: Ajustar R:R
   - Si TP2 rara vez se alcanza → Bajar `RNR` de 2.0 a 1.5
   - Si trades se cierran muy rápido → Subir `RR_EXIT` de 0.5 a 0.7

5. **Mes 2**: Ajustar MIN_SCORE
   - Win rate > 60% con 5 trades/día → Bajar MIN_SCORE a 4-5 (más trades)
   - Win rate < 40% → Subir MIN_SCORE a 7-8 (más calidad)

---

## 📊 INDICADORES DE ÉXITO v13

### Métricas clave en Telegram:

✅ **Win Rate > 45%** = Configuración saludable
✅ **Profit Factor > 1.5** = Ganancias 50% mayores que pérdidas
✅ **Drawdown < 10%** = Capital bien protegido
✅ **UTBot activo en >30% señales** = Confirma tendencias reales
✅ **WT activo en >25% señales** = Oscillator funcionando

⚠️ **Señales de alerta:**
- Win rate < 35% → Subir MIN_SCORE en +2
- 0 trades en 8h → Bajar MIN_SCORE en -1 o revisar BTC_FILTER
- UTBot cierra muchos trades → Subir UTBOT_KEY_VALUE
- Trades expirados muy frecuentes → Subir TRADE_EXPIRE_BARS o ponerlo en 0

---

## 📋 GUÍA DE VARIABLES NUEVAS

| Variable | Efecto de subir | Efecto de bajar |
|----------|----------------|----------------|
| `UTBOT_KEY_VALUE` | Menos señales, más tardías | Más señales, más pronto |
| `WT_OB` / `WT_OS` | Zona OB/OS más difícil de activar | Señales más frecuentes |
| `RNR` | TP2 más lejos, mayor beneficio potencial | TP2 más cercano, más rápido |
| `RISK_MULT` | SL más lejos del swing (más espacio) | SL más ajustado |
| `RR_EXIT` | Trail se activa más tarde (más recorrido) | Trail se activa antes |
| `BB_STD` | Bandas más anchas, menos señales BB | Más señales BB |
| `TRADE_EXPIRE_BARS` | Trades duran más antes de expirar | Expiración más agresiva |

---

## ⚠️ ADVERTENCIAS

- **NUNCA cambies todas las variables a la vez** — cambia 1-2, observa 3-5 días
- **MIN_SCORE sobre 16** — considera que 16 = señal perfecta (prácticamente imposible)
  - Rango útil: 4-10 dependiendo del perfil
- **UTBot y WT pueden conflictuar** — si ambos dan señales opuestas, el score neutro filtra
- **RNR alto con capital pequeño** — el SL quedará muy lejos, cuida el slippage
- **TRADE_EXPIRE_BARS en 1h** — 72 barras = 3 días, cuidado en mercados lentos

---

🎯 **Empieza conservador (MIN_SCORE=7-8), ajusta progresivamente hacia abajo conforme ganas confianza en los indicadores.**
