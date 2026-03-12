# ⚡ SMC Bot BingX v4.0 — REAL MONEY | 24/7 | AUTO-LEARN

## 🧠 Novedades v4.0 vs v3.1

| # | Mejora | Descripción |
|---|--------|-------------|
| 1 | **Pin Bar + Engulfing** | Detección de patrones de reversión de alta precisión |
| 2 | **Liquidity Sweeps** | Detecta barrida de stops antes del movimiento real |
| 3 | **VWAP como filtro** | LONG solo sobre VWAP, SHORT solo bajo VWAP |
| 4 | **EMA 9/21 local** | Tendencia inmediata de la vela actual |
| 5 | **Cooldown por par** | Evita señales consecutivas (mín 5 velas = 25min en 5m) |
| 6 | **ATR7 para SL** | Stop loss más ajustado y preciso en 5m |
| 7 | **Score /14** | Sistema ampliado de 12 → 14 puntos máximos |
| 8 | **Momentum confirmador** | Al menos 1 de 2 velas previas debe ir en dirección |
| 9 | **Compounding mejorado** | Cada $30 ganados → +$1/trade (antes $50) |
| 10 | **Notificación VWAP** | Telegram muestra posición respecto a VWAP |

---

## 💰 Lógica de Capital

```
Base fija:    $10 USDT × 10x = $100 de exposición
Compounding:  cada $30 ganados netos → +$1 por trade
Máximo:       $50 USDT × 10x = $500 de exposición
Capital base: NUNCA se toca, solo se reinvierten ganancias
```

Ejemplo de progresión:
- 0 ganado → $10/trade
- $30 ganado → $11/trade
- $60 ganado → $12/trade
- $300 ganado → $20/trade

---

## 🎯 Sistema de Score v4.0 (máximo 14 puntos)

| Confluencia | Puntos | Descripción |
|-------------|--------|-------------|
| FVG activo | +2 | Fair Value Gap (obligatorio) |
| FVG grande | +1 | FVG ≥ 0.3 ATR |
| Liquidity Sweep | +2 | Barrida de stops + cierre dentro ← NUEVO |
| Order Block | +2 | Precio dentro del OB |
| BOS / CHoCH | +1 | Break of Structure / Change of Character |
| Pin Bar / Engulfing | +2 | Patrón de reversión de alta calidad ← NUEVO |
| Bull/Bear strong | +1 | Vela de cuerpo >50% |
| MTF 1h alineado | +1 | EMA21 > EMA50 en 1h |
| EMA9 + VWAP | +1 | EMA9>21 local Y precio sobre/bajo VWAP ← NUEVO |
| EMA21/50 5m | +1 | Tendencia en timeframe operativo |
| RSI favorable | +1 | RSI <68 para LONG, >32 para SHORT |
| MACD confirmado | +1 | Histograma positivo/negativo |
| Volumen spike | +1 | Volumen actual ≥1.3× media |
| Killzone activa | +1 | Asia/London/NY |
| Zonas S/R | +1 cada | S1/S2/EQL/PP/ASIA_LOW (acumulativas) |

---

## 🔒 Filtros obligatorios para ejecutar

Además del score mínimo, la señal debe cumplir **TODOS**:

1. ✅ Vela confirmadora (cierra en dirección correcta)
2. ✅ Mecha no excesiva (<40% en dirección contraria)
3. ✅ Momentum: al menos 1 de las 2 velas previas va en dirección
4. ✅ RSI < 68 para LONG | RSI > 32 para SHORT
5. ✅ Cooldown: ≥25 minutos desde última señal en el mismo par
6. ✅ R:R ≥ 2.0 (recompensa doble del riesgo mínima)
7. ✅ HTF 1h no va explícitamente en contra

---

## 🚀 Despliegue Railway

### Variables de entorno obligatorias

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `BINGX_API_KEY` | `tu_key` | API Key BingX |
| `BINGX_SECRET_KEY` | `tu_secret` | Secret Key |
| `TELEGRAM_TOKEN` | `123:ABC...` | Bot token |
| `TELEGRAM_CHAT_ID` | `tu_id` | Tu chat ID |
| `MODO_DEMO` | `false` | LIVE real |
| `MEMORY_DIR` | `/data` | Railway Volume |

### Variables opcionales (ya tienen defaults óptimos)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `LEVERAGE` | `10` | Apalancamiento |
| `SCORE_MIN` | `5` | Puntos mínimos (5-14) |
| `MAX_POSICIONES` | `3` | Simultáneas |
| `TRADE_USDT_BASE` | `10.0` | Base por trade |
| `MIN_RR` | `2.0` | R:R mínimo |
| `COOLDOWN_VELAS` | `5` | Velas entre señales |
| `PINBAR_RATIO` | `0.55` | % mecha para Pin Bar |
| `PARES_BLOQUEADOS` | `RESOLV-USDT` | Separados por coma |

### Configurar Railway Volume (persistencia de memoria)
1. Railway → tu servicio → **Volumes**
2. **Add Volume** → Mount Path: `/data`
3. Variable de entorno: `MEMORY_DIR=/data`

---

## 🧠 Sistema de aprendizaje

El bot guarda en `/data/memoria.json`:

- **Por par**: gana/pierde, PnL acumulado, racha
  - Blacklist 2h si 3 pérdidas seguidas
  - Blacklist 4h si WR ≤ 25% (≥6 trades)
- **Por killzone**: qué sesión tiene mejor historial
- **Por patrón**: qué combinación de señales funciona mejor

Ajuste dinámico de score:
- WR ≥ 70% → +2 puntos (par confiable)
- WR ≥ 60% → +1 punto
- WR ≤ 35% → -1 punto
- WR ≤ 25% → -2 puntos (par problemático)

---

## 📁 Archivos

```
├── main.py           # Loop 24/7 + gestión posiciones
├── analizar.py       # Motor SMC v4.0 (score /14 + sweeps + pinbar + vwap)
├── config.py         # Configuración completa
├── exchange.py       # API BingX (SL/TP separados, retry)
├── memoria.py        # Aprendizaje + compounding $10 base
├── scanner_pares.py  # Pares dinámicos por volumen
├── config_pares.py   # Pares prioritarios
├── Procfile          # Railway worker
├── railway.toml      # Railway config
└── requirements.txt  # requests + python-dotenv
```

---

## ⚠️ Gestión de riesgo

- **Circuit breaker**: pausa 30min si pierde >$20 en el día
- **Time exit**: cierra posición si lleva >6h sin tocar TP/SL
- **Anti-hedge**: no abre posición contraria en el mismo par
- **Anti-correlación**: no abre el mismo lado en pares correlacionados
- **Trailing stop**: activa cuando el trade avanza 1.2 ATR, sigue a 0.8 ATR
- **Partial TP**: cierra 50% en TP1 y mueve SL a breakeven
