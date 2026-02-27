# ❓ PREGUNTAS FRECUENTES (FAQ)

## 🔧 CONFIGURACIÓN E INSTALACIÓN

### ¿Cuánto capital necesito para empezar?
**Mínimo recomendado: $50-100**
- Con $50: usa FIXED_USDT=4, MAX_OPEN_TRADES=8
- Con $100: usa FIXED_USDT=8, MAX_OPEN_TRADES=12
- Con $500: usa FIXED_USDT=15, MAX_OPEN_TRADES=15

### ¿Puedo usar Binance en lugar de BingX?
**No directamente.** El bot está específicamente codificado para BingX Perpetual Futures.
Para usar Binance necesitarías modificar el código (cambiar el exchange en ccxt).

### ¿El bot funciona en testnet/paper trading?
**No.** El bot opera directamente en producción con dinero real.
Para probar sin riesgo: usa capital muy pequeño ($20-50) con configuración conservadora.

### ¿Puedo correr el bot en mi PC en lugar de Railway?
**Sí**, pero no es recomendable:
- Tu PC debe estar encendida 24/7
- Necesitas conexión a internet estable
- Railway ofrece mayor uptime y menos problemas

Para correr local:
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
**Máximo:** El valor de `DAILY_LOSS_LIMIT` (default 8%)
- Con $100 y DAILY_LOSS_LIMIT=8 → máximo $8/día
- El bot se detiene automáticamente al alcanzar este límite

### ¿Cuánto puedo perder en total?
**Máximo:** El valor de `MAX_DRAWDOWN` (default 15%)
- Con $100 y MAX_DRAWDOWN=15 → el bot para si pierdes $15 totales
- Circuit breaker protege tu capital

### ¿Cuánto puedo ganar al mes?
**Depende de muchos factores:**
- Capital: $100-200 → 5-20%/mes (conservador)
- Capital: $500-1000 → 10-40%/mes (balanceado)
- Capital: $1000+ → 20-100%/mes (agresivo)

**⚠️ NO hay garantías.** Los resultados pasados no garantizan resultados futuros.

### ¿Qué pasa si mi balance llega a $0?
El bot se detendrá automáticamente porque no tendrá fondos para abrir trades.
Por esto es importante usar protecciones (MAX_DRAWDOWN, DAILY_LOSS_LIMIT).

---

## 🤖 FUNCIONAMIENTO DEL BOT

### ¿El bot opera 24/7 sin descanso?
**Sí.** El bot escanea el mercado continuamente:
- Sin horarios
- Sin pausas
- Sin días festivos
- Opera fines de semana

### ¿Cuántos trades puede hacer por día?
Depende de la configuración:
- **Conservador**: 2-5 trades/día
- **Balanceado**: 8-15 trades/día
- **Agresivo**: 20-40 trades/día

### ¿Puede hacer LONG y SHORT del mismo par simultáneamente?
**No** (por diseño). Si hay LONG en BTC/USDT, no abrirá SHORT en BTC/USDT.
Esto evita operaciones conflictivas en la misma moneda base.

### ¿Qué pasa si se cae Railway?
- Railway tiene 99.9% uptime
- Si cae, el bot simplemente se detiene
- Las posiciones abiertas en BingX mantienen sus stop loss
- Al volver Railway, el bot continúa desde donde quedó

### ¿El bot cierra posiciones antes de apagarse?
**No.** Si detienes el bot, las posiciones quedan abiertas en BingX con sus SL/TP.
Para cerrar todo: ve a BingX manualmente y cierra las posiciones.

---

## 📊 ESTRATEGIA Y TRADES

### ¿Cómo decide el bot qué pares tradear?
1. Escanea TOP_N_SYMBOLS pares (default 300)
2. Filtra por volumen mínimo (MIN_VOLUME_USDT)
3. Calcula score de 0-12 para LONG y SHORT
4. Abre trades si score >= MIN_SCORE (default 4)
5. Prioriza por score más alto (no por volumen)

### ¿Qué es el "score" de confluencia?
Un sistema de puntos (0-12) que evalúa 12 condiciones técnicas:
- Tendencia (EMAs)
- Momentum (ADX, MACD)
- Osciladores (RSI, Stochastic)
- Volumen (compra vs venta)
- Patrones (velas, divergencias)

**Score mayor = señal más fuerte**

