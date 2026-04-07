# 🔧 GUÍA DE REPARACIÓN - BOT LONGS v5.6.1

## ❌ PROBLEMA IDENTIFICADO

**Error:** `SyntaxError: f-string expression part cannot include a backslash`
**Línea:** 558 en main.py
**Causa:** Python no permite usar backslashes (\n) directamente dentro de expresiones f-string

## ✅ SOLUCIÓN APLICADA

### Cambios realizados en v5.6.1:

1. **Línea 558 - aurolo_signal()**: 
   - ❌ ANTES: `result['descripcion'] = f"P1... \n P2..."`
   - ✅ AHORA: Construcción de string sin backslashes en f-strings

2. **Learning._reporte()**: 
   - ❌ ANTES: Múltiples f-strings con `\n` embebidos
   - ✅ AHORA: Construcción con listas y join()

3. **_report()**: 
   - ❌ ANTES: f-strings con saltos de línea directos
   - ✅ AHORA: Construcción segura de mensajes

## 📋 PASOS PARA IMPLEMENTAR EN RAILWAY

### 1. Actualizar el archivo main.py

Reemplaza tu `main.py` actual con el contenido del archivo corregido.

**Archivos a subir a tu repositorio:**
- `main.py` (versión corregida)
- `requirements.txt`
- `railway.toml`
- `.env.example` (NO subas el .env real con tus keys)

### 2. Configurar Variables de Entorno en Railway

En Railway Dashboard → Variables:

**OBLIGATORIAS:**
```
BINGX_API_KEY=tu_key_real
BINGX_API_SECRET=tu_secret_real
```

**RECOMENDADAS:**
```
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
AUTO_TRADING_ENABLED=true
MAX_POSITION_SIZE=10
LEVERAGE=2
MAX_OPEN_TRADES=3
```

### 3. Deploy en Railway

```bash
# 1. Commitear cambios
git add main.py requirements.txt railway.toml
git commit -m "Fix: f-string syntax errors v5.6.1"
git push origin main

# 2. Railway se redesplegará automáticamente
# Verifica logs en Railway Dashboard
```

### 4. Verificación

Revisa los logs en Railway Dashboard. Deberías ver:

```
✅ BingX conectado | $XXX.XX USDT
  Modo: HEDGE
  Contratos: XX
  Símbolos: XX
🚀 Bot LONGS v5.6.1 — Optimizado para rentabilidad
```

## 🐛 OTROS PROBLEMAS COMUNES

### Bot no abre trades:

1. **Verifica conectividad API:**
   - API Keys correctas
   - IP whitelisting en BingX (si aplica)

2. **Score demasiado alto:**
   - El bot está en modo "aprendizaje"
   - Después de 15 trades se auto-ajusta
   - Puedes bajar `MIN_SCORE=40` temporalmente

3. **Circuit breaker activo:**
   - Revisa `CIRCUIT_BREAKER_PCT`
   - Espera el tiempo de pausa configurado

### Bot crashea en Railway:

1. **Memory limit:**
   - Verifica uso de RAM en Dashboard
   - Railway free tier tiene límites

2. **Network timeout:**
   - BingX API puede estar caída temporalmente
   - El bot tiene retry logic incorporado

## 📊 MONITOREO

### Logs importantes:

```bash
# Conexión exitosa
✅ BingX conectado

# Escaneo funcionando
Escaneando 60 símbolos...

# Señal detectada
💡 SYMBOL [LONG_2/3] | Score:65/50 | RR:2.5:1

# Trade abierto
🟢 LONG [LONG_2/3] — SYMBOL

# Problemas
❌ API /endpoint: error
⚠️ LIMIT sin fill → MARKET
```

## 🔄 ROLLBACK (si necesitas volver atrás)

```bash
git revert HEAD
git push origin main
```

## 📞 SOPORTE

Si el problema persiste:
1. Revisa los logs completos de Railway
2. Verifica que todas las variables de entorno estén configuradas
3. Prueba en local primero: `python3 main.py`

## ✨ MEJORAS v5.6.1

- ✅ Syntax errors corregidos
- ✅ Better error handling
- ✅ Railway-optimized configuration
- ✅ Improved logging
