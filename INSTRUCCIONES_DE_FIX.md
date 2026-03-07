# 🔧 INSTRUCCIONES PASO A PASO PARA REPARAR EL BOT

## 📥 PASO 1: Descargar los archivos corregidos

He preparado 3 archivos corregidos:
- ✅ `trader.py` — Typo REENTRY_COOL_DOWN → REENTRY_COOLDOWN
- ✅ `strategy.py` — Lógica SHORT invertida + condición trend flexible  
- ✅ `bingx_api.py` — Debug mejorado en fetch_klines

**Reemplaza estos 3 archivos en tu repositorio.**

---

## 🔄 PASO 2: Actualizar en GitHub

```bash
# En tu carpeta local del bot
cd ~/trading-bot  # (o donde tengas el repo)

# Reemplaza los 3 archivos con las versiones corregidas
# (copia trader.py, strategy.py, bingx_api.py)

git add trader.py strategy.py bingx_api.py
git commit -m "FIX: typo REENTRY_COOLDOWN + lógica SHORT + debug fetch_klines"
git push origin main
```

---

## 🚀 PASO 3: Redeploy en Railway

**Opción A: Automático**
- Railway detecta el push → redeploy automático (2-3 min)
- Espera a que vea "Build successful" ✅

**Opción B: Manual**
- Railway Dashboard → Tu proyecto → "Deploy"
- Click en "Redeploy commit"

---

## ✅ PASO 4: Verificar que funciona

### 4a. Ver logs en Railway

Desde Railway → Logs, deberías ver:

**ANTES (❌ sin datos):**
```
RSR-USDT: ⚠️  sin datos de BingX
LINK-USDT: ⚠️  sin datos de BingX
...
```

**DESPUÉS (✅ con datos):**
```
RSR-USDT  P=0.00524  — sin señal
LINK-USDT  P=24.5  — sin señal
AKE-USDT  P=0.103  ✅ SEÑAL LONG score=68 rsi=25.3 rr=2.1 4h=neutral
ZEC-USDT  P=78.2  ✅ SEÑAL SHORT score=72 rsi=68.5 rr=1.8 4h=neutral
```

Si ves esto → ✅ **FUNCIONANDO**

### 4b. Recibir notificación en Telegram

**Primer ciclo:**
- Deberías recibir un mensaje: "🟡 BOT INICIADO v13.0"
- Luego, cuando encuentre una señal: "📈 LONG RSR-USDT" o similar

**Si NO recibes nada:**
1. Verifica que TELEGRAM_TOKEN esté en Railway Variables
2. Verifica que TELEGRAM_CHAT_ID sea el tuyo (número, no nombre)
3. Ejecuta `python test_telegram.py` en Railway Logs

### 4c. Verificar Dashboard

- Railway expone la URL del dashboard (port 8080)
- Debería mostrar balance, posiciones, trades
- Auto-refresh cada 60 segundos

---

## 🐛 Si SIGUE sin funcionar

### Problema: "sin datos de BingX" para TODO

**Causas posibles:**

1. **API Key sin permiso de lectura**
   - Railway → Variables → Verifica BINGX_API_KEY y BINGX_API_SECRET
   - En BingX: crea nueva API con ✅ Read + ✅ Trade (sin Withdraw)

2. **BingX rechaza la API**
   - Ejecuta en Railway Logs:
     ```bash
     python test_bingx.py
     ```
   - Debería mostrar tu balance, si funciona la firma
   - Si ves error 100004 (Permission denied) → API key sin "Trade" permission

3. **Red bloqueada**
   - Railway por defecto tiene acceso a internet
   - Pero verifica: Railway → Settings → Network

### Problema: Señales pero TODAS rechazadas

**Ejemplo logs:**
```
RSR-USDT: ❌ volumen bajo — descartado
LINK-USDT: RSI muy alto para LONG (>=36)
ZEC-USDT: LONG score=25 < 40 — descartado
```

**Soluciones:**
- Bajar `SCORE_MIN` en config.py: 40 → 30
- Bajar `RSI_LONG` en config.py: 36 → 32
- Desactivar `VOLUME_FILTER`: False en config.py