### ¿Por qué no está abriendo trades?
Posibles causas:
1. **Score muy alto**: Reduce MIN_SCORE de 4 a 3
2. **Filtro BTC activo**: Si BTC bajista, bloquea LONGs (y viceversa)
3. **Spread alto**: Los pares tienen spread > MAX_SPREAD_PCT
4. **Cooldown activo**: Par cerrado recientemente (COOLDOWN_MIN)
5. **Universo pequeño**: Aumenta TOP_N_SYMBOLS o reduce MIN_VOLUME_USDT

### ¿Cómo sé si un trade va bien?
Alertas en Telegram:
- ⚡ Entrada → trade abierto
- 🎯 TP1 (50%) → primera ganancia, SL movido a break-even
- 🏆 TP2 (100%) → ganancia completa
- 🛑 Stop Loss → pérdida

También: revisa logs en Railway → muestra profit/loss en tiempo real

### ¿Puedo cerrar un trade manualmente?
**Sí**, en BingX:
1. Ve a Positions
2. Click en el par
3. Close Position
El bot detectará el cierre en el siguiente ciclo (~60s)

---

## ⚙️ CONFIGURACIÓN AVANZADA

### ¿Qué es BTC_FILTER y debo usarlo?
**BTC_FILTER=true** (recomendado):
- Si BTC bajista → No abre LONGs
- Si BTC alcista → No abre SHORTs
- Reduce trades contra tendencia macro

**BTC_FILTER=false** (más trades, más riesgo):
- Opera LONGs y SHORTs sin importar BTC
- Mayor cantidad de señales

### ¿Qué es BLACKLIST?
Lista de pares que NO quieres tradear:
```
BLACKLIST=BTC/USDT:USDT,ETH/USDT:USDT
```
Útil para excluir pares muy volátiles o con alta comisión.

### ¿Qué timeframe es mejor?
Depende de tu estilo:
- **1m/5m**: Scalping, muchos trades, alta frecuencia
- **5m/15m**: Intraday, balance (recomendado)
- **15m/1h**: Swing, menos trades, mayor duración
- **1h/4h**: Position, pocos trades, días de duración

### ¿Puedo cambiar TP y SL?
Sí, pero requiere modificar el código (bot.py):
```python
TP1_MULT = 1.2  # TP1 a 1.2x ATR (default)
TP2_MULT = 3.0  # TP2 a 3.0x ATR (default)
SL_ATR   = 1.0  # SL a 1.0x ATR (default)
```

---

## 🔒 SEGURIDAD

### ¿Es seguro dejar mis API keys en Railway?
**Sí**, Railway encripta las variables de entorno.
**Importante:**
- Repo GitHub debe ser PRIVADO
- Nunca compartas tus variables públicamente
- Usa API keys sin permiso de "Withdraw"

### ¿Pueden robarme fondos con las API keys?
**No**, si sigues estas reglas:
1. API con permisos SOLO Read + Trade
2. Sin permiso "Withdraw"
3. (Opcional) IP whitelist en BingX

### ¿Qué hago si expongo mis API keys accidentalmente?
**INMEDIATAMENTE:**
1. Ve a BingX → API Management
2. Revoca/borra la API Key comprometida
3. Crea nueva API Key
4. Actualiza en Railway → Variables

### Mi bot fue hackeado, ¿qué hago?
1. **Detén el bot** en Railway
2. **Revoca API keys** en BingX
3. **Cambia contraseñas** de BingX, GitHub, Railway
4. **Revisa transacciones** en BingX
5. Si hay retiros no autorizados: contacta soporte BingX

---

## 📱 TELEGRAM

### No recibo alertas de Telegram
**Checklist:**
1. ¿TOKEN correcto? Verifica con @BotFather
2. ¿CHAT_ID correcto? Verifica con @userinfobot
3. ¿Bot en el grupo? Si usas grupo, añade el bot
4. ¿Chat ID empieza con -100...? Para grupos debe empezar así
5. ¿Variables en Railway? Verifica que están configuradas

### Recibo demasiadas alertas
**Reduce la frecuencia:**
- El bot envía resumen cada 20 ciclos
- Si POLL_SECONDS=60 → resumen cada ~20min
- Si quieres menos: aumenta POLL_SECONDS a 120 o 180

O **desactiva alertas de entradas** modificando el código.

### ¿Puedo controlar el bot desde Telegram?
**No** (por diseño). El bot solo envía alertas, no recibe comandos.
Para control remoto necesitarías añadir comandos de Telegram al código.

---

## 🚨 PROBLEMAS COMUNES

