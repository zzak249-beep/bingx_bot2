# ⚡ SMC Bot BingX — FVG + EQH/EQL + Killzones

Bot de trading automático para BingX Futuros Perpetuos basado en la estrategia **Smart Money Concepts**:
- 📦 **Fair Value Gaps** (FVG alcista y bajista)
- ⚖️ **Equal Highs / Equal Lows** (zonas de liquidez)
- 🕐 **ICT Killzones** (Asia · Londres · Nueva York)
- 📍 **Pivotes Diarios** (PP, R1, R2, S1, S2)
- 📈 **Filtros**: EMA tendencia + RSI

---

## 📁 Archivos del proyecto

```
main.py          → Loop principal, gestión de posiciones, anti-hedge
analizar.py      → Motor de señales SMC (FVG, EQH/EQL, Killzones, Pivotes)
exchange.py      → API REST de BingX (firma HMAC-SHA256)
config.py        → Todas las variables de configuración
config_pares.py  → Lista de pares a monitorear
memoria.py       → Historial de trades y aprendizaje
requirements.txt → Dependencias Python
Procfile         → Comando para Railway
railway.toml     → Configuración Railway
.env.template    → Plantilla de variables de entorno
```

---

## 🚀 Puesta en marcha

### 1. Subir a GitHub

```bash
git init
git add .
git commit -m "SMC Bot v1.0"
git remote add origin https://github.com/tu-usuario/smc-bot-bingx.git
git push -u origin main
```

### 2. Crear proyecto en Railway

1. Ir a [railway.app](https://railway.app) → **New Project**
2. Seleccionar **Deploy from GitHub repo**
3. Elegir el repositorio que acabas de crear
4. Railway detectará el `Procfile` automáticamente

### 3. Configurar Variables en Railway

En tu proyecto Railway → **Variables** → añadir una a una:

| Variable | Valor | Descripción |
|---|---|---|
| `BINGX_API_KEY` | `tu_key` | API Key de BingX |
| `BINGX_SECRET_KEY` | `tu_secret` | Secret Key de BingX |
| `TELEGRAM_TOKEN` | `123:ABC...` | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | `tu_chat_id` | Tu Chat ID de Telegram |
| `MODO_DEMO` | `false` | `true` para probar sin dinero |
| `LEVERAGE` | `10` | Apalancamiento (máx 125x) |
| `MAX_POSICIONES` | `3` | Posiciones simultáneas |
| `RIESGO_PCT` | `2.0` | % del balance por trade |
| `SCORE_MIN` | `4` | Score mínimo para entrar |
| `TIMEFRAME` | `5m` | Temporalidad |
| `SOLO_LONG` | `false` | Solo LONGs (recomendado para empezar) |

> Ver `.env.template` para la lista completa de variables.

### 4. Obtener API Keys de BingX

1. Ir a BingX → **Cuenta** → **API Management**
2. Crear nueva API key con permisos: **Lectura** + **Trading de Futuros**
3. **NO** marcar permisos de retiro
4. Guardar `API Key` y `Secret Key`

### 5. Obtener Chat ID de Telegram

```
1. Habla con @BotFather → crea un bot → guarda el TOKEN
2. Habla con @userinfobot → te da tu CHAT_ID
```

---

## ⚙️ Cómo funciona la estrategia

### Condiciones para entrar en LONG
```
✅ Fair Value Gap alcista detectado (últimas 20 velas)
✅ Precio dentro de Killzone activa (Londres o NY)
✅ Precio cerca de S1, S2 o Equal Low detectado
✅ EMA21 > EMA50 (tendencia alcista)
✅ RSI ≤ 55 (no sobrecomprado)
Score mínimo: 4/8
```

### Condiciones para entrar en SHORT
```
✅ Fair Value Gap bajista detectado (últimas 20 velas)
✅ Precio dentro de Killzone activa (Londres o NY)
✅ Precio cerca de R1 o Equal High detectado
✅ EMA21 < EMA50 (tendencia bajista)
✅ RSI ≥ 45 (no sobrevendido)
Score mínimo: 4/8
```

### Gestión de la posición
```
TP1 (50%): +1×ATR → cierra la mitad, SL se mueve a breakeven
TP2 (50%): +2×ATR → cierra el resto
SL: -1×ATR desde entrada
Trailing Stop: activo tras TP1
Time Exit: cierra tras 8h sin resolver
```

---

## 🔒 Protecciones anti-hedge

El bot incluye 3 capas de protección para nunca abrir LONG y SHORT del mismo par:

1. **Al arrancar**: lee posiciones reales de BingX → las carga en memoria
2. **Antes de cada orden**: verifica que el par no tenga posición abierta
3. **Sincronización continua**: detecta si BingX cerró una posición externamente

---

## 📊 Composición del Score

| Señal | Puntos | Descripción |
|---|---|---|
| FVG Bull/Bear | +2 | Condición base (obligatoria) |
| Killzone activa | +1 | Condición base (obligatoria) |
| Cerca S1/S2 | +1 c/u | Solo LONG |
| Equal Low | +1 | Solo LONG |
| Cerca R1 | +1 | Solo SHORT |
| Equal High | +1 | Solo SHORT |
| EMA tendencia | +1 | Confirmación de tendencia |
| RSI filtrado | +1 | No sobrecomprado/vendido |

**Score máximo: 8** | **Recomendado: ≥4 para alta calidad**

---

## ⚠️ Recomendaciones para dinero real

- Empieza con `MODO_DEMO=true` al menos 24-48h para verificar que las señales llegan correctamente
- Usa `LEVERAGE=5` o `LEVERAGE=10` máximo al principio
- `RIESGO_PCT=1.0` (1% del balance por trade) es más conservador
- `MAX_PERDIDA_DIA=20` limita las pérdidas diarias
- `SOLO_LONG=true` es más seguro para empezar
- `SCORE_MIN=5` filtra más señales pero de mayor calidad

---

## 📈 Killzones (UTC)

| Sesión | Horario UTC | Descripción |
|---|---|---|
| 🌙 Asia | 00:00 – 04:00 | Menor volatilidad |
| 🇬🇧 Londres | 07:00 – 10:00 | Alta volatilidad |
| 🗽 Nueva York | 13:00 – 16:00 | Máxima volatilidad |

El bot **solo entra en Londres o NY** (las killzones con más volumen).
