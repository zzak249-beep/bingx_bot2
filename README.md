# QF×JP Fusion Bot v3.4 🤖

**Sistema de trading algorítmico para BingX Perpetual Swaps**  
Scanner multi-moneda · Señales Telegram · Auto-ejecución opcional · Railway-ready

---

## ⚡ Los 4 Pilares + Ventaja Especial

### 1. 🎯 COMPOSITE SCORE (0-100)
Score multi-factor ponderado dinámicamente por régimen de mercado:
- Momentum normalizado por volatilidad
- Mean-reversion estadística  
- Volume factor (OBV)
- Decay de señal (IC rolling)
- CVD Delta sintético
- Estructura de mercado (CHoCH/BoS)

**3 niveles de señal:**
| Nivel | Score | Calidad |
|-------|-------|---------|
| STD   | ≥ 55  | Entrada básica |
| FUEL  | ≥ 68  | Alta probabilidad |
| SUP ⭐| ≥ 80  | Máxima calidad |

---

### 2. 🧭 HTF ALIGNMENT (0/3 → 3/3)
Confluencia de 3 timeframes:
- **15m**: EMA9 vs EMA21
- **1h**: EMA9 vs EMA21  
- **3m**: Estructura de mercado (CHoCH/BoS)

**Mínimo 2/3 requerido** para señal válida (configurable via `HTF_MIN`).

---

### 3. 🔢 CONVICTION (0-12)
12 sub-filtros binarios:
1. Norm score direccional > 0.10
2. Decay de señal activo
3. Execution filter OK (spread)
4. HTF ≥ 2/3 alineados
5. Asimetría VAI confirmada
6. Swing exhaustion (HL/LH count)
7. Liquidity sweep o CHoCH
8. CVD direccional
9. Squeeze momentum fire
10. OI Delta confirmado
11. VWAP posición
12. VAI score > 0.60

---

### 4. 📐 ASIMETRÍA (VAI — Volume Asymmetry Index)
**La ventaja especial sobre otros bots.**

El VAI mide la **presión institucional** comparando el rango de velas alcistas vs bajistas, ponderado por volumen:

```
VAI = log(avg_volume_weighted_up_range / avg_volume_weighted_down_range)
```

**¿Por qué es mejor que el original?**
- El script original usa rango simple (high-low)
- El VAI usa rango × volumen → filtra el ruido
- Una vela grande con poco volumen = ruido
- Una vela grande con mucho volumen = intención institucional

| VAI Score | Significado |
|-----------|-------------|
| > 0.70    | Presión compradora institucional |
| 0.40-0.60 | Equilibrio / neutral |
| < 0.30    | Presión vendedora institucional |

**Contribuye al score en +5% máx y cuenta como 1 punto de convicción.**

---

## 📨 Formato de Señales Telegram

```
⭐ LONG SUPREMA 🔵
━━━━━━━━━━━━━━━━━━━━━
📊 DOGEUSDT  @  0.08234

🎯 SCORE LONG: 83/100   Conv: 9/12
⚡ ASIMETRÍA VAI: BULL 1.45×
   [▓▓▓▓▓▓░░] 72%
🧭 HTF 3TF: ✓15m ✓1h ✓3m  (3L / 0S)
🏛 Estructura: CHoCH↑ SWP↑

📐 TRADE PLAN
  💲 Entry:  0.08234
  🛑 SL:     0.08150
  🎯 TP1:    0.08360  R:R 1.5×
  🏁 TP2:    0.08500  R:R 3.2×
  📦 Size:   145.3 u  (Kelly 12%)

📈 FACTORES
  ADX: 28 [TEND↑]   RSI: 42
  CVD: ACUM↑   SQ: FUEGO↑
  VWAP: SOBRE   OI: CONF↑
  ATR: 0.000821
```

---

## 🚀 Despliegue en Railway

### 1. Preparar GitHub

```bash
git clone https://github.com/tu-usuario/qfbot
cd qfbot
git init
git add .
git commit -m "QF×JP Bot v3.4 initial"
git remote add origin https://github.com/tu-usuario/qfbot.git
git push -u origin main
```

### 2. Railway

