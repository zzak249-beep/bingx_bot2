# ⚡ SMC Bot BingX v2.1 [FIXED]

## 🔧 Correcciones aplicadas en esta versión

| # | Problema | Fix |
|---|---|---|
| 1 | HMAC firma incorrecta (todas las órdenes fallaban) | `hmac.new()` con `digestmod` explícito |
| 2 | SL/TP ignorados por BingX | Órdenes separadas `STOP_MARKET` + `TAKE_PROFIT_MARKET` |
| 3 | RSI calculado con promedio simple | RSI Wilder (RMA) igual que TradingView |
| 4 | FVG buscaba en toda la historia | Limitado a últimas 20 velas |
| 5 | `memoria.json` se borraba en cada redeploy | Guardado atómico + backup + soporte `/data` (Railway Volume) |
| 6 | Score mínimo 4 muy permisivo | Subido a 5 — más confluencia requerida |
| 7 | Sin filtro de volumen en vela | Descarta velas con < 30% del volumen medio |
| 8 | RSI demasiado permisivo | BUY_MAX=50, SELL_MIN=50 (más conservador) |

---

## 🚀 Despliegue en Railway

### 1. Subir a GitHub
```bash
git add .
git commit -m "SMC Bot v2.1 fixed"
git push
```

### 2. Variables de entorno en Railway

| Variable | Valor recomendado | Descripción |
|---|---|---|
| `BINGX_API_KEY` | `tu_key` | API Key BingX |
| `BINGX_SECRET_KEY` | `tu_secret` | Secret Key BingX |
| `TELEGRAM_TOKEN` | `123:ABC...` | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | `tu_chat_id` | Tu Chat ID |
| `MODO_DEMO` | `false` | Live trading |
| `LEVERAGE` | `10` | Apalancamiento |
| `MAX_POSICIONES` | `3` | Máx posiciones simultáneas |
| `SCORE_MIN` | `5` | Score mínimo (recomendado 5-6) |
| `SOLO_LONG` | `false` | Solo longs (más seguro al inicio) |
| `MEMORY_DIR` | `/data` | Directorio memoria persistente |

### 3. ✅ IMPORTANTE — Añadir Volume para persistencia de memoria

Sin Volume, `memoria.json` se borra en cada redeploy (Railway filesystem efímero).

1. En Railway → tu servicio → **Volumes**
2. **Add Volume** → Mount Path: `/data`
3. Añadir variable de entorno: `MEMORY_DIR=/data`

Esto garantiza que el historial de trades y el compounding sobrevivan reinicios.

---

## 📊 Lógica de señales (Score mínimo 5/8)

### LONG requiere:
- ✅ FVG alcista (últimas 20 velas) — **+2** (obligatorio)
- ✅ En killzone London o NY — **+1** (obligatorio)
- ✅ Cerca de S1, S2 o Equal Low — **+1** (al menos uno, obligatorio)
- ✅ EMA21 > EMA50 — **+1**
- ✅ RSI ≤ 50 — **+1**

### SHORT requiere:
- ✅ FVG bajista (últimas 20 velas) — **+2** (obligatorio)
- ✅ En killzone London o NY — **+1** (obligatorio)
- ✅ Cerca de R1 o Equal High — **+1** (al menos uno, obligatorio)
- ✅ EMA21 < EMA50 — **+1**
- ✅ RSI ≥ 50 — **+1**

Score mínimo 5 significa que necesitas FVG+KZ+zona+tendencia como mínimo.

---

## ⚠️ Gestión de riesgo recomendada

- Empieza con `SOLO_LONG=true` las primeras 48h
- `LEVERAGE=5` para comenzar (subir gradualmente)
- `MAX_POSICIONES=3` máximo
- `MAX_PERDIDA_DIA=20` para protección diaria
- `SCORE_MIN=6` si quieres señales aún más selectivas

---

## 📈 Killzones (UTC)

| Sesión | UTC | Recomendación |
|---|---|---|
| 🌙 Asia | 00:00–04:00 | Evitar |
| 🇬🇧 Londres | 07:00–10:00 | ✅ Mejor |
| 🗽 Nueva York | 13:00–16:00 | ✅ Mejor |