### Problema: Crash con error NameError

**Ejemplo:**
```
NameError: name 'REENTRY_COOLDOWN' is not defined
```

→ **Ya está fijo** con este update. Si sigue apareciendo, asegúrate de usar la `strategy.py` y `trader.py` correctas.

---

## 📊 Esperar a que funcione

El bot **necesita datos históricos para calcular indicadores**:

- **Primeras 2 velas:** Calcula BB, RSI, ATR (sin acción)
- **Vela 3 en adelante:** Busca señales
- **Ciclos:** Cada 15 minutos (POLL_INTERVAL en config.py)

**Timeline esperado:**
- `00:00` — Deploy completa ✅
- `00:05` — Primer ciclo, probablemente sin señales
- `00:20` — Segundo ciclo, puede haber señales
- `00:35` — Tercero ciclo, señales más claras

**En LIVE mode:**
- Cuando haya señal → abre orden en BingX
- Notificación Telegram: "✅ ORDEN ABIERTA LONG RSR-USDT"

**En PAPER mode:**
- Cuando haya señal → simula la orden
- Se guarda en `paper_trades.json`
- Puedes ver en Dashboard → "Últimos 30 Trades"

---

## ✨ CAMBIOS EXACTOS REALIZADOS

### trader.py
```diff
- return hours_passed >= REENTRY_COOL_DOWN
+ return hours_passed >= REENTRY_COOLDOWN
```

### strategy.py (SHORT)
```diff
- if trend_1h == "flat" and price <= sma * 1.03:
+ if trend_1h != "up" and price <= sma * 1.03:
```

```diff
- bull_bars = momentum_bars(df["close"], i, lookback=5)
+ # Invertir: contar velas ALCISTAS
+ bear_count = momentum_bars(df["close"], i, lookback=5)
+ bull_bars = 5 - bear_count
```

### bingx_api.py (fetch_klines)
```diff
+ # Verificar si hay error en la respuesta JSON
+ if isinstance(data, dict) and data.get("code") != 0:
+     print(f"  [API] {symbol}: code={data.get('code')} msg={data.get('msg','')}")
+     continue
```

---

## 📞 Si necesitas más ayuda

1. **Verifica los logs** en Railway → mira los últimos 100 líneas
2. **Busca patterns:**
   - Si ves "sin datos" → problema API key
   - Si ves "score=30 < 40" → parámetros demasiado estrictos
   - Si ves "ERROR" → hay excepción en el código
3. **Prueba test scripts:**
   ```bash
   # En Railway Logs → Run command
   python test_bingx.py      # Verifica API
   python test_telegram.py   # Verifica Telegram
   python backtest_final.py  # Verifica estrategia
   ```

---

## ✅ CHECKLIST FINAL

- [ ] He reemplazado `trader.py`, `strategy.py`, `bingx_api.py`
- [ ] He hecho push a GitHub
- [ ] Railway ha terminado de desplegar (Build successful)
- [ ] Veo logs con datos de precios (P=0.00524, etc)
- [ ] Recibo notificación "BOT INICIADO" en Telegram
- [ ] He esperado 2-3 ciclos (30-45 min) para posibles señales
- [ ] En caso de señal, he visto notificación en Telegram

---

## 🎯 PRÓXIMOS PASOS TRAS VERIFICAR

1. **En PAPER mode por 3-5 días:**
   - Verifica que las señales son sensatas
   - Mira la métrica Profit Factor en Dashboard
   - Ajusta parámetros en config.py si es necesario

2. **Antes de LIVE:**
   - Cambia `TRADE_MODE = "live"` en Railway Variables
   - Verifica que API key tiene PERMISO TRADE activado
   - Comienza con capital pequeño ($100-500)
   - Monitorea los primeros trades en BingX

3. **Monitoreo continuo:**
   - Revisa Dashboard cada día
   - Revisa Telegram notifications
   - Si drawdown > 15%, ejecuta `/pause` y revisa parámetros

---

¡**Avísame cuando veas la primera señal en los logs!** 🚀
