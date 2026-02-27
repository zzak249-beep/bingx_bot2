# 🤖 BingX Scalping Bot

Bot de trading automático para BingX Futures.  
**Estrategia:** Squeeze Momentum + SuperTrend + VWAP + RSI  
**Por trade:** 8 USDT × 7x = 56 USDT nocional  
**Ganadores:** trailing stop ATR — deja correr hasta que pare  
**Perdedores:** smart cut — cierra cuando ve 3+ velas consecutivas en contra con pérdida >30%

---

## 📋 Lógica del Bot

### Señal de Entrada
Se necesitan **las 4 condiciones al mismo tiempo**:

| Indicador | Condición LONG | Condición SHORT |
|---|---|---|
| Squeeze Momentum | Cruz gris ↑ + histograma > 0 | Cruz gris ↓ + histograma < 0 |
| SuperTrend | Dirección UP (verde) | Dirección DOWN (rojo) |
| VWAP | Precio > VWAP | Precio < VWAP |
| RSI | RSI < 70 (no sobrecomprado) | RSI > 30 (no sobrevendido) |

### Gestión de Trade
- **Stop Loss inicial:** entry ± 1.5 × ATR
- **Take Profit:** SL × 2 (ratio 1:2)
- **Trailing Stop:** se actualiza cada vela a `best_price - 1.5 × ATR`
- **Smart Cut:** si hay 3+ velas en contra Y pérdida > 30% del colateral → cierra

### Mensajes Telegram
- 🟢 Trade abierto (entry, SL, TP, cantidad)
- ✅/❌ Trade cerrado (PnL, razón, duración)
- 📊 Resumen diario a las 23:55 UTC
- ⚠️ Alertas de error

---

## 🚀 Despliegue en Railway (Recomendado)

### 1. Preparar el repo en GitHub

```bash
git init
git add .
git commit -m "feat: bingx scalping bot"
git remote add origin https://github.com/TU_USUARIO/bingx-bot.git
git push -u origin main
```

### 2. Crear proyecto en Railway

1. Ve a [railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** → selecciona `bingx-bot`
3. Railway detecta automáticamente el `Procfile`

### 3. Configurar Variables de Entorno en Railway

En tu proyecto Railway → **Variables** → añade:

```
BINGX_API_KEY       = tu_api_key
BINGX_API_SECRET    = tu_api_secret
SYMBOL              = BTC-USDT
TIMEFRAME           = 5m
LEVERAGE            = 7
TRADE_USDT          = 8.0
TAKE_PROFIT_R       = 2.0
PAPER_MODE          = true          ← empieza siempre en paper
TELEGRAM_TOKEN      = tu_token
TELEGRAM_CHAT_ID    = tu_chat_id
```

### 4. Deploy

Railway hace deploy automático al pushear a `main`.  
Ve a **Logs** para ver el bot en acción.

---

## 🔑 Configurar API de BingX

1. Entra en [BingX](https://bingx.com) → **API Management**
2. **Create API Key** → nombre: `trading-bot`
3. Permisos: ✅ **Read** + ✅ **Perpetual Futures Trading**
4. Whitelist IP: deja vacío (Railway usa IPs dinámicas)
5. Copia `API Key` y `Secret Key`

---

## 📱 Configurar Telegram Bot

```bash
# 1. Habla con @BotFather
/newbot
# → te dará un token: 123456:ABCdef...

# 2. Escribe un mensaje a tu bot nuevo

# 3. Obtén tu chat_id:
curl https://api.telegram.org/bot<TU_TOKEN>/getUpdates
# → busca "chat":{"id": ESTE_NUMERO}
```

---

## 🧪 Test Local

```bash
# Instalar dependencias
pip install -r requirements.txt

# Configurar entorno
cp .env.example .env
# → edita .env con tus claves

# Ejecutar en paper mode (sin dinero real)
python main.py
```

---

## ⚠️ Advertencias Importantes

- **Empieza SIEMPRE con `PAPER_MODE=true`** y observa al menos 50 trades
- El bot opera con dinero real cuando `PAPER_MODE=false`
- 8 USDT × 7x = riesgo máximo de ~8 USDT por trade (pérdida limitada al colateral en modo ISOLATED)
- Los futuros pueden liquidar tu posición si el mercado se mueve fuerte
- Monitorea los logs en Railway diariamente
- Nunca arriesgues dinero que no puedas permitirte perder

---

## 📁 Estructura

```
bingx-bot/
├── main.py                  # Punto de entrada
├── config.py                # Variables de configuración
├── requirements.txt
├── Procfile                 # Para Railway
├── railway.json             # Config Railway
├── .env.example             # Plantilla de variables
└── core/
    ├── bot.py               # Orquestador principal
    ├── bingx_client.py      # Cliente API BingX
    ├── indicators.py        # Squeeze + SuperTrend + VWAP + RSI
    ├── trade_manager.py     # Trailing stop + Smart Cut
    └── telegram_notifier.py # Alertas Telegram
```

---

## 📊 Parámetros Clave

| Variable | Default | Descripción |
|---|---|---|
| `SYMBOL` | BTC-USDT | Par a operar |
| `TIMEFRAME` | 5m | Temporalidad |
| `LEVERAGE` | 7 | Apalancamiento |
| `TRADE_USDT` | 8.0 | USDT por trade |
| `TAKE_PROFIT_R` | 2.0 | TP = SL × 2 |
| `SQZ_BB_LEN` | 20 | Período BB del Squeeze |
| `SQZ_KC_MULT` | 1.5 | Multiplicador KC |
| `ST_ATR_LEN` | 7 | Período ATR SuperTrend |
| `ST_FACTOR` | 2.0 | Factor SuperTrend |
