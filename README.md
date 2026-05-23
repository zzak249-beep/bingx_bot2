# Sniper Bot V45 — BINGXBOT2 ZESTY

Bot de trading automatizado para BingX Futuros en **ONE-WAY Mode** (default BingX).

## Archivo único

Todo el bot está en `main.py` — BingXClient, indicadores, scanner, risk y loops.

## Setup Railway

1. Sube este directorio a un repositorio GitHub
2. Crea un nuevo servicio en Railway conectado al repo
3. En **Variables**, añade todas las del `env.example`:

```
BINGX_API_KEY=...
BINGX_API_SECRET=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
```

4. Railway arranca con `python main.py`

## Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `LEVERAGE` | `5` | Apalancamiento |
| `MAX_RISK_PCT` | `0.5` | % balance por trade |
| `MAX_POS_USDT` | `25` | Tamaño máximo posición USDT |
| `MAX_POSITIONS` | `9` | Posiciones simultáneas máx |
| `TIMEFRAME` | `15m` | Timeframe principal |
| `TIMEFRAME_HIGH` | `1h` | Timeframe confirmación |
| `SCORE_ENTRY` | `55` | Score mínimo para abrir |
| `MIN_VOL_USDT` | `50000000` | Volumen mínimo 24h |
| `SCAN_INTERVAL_MIN` | `5` | Intervalo escaneo (minutos) |
| `RVOL_MIN` | `1.3` | Volumen relativo mínimo |
| `SLOPE_MIN` | `25` | Pendiente EMA mínima |
| `ADX_MAX` | `35` | ADX máximo permitido |
| `RR_RATIO` | `2.0` | Ratio riesgo/recompensa |
| `ATR_SL_MULT` | `1.2` | Multiplicador ATR para SL |
| `POC_LOOKBACK` | `50` | Velas para calcular POC |
| `USE_WHITELIST` | `true` | Usar lista de pares permitidos |
| `BLACKOUT_START_UTC` | `0` | Hora inicio blackout (UTC) |
| `BLACKOUT_END_UTC` | `2` | Hora fin blackout (UTC) |

## Lógica de entrada (V45)

Condición **LONG** (todas deben cumplirse):
- Precio tocó mínimo reciente (`low < valley`)
- Precio por debajo del VWAP
- Pendiente EMA > `SLOPE_MIN`
- STC subiendo
- ADX < `ADX_MAX`
- Precio alejado del POC > 1.5×ATR
- Volumen relativo > `RVOL_MIN`

Condición **SHORT**: espejo inverso.

Score base 85 + confirmación HTF (1h) +10 + EMA cross +5.

## Requisitos BingX

- Cuenta en **ONE-WAY mode** (modo por defecto de BingX)
- Balance mínimo recomendado: **$50 USDT** en Futuros
- API Key con permisos de **lectura + trading de futuros**

## Fixes incluidos (vs versión original)

- ✅ `calc_qty`: aplica `LEVERAGE` correctamente (qty era 5× menor)
- ✅ `calc_qty`: valida notional real antes de devolver qty (evita qty inviable)
- ✅ `place_sl_tp()`: SL y TP colocados como órdenes reales en BingX
  - Antes solo se gestionaban en Python con polling cada 60s
  - Ahora son órdenes `STOP_MARKET` y `TAKE_PROFIT_MARKET` reales
- ✅ `half_closed`: se limpia automáticamente cuando la posición ya no existe
- ✅ Gestión manual de SL/TP en Python como **backup** por si falla la orden
