# 🔧 SOLUCIÓN AL ERROR: "can't open file 'main_jofs.py'"

## ❌ El Problema

Railway está intentando ejecutar `/app/main_jofs.py` en lugar de `/app/main.py`

```
python: can't open file '/app/main_jofs.py': [Errno 2] No such file or directory
```

---

## ✅ SOLUCIÓN RÁPIDA (5 minutos)

### Opción 1: Redesplegar desde GitHub (RECOMENDADO)

1. **Elimina el deployment actual en Railway**:
   - Ve a tu proyecto en Railway
   - Settings → Danger Zone → Delete Service
   - Confirma la eliminación

2. **Crea un nuevo proyecto**:
   - New Project → Deploy from GitHub repo
   - Selecciona tu repositorio
   - Railway detectará automáticamente el Dockerfile

3. **Configura variables de entorno**:
   ```
   BINGX_API_KEY=tu_key
   BINGX_API_SECRET=tu_secret
   TELEGRAM_BOT_TOKEN=tu_token
   TELEGRAM_CHAT_ID=tu_chat_id
   SYMBOLS=BTC-USDT,ETH-USDT,SOL-USDT
   TIMEFRAME=15m
   CHECK_INTERVAL=60
   MAX_POSITION_SIZE=100
   MAX_POSITIONS=3
   ```

4. **Deploy automático** ✅

---

### Opción 2: Forzar Rebuild

1. **Ve a tu proyecto en Railway**
2. **Deployments → Latest deployment**
3. **⋯ (tres puntos) → Redeploy**
4. Espera a que termine el rebuild

---

### Opción 3: Limpiar y Actualizar Repository

En tu terminal local:

```bash
# 1. Asegúrate de tener todos los archivos actualizados
cd trading-bot

# 2. Elimina archivos problemáticos
rm -f Procfile  # SI EXISTE, elimínalo

# 3. Verifica que main.py existe
ls -l main.py  # Debe mostrar el archivo

# 4. Commit y push
git add .
git commit -m "Fix: eliminar Procfile conflictivo"
git push origin main

# 5. Railway redesplegará automáticamente
```

---

## 🔍 VERIFICACIÓN

Después del redespliegue, los logs deben mostrar:

```
✅ Successfully built imagen
✅ Container started
✅ 🤖 Bot inicializado - Pares: 3, Timeframe: 15m
```

**NO debe aparecer**: `can't open file 'main_jofs.py'`

---

## 📋 ARCHIVOS NECESARIOS EN EL REPOSITORIO

Asegúrate de tener estos archivos:

```
✅ main.py                  (BOT PRINCIPAL)
✅ strategy.py
✅ bingx_client.py
✅ telegram_notifier.py
✅ requirements.txt
✅ Dockerfile
✅ railway.json
✅ .env.example
✅ .gitignore

❌ Procfile               (ELIMINAR SI EXISTE)
```

---

## 🚨 SI EL PROBLEMA PERSISTE

### 1. Verificar Dockerfile

Asegúrate de que `Dockerfile` contiene:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### 2. Verificar railway.json

Debe contener:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "python main.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### 3. Verificar estructura en GitHub

Ve a tu repositorio en GitHub y verifica que `main.py` esté en la raíz:

```
tu-repo/
├── main.py          ← DEBE ESTAR AQUÍ
├── strategy.py
├── bingx_client.py
└── ...
```

**NO debe estar en subcarpetas**.

---

## 💡 CAUSA DEL ERROR

El error `main_jofs.py` sugiere que:

1. **Había un Procfile mal configurado** que Railway leyó primero
2. **O un archivo corrupto** en el deployment anterior
3. **O Railway cacheó configuración antigua**

**Solución**: Redesplegar limpiamente desde GitHub.

---

## ✅ PASOS FINALES

Una vez resuelto, deberías ver en los logs de Railway:

```
🤖 Bot inicializado - Pares: 3, Timeframe: 15m
🚀 Iniciando loop de trading...
```

Y en Telegram:

```
🤖 Bot Multi-Par Iniciado

📊 Analizando 3 pares:
  • BTC-USDT
  • ETH-USDT
  • SOL-USDT

⏱ Timeframe: 15m
💰 Max posiciones: 3
📦 Tamaño por posición: $100
```

---

## 🆘 ¿Aún no funciona?

1. Descarga todos los archivos del proyecto nuevamente
2. Crea un repositorio completamente nuevo en GitHub
3. Sube los archivos al nuevo repositorio
4. Crea un nuevo proyecto en Railway
5. Conecta el nuevo repositorio

**Esto garantiza un inicio limpio sin archivos residuales.**

---

**¡El problema se solucionará con un redespliegue limpio! 🚀**
