# 🚀 BOT FUSIONADO v2.0 — GUÍA DE DESPLIEGUE

## 📋 Resumen

Bot de trading fusionado que combina:
- **BB+RSI Elite:** Estrategia Bollinger Bands + RSI
- **Análisis + Learning:** Diagnóstico inteligente
- **Testing integrado:** Verificación automática
- **Logging mejorado:** Debugging fácil

**Estado:** ✅ Todos los tests pasaron (8/8)

---

## 🔧 Instalación Local (Prueba)

### Paso 1: Clonar repositorio
```bash
git clone https://github.com/tu-usuario/trading-bot.git
cd trading-bot
```

### Paso 2: Instalar dependencias
```bash
pip install -r requirements.txt
```

### Paso 3: Configurar variables de entorno
```bash
cp .env.template .env
# Editar .env con tus credenciales:
# BINGX_API_KEY=xxx
# BINGX_API_SECRET=xxx
# TELEGRAM_TOKEN=xxx
# TELEGRAM_CHAT_ID=xxx
# TRADE_MODE=paper
```

### Paso 4: Ejecutar tests
```bash
python bot_v2_test.py
```

**Salida esperada:**
```
RESULTADO: 8/8 tests pasados
🎉 ¡TODOS LOS TESTS PASARON! El bot está listo.
```

### Paso 5: Ejecutar bot en modo paper
```bash
python bot_v2_main.py
```

---

## 🌐 Despliegue en Railway

### Paso 1: Subir a GitHub

```bash
git add .
git commit -m "Bot v2.0 - Testing suite + Main mejorado"
git push origin main
```

### Paso 2: Crear proyecto en Railway

1. Ve a https://railway.app
2. Login → New Project
3. Deploy from GitHub
4. Selecciona tu repositorio
5. Click "Deploy"

### Paso 3: Configurar Variables (Railway Dashboard)

**Settings → Variables:**

| Variable | Valor | Ejemplo |
|----------|-------|---------|
| `BINGX_API_KEY` | Tu API key | `abcd1234...` |
| `BINGX_API_SECRET` | Tu secret | `xyz9876...` |
| `TELEGRAM_TOKEN` | Token de @BotFather | `1234567:ABC...` |
| `TELEGRAM_CHAT_ID` | Tu chat ID | `-1001234567890` |
| `TRADE_MODE` | `paper` o `live` | `paper` |
| `PORT` | Puerto (auto) | `8080` |
| `POLL_INTERVAL` | Intervalo en segundos | `900` |

### Paso 4: Verificar Deploy

**Railway Dashboard:**
- Status: "Build successful" ✅
- Logs: Deberías ver "🤖 BOT FUSIONADO v2.0"

---

## ✅ Verificar que Funciona

### En los Logs (Railway)

**Busca estas líneas:**

```
✅ Todos los módulos importados correctamente
🔍 DIAGNÓSTICO DE SISTEMA:
  ✅ BingX API OK - Balance: $XXX.XX
  ✅ Data feed OK - N velas descargadas
🚀 BOT INICIADO - Esperando ciclos...
```

### Primer Ciclo (primeros 15 min)

Deberías ver algo como:
```
CICLO #1 | 2026-03-07 12:00 UTC | Balance: $100.00
  RSR-USDT  P=0.00524  🚀 SEÑAL LONG | score=65 | rsi=28.5 | 4h=neutral
  LINK-USDT  P=24.5  — (sin señal)
✅ Ciclo #1 completado - 1 señal(es) | 1 trade(s) abierto(s)
```

### Telegram

Deberías recibir:
1. **Notificación de inicio:** "🟡 BOT INICIADO v2.0"
2. **Notificación de señal:** "📈 LONG RSR-USDT | score=65"
3. **Heartbeat cada 1.5 horas:** Resumen del estado

---

## 🐛 Troubleshooting

### Problema: "Sin datos de BingX" para todo

**Causa:** API key sin permiso de lectura

**Solución:**
1. BingX → Profile → API Management
2. Crea nueva API key con ✅ Read activado
3. Railway → Variables → BINGX_API_KEY (nueva)
4. Redeploy

### Problema: Cero señales

**Posible causa:** Parámetros muy estrictos

