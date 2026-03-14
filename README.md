# Bellsz Bot v1.0 — Liquidez Lateral [Bellsz]

Bot de trading basado en la estrategia **Liquidez Lateral [Bellsz]** para BingX Perpetual Futures.

---

## Archivos del bot

| Archivo | Descripción |
|---|---|
| `config.py` | Configuración y variables de entorno |
| `analizar_bellsz.py` | **Motor de señales Bellsz** (3 capas + confluencias) |
| `main_bellsz.py` | Loop principal 24/7 |
| `backtest_bellsz.py` | Backtest con datos reales de Binance |
| `exchange.py` | API BingX (copiar del bot original) |
| `memoria.py` | Compounding y aprendizaje (copiar del bot original) |
| `scanner_pares.py` | Scanner de pares (copiar del bot original) |
| `metaclaw.py` | Validación IA (copiar del bot original, opcional) |
| `optimizador.py` | Auto-optimización (copiar del bot original, opcional) |
| `config_pares.py` | Lista fallback de pares (copiar del bot original) |

---

## Estrategia — Cómo funciona

### Capa 1 — Liquidez (NÚCLEO Bellsz)
Detecta niveles BSL (máximos) y SSL (mínimos) de liquidez en H1, H4 y Diario.

**PURGA ALCISTA → LONG**:
- El precio bajó hasta el SSL (stops de compradores)
- Pero cerró POR ENCIMA del SSL → trampa bajista, revertirá al alza

**PURGA BAJISTA → SHORT**:
- El precio subió hasta el BSL (stops de vendedores)
- Pero cerró POR DEBAJO del BSL → trampa alcista, revertirá a la baja

**Sin purga = sin señal.** La purga es obligatoria.

Peso por timeframe:
- SSL/BSL H1 → +1 punto
- SSL/BSL H4 → +2 puntos
- SSL/BSL Diario → +3 puntos

### Capa 2 — EMA 9/21
Confirma que la tendencia local va en la misma dirección que la señal.
- LONG: EMA 9 > EMA 21 (o cruce alcista reciente) → +1-2 puntos
- SHORT: EMA 9 < EMA 21 (o cruce bajista reciente) → +1-2 puntos

### Capa 3 — RSI con momentum
Confirma que hay fuerza en la dirección de la señal y el precio no está en zona extrema.
- RSI entre 30-70 y con momentum alcista → +2 puntos (LONG)
- RSI entre 30-70 y con momentum bajista → +2 puntos (SHORT)

### Confluencias extra (+1-2 pts cada una)
- Order Blocks (OB) + Fair Value Gaps (FVG)
- CHoCH / BOS (cambio de estructura)
- Liquidity Sweep
- MTF H1 y H4 tendencia
- VWAP (zona de valor)
- Premium/Discount zones
- Killzone activa (Asia/Londres/NY)
- Patrón de vela (Pin Bar, Engulfing)
- MACD histogram
- Displacement (vela grande)

**Score mínimo por defecto: 5/~15**

---

## SL / TP

- **SL**: swing estructural (mínimo/máximo reciente) con buffer
- **TP**: `dist_SL × TP_DIST_MULT` (por defecto 3.0 → R:R 1:3)
- **TP1**: `dist_SL × 1.5` (salida parcial 50%)
- **Break-even**: automático cuando el precio avanza 1 ATR
- **Trailing stop**: activa tras 1.5 ATR de beneficio

---

## Instalación en Railway

### 1. Copiar archivos del bot original
```
exchange.py, memoria.py, scanner_pares.py, metaclaw.py,
optimizador.py, config_pares.py
```

### 2. Subir todos los archivos a Railway

### 3. Variables de entorno en Railway
```
BINGX_API_KEY=tu_api_key
BINGX_SECRET_KEY=tu_secret_key
TELEGRAM_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
MEMORY_DIR=/app/data

# Estrategia Bellsz
TIMEFRAME=5m
LIQ_LOOKBACK=50         # velas para BSL/SSL
LIQ_MARGEN=0.001        # margen de zona (%)
EMA_FAST=9
EMA_SLOW=21
RSI_BUY_MAX=70
RSI_SELL_MIN=30
SCORE_MIN=5
TP_DIST_MULT=3.0        # TP = dist_SL × 3
TP1_DIST_MULT=1.5       # TP1 = dist_SL × 1.5
MIN_RR=2.0

# Gestión de riesgo
TRADE_USDT_BASE=10
TRADE_USDT_MAX=100
LEVERAGE=10
MAX_POSICIONES=3
MAX_PERDIDA_DIA=30

# Compounding
COMPOUND_STEP_USDT=50
COMPOUND_ADD_USDT=5

# MetaClaw (opcional — requiere ANTHROPIC_API_KEY)
METACLAW_ACTIVO=false
ANTHROPIC_API_KEY=tu_anthropic_key
```

### 4. Comando de inicio
```
python main_bellsz.py
```

---

## Backtest

```bash
# Ejecutar backtest completo (descarga 30 días de datos reales)
python backtest_bellsz.py

# Tarda ~3-5 minutos (8 pares × 30 días)
# Resultados guardados en backtest_bellsz_results.json
```

El backtest hace un **grid search** automático de:
- TP multiplier: 1.5x, 2.0x, 2.5x, 3.0x
- Score mínimo: 4, 5, 6

Y muestra el ranking con el mejor parámetro.

---

## Diferencias vs bot SMC original

| Aspecto | SMC Bot original | Bellsz Bot |
|---|---|---|
| Señal base | FVG + OB + BOS | **Purga BSL/SSL** |
| Confirmación 1 | EMA 21/50 HTF | **EMA 9/21 cruce** |
| Confirmación 2 | RSI | **RSI momentum** |
| Peso HTF | 1h tendencia | **H1 + H4 + Diario niveles** |
| TP | ATR × mult | **dist_SL × mult** (probado) |
| Score máx | 16 | ~15 |
| Filtro adicional | KZ obligatorio | **KZ opcional** (+1 punto) |

---

## Notas importantes

- La **purga es el evento clave** — sin purga no hay señal
- Usar en **gráfico de 5 minutos** para mejor granularidad
- Los niveles HTF se calculan en tiempo real (H1, H4, Diario)
- El bot opera en **BingX Perpetual Futures** con el mismo exchange.py
- La memoria, compounding y MetaClaw son **idénticos** al bot original
