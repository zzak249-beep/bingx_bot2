# ⚡ SMC Bot BingX v3.1 [CORREGIDO + MEJORADO]

## 🔧 Fixes críticos aplicados (v3.0 → v3.1)

| # | Bug | Causa | Fix |
|---|-----|-------|-----|
| 1 | **Sin señales nunca** | `PIVOT_NEAR_PCT=0.20%` → BTC necesitaba estar a ±$160 de un pivot | Subido a `0.80%` → ±$640 de margen real |
| 2 | **Tendencia MTF bloquea todo** | `trend_ok = EMA_5m AND EMA_1h` — mercados laterales nunca alineaban ambos | Ahora solo bloquea si 1h va en contra (`htf != BEAR` para LONG) |
| 3 | **SCORE_MIN=5 inalcanzable** | Base obligatoria (FVG+KZ+zona) ya vale 4 pts, con mín 5 nunca pasaba | Bajado a `4` — exige confluencia real sin ser imposible |
| 4 | **RSI demasiado estricto** | BUY_MAX=50 / SELL_MIN=50 dejaba muy poco margen | BUY_MAX=55 / SELL_MIN=45 |
| 5 | **Sin debug visible** | No había logging de por qué fallaban las señales | Log DEBUG cuando score≥3 pero no genera señal |
| 6 | **Backup de memoria** | Sin backup → memoria.json corrompida = pérdida de datos | Backup automático antes de cada guardado |
| 7 | **Retry en API** | Sin reintentos → errores de red mataban el ciclo | 3 reintentos con backoff en GET/POST |

---

## 🚀 Despliegue en Railway

### 1. Subir a GitHub
```bash
git init
git add .
git commit -m "SMC Bot v3.1 fixed"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### 2. Variables de entorno en Railway

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `BINGX_API_KEY` | `tu_key` | API Key BingX |
| `BINGX_SECRET_KEY` | `tu_secret` | Secret Key BingX |
| `TELEGRAM_TOKEN` | `123:ABC...` | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | `tu_chat_id` | Tu Chat ID |
| `MODO_DEMO` | `false` | Live trading |
| `LEVERAGE` | `10` | Apalancamiento |
| `MAX_POSICIONES` | `3` | Máx simultáneas |
| `SCORE_MIN` | `4` | Score mínimo (4-6) |
| `PIVOT_NEAR_PCT` | `0.80` | ✅ FIX: zona pivot % |
| `SOLO_LONG` | `false` | Solo longs |
| `MEMORY_DIR` | `/data` | Dir persistente Railway |
| `LOG_LEVEL` | `DEBUG` | Para ver no-señales |

### 3. ✅ Volume para persistencia de memoria

Sin Volume, `memoria.json` se borra en cada redeploy.

1. Railway → tu servicio → **Volumes**
2. **Add Volume** → Mount Path: `/data`
3. Variable de entorno: `MEMORY_DIR=/data`

---

## 📊 Sistema de Score v3.1 (máximo 12 puntos)

### LONG (base obligatoria: FVG + KZ + Zona)

| Condición | Puntos | Obligatorio |
|-----------|--------|-------------|
| FVG alcista (últimas 20 velas) | +2 | ✅ Base |
| En Killzone London/NY | +1 | ✅ Base |
| Cerca de S1/S2/EQL/AsiaLow/OB | +1-2 | ✅ Base (1 mínimo) |
| Order Block alcista | +2 | Opcional |
| BOS / CHoCH alcista | +1 | Opcional |
| MTF 1h = BULL | +1 | Opcional |
| EMA21 > EMA50 en 5m | +1 | Opcional |
| RSI ≤ 55 | +1 | Opcional |
| Vela confirmadora | +1 | Opcional |

> Con SCORE_MIN=4: necesitas FVG+KZ+zona como base mínima.
> Con SCORE_MIN=5: necesitas además EMA o RSI o vela.
> Con SCORE_MIN=6: señales muy selectivas (recomendado para cuentas >$500).

### SHORT (simétrico)

Mismo sistema con FVG bajista + KZ + R1/R2/EQH/AsiaHigh/OB bajista.

---

## ⚠️ Gestión de riesgo recomendada

| Parámetro | Inicio | Intermedio | Agresivo |
|-----------|--------|------------|---------|
| `LEVERAGE` | 5 | 10 | 15 |
| `SCORE_MIN` | 5 | 4 | 4 |
| `MAX_POSICIONES` | 2 | 3 | 5 |
| `SOLO_LONG` | true | false | false |
| `MAX_PERDIDA_DIA` | 15 | 25 | 40 |
| `MIN_RR` | 2.0 | 1.5 | 1.2 |

---

## 🕐 Killzones (UTC)

| Sesión | UTC | Para señales | Notas |
|--------|-----|-------------|-------|
| 🌙 Asia | 00:00–04:00 | ❌ Solo rango S/R | Se usa como zona de referencia |
| 🇬🇧 Londres | 07:00–10:00 | ✅ Activo | Mejor con pares EUR/cripto |
| 🗽 Nueva York | 13:00–16:00 | ✅ Activo | Mayor volumen |

---

## 🧠 Sistema de aprendizaje (memoria.py)

El bot aprende de cada trade:
- **Por par**: ajusta score ±2 según win rate histórico
- **Por killzone**: ajusta ±1 según rentabilidad por sesión
- **Por patrón de señales**: ajusta ±1 según combinación de indicadores
- **Blacklist automática**: 2h si 3 pérdidas seguidas, 4h si 75%+ pérdida ratio

El compounding es conservador: base $10, +$1 por cada $50 ganados, máximo $50.

---

## 📁 Estructura de archivos

```
├── main.py           # Loop principal + gestión de posiciones
├── analizar.py       # Motor de señales SMC (score 0-12)
├── config.py         # Todos los parámetros configurables
├── exchange.py       # API BingX con retry
├── memoria.py        # Aprendizaje + compounding + persistencia
├── scanner_pares.py  # Obtiene pares dinámicamente de BingX
├── config_pares.py   # Pares prioritarios (opcionales)
├── Procfile          # Railway: worker process
├── railway.toml      # Configuración Railway
└── requirements.txt  # requests + python-dotenv
```

---

## 🐛 Debug de señales

Si el bot escanea pero no da señales, activa `LOG_LEVEL=DEBUG` en Railway.
Verás logs como:
```
[NO-SEÑAL] BTC-USDT | L:3pts(FVG,KZ_NY,EMA) S:2pts(FVG,KZ_NY) |
base_L=False(fvg=True,kz=True,zona=False) ...
```

Esto indica qué condición específica falla para cada par.

---

## 📈 Historial de versiones

| Versión | Cambios principales |
|---------|---------------------|
| v1.0 | Base: FVG + Killzones |
| v2.0 | Equal Highs/Lows + Pivotes diarios |
| v2.1 | Fix HMAC + RSI Wilder + SL/TP separados |
| v3.0 | MTF + Order Blocks + BOS/CHoCH + Rango Asia |
| **v3.1** | **Fix PIVOT_NEAR_PCT + Fix MTF NEUTRAL + Score min 4 + Debug logging + Retry API** |
