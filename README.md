# Bot Dual Strategy v1.0
**Trend Magic + RMI Trend Sniper × Magical Momentum**

Bot de trading automático para BingX Futuros que combina dos estrategias de TradingView traducidas a Python, con todos los fixes de producción.

---

## Estrategias incluidas

### Estrategia 1 — Trend Magic + EMA + RMI Trend Sniper
- **Trend Magic**: CCI(20) + ATR(5) → línea de soporte/resistencia dinámica
- **EMA(9)**: tendencia rápida del precio
- **RMI**: combina RSI + MFI → señal BUY cuando cruza >66, SELL cuando cae <30

### Estrategia 2 — Magical Momentum
- **Worm**: EMA adaptativa con velocidad limitada por StdDev
- **Momentum**: log-normalizado y suavizado → valor positivo = alcista
- **Aceleración**: detecta cuándo el momentum se acelera (señal más fuerte)

### Lógica de entrada combinada
| Dirección | Condición |
|-----------|-----------|
| **LONG**  | 1h alcista + Trend Magic bull + RMI BUY + Momentum acelerando al alza |
| **SHORT** | 1h bajista + Trend Magic bear + RMI SELL + Momentum acelerando a la baja |

---

## Fixes de producción incluidos
- ✅ **Qty en notional**: `qty = (usdt × leverage) / price` (antes daba 0.02 BCH en vez de 0.11)
- ✅ **Multi-timeframe**: 1h confirma tendencia antes de entrar en 15m
- ✅ **TP/SL garantizados**: espera 90s + 5 reintentos con delays crecientes
- ✅ **Anti-correlación**: máx 2 trades en la misma dirección
- ✅ **RSI mínimo para SHORT**: evita entrar cuando el precio ya cayó
- ✅ **2× comisión en PnL**: descuenta entrada + salida
- ✅ **Reconciliación**: recupera posiciones abiertas al reiniciar
- ✅ **Score 0-100**: normalizado, no infla a 118+

---

## Despliegue paso a paso

### 1. Preparar BingX

1. Entra en [BingX](https://bingx.com) → **Perfil → API Management**
2. Crea una API key con permisos: **Trade** (NO habilites retiradas)
3. Anota `API Key` y `Secret Key`
4. En BingX Futuros, configura el leverage de cada par que quieras operar al mismo valor que `LEVERAGE` en el .env (por defecto 5x)

### 2. Crear bot de Telegram

```
1. Abre Telegram y busca @BotFather
2. Envía: /newbot
3. Elige un nombre y username para tu bot
4. Copia el TOKEN que te da BotFather
5. Inicia una conversación con tu nuevo bot (pulsa Start)
6. Visita en el navegador:
   https://api.telegram.org/bot<TU_TOKEN>/getUpdates
7. Copia el valor "id" que aparece en "chat" → es tu CHAT_ID
```

### 3. Subir a GitHub

```bash
git init
git add .
git commit -m "Bot Dual Strategy v1.0"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### 4. Desplegar en Railway

1. Ve a [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
2. Selecciona tu repositorio
3. Railway detectará el `Procfile` automáticamente
4. Ve a **Settings → Variables** y añade todas las variables del `.env.example`:

| Variable | Valor |
|----------|-------|
| `BINGX_API_KEY` | tu key de BingX |
| `BINGX_API_SECRET` | tu secret de BingX |
| `TELEGRAM_BOT_TOKEN` | token de @BotFather |
| `TELEGRAM_CHAT_ID` | tu chat id |
| `AUTO_TRADING_ENABLED` | `true` |
| `MAX_POSITION_SIZE` | `10` (USDT por trade) |
| `LEVERAGE` | `5` |
| `TAKE_PROFIT_PCT` | `2.0` |
| `STOP_LOSS_PCT` | `1.0` |
| `MAX_OPEN_TRADES` | `3` |
| `MIN_SCORE` | `65` |

5. El bot arranca automáticamente. Ve a **Deploy Logs** para confirmar que dice `BingX OK`

---

## Variables de entorno

Ver `.env.example` para la lista completa con descripciones.

### Variables críticas para rentabilidad

```
LEVERAGE=5              # Debe coincidir con BingX
MAX_POSITION_SIZE=10    # Margen real por trade (no el notional)
MIN_SCORE=65            # Subir a 70+ para señales más selectivas
MAX_SAME_DIRECTION=2    # Anti-correlación: máx 2 longs o 2 shorts
BTC_FILTER_PCT=2.5      # Bloquea si BTC cae/sube más de 2.5% en 1h
```

### Parámetros de las estrategias

```
# Trend Magic
CCI_LENGTH=20           # Período del CCI
ATR_LENGTH=5            # Período del ATR
ATR_MULTIPLIER=1.0      # Multiplicador ATR

# RMI
RMI_LENGTH=14
RMI_POSITIVE_ABOVE=66   # Umbral señal BUY
RMI_NEGATIVE_BELOW=30   # Umbral señal SELL

# Magical Momentum
MOMENTUM_PERIOD=50
MOMENTUM_RESPONSIVENESS=0.9  # 0.1=lento, 1.0=rápido
```

---

## Estructura del score (0-100)

| Componente | LONG | SHORT |
|------------|------|-------|
| Tendencia 1h | +20 bull / +8 neutral / BLOQUEADO si bear | +20 bear / +8 neutral / BLOQUEADO si bull |
| Trend Magic | +20 bull | +20 bear |
| RMI señal | +25 BUY / +10 ok | +25 SELL / +10 ok |
| Momentum acelerando | +25 | +25 |
| RSI favorable | +5 | +5 |
| Volumen spike | +5 | +5 |

**Entrada cuando score ≥ MIN_SCORE (default 65)**

---

## Logs de referencia

```
✅ BingX OK | Balance: $150.00 USDT          ← API conectada
★ LONG SOL-USDT 78/100 ✅TM ✅RMI MOM:+0.0123   ← señal detectada
➤ LONG SOL-USDT                              ← abriendo trade
✅ Posición confirmada: qty=0.58 entry=$87.17  ← posición confirmada
TP ✅ @ $88.91  SL ✅ @ $86.30              ← TP/SL fijados
✅ TAKE PROFIT SOL-USDT PnL:$0.312(+3.12%)  ← trade cerrado
```

---

## Advertencia

Este bot opera con dinero real. Úsalo bajo tu propia responsabilidad. Empieza con capital pequeño ($5-$10 por trade) hasta validar que funciona correctamente en tu cuenta.
