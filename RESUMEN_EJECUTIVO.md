╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║           🚀 SATY ELITE v13 — FULL STRATEGY EDITION              ║
║         UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI            ║
║                   Bot de Trading 24/7 Verificado                  ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝


✅ ESTADO: TODOS LOS ARCHIVOS VERIFICADOS Y LISTOS — v13
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🆕 NOVEDADES v13 vs v12
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Score: 12 → 16 puntos (4 Pine Scripts integrados)

  ┌── 🤖 Punto 13: UTBot (HPotter / Yo_adriiiiaan) ────────────────┐
  │  · ATR Trailing Stop como señal de entrada y salida            │
  │  · Variables: UTBOT_KEY_VALUE=10, UTBOT_ATR_PERIOD=10         │
  └────────────────────────────────────────────────────────────────┘
  ┌── 🌊 Punto 14: WaveTrend (Instrument-Z / OscillateMatrix) ─────┐
  │  · TCI oscillator — cruces en zonas OB/OS                      │
  │  · Trade Expiration y Minimum Profit integrados                │
  │  · Variables: WT_CHAN_LEN, WT_AVG_LEN, WT_OB, WT_OS           │
  │              TRADE_EXPIRE_BARS, MIN_PROFIT_PCT                 │
  └────────────────────────────────────────────────────────────────┘
  ┌── 📐 Punto 15: Bj Bot (3Commas framework) ─────────────────────┐
  │  · R:R dinámico: TP/SL desde swing pivots + ATR buffer         │
  │  · TP2 = entrada + RNR × riesgo. TP1 = punto medio            │
  │  · R:R trail trigger (rrExit): trailing agresivo al X% del TP  │
  │  · Variables: RNR=2.0, RISK_MULT=1.0, RR_EXIT=0.5, SWING_LB  │
  └────────────────────────────────────────────────────────────────┘
  ┌── 📊 Punto 16: BB+RSI (rouxam / DCA 3commas) ──────────────────┐
  │  · Bollinger Bands con filtro RSI                               │
  │  · Buy: precio < banda inferior + RSI < umbral                 │
  │  · Variables: BB_PERIOD=20, BB_STD=2.0, BB_RSI_OB=65          │
  └────────────────────────────────────────────────────────────────┘


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
│  2. Escribe: /newbot → sigue instrucciones → copia el TOKEN      │
│                                                                  │
│  Para obtener Chat ID:                                           │
│  • Busca @userinfobot en Telegram                                │
│  • Envíale cualquier mensaje → te devuelve tu Chat ID            │
│                                                                  │
│  Para grupo (recomendado):                                       │
│  • Crea grupo → añade tu bot + @userinfobot                      │
│  • Copia el Chat ID (empieza con -100...)                        │
│  • Elimina @userinfobot del grupo                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


