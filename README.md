# 🚀 SATY ELITE v11 — Real Money Bot

Bot de trading algorítmico para **BingX Perpetual Futures** con 12 trades simultáneos, 24/7, universo completo de pares USDT de bajo volumen.

```
╔══════════════════════════════════════════════════════════════╗
║         SATY ELITE v11 — REAL MONEY EDITION                 ║
║         BingX Perpetual Futures · 12 Trades · 24/7         ║
╚══════════════════════════════════════════════════════════════╝

✅ Todo verificado y listo para Railway
✅ Código probado y funcionando
✅ Documentación completa incluida
```

---

## 📚 ÍNDICE DE DOCUMENTACIÓN

### 🚀 INICIO RÁPIDO
- **[QUICK_START.md](QUICK_START.md)** ← Empieza aquí (5 minutos)
- **[RESUMEN_EJECUTIVO.md](RESUMEN_EJECUTIVO.md)** ← Guía completa paso a paso

### ⚙️ CONFIGURACIÓN
- **[railway_variables.txt](railway_variables.txt)** ← Variables para copiar/pegar
- **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)** ← Instrucciones detalladas Railway

### 🎯 ESTRATEGIAS
- **[ESTRATEGIAS_AVANZADAS.md](ESTRATEGIAS_AVANZADAS.md)** ← Configuraciones por perfil

### ❓ AYUDA
- **[FAQ.md](FAQ.md)** ← Preguntas frecuentes
- **[verify.sh](verify.sh)** ← Script de verificación automática

---

## ⚡ DEPLOY EN 3 PASOS

### 1️⃣ Obtener credenciales (10 min)
- API Key de BingX (con permisos Read + Trade)
- Token de bot de Telegram (@BotFather)
- Chat ID de Telegram (@userinfobot)

### 2️⃣ Subir a GitHub (2 min)
```bash
git init
git add .
git commit -m "initial deploy"
git remote add origin https://github.com/TU_USUARIO/saty-bot.git
git push -u origin main
```
⚠️ **IMPORTANTE:** Repo debe ser **PRIVADO**

### 3️⃣ Deploy en Railway (3 min)
1. https://railway.app → New Project → Deploy from GitHub
2. Conecta tu repo
3. Variables → RAW Editor → pega las 4 variables obligatorias
4. ✅ Bot desplegado

---

## 📋 VARIABLES OBLIGATORIAS

```env
BINGX_API_KEY=tu_api_key_aqui
BINGX_API_SECRET=tu_secret_aqui
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

**Variables opcionales** tienen valores por defecto optimizados.
Ver [railway_variables.txt](railway_variables.txt) para todas las opciones.

---

## 🎯 CARACTERÍSTICAS v11

### ✨ Novedades vs v10
- ✅ 12 trades simultáneos (antes 8)
- ✅ 24/7 siempre activo (sin horarios)
- ✅ Una posición por moneda base (no duplica)
- ✅ Volumen mínimo reducido a 100K (altcoins pequeños)
- ✅ Escanea hasta 300 pares (universo completo)
- ✅ Detecta pares nuevos listados en BingX
- ✅ Prioriza por score (no por volumen)

### 📊 Sistema de Trading
- **Análisis multi-timeframe**: 5m + 15m + 1h
- **Score de confluencia**: 12 indicadores técnicos (0-12 puntos)
- **Gestión de riesgo**: TP1 (50%), TP2 (100%), SL dinámico
- **Trailing stop**: 3 fases (normal/tight/locked)
- **Protecciones**: Circuit breaker + límite diario + cooldown

### 🛡️ Seguridad
- Stop loss automático en cada trade
- Circuit breaker a 15% drawdown (configurable)
- Límite diario 8% pérdida (configurable)
- Cooldown 20 min post-cierre (evita overtrading)

---

## 📁 ESTRUCTURA DEL PROYECTO

```
saty-elite-v11/
├── bot.py                      ← Código principal (verificado ✓)
├── requirements.txt            ← Dependencias Python
├── Procfile                    ← Config Railway
├── railway.toml                ← Config Railway
├── runtime.txt                 ← Python 3.11.9
├── .gitignore                  ← Archivos a ignorar
│
├── QUICK_START.md              ← Inicio rápido (5 min)
├── RESUMEN_EJECUTIVO.md        ← Guía completa
├── RAILWAY_SETUP.md            ← Setup Railway detallado
├── railway_variables.txt       ← Variables copiar/pegar
├── ESTRATEGIAS_AVANZADAS.md    ← Configuraciones avanzadas
├── FAQ.md                      ← Preguntas frecuentes
└── verify.sh                   ← Script verificación
```

---

## 💰 COSTOS

| Servicio | Costo |
|----------|-------|
| **Railway** | $5/mes (Hobby Plan, recomendado) |
| **BingX** | 0.02-0.04% por trade (~$5-15/mes) |
| **Total** | ~$10-20/mes |

**Free tier Railway**: ~500 horas/mes (suficiente para probar)

---

## 📊 PERFILES RECOMENDADOS

### 💚 Principiante ($50-200)
```
FIXED_USDT=5
MAX_OPEN_TRADES=8
MIN_SCORE=5
```

### 💙 Intermedio ($200-1000)
```
FIXED_USDT=10
MAX_OPEN_TRADES=12
MIN_SCORE=4
```

### 💜 Avanzado ($1000+)
```
FIXED_USDT=25
MAX_OPEN_TRADES=15
MIN_SCORE=4
```

Ver [ESTRATEGIAS_AVANZADAS.md](ESTRATEGIAS_AVANZADAS.md) para más perfiles.

---

## ✅ VERIFICACIÓN PRE-DEPLOY

Ejecuta el script de verificación:
```bash
chmod +x verify.sh
./verify.sh
```

Verifica:
- ✓ Todos los archivos presentes
- ✓ Configuración correcta
- ✓ Sintaxis Python válida
- ✓ Dependencias correctas

---

## 📱 ALERTAS TELEGRAM

Una vez funcionando, recibirás:

| Alerta | Descripción |
|--------|-------------|
| ⚡ **ENTRADA** | Cada vez que abre un trade |
| 🎯 **TP1 (50%)** | Primera toma de ganancias |
| 🏆 **TP2 (100%)** | Ganancia completa |
| 🛑 **STOP LOSS** | Trade cerrado con pérdida |
| 📊 **RESUMEN** | Cada 20 ciclos (~20 minutos) |
| 💓 **HEARTBEAT** | Cada hora (balance + estadísticas) |

---

## 🔄 ACTUALIZAR EL BOT

```bash
# Hacer cambios en el código
git add .
git commit -m "update: descripción"
git push

