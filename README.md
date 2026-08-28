# Bot RSI Doble Suelo + SuperTrend — BingX

Traducción fiel y standalone del script Pine "ProBorsa: RSI &
SuperTrend Özel Dip Stratejisi". **Proyecto aparte** del bot de
reversión — no comparte filtros, no comparte estado, no comparte
carpeta en el repo.

**Arranca en modo SIGNAL.** Avisa por Telegram y no toca el exchange.

---

## Antes de nada: esto no tiene nada de lo que sí tiene el bot de reversión

Y hay que decirlo claro, porque el contraste importa:

- **Sin filtro de amplitud.** El bot de reversión no opera un símbolo
  si el ATR no cubre 30× el coste de operar — el hallazgo principal de
  todo ese proyecto. Este bot no tiene ningún filtro así: si el RSI
  cruza dos veces bajo 50, entra, sea cual sea la volatilidad del
  símbolo.
- **Sin backtest.** El bot de reversión tiene 35 operaciones medidas
  (pocas, pero medidas) y un README entero explicando qué combinación
  de símbolo y contexto funcionó. Este es un script encontrado y
  traducido — cero operaciones medidas, cero garantía de que el RSI
  cruzando dos veces bajo 50 sea una ventaja real y no ruido con buena
  pinta.
- **Volumen de señales altísimo.** El log que dio origen a esto generó
  más de 40 señales en un solo día. El bot de reversión, con su filtro
  de amplitud, puede pasar días sin ninguna. Esa diferencia no es un
  defecto de ninguno de los dos — es que son estrategias completamente
  distintas, y este genera muchísimas más operaciones, así que cada
  error de tamaño se repite muchísimas más veces.
- **Sin TP, salida por SuperTrend.** El tamaño del ganador lo decide
  por completo cuánto tarde el SuperTrend en girar — puede ser una
  racha muy buena o una sangría lenta si el mercado se mueve lateral.
  Sin datos propios no hay forma de saber cuál de las dos es más
  probable en tu universo.

**Recomendación honesta:** déjalo en SIGNAL bastante más tiempo del que
dejarías el bot de reversión — no por ser peor estrategia, sino porque
no hay NADA medido todavía, ni siquiera 35 operaciones.

---

## Bug corregido (visto en producción el 28/08/2026)

La primera versión desplegada cerraba posiciones al instante, al mismo
precio de entrada (`REDSTONE-USDT` se abrió y cerró 3 veces en 11
minutos, siempre 0.1044 → 0.1044, +0.00%). No era el mercado — la
función de salida miraba "¿el SuperTrend está bajista AHORA?" en vez de
"¿ACABA de girar a bajista?" (`ta.change(stDirection) > 0` en el Pine
original). Si una señal de doble suelo RSI entraba en una vela donde el
SuperTrend ya estaba bajista por otra razón, la siguiente comprobación
lo veía "bajista" y cerraba en el acto.

Dos arreglos, ambos en `entry_rsi.py`:
- `flipped_bearish()` sustituye a la función anterior — detecta el
  CAMBIO de dirección, no el estado, igual que el Pine original.
- La entrada ahora exige que el SuperTrend NO esté ya bajista en la
  vela de la señal — pequeña desviación deliberada del original, para
  no quedar atascado esperando dos giros en vez de uno.
- `REENTRY_COOLDOWN_MIN` (15 min por defecto): cerrojo adicional para
  no perseguir el mismo símbolo dos veces seguidas en un mercado picado.

---

## La estrategia, en corto

1. RSI(10) y su propia media móvil SMA(10).
2. Cada vez que el RSI cruza por ENCIMA de su media MIENTRAS sigue por
   debajo de 50 (zona débil), cuenta un cruce.
3. El contador se reinicia cada vez que el RSI supera 50.
4. En el **2º cruce** desde el último reinicio, entra en largo — es un
   doble suelo visto en el RSI, no en el precio.
5. Sale cuando el SuperTrend(10, 2.5) gira de alcista a bajista. No hay
   TP ni SL de precio fijo en el script original.

Solo largo. El script Pine no tiene lado corto, y aquí no se le añadió
uno — a diferencia del RSI del bot de reversión, que sí se hizo
simétrico porque ese bot opera los dos lados.

---

## El stop de emergencia que el script original NO tenía

El Pine original nunca gestiona dinero real por sí solo — vive en
TradingView, cierra por lógica cuando cambia una variable interna. Eso
es aceptable en SIGNAL. Pero en LIVE, sin ningún stop físico en el
exchange, si el bot se cae o pierde conexión, la posición queda abierta
**sin nada protegiéndola** hasta que el bot vuelva a arrancar y sondee
el SuperTrend de nuevo.

Por eso, y SOLO en LIVE, este bot manda un stop de emergencia ancho
(`EMERGENCY_SL_PCT`, 8% por defecto) junto a la orden de entrada — no
debería tocarse en condiciones normales, es la red bajo la red. Puedes
desactivarlo con `EMERGENCY_SL_ENABLED=false` si prefieres una
traducción 100% literal, pero no es lo que se recomienda.

---

## Despliegue en Railway

1. Repo aparte en GitHub con estos archivos.
2. Railway → New Project → Deploy from GitHub repo.
3. Monta un volumen en `/data` (mismo motivo que el otro bot: sin
   volumen, el estado se pierde en cada redeploy).
4. Variables desde `.env.example` — mínimo `TELEGRAM_TOKEN` y
   `TELEGRAM_CHAT_ID` para SIGNAL.
5. Si ya tienes el bot de reversión en el mismo proyecto de Railway,
   usa un servicio NUEVO, no el mismo — `STATE_PATH` ya apunta a un
   archivo distinto (`state_rsi.json`) por si acaso comparten volumen,
   pero son dos procesos independientes.

## Pasar a LIVE

Mismos dos cerrojos que el otro bot:

```
MODE=LIVE
LIVE_CONFIRMED=true
BINGX_API_KEY=...
BINGX_API_SECRET=...
```

Con el volumen de señales de este bot, `RISK_PCT` importa todavía más
que en el de reversión — 0.25% por defecto multiplicado por 40+
señales/día es una exposición agregada que conviene mirar con calma
antes de subirla.

---

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `main.py` | Bucle: escaneo, señales, salidas por giro de SuperTrend |
| `entry_rsi.py` | Motor — RSI doble cruce + SuperTrend, traducción del Pine |
| `bingx.py` | Cliente de la API (reutilizado del bot de reversión, sin cambios) |
| `notify.py` | Telegram y estado en disco (reutilizado, sin cambios) |
| `config.py` | Variables de entorno |
| `requirements.txt` | httpx |
| `Procfile` / `railway.json` | Arranque en Railway |
| `.env.example` | Todas las variables documentadas |
| `.gitignore` | — |
