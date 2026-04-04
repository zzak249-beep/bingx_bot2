# 🤖 Bot Longs Rentable v2.0 - Guía de Uso

## 📋 Tabla de Contenidos

1. [Características Principales](#características-principales)
2. [Requisitos](#requisitos)
3. [Instalación](#instalación)
4. [Configuración](#configuración)
5. [Ejecución](#ejecución)
6. [Monitoreo](#monitoreo)
7. [Solución de Problemas](#solución-de-problemas)
8. [FAQ](#faq)

---

## ✨ Características Principales

### ✅ Mejoras vs v1.6:

- **87% menos comisiones** → Órdenes LIMIT siempre (0.02% vs 0.05%)
- **Matemática favorable** → RR 2:1 con expectativa positiva
- **Sin leverage o leverage mínimo** → Menos riesgo
- **Sistema de aprendizaje** → Mejora automáticamente
- **Circuit breakers efectivos** → Protección real del capital
- **Trading selectivo** → 1 trade a la vez, calidad > cantidad

### 📊 Resultados Esperados:

```
Con $10 capital inicial:
- Win Rate objetivo: 55-60%
- PnL por trade: +$0.191 promedio
- Rentabilidad mensual: +$14-20 (140-200%)
- Comisiones: <5% del PnL bruto
```

---

## 🔧 Requisitos

### Plataformas Compatibles:
- ✅ Railway
- ✅ Render
- ✅ Heroku
- ✅ VPS/Servidor propio
- ✅ Computadora local

### Python:
```bash
Python 3.8 o superior
```

### Dependencias:
```bash
requests
asyncio (incluido en Python 3.7+)
```

### Cuenta BingX:
- API Key con permisos de trading
- Saldo mínimo: $15-20 USDT recomendado
- Modo Hedge activado

### Telegram (opcional pero recomendado):
- Bot token
- Chat ID

---

## 📥 Instalación

### Opción 1: Railway (Recomendado)

1. **Fork del repositorio:**
   ```bash
   # Tu repo debe contener:
   - main_optimized.py
   - requirements.txt
   - railway.json (si aplica)
   ```

2. **Crear proyecto en Railway:**
   - Conectar con GitHub
   - Seleccionar repositorio
   - Railway detectará Python automáticamente

3. **Variables de entorno:**
   - Agregar todas las variables del archivo `.env.optimized`
   - Ver sección [Configuración](#configuración)

4. **Deploy:**
   - Railway hará deploy automático
   - Ver logs para confirmar inicio

### Opción 2: VPS/Local

1. **Clonar archivos:**
   ```bash
   mkdir bot_trading
   cd bot_trading
   # Copiar main_optimized.py y .env.optimized
   ```

2. **Instalar dependencias:**
   ```bash
   pip install requests
   ```

3. **Configurar variables:**
   ```bash
   # Renombrar y editar
   cp .env.optimized .env
   nano .env
   ```

4. **Ejecutar:**
   ```bash
   python3 main_optimized.py
   ```

---

## ⚙️ Configuración

### 1. Variables Obligatorias:

```bash
# Copiar de BingX
BINGX_API_KEY=tu_api_key_aqui
BINGX_API_SECRET=tu_secret_aqui

# Copiar de Telegram (opcional)
TELEGRAM_BOT_TOKEN=tu_bot_token
TELEGRAM_CHAT_ID=tu_chat_id
```

### 2. Configuración Inicial (CONSERVADORA):

```bash
# ¡NO MODIFICAR HASTA TENER EXPERIENCIA!
AUTO_TRADING_ENABLED=true
MAX_POSITION_SIZE=10          # $10 por trade
LEVERAGE=1                     # SIN leverage
TAKE_PROFIT_PCT=6.0           # TP 6%
STOP_LOSS_PCT=3.0             # SL 3%
MAX_OPEN_TRADES=1             # 1 trade a la vez
MIN_SCORE=95                  # Muy selectivo
CIRCUIT_BREAKER_USDT=1.5      # Stop tras -$1.5 diario
```

### 3. Telegram Bot (Muy Recomendado):

**Crear bot:**
1. Abrir @BotFather en Telegram
2. Enviar `/newbot`
3. Seguir instrucciones
4. Copiar token

**Obtener Chat ID:**
1. Abrir @userinfobot
2. Enviar cualquier mensaje
3. Copiar "Id"

---

## 🚀 Ejecución

### Fase 1: Paper Trading (Semana 1)

**Objetivo:** Observar sin arriesgar dinero real

```bash
# En .env:
AUTO_TRADING_ENABLED=false

# Ejecutar:
python3 main_optimized.py
```

**Qué observar:**
- ✅ Cuántas señales genera por hora
- ✅ Score promedio de señales
- ✅ Win rate simulado
- ✅ Símbolos más frecuentes

**Criterio de éxito:**
- Al menos 10 señales en la semana
- Win rate simulado >50%
- Sin errores de ejecución

### Fase 2: Trading Real (Semana 2)

**Activar trading:**

```bash
# En .env:
AUTO_TRADING_ENABLED=true
MAX_POSITION_SIZE=10
LEVERAGE=1
MAX_OPEN_TRADES=1
```

**Monitorear de cerca:**
- ✅ Primer trade abre correctamente
- ✅ TP/SL se colocan bien
- ✅ Cierre funciona (TP o SL)
- ✅ Comisiones son bajas (~$0.004/trade)

**Objetivo semana 2:**
- PnL: +$2 a +5 mínimo
- Win rate: >45%
- Sin errores técnicos

### Fase 3: Optimización (Semana 3+)

**Si semana 2 fue exitosa:**

```bash
# Puedes considerar (OPCIONAL):

# Opción A: Aumentar capital
MAX_POSITION_SIZE=15

# Opción B: Leverage moderado
LEVERAGE=2

# Opción C: Más trades simultáneos
MAX_OPEN_TRADES=2

# ⚠️ NUNCA cambiar todo a la vez!
# Solo un parámetro por semana
```

---

## 📊 Monitoreo

### Dashboard Telegram:

El bot envía mensajes automáticos:

```
🟢 LONG ABIERTO
BTC-USDT
Score: 98/95 | RSI: 32 | RR: 2.0:1
Entrada: $98,234.50
✅ TP: $104,328.57 (+6.0%)
✅ SL: $95,307.47 (-3.0%)
Capital: $10x1 | Comisión: $0.004
PnL día: +$0.45
```

```
✅ LONG CERRADO — TAKE PROFIT
BTC-USDT
PnL: +$0.58 (+5.8%) | 47min
Entrada: $98,234.50 → Salida: $104,120.00
Comisiones: $0.004
Total: +$2.34 | WR: 58.3%
Día: +$0.58
```

### Reportes Horarios:

```
📊 Reporte LONGS v2.0
PnL total: +$3.45 | WR: 57.1%
PnL día: +$0.82 (límite: -$1.50)
Comisiones pagadas: $0.08
(8W / 6L | 14 trades)
Abiertos: 1/1 | BTC: +1.2%
Circuit: 🔓 OK
  BTC-USDT: +2.3%

Mejores señales:
  RSI<30: 75.0% (4 trades)
  EMA↑: 62.5% (8 trades)
```

### Logs en Consola:

```bash
================================================================================
  Iteración #42 | 15:23:45
  Abiertos: 1/1 | PnL: +$2.45 | WR: 55.6%
  BTC: +0.8% 🟢 OK | ✅ | Score mín: 95.0
  Día: +$0.67 | Fees: $0.12
================================================================================

  💡 Señal: ETH-USDT | Score: 102.0 | RSI: 28.0
  🎯 LONG ETH-USDT
  Score: 102.0/95.0 | RSI: 28.0 | RR: 2.1:1
  EMA↑(30) | RSI28(32) | Vol2.1x(15) | NearLow(15)
  
  ⚙️  Leverage ETH-USDT → 1x
  📊 ETH-USDT: 4.2 cts × $594.05 = $10.00 notional
  ✅ LIMIT BUY @ $593.52 | OID: 123456789
  ✅ Ejecutada: 4.2 @ $593.52
  ✅ Posición confirmada: 4.2 @ $593.52
  ✅ TP @ $629.53
  ✅ SL @ $575.72
```

---

## 🔍 Indicadores Clave

### ✅ Señales de que funciona bien:

1. **Win Rate 52-60%**
2. **PnL semanal positivo**
3. **Comisiones <5% del PnL bruto**
4. **Circuit breaker se activa <1 vez/semana**
5. **Sistema de aprendizaje ajusta score**

### ⚠️ Señales de alerta:

1. **Win Rate <45% por >20 trades**
   - Acción: Aumentar MIN_SCORE a 100
   
2. **Pérdidas consecutivas >5**
   - Acción: Pausar 24h, revisar mercado
   
3. **Circuit breaker diario frecuente**
   - Acción: Reducir MAX_POSITION_SIZE
   
4. **Comisiones >10% del PnL**
   - Acción: Verificar que usa LIMIT orders

---

## 🛠️ Solución de Problemas

### Error: "CRITICO: no confirmada"

**Causa:** Orden LIMIT no se ejecutó en 30s

**Solución:**
```bash
# El bot intenta MARKET automáticamente
# Si persiste, verificar:
- Saldo suficiente en cuenta
- Símbolo existe en BingX
- No hay mantenimiento de BingX
```

### Error: "[109400] Hedge mode"

**Causa:** BingX en modo Hedge pero comando no compatible

**Solución:**
```
El bot v2.0 ya está adaptado a Hedge mode
Si ves este error:
1. Actualizar a última versión del código
2. Verificar que no hay modificaciones manuales
```

### Error: "SL crítico fallido - cerrando"

**Causa:** No se pudo colocar Stop Loss

**Solución:**
```
El bot cierra la posición por seguridad (CORRECTO)
Verificar:
- API Key tiene permisos de trading
- No hay límite de órdenes activas
- Reintentar trade en siguiente señal
```

### Win Rate muy bajo (<40%):

**Diagnóstico:**
1. Ver `trade_history.json`
2. Identificar scores perdedores
3. Revisar símbolos en blacklist

**Acciones:**
```bash
# Aumentar selectividad:
MIN_SCORE=100

# Reducir símbolos:
MAX_SYMBOLS_TO_ANALYZE=20

# Filtro BTC más estricto:
BTC_MIN_TREND_PCT=0.5
```

### Circuit breaker activo constantemente:

**Causa:** Pérdidas superan -$1.5 diario frecuentemente

**Solución:**
```bash
# Opción 1: Más conservador
MAX_POSITION_SIZE=8
MIN_SCORE=100

# Opción 2: Umbral más alto (NO recomendado)
CIRCUIT_BREAKER_USDT=2.5  # -25% capital

# Opción 3: Pausar y revisar estrategia
AUTO_TRADING_ENABLED=false
# Analizar logs y ajustar
```

---

## ❓ FAQ

### ¿Cuánto capital necesito?

**Mínimo:** $15 USDT
**Recomendado:** $50-100 USDT
**Ideal:** $200+ USDT para absorber drawdowns

### ¿Puedo usar más leverage?

**Sí, pero NO es recomendado inicialmente:**
- Leverage 1x: Seguro, aprende el sistema
- Leverage 2x: Moderado, tras 1 mes exitoso
- Leverage 3x+: Alto riesgo, solo expertos

### ¿Por qué solo 1 trade a la vez?

**Beneficios:**
- ✅ Enfoque total en el trade activo
- ✅ Menos exposición = menos riesgo
- ✅ Más fácil monitorear
- ✅ Mejor gestión emocional

Puedes subir a 2-3 tras demostrar consistencia.

### ¿Cuánto tiempo dedicar al bot?

**Mínimo diario:**
- 5 min: Revisar Telegram (mensajes del bot)
- 10 min: Ver logs si hubo trades
- 30 min: Análisis semanal de resultados

**No requiere:**
- ❌ Monitoreo 24/7
- ❌ Intervención manual en trades
- ❌ Ajustes diarios de parámetros

### ¿Funciona en mercado bajista?

**Limitado:**
- El bot es LONGS only (compra)
- Necesita BTC alcista (>0.3%)
- En bear market fuerte: se pausa automáticamente
- Considera versión SHORTS en bear market

### ¿Qué pasa si se cae mi servidor?

**Posiciones abiertas:**
- TP/SL están en BingX → se ejecutarán
- Bot recupera posiciones al reiniciar
- Minimal impacto si downtime <30 min

**Prevención:**
- Usar Railway/Render (alta disponibilidad)
- Telegram notifica si bot se detiene

### ¿Puedo modificar el código?

**Sí, pero con cuidado:**
- ✅ Ajustar parámetros en `.env`
- ✅ Agregar símbolos a whitelist
- ⚠️ Modificar lógica de scoring (testar antes)
- ❌ Quitar circuit breakers
- ❌ Eliminar comisiones de cálculos

### ¿Es rentable garantizado?

**NO:**
- Trading tiene riesgo inherente
- Resultados pasados ≠ futuros
- Mercado crypto es volátil
- Solo arriesga lo que puedas perder

**Pero:**
- Matemática es favorable
- Sistema de aprendizaje mejora con tiempo
- Con disciplina, probabilidades a tu favor

---

## 📞 Soporte

### Recursos:

- 📄 **Análisis completo:** `ANALISIS_MEJORAS.md`
- 📊 **Configuración:** `.env.optimized`
- 🐛 **Issues:** Revisar logs y Telegram

### Comunidad:

- Comparte resultados (sin mostrar API keys)
- Ayuda a otros usuarios
- Reporta bugs encontrados

---

## ⚖️ Disclaimer Legal

```
ESTE SOFTWARE SE PROPORCIONA "TAL CUAL", SIN GARANTÍA DE NINGÚN TIPO.

Trading de criptomonedas involucra riesgo sustancial de pérdida.
Solo opera con capital que puedas permitirte perder.

Los desarrolladores NO son responsables de:
- Pérdidas financieras
- Errores de configuración
- Problemas con APIs de terceros
- Cambios en regulaciones

Usa bajo tu propio riesgo y responsabilidad.
```

---

## 📝 Changelog

### v2.0 (2026-04-04)
- ✅ Reducción 87% comisiones (LIMIT orders)
- ✅ Sistema de aprendizaje integrado
- ✅ Circuit breakers efectivos
- ✅ Matemática favorable (RR 2:1)
- ✅ Sin leverage por defecto
- ✅ Trading selectivo (1 trade)
- ✅ Filtros BTC estrictos

### v1.6 (anterior)
- ❌ Comisiones altas (MARKET)
- ❌ Sin aprendizaje
- ❌ Circuit breaker inútil
- ❌ RR desfavorable
- ❌ Leverage 3x riesgoso

---

**¡Feliz trading! 🚀**

Recuerda: Paciencia, disciplina y gestión de riesgo son clave para el éxito a largo plazo.
