# ❓ PREGUNTAS FRECUENTES (FAQ) — v13

---

## 🔧 CONFIGURACIÓN E INSTALACIÓN

### ¿Cuánto capital necesito para empezar?
**Mínimo recomendado: $50-100**
- Con $50: `FIXED_USDT=4`, `MAX_OPEN_TRADES=8`, `MIN_SCORE=8`
- Con $100: `FIXED_USDT=8`, `MAX_OPEN_TRADES=12`, `MIN_SCORE=6`
- Con $500: `FIXED_USDT=15`, `MAX_OPEN_TRADES=15`, `MIN_SCORE=5`

### ¿El bot funciona en testnet/paper trading?
**No.** Opera directamente en producción con dinero real.
Para probar sin riesgo: usa capital muy pequeño ($20-50) con MIN_SCORE=9.

### ¿Puedo correr el bot en mi PC?
**Sí**, pero no recomendable (necesitas 24/7). Para correr local:
```bash
pip install -r requirements.txt
export BINGX_API_KEY="tu_key"
export BINGX_API_SECRET="tu_secret"
export TELEGRAM_BOT_TOKEN="tu_token"
export TELEGRAM_CHAT_ID="tu_chat_id"
python bot.py
```

---

## 💰 CAPITAL Y RIESGO

### ¿Cuánto puedo perder en un día?
**Máximo:** valor de `DAILY_LOSS_LIMIT` (default 8%)
- Con $100 y DAILY_LOSS_LIMIT=8 → máximo $8/día
- El bot se detiene automáticamente al alcanzar este límite

### ¿Cuánto puedo perder en total?
**Máximo:** valor de `MAX_DRAWDOWN` (default 15%)
- Circuit breaker se activa → bot para de operar

### ¿Cuánto puede ganar al mes?
Depende del perfil, el mercado y la configuración. No hay garantías.
Los resultados varían enormemente según las condiciones del mercado.

---

## 🤖 FUNCIONAMIENTO DEL BOT

### ¿El bot opera 24/7 sin descanso?
**Sí.** Sin horarios, sin pausas, sin días festivos.

### ¿Cuántos trades puede hacer por día?
- **Conservador** (MIN_SCORE=8): 1-4 trades/día
- **Balanceado** (MIN_SCORE=5): 6-14 trades/día
- **Agresivo** (MIN_SCORE=4): 20-40 trades/día

### ¿Puede hacer LONG y SHORT del mismo par simultáneamente?
**No.** Si hay LONG en BTC/USDT, no abrirá SHORT en BTC/USDT (mismo base currency).

### ¿Qué pasa si se cae Railway?
Las posiciones abiertas en BingX mantienen sus SL/TP.
Al volver Railway, el bot continúa. Las posiciones cerradas externamente son detectadas.

---

## 📊 ESTRATEGIA — SCORE Y SEÑALES

### ¿Qué es el "score" de confluencia en v13?
Un sistema de puntos de **0 a 16** que evalúa:
- Puntos 1-9: Indicadores clásicos (EMAs, ADX, RSI, MACD, volumen, velas)
- Punto 10-11: SMI (Stochastic Momentum Index)
- Punto 12: Divergencias RSI / Engulfing
- Punto 13: **UTBot** (ATR Trailing Stop signal — HPotter)
- Punto 14: **WaveTrend** (TCI oscillator — Instrument-Z)
- Punto 15: **MA Cross** EMA8/EMA21 (Bj Bot framework)
- Punto 16: **BB+RSI** (Bollinger Bands — rouxam)

**Score mayor = más indicadores confirmando la misma dirección.**

### ¿Por qué ahora el score es sobre 16 y no 12?
La v13 integró 4 Pine Scripts de TradingView, añadiendo 4 nuevos puntos al sistema.
MIN_SCORE default cambió de 4 a 5. Si usabas MIN_SCORE=4 en v12, usa MIN_SCORE=5 o 6 en v13.

### ¿Por qué no está abriendo trades?
Posibles causas:
1. **MIN_SCORE muy alto**: Con score=16, baja a 5-7
2. **UTBot sin señal**: Sube `UTBOT_KEY_VALUE` para activarlo en más situaciones
3. **WaveTrend en zona neutral**: El WT no está en OB/OS ni cruzando
4. **Filtro BTC activo**: BTC_FILTER bloquea LONGs si BTC bajista
5. **Spread alto**: Los pares tienen spread > MAX_SPREAD_PCT
6. **Cooldown activo**: Par cerrado recientemente
7. **Universo pequeño**: Aumenta TOP_N_SYMBOLS

### ¿Cómo funcionan los nuevos targets de TP y SL?
Con el Bj Bot framework (R:R dinámico):
- **SL** = swing_low (LONG) o swing_high (SHORT) - ATR × RISK_MULT
- **TP2** = entrada + RNR × (entrada - SL)
- **TP1** = punto medio entre entrada y TP2

Ejemplo con RNR=2.0: si SL está $100 abajo de entrada → TP2 está $200 arriba.

### ¿Qué hace el UTBot en la gestión del trade?
Dos funciones:
1. **Score**: La señal buy/sell del UTBot suma 1 punto (punto 13/16)
2. **Trailing stop adicional**: Si el UTBot genera señal contraria mientras hay profit activo, cierra el trade. Actúa como una 2ª capa de protección tras TP1.

