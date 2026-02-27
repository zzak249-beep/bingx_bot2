╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║              🚀 SATY ELITE v11 - DEPLOYMENT RAILWAY               ║
║                   Bot de Trading 24/7 Verificado                  ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝


✅ ESTADO: TODOS LOS ARCHIVOS VERIFICADOS Y LISTOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 PASO 1: OBTENER CREDENCIALES (15 minutos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── BingX API ───────────────────────────────────────────────────┐
│                                                                  │
│  1. Ve a: https://bingx.com                                      │
│  2. Login → Perfil → API Management                              │
│  3. Create API Key con permisos:                                 │
│     ✅ Read    (leer balance y posiciones)                       │
│     ✅ Trade   (abrir/cerrar órdenes)                            │
│     ❌ Withdraw (NUNCA activar)                                  │
│  4. Guarda:                                                      │
│     - API Key                                                    │
│     - API Secret                                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Telegram Bot ────────────────────────────────────────────────┐
│                                                                  │
│  1. Abre Telegram → busca @BotFather                             │
│  2. Escribe: /newbot                                             │
│  3. Sigue instrucciones → copia el TOKEN                         │
│                                                                  │
│  Para obtener Chat ID:                                           │
│  • Busca @userinfobot en Telegram                                │
│  • Envíale cualquier mensaje                                     │
│  • Te devolverá tu Chat ID                                       │
│                                                                  │
│  Para grupo (recomendado):                                       │
│  • Crea grupo en Telegram                                        │
│  • Añade tu bot al grupo                                         │
│  • Añade @userinfobot al grupo                                   │
│  • Copia el Chat ID (empieza con -100...)                        │
│  • Elimina @userinfobot                                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


📦 PASO 2: SUBIR A GITHUB (5 minutos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

En tu terminal (dentro de la carpeta del proyecto):

```bash
# Inicializar Git
git init
git add .
git commit -m "SATY ELITE v11 - initial deploy"

# Crear repo en GitHub
# Ve a: https://github.com/new
# Nombre: saty-elite-v11
# ⚠️ IMPORTANTE: Marca como PRIVADO

# Conectar y pushear
git remote add origin https://github.com/TU_USUARIO/saty-elite-v11.git
git branch -M main
git push -u origin main
```

⚠️ CRÍTICO: El repositorio DEBE ser PRIVADO (contiene tu estructura de trading)


🚂 PASO 3: CONFIGURAR RAILWAY (10 minutos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Crear Proyecto ──────────────────────────────────────────────┐
│                                                                  │
│  1. Ve a: https://railway.app                                    │
│  2. Click en "New Project"                                       │
│  3. Selecciona "Deploy from GitHub repo"                         │
│  4. Conecta tu cuenta GitHub                                     │
│  5. Selecciona: saty-elite-v11                                   │
│  6. Railway detectará Procfile automáticamente                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Variables de Entorno (Railway → Variables) ─────────────────┐
│                                                                  │
│  MÉTODO 1: RAW EDITOR (Más rápido)                              │
│  ────────────────────────────────────                            │
│  1. Click en pestaña "Variables"                                │
│  2. Click en "RAW Editor" (arriba derecha)                       │
│  3. Pega este contenido:                                         │
│                                                                  │
│     BINGX_API_KEY=tu_api_key_aqui                                │
│     BINGX_API_SECRET=tu_secret_aqui                              │
│     TELEGRAM_BOT_TOKEN=123456:ABC...                             │
│     TELEGRAM_CHAT_ID=-1001234567890                              │
│                                                                  │
│     FIXED_USDT=8                                                 │
│     MAX_OPEN_TRADES=12                                           │
│     MIN_SCORE=4                                                  │
│     MAX_DRAWDOWN=15                                              │
│     DAILY_LOSS_LIMIT=8                                           │
│     MIN_VOLUME_USDT=100000                                       │
│     TOP_N_SYMBOLS=300                                            │
│     MAX_SPREAD_PCT=1.0                                           │
│     BTC_FILTER=true                                              │
│                                                                  │
│  4. Click "Update Variables"                                     │
│                                                                  │
│  ────────────────────────────────────                            │
│  MÉTODO 2: Variable por Variable                                │
│  ────────────────────────────────────                            │
│  1. Click "+ New Variable"                                       │
│  2. Añade cada variable manualmente                              │
│  3. Click "Add" por cada una                                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


🔧 CONFIGURACIONES POR CAPITAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Capital Pequeño: $50-$200 (Conservador) ─────────────────────┐
│                                                                  │
│  FIXED_USDT=5                                                    │
│  MAX_OPEN_TRADES=8                                               │
│  MIN_SCORE=5                                                     │
│  MAX_DRAWDOWN=12                                                 │
│  DAILY_LOSS_LIMIT=6                                              │
│  MIN_VOLUME_USDT=500000                                          │
│  TOP_N_SYMBOLS=100                                               │
│  MAX_SPREAD_PCT=0.5                                              │
│  BTC_FILTER=true                                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Capital Medio: $200-$1000 (Balanceado) ──────────────────────┐
│                                                                  │
│  FIXED_USDT=10                                                   │
│  MAX_OPEN_TRADES=12                                              │
│  MIN_SCORE=4                                                     │
│  MAX_DRAWDOWN=15                                                 │
│  DAILY_LOSS_LIMIT=8                                              │
│  MIN_VOLUME_USDT=100000                                          │
│  TOP_N_SYMBOLS=300                                               │
│  MAX_SPREAD_PCT=1.0                                              │
│  BTC_FILTER=true                                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Capital Grande: $1000+ (Agresivo) ───────────────────────────┐
│                                                                  │
│  FIXED_USDT=25                                                   │
│  MAX_OPEN_TRADES=15                                              │
│  MIN_SCORE=4                                                     │
│  MAX_DRAWDOWN=15                                                 │
│  DAILY_LOSS_LIMIT=10                                             │
│  MIN_VOLUME_USDT=100000                                          │
│  TOP_N_SYMBOLS=300                                               │
│  MAX_SPREAD_PCT=1.0                                              │
│  BTC_FILTER=false                                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


✅ PASO 4: VERIFICAR QUE FUNCIONA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── En Railway (Logs) ───────────────────────────────────────────┐
│                                                                  │
│  1. Ve a: Deployments → Build Logs                              │
│  2. Espera el build (~2-3 minutos)                               │
│  3. Verifica logs:                                               │
│     ✓ "=== SATY ELITE v11 — REAL MONEY · 12 TRADES · 24/7"      │
│     ✓ "Exchange conectado ✓"                                     │
│     ✓ "Modo cuenta: HEDGE" (o ONE-WAY)                           │
│     ✓ "Balance: $XXX.XX USDT"                                    │
│     ✓ "━━━ SCAN #1 ... | 300 pares | 0/12 trades ━━━"            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── En Telegram ─────────────────────────────────────────────────┐
│                                                                  │
│  Deberías recibir un mensaje como:                               │
│                                                                  │
│  🚀 SATY ELITE v11 INICIADO                                      │
│  💰 Balance: $XXX.XX USDT                                        │
│  🎯 12 trades · 300 pares · score≥4                              │
│  📊 Universo: 300 pares disponibles                              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


🔴 TROUBLESHOOTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Problema: "DRY-RUN: sin claves API" ─────────────────────────┐
│                                                                  │
│  ❌ Causa: Variables BINGX_API_KEY o BINGX_API_SECRET faltantes │
│  ✅ Solución: Railway → Variables → añadir ambas claves          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: "No se pudo conectar al exchange" ─────────────────┐
│                                                                  │
│  ❌ Causa: Claves incorrectas o sin permisos                     │
│  ✅ Solución: Verificar en BingX:                                │
│     • API Key activa                                             │
│     • Permisos: Read + Trade (NO Withdraw)                       │
│     • IP whitelist vacía (o IP de Railway)                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: No recibo mensajes de Telegram ───────────────────┐
│                                                                  │
│  ❌ Causa: TOKEN o CHAT_ID incorrectos                           │
│  ✅ Solución:                                                    │
│     • Verifica TOKEN con @BotFather                              │
│     • Verifica CHAT_ID con @userinfobot                          │
│     • Si es grupo: el bot debe estar en el grupo                 │
│     • Chat ID de grupo empieza con -100...                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: Build falla en Railway ───────────────────────────┐
│                                                                  │
│  ❌ Causa: Archivos del proyecto incorrectos                     │
│  ✅ Solución: Verificar que existan:                             │
│     • bot.py                                                     │
│     • requirements.txt                                           │
│     • Procfile                                                   │
│     • railway.toml                                               │
│     • runtime.txt                                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: "Circuit breaker activated" ──────────────────────┐
│                                                                  │
│  ✅ Esto es NORMAL - protección automática                       │
│  • El bot se detiene si pérdida > MAX_DRAWDOWN (15%)            │
│  • Reinicia el service en Railway para continuar                │
│  • Considera reducir FIXED_USDT o MAX_OPEN_TRADES               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


💰 COSTOS RAILWAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Free Tier:   ~500 horas/mes (suficiente para pruebas)
Hobby Plan:  $5/mes (recomendado, sin límites)

💡 El bot consume muy pocos recursos. El Hobby Plan es más que suficiente.


📊 ALERTAS DE TELEGRAM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Una vez funcionando, recibirás:

⚡ ENTRADA:     Cada vez que abre un trade
🎯 TP1 (50%):   Primera toma de ganancias
🏆 TP2 (100%):  Ganancia completa
🛑 STOP LOSS:   Pérdida
📊 RESUMEN:     Cada 20 ciclos (~20 minutos)
💓 HEARTBEAT:   Cada hora (balance + stats)


⚠️ ADVERTENCIAS IMPORTANTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 DINERO REAL
   Este bot opera con fondos reales. Empieza con capital pequeño.

🔴 REPO PRIVADO
   Nunca hagas público el repositorio GitHub. Contiene tu estrategia.

🔴 SIN GARANTÍAS
   El trading conlleva riesgo de pérdida total del capital.

🔴 MONITORIZA
   Revisa logs de Railway y alertas de Telegram diariamente.

🔴 CLAVES API
   Si expones tus claves, revócalas INMEDIATAMENTE en BingX.

🔴 PERMISSIONS
   NUNCA actives "Withdraw" en los permisos de la API.


🔄 ACTUALIZAR EL BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para actualizar el código:

```bash
git add .
git commit -m "update: descripción del cambio"
git push
```

Railway redesplegará automáticamente en ~2 minutos.


═══════════════════════════════════════════════════════════════════

            ✅ TODO VERIFICADO Y LISTO PARA DEPLOYAR

═══════════════════════════════════════════════════════════════════

📁 Archivos incluidos en este paquete:

  • bot.py                    → Código del bot (verificado ✓)
  • requirements.txt          → Dependencias Python (verificado ✓)
  • Procfile                  → Configuración Railway (verificado ✓)
  • railway.toml              → Configuración Railway (verificado ✓)
  • runtime.txt               → Python 3.11 (verificado ✓)
  • .gitignore                → Protección archivos sensibles
  • RAILWAY_SETUP.md          → Guía completa
  • railway_variables.txt     → Variables para copiar/pegar
  • verify.sh                 → Script de verificación
  • RESUMEN_EJECUTIVO.md      → Este archivo

═══════════════════════════════════════════════════════════════════

            🚀 ¡ÉXITO EN TU TRADING ALGORÍTMICO!

═══════════════════════════════════════════════════════════════════
