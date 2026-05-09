# 🎯 Sniper Bot V26.1 — Institutional Apex

Bot de trading automático para **BingX Futures** que combina lo mejor de dos estrategias institucionales con notificaciones por **Telegram**, listo para desplegar en **Railway** con un clic.

---

## 📐 Estrategia

Fusiona **Sniper Apex V26.1** + **EMA Slope ChartArt** para señales de alta probabilidad:

| Indicador | Rol |
|-----------|-----|
| EMA 7 / 17 | Cruce principal de tendencia |
| EMA 2 / 4 / 20 | Confirmación de slope (ChartArt) |
| Hull MA 50 | Filtro de tendencia macro |
| STC (10, 23, 50) | Momentum / divergencias |
| Volumen >1.5× SMA20 | Detección de volumen institucional |
| Pivot High/Low 5 | Niveles de liquidez (SL y rotura) |

**Reglas de entrada:**
- **LONG**: EMA7 cruza EMA17 ↑ + cierre sobre pivot high + vol. institucional + precio > Hull + STC subiendo + slope positivo + confirmación ChartArt.
- **SHORT**: Condiciones inversas.

**Gestión de riesgo 1:3** — SL en el último pivot, TP = riesgo × 3.

---

## 🗂️ Estructura

```
sniper-bot/
├── main.py              # Punto de entrada
├── railway.toml         # Config Railway
├── requirements.txt
├── .env.example         # Plantilla de variables
└── src/
    ├── bot.py           # Bucle principal
    ├── exchange.py      # Cliente BingX REST
    ├── strategy.py      # Lógica de señales
    ├── risk_manager.py  # Cálculo de tamaño y drawdown
    └── telegram_bot.py  # Notificaciones
```

---

## 🚀 Deploy en Railway (recomendado)

### 1. Fork + Push a GitHub

```bash
git clone https://github.com/tu-usuario/sniper-bot.git
cd sniper-bot
# (edita lo que necesites)
git add . && git commit -m "init" && git push
```

### 2. Crear proyecto en Railway

1. Ve a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Selecciona tu repositorio `sniper-bot`
3. Railway detecta `railway.toml` automáticamente

### 3. Añadir variables de entorno

En Railway → tu proyecto → **Variables** → añade:

```
BINGX_API_KEY        = tu_key
BINGX_API_SECRET     = tu_secret
TELEGRAM_TOKEN       = tu_token
TELEGRAM_CHAT_ID     = tu_chat_id
SYMBOL               = BTC-USDT
TIMEFRAME            = 15m
LEVERAGE             = 5
MAX_RISK_PCT         = 1.0
```

### 4. Deploy

Haz clic en **Deploy** — Railway instalará dependencias y ejecutará `python main.py` automáticamente.

---

## 🤖 Configurar Telegram Bot

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el **TOKEN**
2. Añade el bot a tu grupo o inicia conversación con él
3. Obtén el **CHAT_ID**:
   - Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador
   - Envía un mensaje al bot, recarga la URL y busca `"chat":{"id":...}`

---

## 🔑 Crear API Key en BingX

1. [BingX](https://bingx.com) → Perfil → **API Management** → **Create API**
2. Permisos necesarios: ✅ **Trade** (NO habilites retiros)
3. Whitelist IP: añade la IP de tu servidor Railway (recomendado)
4. Copia `API Key` y `Secret Key`

---

## ⚠️ Advertencias

- **Dinero real**: este bot opera con capital real. Empieza con `MAX_RISK_PCT=0.5` (0.5% por trade).
- **Testnet primero**: BingX tiene entorno demo; crea una cuenta demo y prueba antes de usar real.
- **Drawdown**: el bot no tiene stop global por defecto. Monitorea manualmente o añade lógica en `risk_manager.py`.
- **Deslizamiento**: en mercados ilíquidos el fill puede diferir del precio calculado.

---

## 📊 Mensajes de Telegram que recibirás

```
🟢 LONG ABIERTO
Par: BTC-USDT
Entry: 67234.5000
SL: 66800.0000
TP: 68537.5000 (3R)
Qty: 0.007
ATR: 145.2300

🔴 SHORT ABIERTO
...

🔄 Cierre posición LONG
BTC-USDT @ 67100.0000

⚠️ Error bot: [descripción]
```

---

## 📝 Licencia

MIT — úsalo bajo tu responsabilidad. El autor no se hace responsable de pérdidas.
