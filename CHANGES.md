# Cambios de esta tanda

## Por qué no daba señales (diagnóstico + arreglo aplicado)

`MIN_COST_COVER=30` × `COST_ROUNDTRIP_PCT=0.25%` exigía un ATR del **7.5%
en velas de 5 minutos**. Simulando incluso un escenario "extremo de
pump/dump" (±1.5% por vela) el ATR resultante ronda 1.9-2.8% — nunca
llega a 7.5%. Con 201 símbolos y 0 candidatas en todos los ciclos, esto
explica el síntoma sin necesitar ninguna otra causa.

**Aplicado en `railway_vars_LIVE.txt` y `railway_vars_SIGNAL.txt`:**
`MIN_COST_COVER` 30 → **6** (umbral efectivo 7.5% → **1.5%** de ATR en 5m).
Es un punto de partida razonado, no un número mágico — mira cuántas
candidatas aparecen los primeros días y ajusta desde ahí.

## Archivos nuevos

- **`wyckoff.py`** — confirmación por volumen/estructura (climax de
  volumen, spring/upthrust, esfuerzo-vs-resultado). Mismo patrón que
  `rsi_confirm.py`: nunca bloquea sola, solo suma al score. Probado con
  patrones fabricados de spring y upthrust.
- **`momentum.py`** — modo de ruptura tras contracción estilo
  Qullamaggie. **Filosofía opuesta** a la reversión existente (compra
  fuerza con la tendencia, no debilidad esperando rebote) — por eso es
  un módulo aparte, no un cambio a `strategy.py`. **Apagado por defecto**
  (`MOMENTUM_ENABLED=false`): con el flag en `false` no cambia nada del
  comportamiento actual. Probado con tendencia+contracción+ruptura
  fabricadas a mano.

## Archivos modificados en esta tanda

- **`main.py`** — además de los 3 arreglos de la auditoría anterior:
  - `scan_once()` prueba `momentum.evaluate()` como alternativa SOLO
    cuando `strategy.evaluate()` no da señal Y `MOMENTUM_ENABLED=true`.
  - Se calcula `wyckoff.evaluate()` sobre las mismas velas y se pasa al
    score.
  - El filtro de contra-tendencia de 30m tiene una variante estricta
    para momentum (`MOMENTUM_REQUIRE_30M_ALIGNMENT=true` exige
    alineación real, no solo "no en contra") — apagada por defecto.
  - El log de fin de ciclo ahora también cuenta señales de momentum.
- **`score.py`** — nuevo componente `wyckoff` en el desglose (hasta
  +10, nunca resta si contradice — a diferencia del RSI, que si penaliza,
  porque Wyckoff todavía no tiene datos propios que respalden penalizar).
  Compatible con las llamadas existentes (`wyckoff_result` es opcional).
- **`railway_vars_LIVE.txt`** / **`railway_vars_SIGNAL.txt`** —
  calibración de `MIN_COST_COVER` + todas las variables nuevas de
  Wyckoff y momentum, añadidas al final.

## Sin cambios desde la entrega anterior (no hace falta volver a copiarlos)

`bingx.py` y `stats.py` — ya tienen los 3 arreglos de la auditoría
anterior (`position_amt()`, `format_report()`) y no se han tocado en
esta tanda.

## Lo que sigue igual de pendiente

`config.py` y `strategy.py` reales — `wyckoff.py` y `momentum.py` se
diseñaron a propósito para NO depender de ellos (leen sus propias
variables de entorno), así que esto funciona sin esos dos archivos. Pero
la propia estrategia de reversión (la vela de agotamiento, el R:R, el
tamaño de posición) sigue sin poder auditarse.

## Simons, Kotegawa

No hay nada concreto y verificable que añadir con esos dos nombres (ver
la respuesta anterior) — no está aquí, y no está por omisión, no por
descuido.
