# 🚀 QUICK START - 5 MINUTOS AL AIRE

## Necesitas tener listo:

1. ✅ API Key de BingX (con permisos Read + Trade)
2. ✅ Token de bot de Telegram (@BotFather)
3. ✅ Tu Chat ID de Telegram (@userinfobot)
4. ✅ Cuenta en GitHub
5. ✅ Cuenta en Railway.app

---

## Paso 1: Subir a GitHub (2 min)

```bash
git init
git add .
git commit -m "initial deploy"

# Crear repo PRIVADO en github.com/new
git remote add origin https://github.com/TU_USUARIO/saty-bot.git
git branch -M main
git push -u origin main
```

---

## Paso 2: Railway Deploy (2 min)

1. Ve a https://railway.app
2. New Project → Deploy from GitHub
3. Conecta GitHub → Selecciona tu repo
4. Añade estas 4 variables (Variables → RAW Editor):

```
BINGX_API_KEY=tu_key_aqui
BINGX_API_SECRET=tu_secret_aqui
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

5. Click "Update Variables"

---

## Paso 3: Verificar (1 min)

Railway → Deployments → Ver logs:

```
✓ SATY ELITE v11 — REAL MONEY
✓ Exchange conectado ✓
✓ Balance: $XXX.XX USDT
```

Telegram → Recibirás mensaje de arranque

---

## 🎯 LISTO - Bot operando 24/7

**Variables opcionales** (tienen defaults optimizados):
- Solo cambia si tienes capital > $200
- Ver archivo `railway_variables.txt` para configuraciones avanzadas

**Costos**: Railway Hobby Plan $5/mes (recomendado)

**⚠️ IMPORTANTE**: 
- Repo debe ser PRIVADO
- Nunca actives "Withdraw" en API de BingX
- Empieza con capital pequeño ($50-100)

---

Ver `RESUMEN_EJECUTIVO.md` para guía completa.
