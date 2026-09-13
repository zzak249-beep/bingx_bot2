# Crowding + CISD Bot

Bot de señales que combina **Crowding** (posicionamiento amontonado) + **CISD** (Change in State of Delivery).

**NO OPERA. NO PIDE CLAVES DE API.** Solo usa endpoints públicos de BingX.

## Qué hace

1. Detecta crowding (basis extremo + Open Interest subiendo + precio en extremo)
2. Espera la primera vela en contra de la multitud
3. Confirma con **CISD + Retest + Volumen**
4. Abre operación **virtual** con stop y take profit
5. Registra el resultado en R

## Estructura de archivos

```
├── crowding_bot.py     # Bot principal (con filtro CISD integrado)
├── cisd.py             # Módulo CISD + OB + FVG + Volumen
├── confirm.py          # Filtro de régimen (Variance Ratio)
├── requirements.txt
├── Procfile
├── .gitignore
└── README.md
```

## Despliegue en Railway

1. Crea un proyecto nuevo desde este repo
2. **Monta un Volume en `/data`** (importante para no perder historial)
3. Configura las variables de entorno

## Variables importantes

```
TIMEFRAME=15m
SCAN_SEC=300
MIN_VOL_24H=2000000
MAX_SYMBOLS=300
HIST_HORAS=168
MIN_HORAS=30
MIN_MUESTRAS=200
OI_LOOK_H=6
Z_BASIS=2.0
Z_OI=1.0
EXT_PCT=80
ATR_LEN=14
SL_ATR=1.5
TP_R=2.0
MAX_BARS=16
MIN_ATR_PCT=1.0
COST_PCT=0.25
MAX_COST_R=0.20
STATE=/data/crowding_state.json
CSV=/data/crowding_ops.csv
TG_TOKEN=
TG_CHAT=
TG_SIGNALS=false
TG_CLOSES=false
REPORT_HOUR=7
```

## Calentamiento

El bot necesita ~30 horas + 200 muestras por símbolo antes de emitir señales (BingX no da histórico de Open Interest).

## Lógica de entrada (Crowding + CISD)

| Capa | Función |
|------|---------|
| **Crowding** | Detecta gente atrapada (basis + OI + extremo) |
| **Vela en contra** | Primer signo de debilidad de la multitud |
| **CISD** | Confirma cambio de delivery (score ≥ 4) |
| **Retest + Volumen** | Entrada precisa |

## Notas

- El módulo `confirm.py` solo registra el régimen (no bloquea).
- `CONFIRM_BLOQUEAR` está en `False` a propósito.
- Todo queda en el CSV para análisis posterior.