1. Ve a [railway.app](https://railway.app)
2. **New Project** → **Deploy from GitHub repo**
3. Selecciona tu repo `qfbot`
4. Railway detecta el `Dockerfile` automáticamente
5. Ve a **Variables** y añade todas las del `.env.example`

**Variables mínimas obligatorias:**
```
BINGX_API_KEY=xxx
BINGX_API_SECRET=xxx
TELEGRAM_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

### 3. Modo señales-only (recomendado al inicio)
```
AUTO_TRADE=false
TESTNET=false
```
El bot escanea todas las monedas y envía señales a Telegram sin ejecutar nada.

### 4. Modo paper trading
```
AUTO_TRADE=true
TESTNET=true
```

### 5. Modo live (solo cuando estés seguro)
```
AUTO_TRADE=true
TESTNET=false
MIN_SIGNAL=FUEL    # Solo ejecuta FUEL y SUP
CAPITAL=200        # Empieza con poco capital
LEVERAGE=3         # Leverage conservador
```

---

## 🔑 Obtener API Keys BingX

1. Ve a [bingx.com](https://bingx.com) → Account → API Management
2. Crea nueva API Key
3. Permisos necesarios: **Read** + **Trade** (NO Withdraw)
4. Guarda la key y secret de inmediato (solo se muestra una vez)
5. Whitelist de IP: opcional pero recomendado

---

## 🤖 Obtener Bot Token Telegram

1. Habla con [@BotFather](https://t.me/BotFather)
2. `/newbot` → pon un nombre → pon un username
3. Copia el **token**
4. Para el chat_id: habla con [@userinfobot](https://t.me/userinfobot) → copia tu ID

---

## ⚙️ Variables de Configuración Clave

| Variable | Default | Descripción |
|----------|---------|-------------|
| `AUTO_TRADE` | false | Ejecutar órdenes reales |
| `CAPITAL` | 1000 | Capital total USDT |
| `LEVERAGE` | 5 | Apalancamiento |
| `MIN_SIGNAL` | FUEL | Calidad mínima para auto-trade |
| `THR_SUP` | 80 | Score para señal SUPREMA |
| `HTF_MIN` | 2 | TFs mínimos alineados |
| `MAX_POSITIONS` | 5 | Posiciones abiertas máx |
| `MAX_DAILY_LOSS` | 3.0 | % pérdida diaria máx |
| `SCAN_INTERVAL` | 30 | Segundos entre scans |
| `MIN_VOLUME` | 500000 | Volumen mínimo USDT/24h |
| `KEL_FRAC` | 0.25 | Fracción Kelly (conservador) |

---

## 📁 Estructura del Proyecto

```
qfbot/
├── main.py              # Entry point
├── Dockerfile           # Container para Railway
├── railway.toml         # Config Railway
├── requirements.txt     # Dependencies
├── .env.example         # Template variables
├── config/
│   └── settings.py      # Config loader (env vars)
├── src/
│   ├── engine.py        # 🧠 Core: 4 pilares + VAI
│   ├── exchange.py      # 📡 BingX API connector
│   ├── telegram.py      # 📨 Telegram notifier
│   ├── scanner.py       # 🔍 Multi-symbol scanner
│   ├── risk.py          # 💼 Risk manager + Kelly
│   └── bot.py           # 🤖 Main orchestrator
└── logs/
    └── bot.log          # Runtime logs
```

---

## ⚠️ Disclaimer

Este software es solo para propósitos educativos. El trading con apalancamiento conlleva riesgo significativo de pérdida. Siempre prueba en testnet antes de operar con capital real. Empieza con capital mínimo que puedas permitirte perder.

---

## 🔄 Ciclo de Vida de una Señal

```
SCAN (cada 30s)
  └─ Todos los pares USDT con volumen suficiente
      └─ QFEngine.analyze() por símbolo
          ├─ Score Compuesto (0-100)
          ├─ HTF Alignment (0-3)
          ├─ Conviction (0-12)
          └─ VAI Asymmetry
              └─ Signal?
                  ├─ STD  → Telegram only
                  ├─ FUEL → Telegram + (auto-trade si enabled)
                  └─ SUP  → Telegram + auto-trade prioritario
                      └─ RiskManager
                          ├─ Kelly sizing
                          ├─ SL/TP automático
                          └─ Partial TP @ 0.5×ATR (25% close + SL→BE)
```