### ¿Qué es el R:R Trail (Bj Bot rrExit)?
Cuando el precio alcanza `RR_EXIT × (TP2-entrada)`, se activa el trailing agresivo.
- `RR_EXIT=0.5` → trailing activo al llegar al 50% del camino a TP2
- `RR_EXIT=0.0` → trailing inmediato desde TP1
- `RR_EXIT=0.8` → trailing solo cuando estás muy cerca de TP2

### ¿Qué hace el TRADE_EXPIRE_BARS?
Cierra automáticamente trades que llevan demasiadas barras abiertos.
Inspirado en Instrument-Z (expire trades que no se mueven).
- `TRADE_EXPIRE_BARS=0` → desactivado (trades duran lo que sea necesario)
- `TRADE_EXPIRE_BARS=100` en 5m → trade se cierra si no alcanzó TP2 en ~8 horas

---

## ⚙️ CONFIGURACIÓN AVANZADA

### ¿Cómo afecta UTBOT_KEY_VALUE?
- **Valor bajo (7-8)**: Muy sensible, señales frecuentes, puede generar ruido
- **Valor medio (10)**: Recomendado para la mayoría
- **Valor alto (14-20)**: Pocas señales, solo tendencias fuertes

### ¿Cómo afecta RNR?
- `RNR=1.5` → TP2 a 1.5× el riesgo (más trades ganadores pero ganancias menores)
- `RNR=2.0` → TP2 a 2× el riesgo (balance estándar)
- `RNR=3.0` → TP2 a 3× el riesgo (muy pocos alcanzan TP2, pero los que sí son grandes)

### ¿Cambio MIN_SCORE de v12 a v13?
Sí. El score máximo pasó de 12 a 16:
- v12 `MIN_SCORE=4` (33% de 12) ≈ v13 `MIN_SCORE=5` (31% de 16)
- v12 `MIN_SCORE=6` (50% de 12) ≈ v13 `MIN_SCORE=8` (50% de 16)
- v12 `MIN_SCORE=8` (67% de 12) ≈ v13 `MIN_SCORE=11` (67% de 16)

---

## 🔒 SEGURIDAD

### ¿Es seguro dejar mis API keys en Railway?
Sí, Railway encripta las variables de entorno.
**Siempre:** Repo GitHub PRIVADO, API sin permiso "Withdraw".

### ¿Qué hago si expongo mis API keys?
1. BingX → API Management → Revoca la API Key comprometida
2. Crea nueva API Key
3. Actualiza en Railway → Variables

---

## 📱 TELEGRAM

### No recibo alertas de Telegram
1. ¿TOKEN correcto? Verifica con @BotFather
2. ¿CHAT_ID correcto? Verifica con @userinfobot
3. ¿Bot añadido al grupo? Si usas grupo, el bot debe ser miembro
4. ¿CHAT_ID de grupo empieza con -100...?

### ¿Qué nuevas alertas hay en v13?
- 📐 **R:R TRAIL ACTIVADO** — cuando el precio alcanza el trigger de Bj Bot
- 🤖 **UTBOT TRAILING STOP** — cuando UTBot cierra el trade
- ⏳ **EXPIRADO** — cuando TRADE_EXPIRE_BARS se alcanza
- Las alertas de entrada ahora muestran: UTBot stop level + WaveTrend value

---

## 🚨 PROBLEMAS COMUNES

### "Score 0 en todos los pares"
- Verifica que los datos tienen suficiente historia (UTBot necesita >10 barras, WT >12)
- Si usas timeframe 1m, asegúrate que POLL_SECONDS=30 o menos

### "UTBot nunca señala"
- Baja `UTBOT_KEY_VALUE` de 10 a 7
- Reduce `UTBOT_ATR_PERIOD` de 10 a 7

### "WaveTrend nunca en OB/OS"
- El mercado puede estar en tendencia lateral (WT se queda en zona neutral)
- Baja `WT_OB` de 60 a 50 y `WT_OS` de -60 a -50

### "TP2 casi nunca se alcanza"
- Reduce `RNR` de 2.0 a 1.5
- O reduce `RR_EXIT` para activar el trailing antes

### "Circuit breaker activated"
Normal — protección activada. Reinicia en Railway.
Considera: reducir FIXED_USDT o subir MIN_SCORE.

### "Insufficient balance"
Reduce `FIXED_USDT` o `MAX_OPEN_TRADES`.

---

## 💵 COSTOS

| Servicio | Costo |
|----------|-------|
| Railway Hobby | $5/mes |
| BingX comisiones | 0.02-0.04% por trade |
| Total estimado | $10-20/mes |

---

## 📈 RESULTADOS ESPERADOS

| Perfil | MIN_SCORE | Win Rate | Trades/día | 
|--------|-----------|----------|------------|
| Conservador | 8 | 55-65% | 1-4 |
| Balanceado | 5-6 | 48-58% | 6-14 |
| Agresivo | 4 | 42-52% | 20-40 |
| Scalper | 5 | 45-52% | 30-70 |

**No hay garantías.** Los resultados dependen del mercado y la configuración.

### ¿Después de cuánto tiempo veo resultados?
Mínimo 2-3 semanas para evaluar win rate y profit factor.
No juzgues el bot en menos de 50 trades.

---

## ⚠️ DISCLAIMER LEGAL

**Este bot es para uso educativo y experimental.**
- ❌ No hay garantías de ganancias
- ❌ El trading conlleva riesgo de pérdida total
- ❌ No somos asesores financieros
- ❌ No nos responsabilizamos por pérdidas

**Usa bajo tu propio riesgo.**
