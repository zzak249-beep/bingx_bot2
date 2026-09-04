# RESEARCH.md — ¿Qué ventaja matemática tiene realmente esta estrategia?

## 1. Lo que el hilo de X vende vs. lo que el script hace

El hilo original vende la idea de "wavelets de Ingrid Daubechies" (real
matemática belga, premio Wolf 2019/Abel-adjacent, inventora de las wavelets
ortogonales de soporte compacto que se usan en JPEG2000 y compresión de
huellas dactilares del FBI) + una estadística concreta ("$80 → $4.900 en 38
días, 71% aciertos, Sharpe 2.44") a cambio de like+follow+DM. Eso es un
patrón clásico de growth-hacking en trading: **la cifra es la carnada, no
un resultado auditable**. Ni el periodo, ni el símbolo, ni el drawdown máximo,
ni si es cuenta real o demo, ni el tamaño de la muestra (38 días es
estadísticamente casi nada en 5m) están verificados. Trátalo como
publicidad, no como evidencia.

Lo que el script Pine implementa **no es una DWT de Daubechies**. Es esto:

```
haar_detail(s, len) = (SMA(s, len) - SMA(s[len], len)) / sqrt(2)
```

Eso es una **diferencia de dos medias móviles desplazadas**, evaluada en 4
escalas (1, 2, 4, 8 barras), elevada al cuadrado y sumada en una ventana de
40 barras para obtener una "energía" por escala. Es matemáticamente
equivalente a un banco de filtros paso-banda muy tosco, mucho más parecido
a un MACD multi-escala o a un oscilador de momentum jerárquico que a una
transformada wavelet ortogonal de verdad. No hay downsampling diádico, no
hay ortogonalidad garantizada, no hay reconstrucción perfecta — es una
versión *redundante* y *causal* de la idea "à trous" (algorithme à trous,
Holschneider et al. 1989), que sí es una técnica real y usada en
procesamiento de señales, pero está muy simplificada aquí.

**Conclusión honesta**: el nombre "wavelet" es marketing. La mecánica real
es "compara la energía del ruido de corto plazo (1-2 barras) contra la
energía de la tendencia de medio plazo (4-8 barras), y solo opera cruces de
precio sobre su SMA(8) cuando domina lo segundo". Eso es un **filtro de
régimen tendencia/ruido**, una idea legítima, pero nada exclusivo de
wavelets — el mismo objetivo lo cumplen:

- **Efficiency Ratio de Kaufman** (`ER = |cambio neto| / suma de |cambios|`)
- **ADX / DMI** (fuerza direccional)
- **Exponente de Hurst** o **dimensión fractal** (persistencia vs. mean-reversion)
- **Ratio de varianza a distintos horizontes** (variance ratio test, Lo-MacKinlay)

Todos miden esencialmente lo mismo: ¿el movimiento reciente tiene estructura
persistente (autocorrelación positiva en retornos) o es ruido browniano?

## 2. ¿Hay una ventaja matemática real aquí?

Sí, una modesta y bien conocida, no la "genialidad oculta" que insinúa el
hilo:

1. **Filtrar régimen antes de operar cruces de MA reduce whipsaws.** Un
   cruce de precio sobre su SMA en un mercado lateral genera muchas señales
   falsas. Exigir que la energía de baja frecuencia domine sobre la de alta
   frecuencia es una forma razonable (aunque burda) de exigir "está
   tendencial" antes de disparar. Esto es la misma lógica de un ADX>25 como
   filtro de un cruce de medias — técnica de décadas, no una ventaja nueva.

2. **La verdadera pregunta estadística** no es "¿el filtro se llama
   wavelet?" sino: **¿los retornos del activo en 5m tienen memoria de corto
   plazo (autocorrelación) que este filtro capture de forma consistente,
   neta de comisión+slippage+funding?** Eso solo se responde con datos, no
   con la estética del método. Los mercados de perpetuos de cripto en 5m
   son extremadamente competidos (HFT, market makers, otros bots) — cualquier
   patrón de autocorrelación simple y público como este tiende a arbitrarse
   rápido si es real y explotable a gran escala. Que exista *algo* de señal
   residual localmente (activo/periodo concretos) es plausible; que sea
   grande y estable en el tiempo es poco probable.

3. **Riesgo real no capturado en el backtest de Pine**: comisión asumida
   0.05% (razonable para taker en BingX con descuento), pero el backtest de
   Strategy Tester de Pine no modela bien: profundidad de libro real en 5m
   para el tamaño de tu cuenta, funding rate acumulado si mantienes
   posición varias horas, latencia webhook→ejecución (normalmente 1-5s, a
   veces más si TradingView tiene cola), ni slippage real en momentos de
   alta volatilidad donde el filtro "coarse>fine" probablemente dispara más
   señales (los saltos de volatilidad SÍ elevan energía en todas las
   escalas, no solo en la gruesa).

## 3. Cómo validar esto de verdad antes de arriesgar capital

En orden de prioridad:

1. **Walk-forward, no solo backtest en una ventana.** Divide el histórico
   en bloques (ej. 3 meses train / 1 mes test, rodante) y comprueba que el
   edge (si existe) se mantiene fuera de muestra, no solo en el periodo que
   usaste para tunear `k_dominance`, `lookback_energy`, `atr_mult_*`.

2. **Compara contra un baseline simple.** Corre la misma estrategia de
   entrada (cruce de precio sobre SMA(8)) **sin** el filtro de energía
   (`is_trending` siempre true) y compara. Si el filtro "wavelet" no mejora
   claramente el Sharpe/profit factor fuera de muestra frente al baseline,
   el valor añadido del aparato matemático es ilusorio y lo único que
   funciona (si algo funciona) es el cruce de SMA con buen SL/TP en ATR.

3. **Multiplicidad de símbolos/periodos.** Si el edge solo aparece en
   BTCUSDT en un rango de fechas concreto, es sobreajuste. Debería mostrar
   *alguna* consistencia direccional (aunque no igual de fuerte) en varios
   perpetuos correlacionados (ETH, SOL) y en distintos años.

4. **Test de significancia estadística real**, no solo "71% de aciertos".
   Con pocas decenas de operaciones, un 71% de win rate no es
   estadísticamente distinguible de azar con sesgo de tamaño de muestra.
   Calcula el intervalo de confianza del win rate (ej. Wilson score) y el
   profit factor con su varianza — no solo el punto estimado.

5. **Forward test en real con capital mínimo** (lo que ya monta este bot en
   modo `AUTO_TRADE=false` primero, y con tamaño mínimo después) durante
   semanas, comparando P&L real vs. lo que decía el backtest. La diferencia
   entre ambos te dice cuánto "edge" era matemático real y cuánto era
   artefacto del backtest.

## 4. Recomendación concreta

- Trátalo como **un filtro de régimen razonable para tu cruce de SMA(8)**,
  no como una técnica con ventaja matemática superior por ser "wavelet".
- El valor real está en la **disciplina de riesgo** que ya tienes
  incorporada en tu arquitectura habitual (position sizing por %, SL/TP por
  ATR, circuit breaker, cooldown) más que en el propio filtro de energía.
- Antes de subir `AUTO_TRADE=true`, corre el punto 2 (comparar contra
  baseline sin filtro) — es la prueba más barata y más informativa de si
  el "wavelet" aporta algo por encima de un cruce de medias con buena
  gestión de riesgo.
## 5. Lo que muestra tu cuenta real: ilíquidez, no falta de "más wavelet"

Si tu cuenta tiene posiciones abiertas en símbolos como DRAM, FOGO,
Zinc(XZN), ALLO, BLUAI, KGEN, OG, IN — eso es una señal en sí misma, y no
buena. Son altcoins de capitalización pequeña/ilíquidos. En ese tipo de
mercados:

- **El spread bid/ask puede ser 0.2-1%+ por operación**, contra el 0.05%
  de comisión que asume el backtest. Eso solo ya puede comerse todo el edge
  teórico del filtro antes de que el precio se mueva nada.
- **El slippage de una orden de mercado** en un libro fino puede ser
  varias veces mayor que en BTC/ETH — la vela de 5m que ves en el gráfico
  no representa bien a qué precio se ejecutó tu orden.
- **El propio filtro "wavelet" puede disparar más en estos activos** porque
  su volatilidad de baja liquidez genera saltos de precio que inflan la
  energía de las escalas gruesas (coarse) tanto como la fina — recuerda el
  punto 2.3 de este documento: eso es justo el tipo de ruido que el filtro
  puede confundir con tendencia real.

**Antes de buscar "cómo ganar más" ajustando el filtro**, lo más rentable
casi seguro es restringir el universo a pares líquidos:

```
SYMBOLS=BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT,XRP-USDT
```

en vez de `SYMBOLS=ALL`. Menos señales, pero cada una con spread/slippage
mucho más bajo — en la práctica esto suele importar más para la
rentabilidad neta que cualquier ajuste de `k_dominance` o `lookback_energy`.

## 6. Vías reales para mejorar la rentabilidad (en orden de impacto esperado)

1. **Filtrar por liquidez antes que por señal.** Añade un filtro de volumen
   mínimo en 24h (BingX lo da en `/openApi/swap/v2/quote/ticker`) y excluye
   símbolos por debajo de un umbral, incluso en modo `SYMBOLS=ALL`. Esto es
   más importante que cualquier parámetro del wavelet.
2. **Funding rate.** Si mantienes una posición varias horas y el funding va
   en tu contra, es un coste recurrente no modelado en el backtest de Pine.
   Consulta `/openApi/swap/v2/quote/premiumIndex` antes de entrar y evita
   entradas con funding muy desfavorable a tu dirección.
3. **Comparar contra el baseline sin filtro** (punto 3.2 más arriba) — si
   todavía no lo has hecho, es la prueba más barata para saber si el
   "wavelet" aporta algo o si el edge (si lo hay) viene solo del cruce de
   SMA con buen SL/TP en ATR.
4. **Tamaño de muestra real.** Antes de sacar conclusiones sobre si "gana
   más" o "gana menos", necesitas semanas de datos con capital real pequeño,
   no unas pocas docenas de operaciones — con la varianza de un sistema
   intradía en 5m, unas pocas operaciones no dicen casi nada.
5. **No hay atajo matemático que sustituya a esto.** Ninguna variante del
   filtro (más escalas, Daubechies real, etc.) arregla comisión+spread+
   slippage en activos ilíquidos — eso hay que resolverlo con selección de
   universo y sizing, no con más sofisticación en la señal.

## 7. Verificación externa adicional (septiembre 2026)

Búsqueda dirigida sobre tres preguntas concretas que quedaban abiertas en
este documento: (a) ¿hay evidencia empírica real de que un filtro tipo
"energía gruesa vs. fina" mejore un sistema de por sí, más allá del
argumento teórico de la sección 2? (b) ¿qué tan fiable es la literatura
académica que sí reporta resultados con wavelets en trading? (c) ¿sigue
siendo válida la capa de ejecución contra BingX que usa este bot?

### 7.1 Evidencia real del filtro de régimen (Efficiency Ratio de Kaufman)

Dado que el filtro "wavelet" de este bot es matemáticamente primo hermano
del Efficiency Ratio de Kaufman (sección 1), vale mirar qué pasa cuando
*alguien lo prueba de verdad* en vez de solo argumentarlo. Un backtest
publicado por Alvarez Quant Trading, aplicando un filtro de ER como umbral
de entrada sobre dos estrategias de reversión a la media, encontró mejoras
en casi todas las métricas relevantes a la vez (exposición, CAGR, drawdown
máximo, Sharpe, % de aciertos) — pero el mismo filtro **no funcionó** en
una tercera estrategia probada. La lectura correcta no es "el filtro
funciona" ni "no funciona", sino que su efecto depende del sistema al que
se acopla y hay que probarlo empíricamente en cada caso, exactamente lo que
ya recomienda la sección 3 de este documento. Un matiz importante: el uso
*original* de Kaufman para el ER es como filtro estático de selección de
instrumento (calculado una vez sobre el histórico completo, para decidir
qué activos operar), no como semáforo dinámico barra a barra — que es como
lo usa este bot (y como lo usa la mayoría de implementaciones modernas). No
invalida el enfoque, pero es un recordatorio de que "inspirado en Kaufman"
y "lo que Kaufman validó" no son lo mismo.

### 7.2 La literatura de "wavelets + trading" tiene un problema sistemático de sobreajuste

Varios papers académicos que combinan wavelets con trading (denoising +
LSTM, wavelets + genética sobre MACD, etc.) reportan retornos anualizados
del 200%, 300%, incluso 700%+ en backtest. Esto **no es una señal de que la
técnica funcione** — es la firma clásica de sobreajuste: ese nivel de
retorno sostenido no existe en ningún mercado líquido real durante periodos
largos, y ese tipo de papers casi nunca modela comisión+slippage+ejecución
realista ni valida de verdad fuera de muestra. Es la misma trampa que ya
señala la sección 3 de este documento sobre el hilo de X original ("$80 →
$4.900"), solo que con más aparato matemático encima — el aparato
matemático no protege contra el sobreajuste, y a veces lo camufla mejor.
Como contraejemplo de cómo *sí* se debería abordar esto: un trabajo sobre
trading de cripto con RL propone tratar el sobreajuste como una hipótesis
a testear explícitamente (estimar la probabilidad de que un modelo esté
sobreajustado y descartarlo) en vez de reportar un solo backtest bonito —
ese es el estándar contra el que deberías medir cualquier mejora que le
hagas a este bot, incluida la que ya recomienda la sección 3.2 (comparar
contra baseline sin filtro, fuera de muestra).

Si en algún momento quieres ir más allá de la aproximación Haar actual
(diferencia de SMAs, la más burda de todas las wavelets) hacia una DWT real
con Daubechies/Symlets — que es literalmente lo que vendía el hilo de X
original — la librería `PyWavelets` (`pywt.wavedec`/`pywt.waverec`) es el
camino estándar en Python. Vale como experimento, pero no esperes que
cambie la conclusión de fondo: la lógica de "compara energía gruesa vs.
fina" ya está capturada, aunque toscamente, por la versión Haar actual: una
DWT más sofisticada probablemente afina el filtro marginalmente, no lo
transforma en algo cualitativamente distinto.

### 7.3 Capa de ejecución (BingX): sigue vigente, con un dato actualizado

Se verificó contra documentación y wrappers de terceros actuales que el
formato de `bingx_client.py` para adjuntar `stopLoss`/`takeProfit` (JSON
serializado como string dentro de los parámetros del propio `POST` de la
orden, con `type`/`stopPrice`/`workingType`) sigue siendo el patrón
correcto de la API nativa de BingX, y que `positionSide: LONG/SHORT` es
correcto **solo si tu cuenta está en modo hedge** — en modo one-way BingX
espera `positionSide: BOTH` y rechazaría la orden. Esto ya estaba
documentado como advertencia en el README de este proyecto; con
`AUTO_TRADE=true` real vale la pena confirmarlo una vez en BingX (Cuenta →
Preferencias → Modo de posición) antes de dejarlo desatendido.

Dato que sí cambió: el rate limit compartido de los endpoints de datos de
mercado que cita este documento y `scanner.py` (500 peticiones/10s) quedó
desactualizado — BingX lo subió a 2.000 peticiones/10s a lo largo de 2025.
El pacing actual de `scanner.py` (`REQUEST_PACING_SECONDS`) seguía siendo
conservador incluso bajo el límite viejo, así que no hay urgencia de
tocarlo, pero si algún día quieres escanear más símbolos por ciclo en modo
`SYMBOLS=ALL`, hay bastante más margen del que sugería el comentario
original.

### 7.4 Conclusión de esta ronda

Nada de esto cambia la recomendación de fondo de este documento (sección
4): el filtro de régimen es una idea razonable con algo de respaldo
empírico real pero nada garantizado, y el valor más fiable de todo el
sistema sigue siendo la disciplina de riesgo — sizing por %, SL/TP por ATR,
verificación de que el SL/TP se adjuntó de verdad, tope duro de posiciones.
Vale la pena decirlo explícitamente porque es relevante para la decisión
tomada en esta misma sesión de desactivar el circuit breaker automático
(pérdidas consecutivas / drawdown diario): de los cuatro mecanismos de
disciplina que este bot implementa, ahora quedan tres activos (sizing,
SL/TP verificado, tope duro de posiciones) y uno queda como opt-in
(`CIRCUIT_BREAKER_ENABLED=true` para recuperarlo). No es una corrección de
rumbo, es información para que la decisión siga siendo la tuya con el
panorama completo delante.