### "DRY-RUN: sin claves API"
**Solución:** Añade BINGX_API_KEY y BINGX_API_SECRET en Railway → Variables

### "No se pudo conectar al exchange"
**Causas:**
- API Keys incorrectas
- Sin permisos Read + Trade
- IP bloqueada (si tienes whitelist)

**Solución:** Verifica claves en BingX y permisos

### "Circuit breaker activated"
**Esto es normal** - protección activada por pérdidas > MAX_DRAWDOWN
**Solución:**
1. Analiza qué causó las pérdidas
2. Ajusta configuración (reduce FIXED_USDT o MIN_SCORE)
3. Reinicia bot en Railway

### Bot se reinicia constantemente
**Revisa logs en Railway:**
- Error de sintaxis → verifica bot.py
- Error de CCXT → problema con BingX API
- Out of Memory → contacta soporte Railway

### "Insufficient balance"
**Balance insuficiente para abrir trade**
**Solución:**
1. Reduce FIXED_USDT (ej: de 8 a 5)
2. Reduce MAX_OPEN_TRADES
3. Añade más fondos a BingX

---

## 💵 COSTOS

### ¿Cuánto cuesta Railway?
- **Free Tier**: ~500 horas/mes (suficiente para probar)
- **Hobby Plan**: $5/mes (recomendado, ilimitado)

### ¿Cuánto cuesta BingX?
**Comisiones por trade:**
- Maker: 0.02%
- Taker: 0.04%

**Ejemplo:** Trade de $10
- Entrada: $10 × 0.04% = $0.004
- Salida: $10 × 0.04% = $0.004
- **Total por trade: ~$0.01**

Con 20 trades/día = $0.20/día = $6/mes en comisiones

### ¿Hay costos ocultos?
**No.** Solo:
- Railway: $5/mes
- BingX comisiones: ~$5-15/mes (según trades)

---

## 📈 RESULTADOS

### ¿Cuál es el win rate esperado?
Depende de la configuración:
- **Conservador (MIN_SCORE=6+)**: 50-60%
- **Balanceado (MIN_SCORE=4)**: 45-55%
- **Agresivo (MIN_SCORE=3)**: 40-50%

**Nota:** Win rate alto NO significa más ganancias.
Profit factor (ganancias/pérdidas) es más importante.

### ¿Es normal tener días con pérdidas?
**Sí, totalmente normal.** El trading tiene rachas:
- Días buenos: +5-15%
- Días malos: -3-8%
- Días neutros: ±1%

Lo importante es la tendencia mensual positiva.

### ¿Después de cuánto tiempo veo resultados?
**Mínimo 1-2 semanas** para evaluar:
- Win rate
- Profit factor
- Comportamiento en diferentes condiciones

**NO juzgues el bot en 1-2 días.**

---

## 🔄 ACTUALIZACIONES Y MANTENIMIENTO

### ¿Debo actualizar el bot?
Solo si hay nueva versión en el repo original.
El bot funciona indefinidamente sin actualizaciones.

### ¿Cómo actualizo el código?
```bash
# Si hay cambios en el repo original
git pull origin main
git push

# Railway redesplegará automáticamente
```

### ¿Debo monitorear el bot diariamente?
**Recomendado:**
- Revisa Telegram 2-3 veces al día
- Revisa balance semanal en BingX
- Ajusta configuración mensual según resultados

---

## 🆘 SOPORTE

### ¿Dónde obtengo ayuda?
1. **Docs oficiales**: Lee README.md y archivos .md
2. **Logs de Railway**: Revisar errores específicos
3. **Telegram de BingX**: Soporte oficial de la exchange
4. **Comunidades de trading**: Foros y grupos

### ¿Hay soporte técnico?
Este es un bot open-source, no hay soporte oficial.
Cualquier duda técnica debe resolverse por tu cuenta.

### ¿Puedo contratar a alguien para configurarlo?
Sí, pero **ten cuidado:**
- Nunca des acceso a tu cuenta BingX
- Solo comparte variables en Railway (no passwords)
- Verifica identidad de quien contrates

---

## ⚠️ DISCLAIMER LEGAL

**Este bot es para uso educativo y experimental.**

- ❌ No hay garantías de ganancias
- ❌ Trading conlleva riesgo de pérdida total
- ❌ No somos asesores financieros
- ❌ No nos responsabilizamos por pérdidas

**Usa bajo tu propio riesgo.**

---

¿Tienes más preguntas? Revisa los otros archivos .md incluidos en el paquete.