**Soluciones:**
1. Bajar SCORE_MIN: 40 → 30 en `config.py`
2. Desactivar MTF_ENABLED: True → False
3. Desactivar VOLUME_FILTER: True → False

### Problema: No recibe notificaciones Telegram

**Verificar:**
```bash
# En Railway Logs, ejecuta:
python test_telegram.py
```

Si falla:
1. TELEGRAM_TOKEN incorrecto
2. TELEGRAM_CHAT_ID incorrecto (usar número, no nombre)
3. Nunca enviaste `/start` al bot

### Problema: Dashboard no carga

**Solución:**
1. Railway → tu proyecto → Deployments
2. Click en URL (mostrará error si no funciona)
3. Si está timeout, reduce DASHBOARD_ENABLED: False en config.py

---

## 📊 Monitoring

### Dashboard Web

URL: `https://tu-proyecto.railway.app`

Muestra en tiempo real:
- Balance actual
- Posiciones abiertas
- Últimos 30 trades
- Drawdown, Win Rate, Profit Factor

### Telegram Commands

```
/status     → Resumen completo
/balance    → Balance actual
/positions  → Posiciones abiertas
/pause      → Pausar bot
/resume     → Reactivar bot
/close LINK-USDT  → Cerrar posición
/help       → Ayuda
```

### Logs

**Railway Logs:**
```bash
# Filtrar por errors
"ERROR"

# Filtrar por signals
"SEÑAL"

# Filtrar por trades
"ORDEN ABIERTA"
```

---

## 🎛️ Tuning

### Aumentar frecuencia de trading

**Reduce `POLL_INTERVAL` en config.py:**
```python
POLL_INTERVAL = 600  # 10 min (en lugar de 900 = 15 min)
```

### Más conservador (menos señales)

```python
SCORE_MIN = 50       # De 40 a 50
RSI_LONG = 32        # De 36 a 32 (más restrictivo)
MTF_ENABLED = True   # Activar filtro 4h
```

### Más agresivo (más señales)

```python
SCORE_MIN = 25       # De 40 a 25
VOLUME_FILTER = False  # Desactivar filtro
MTF_ENABLED = False  # Desactivar 4h
```

---

## 📈 Phases de Operación

### Fase 1: PAPER (1-2 semanas)

```python
TRADE_MODE = "paper"
```

- Simula operaciones sin dinero real
- Revisa si las señales son sensatas
- Ajusta parámetros si es necesario
- Verifica stats en Dashboard

### Fase 2: LIVE (Capital pequeño)

```python
TRADE_MODE = "live"
INITIAL_BAL = 100  # Empieza con $100
```

- Abre órdenes reales en BingX
- Monitorea primeras 10 operaciones
- Si Win Rate < 50%, vuelve a PAPER
- Si Win Rate > 60%, aumenta capital

### Fase 3: LIVE (Capital grande)

```python
INITIAL_BAL = 1000  # O más según resultados
```

- Bot completamente operativo
- Monitorea drawdown < 20%
- Ajusta parámetros según mercado

---

## 🚨 Checklist Final

- [ ] Variables configuradas en Railway (API key, Telegram, etc)
- [ ] Deploy completado y en "Build successful"
- [ ] Logs muestran "BOT INICIADO" sin errores
- [ ] Primer ciclo completado exitosamente
- [ ] Recibo notificaciones en Telegram
- [ ] Dashboard carga sin errores
- [ ] En PAPER mode por 1 semana mínimo
- [ ] Luego activar LIVE mode con capital pequeño

---

## 📞 Support

Si tienes problemas:

1. **Revisa los logs** en Railway (últimas 100 líneas)
2. **Busca el error** en este doc (sección Troubleshooting)
3. **Ejecuta tests:** `python bot_v2_test.py`
4. **Verifica credenciales:** BingX API key, Telegram token

---

## 🎯 Próximos Pasos

1. ✅ Tests pasaron (8/8)
2. ⏳ Desplegar en Railway
3. ⏳ Esperar 3-5 ciclos (1-1.5 horas)
4. ⏳ Verificar que genera señales
5. ⏳ Cambiar a LIVE mode cuando confíes
6. ⏳ Monitorear progreso durante 2 semanas

---

**¡El bot está listo para producción!** 🚀

¿Dudas? Revisa los logs, ejecuta tests, ajusta config.