# Railway redesplegará automáticamente (~2 min)
```

---

## ⚠️ ADVERTENCIAS IMPORTANTES

### 🔴 DINERO REAL
Este bot opera con fondos reales. Empieza con capital pequeño ($50-100).

### 🔴 REPO PRIVADO
Nunca hagas público el repositorio GitHub. Contiene tu estrategia de trading.

### 🔴 API KEYS
- NUNCA actives "Withdraw" en los permisos de API
- NUNCA compartas tus API keys
- Si se exponen, revócalas inmediatamente

### 🔴 SIN GARANTÍAS
- El trading conlleva riesgo de pérdida total del capital
- Resultados pasados no garantizan resultados futuros
- No somos asesores financieros
- Usa bajo tu propio riesgo

### 🔴 MONITORIZA
Revisa logs de Railway y alertas de Telegram regularmente.

---

## 🆘 SOPORTE

### Documentación
- 📖 Todos los archivos .md en este directorio
- 📝 Comentarios en bot.py
- 🔍 Script verify.sh para diagnóstico

### Troubleshooting
Ver [FAQ.md](FAQ.md) para problemas comunes y soluciones.

### Comunidad
- Telegram de BingX: Soporte oficial exchange
- Foros de trading: Comunidades de algorithmic trading

---

## 📈 RESULTADOS ESPERADOS

Los resultados varían según configuración y condiciones de mercado:

| Perfil | Win Rate | Trades/día | ROI mensual estimado* |
|--------|----------|------------|----------------------|
| Conservador | 50-60% | 2-5 | 5-20% |
| Balanceado | 45-55% | 8-15 | 10-40% |
| Agresivo | 40-50% | 20-40 | 20-100% |

*Estimaciones sin garantía. El trading conlleva riesgo de pérdida.

---

## 🔧 REQUISITOS TÉCNICOS

### Sistema
- Python 3.11+
- Acceso a internet estable
- Cuenta Railway (o VPS alternativo)

### APIs
- BingX cuenta con Perpetual Futures activado
- Telegram bot (@BotFather)

### Dependencias (instaladas automáticamente)
```
ccxt==4.3.89
pandas==2.2.2
numpy==1.26.4
requests==2.32.3
```

---

## 📝 CAMBIOS DE v11

### vs v10
- Máximo trades: 8 → **12**
- Volumen mínimo: 1M → **100K** (altcoins pequeños)
- Pares escaneados: 100 → **300** (universo completo)
- Score mínimo: 5 → **4** (más señales)
- Horarios: 8am-10pm → **24/7**
- Filtro duplicados: Solo pares → **Monedas base**

### Nuevas características
- ✅ Detección automática pares nuevos
- ✅ Prioridad por score (no volumen)
- ✅ Sin duplicar moneda base (BTC long + BTC short)
- ✅ Acepta spread hasta 1% (pares menos líquidos)

---

## 📜 LICENCIA Y USO

**Uso educativo y experimental.**
- Sin garantías de ningún tipo
- No nos hacemos responsables por pérdidas
- Usa bajo tu propio riesgo y responsabilidad

---

## 🚀 EMPEZAR AHORA

1. Lee [QUICK_START.md](QUICK_START.md) (5 minutos)
2. Consigue tus credenciales (BingX + Telegram)
3. Deploy en Railway
4. ¡Empieza a tradear!

---

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║            ✅ TODO VERIFICADO Y LISTO                        ║
║                                                              ║
║            🚀 ¡ÉXITO EN TU TRADING!                          ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```
