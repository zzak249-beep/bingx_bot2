# 🤖 BingX VWAP + EMA9 Bot v1.0

Bot de trading para **BingX Futures Perpetuos**. Detecta entradas de alta probabilidad usando **VWAP con bandas de desviación estándar** + **EMA 9** como filtro de tendencia. Take Profit extendido a **4×ATR** para dejar correr las ganancias.

---

## 📁 Archivos

```
vwap-bot/
├── vwap_bot.py       ← lógica completa del bot
├── requirements.txt  ← dependencias Python
├── railway.toml      ← configuración Railway
├── Procfile          ← comando de inicio
├── .env.example      ← plantilla de variables (renombrar a .env en local)
├── .gitignore        ← protege .env y logs
└── README.md
```

---

## 🧠 Estrategia

```
VWAP ─── banda superior 2σ ──→ SHORT si EMA9 bajista
VWAP ─── banda superior 1σ ──→ SHORT si EMA9 bajista (señal menor)
VWAP ─── línea central
VWAP ─── banda inferior 1σ ──→ LONG si EMA9 alcista (señal menor)
VWAP ─── banda inferior 2σ ──→ LONG si EMA9 alcista
```

### Gestión del trade
| Evento | Acción |
|---|---|
| Precio llega a **2×ATR** (TP1) | Cierra 50% + SL → breakeven |
| Precio llega a **4×ATR** (TP2) | Cierra el 50% restante |
| Trailing activo desde **2×ATR** | Sigue precio a 1×ATR |
| Posición lleva **+10h** sin resolver | Cierre forzado |

---

## 🚀 Deploy en Railway

### 1. Sube a GitHub

```bash
git init
git add .
git commit -m "vwap bot v1.0"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/vwap-bot.git
git push -u origin main
```

### 2. Conecta Railway

1. Ve a [railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** → selecciona tu repo
3. Railway detecta el `railway.toml` automáticamente ✅

### 3. Variables de entorno en Railway

Ve a tu proyecto → pestaña **Variables** → añade:

| Variable | Valor |
|---|---|
| `BINGX_API_KEY` | tu API key de Futures |
| `BINGX_SECRET_KEY` | tu Secret Key |
| `TELEGRAM_TOKEN` | token de tu bot Telegram |
| `TELEGRAM_CHAT_ID` | tu chat ID |
| `MODO_DEMO` | `false` para dinero real |
| `LEVERAGE` | `7` |
| `MARGEN_USDT` | `8` |
| `MAX_POS` | `3` |

El resto de variables tienen valores por defecto en el código.

### 4. Deploy

Railway despliega automáticamente. Ve a **View Logs** para ver el bot en acción.

---

## 🔑 Crear API Key en BingX

1. Ve a [BingX → Gestión de API](https://bingx.com/es-es/account/api)
2. Crea una nueva API Key
3. Activa **solo**: `Perpetual Futures Trading`
4. **NO actives** permisos de retiro
5. Guarda la API Key y el Secret

---

## 📱 Configurar Telegram

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copia el token → `TELEGRAM_TOKEN`
3. Envía cualquier mensaje a tu nuevo bot
4. Abre en el navegador:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
5. Copia el número dentro de `"id"` en el objeto `"chat"` → `TELEGRAM_CHAT_ID`

---

## ⚙️ Parámetros clave

| Variable | Default | Descripción |
|---|---|---|
| `VWAP_PERIODO` | 20 | Velas para calcular el VWAP |
| `VWAP_STD2` | 2.0 | Banda de 2σ — señal principal |
| `EMA_PERIODO` | 9 | EMA rápida de tendencia |
| `SL_ATR_MULT` | 1.5 | Stop Loss en múltiplos de ATR |
| `TP1_ATR_MULT` | 2.0 | TP parcial (50%) |
| `TP_ATR_MULT` | 4.0 | TP extendido (resto) |
| `SCORE_MIN` | 60 | Score mínimo para abrir trade |

---

## ⚠️ Disclaimer

Opera siempre primero con `MODO_DEMO=true` para verificar el funcionamiento. Nunca inviertas más de lo que puedas permitirte perder.