📦 PASO 2: SUBIR A GITHUB (5 minutos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

En tu terminal (dentro de la carpeta del proyecto):

```bash
# Inicializar Git
git init
git add .
git commit -m "SATY ELITE v13 - initial deploy"

# Crear repo en GitHub
# Ve a: https://github.com/new
# Nombre: saty-elite-v13
# ⚠️ IMPORTANTE: Marca como PRIVADO

# Conectar y pushear
git remote add origin https://github.com/TU_USUARIO/saty-elite-v13.git
git branch -M main
git push -u origin main
```

⚠️ CRÍTICO: El repositorio DEBE ser PRIVADO


🚂 PASO 3: CONFIGURAR RAILWAY (10 minutos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Crear Proyecto ──────────────────────────────────────────────┐
│                                                                  │
│  1. Ve a: https://railway.app                                    │
│  2. Click en "New Project"                                       │
│  3. Selecciona "Deploy from GitHub repo"                         │
│  4. Conecta tu cuenta GitHub                                     │
│  5. Selecciona: saty-elite-v13                                   │
│  6. Railway detectará Procfile automáticamente                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Variables de Entorno (Railway → Variables) ─────────────────┐
│                                                                  │
│  MÉTODO RECOMENDADO: RAW EDITOR                                 │
│  ────────────────────────────────────                            │
│  1. Click en pestaña "Variables"                                │
│  2. Click en "RAW Editor" (arriba derecha)                       │
│  3. Pega este contenido mínimo:                                  │
│                                                                  │
│     BINGX_API_KEY=tu_api_key_aqui                                │
│     BINGX_API_SECRET=tu_secret_aqui                              │
│     TELEGRAM_BOT_TOKEN=123456:ABC...                             │
│     TELEGRAM_CHAT_ID=-1001234567890                              │
│                                                                  │
│  4. Click "Update Variables"                                     │
│                                                                  │
│  VARIABLES NUEVAS v13 (opcionales, tienen defaults):             │
│  ────────────────────────────────────                            │
│     UTBOT_KEY_VALUE=10                                           │
│     UTBOT_ATR_PERIOD=10                                          │
│     WT_CHAN_LEN=9                                                │
│     WT_AVG_LEN=12                                               │
│     WT_OB=60                                                     │
│     WT_OS=-60                                                    │
│     RNR=2.0                                                      │
│     RISK_MULT=1.0                                                │
│     RR_EXIT=0.5                                                  │
│     BB_PERIOD=20                                                 │
│     BB_STD=2.0                                                   │
│     BB_RSI_OB=65                                                 │
│     MIN_SCORE=5                                                  │
│     TRADE_EXPIRE_BARS=0                                          │
│                                                                  │
│  Ver railway_variables.txt para la lista completa               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


🔧 CONFIGURACIONES POR CAPITAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Capital Pequeño: $50-$200 (Conservador) ─────────────────────┐
│                                                                  │
│  FIXED_USDT=5                                                    │
│  MAX_OPEN_TRADES=8                                               │
│  MIN_SCORE=8                                                     │
│  MAX_DRAWDOWN=12                                                 │
│  DAILY_LOSS_LIMIT=6                                              │
│  MIN_VOLUME_USDT=500000                                          │
│  TOP_N_SYMBOLS=100                                               │
│  MAX_SPREAD_PCT=0.5                                              │
│  BTC_FILTER=true                                                 │
│  UTBOT_KEY_VALUE=14                                              │
│  RNR=2.0                                                         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Capital Medio: $200-$1000 (Balanceado) ──────────────────────┐
│                                                                  │
│  FIXED_USDT=10                                                   │
│  MAX_OPEN_TRADES=12                                              │
│  MIN_SCORE=5                                                     │
│  MAX_DRAWDOWN=15                                                 │
│  DAILY_LOSS_LIMIT=8                                              │
│  MIN_VOLUME_USDT=100000                                          │
│  TOP_N_SYMBOLS=300                                               │
│  MAX_SPREAD_PCT=1.0                                              │
│  BTC_FILTER=true                                                 │
│  UTBOT_KEY_VALUE=10                                              │
│  RNR=2.0                                                         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌─── Capital Grande: $1000+ (Agresivo) ───────────────────────────┐
│                                                                  │
│  FIXED_USDT=25                                                   │
│  MAX_OPEN_TRADES=15                                              │
│  MIN_SCORE=5                                                     │
│  MAX_DRAWDOWN=15                                                 │
│  DAILY_LOSS_LIMIT=10                                             │
│  MIN_VOLUME_USDT=100000                                          │
│  TOP_N_SYMBOLS=300                                               │
│  MAX_SPREAD_PCT=1.0                                              │
│  BTC_FILTER=false                                                │
│  UTBOT_KEY_VALUE=8                                               │
│  RNR=2.5                                                         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


✅ PASO 4: VERIFICAR DEPLOYMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── En Railway (Logs) ───────────────────────────────────────────┐
│                                                                  │
│  1. Ve a: Deployments → Build Logs                              │
│  2. Espera el build (~2-3 minutos)                               │
│  3. Verifica logs:                                               │
│     ✓ "SATY ELITE v13 — FULL STRATEGY EDITION"                  │
│     ✓ "UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI"           │
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
│  🚀 SATY ELITE v13 — FULL STRATEGY EDITION                       │
│  🌍 Universo: 300 pares | Vol≥$100K                              │
│  🎯 Score min: 5/16 | Max trades: 12                             │
│  📊 SMI(10,3,10) OB:+40/-40                                      │
│  🌊 WaveTrend(9,12) OB:60/OS:-60                                 │
│  🤖 UTBot KeyVal:10 ATR:10                                       │
│  📈 BB(20,2.0) | R:R=2.0 | RiskMult=1.0                         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


🔴 TROUBLESHOOTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─── Problema: "DRY-RUN: sin claves API" ─────────────────────────┐
│  ❌ Variables BINGX_API_KEY o BINGX_API_SECRET faltantes         │
│  ✅ Railway → Variables → añadir ambas claves                    │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: Sin trades en 6+ horas ───────────────────────────┐
│  ❌ MIN_SCORE demasiado alto (16 puntos = perfecta confluencia)  │
│  ✅ Reduce MIN_SCORE de 8 a 5 o 6                                │
│  ✅ O reduce UTBOT_KEY_VALUE de 10 a 7-8                         │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: "No se pudo conectar al exchange" ─────────────────┐
│  ❌ Claves incorrectas o sin permisos                             │
│  ✅ Verificar en BingX: API activa, Read+Trade, sin whitelist    │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: No recibo mensajes de Telegram ───────────────────┐
│  ✅ Verifica TOKEN con @BotFather                                │
│  ✅ Verifica CHAT_ID con @userinfobot                            │
│  ✅ Si es grupo: bot debe estar en el grupo                      │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: "Circuit breaker activated" ──────────────────────┐
│  ✅ NORMAL — protección automática activada                      │
│  ✅ Reinicia el service en Railway para continuar                │
│  ✅ Considera subir MIN_SCORE o reducir FIXED_USDT               │
└──────────────────────────────────────────────────────────────────┘

┌─── Problema: TP2 casi nunca se alcanza ────────────────────────┐
│  ❌ RNR demasiado alto para el timeframe usado                   │
│  ✅ Reduce RNR de 2.0 a 1.5                                      │
│  ✅ O reduce RR_EXIT de 0.5 a 0.3 para trail antes              │
└──────────────────────────────────────────────────────────────────┘


💡 DIFERENCIAS CLAVE vs v12 (si actualizas)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • Score ahora es sobre 16 (era 12) → ajusta MIN_SCORE
    v12 MIN_SCORE=4 ≈ v13 MIN_SCORE=5
    v12 MIN_SCORE=6 ≈ v13 MIN_SCORE=8

  • TP/SL ahora son dinámicos (Bj Bot R:R) no ATR fijo
    → Los targets varían por trade según swing pivots

  • Nuevo trailing: R:R trigger + UTBot + 3 fases originales
    → Más capas de protección de ganancias

  • Trade Expiration: TRADE_EXPIRE_BARS=0 (off por defecto)
    → Actívalo si quieres forzar salida de trades estancados


💰 COSTOS RAILWAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Free Tier:   ~500 horas/mes (suficiente para pruebas)
Hobby Plan:  $5/mes (recomendado, sin límites)


📊 SISTEMA DE ALERTAS v13
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟢/🔴  ENTRADA:     Score /16 + SMI + WaveTrend + UTBot stop + R:R
🟡     TP1 + BE:    Primera ganancia, SL → break-even
📐     R:R TRAIL:   Trailing activado por Bj Bot (RR_EXIT trigger)
🤖     UTBOT STOP:  Cierre por ATR trailing del UTBot
🏁     AGOTAMIENTO: 9 señales de agotamiento (incluye WT+UTBot)
⏳     EXPIRADO:    Trade cerrado por TRADE_EXPIRE_BARS
✅/❌  CERRADO:     PnL, barras abierto, estadísticas
📡     RESUMEN:     Cada 20 ciclos con top señales
💓     HEARTBEAT:   Cada hora con balance y trades


🔄 ACTUALIZAR EL BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```bash
git add .
git commit -m "v13: descripción del cambio"
git push
```

Railway redesplegará automáticamente en ~2 minutos.


⚠️ ADVERTENCIAS IMPORTANTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 DINERO REAL      Empieza con capital pequeño ($50-100)
🔴 REPO PRIVADO     Nunca hagas público el repositorio GitHub
🔴 SIN GARANTÍAS    El trading conlleva riesgo de pérdida total
🔴 MONITORIZA       Revisa logs de Railway y Telegram diariamente
🔴 API KEYS         NUNCA actives "Withdraw" en los permisos de API
🔴 MIN_SCORE/16     Recuerda que ahora el score máximo es 16


═══════════════════════════════════════════════════════════════════

            ✅ TODO VERIFICADO Y LISTO PARA DEPLOYAR

═══════════════════════════════════════════════════════════════════

📁 Archivos incluidos en este paquete:

  • bot.py                    → Código v13 (verificado ✓)
  • requirements.txt          → Dependencias Python (verificado ✓)
  • Procfile                  → Configuración Railway (verificado ✓)
  • railway.toml              → Configuración Railway (verificado ✓)
  • runtime.txt               → Python 3.11 (verificado ✓)
  • QUICK_START.md            → Guía rápida 5 minutos
  • RAILWAY_SETUP.md          → Instrucciones Railway completas
  • railway_variables.txt     → Variables para copiar/pegar (v13)
  • ESTRATEGIAS_AVANZADAS.md  → Perfiles y estrategias (v13)
  • FAQ.md                    → Preguntas frecuentes (v13)
  • verify.sh                 → Script de verificación
  • RESUMEN_EJECUTIVO.md      → Este archivo

═══════════════════════════════════════════════════════════════════

    🚀 ¡ÉXITO EN TU TRADING ALGORÍTMICO!
    UTBot · WaveTrend · Bj Bot · BB+RSI · SMI

═══════════════════════════════════════════════════════════════════
