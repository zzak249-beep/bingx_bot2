# 🚨 DIAGNÓSTICO CRÍTICO — Bot No Funciona

## ❌ Problemas Encontrados

### 🔴 ERROR #1: Typo en `trader.py` (línea 61)

**Archivo:** `trader.py`, función `_can_reentry()`

```python
# ❌ INCORRECTO (línea actual)
return hours_passed >= REENTRY_COOL_DOWN

# ✅ CORRECTO
return hours_passed >= REENTRY_COOLDOWN
```

**Impacto:** Causa `NameError` si se intenta re-entry. Aunque no está llamado directamente, rompe el flujo.

---

### 🔴 ERROR #2: Lógica invertida en `strategy.py`

**Archivo:** `strategy.py`, cálculo de momentum

```python
# ❌ PROBLEMA: momentum_bars() cuenta velas BAJISTAS
bear_bars = momentum_bars(df["close"], i, lookback=5)  # OK para LONG
bull_bars = momentum_bars(df["close"], i, lookback=5)  # ❌ INCORRECTO - también cuenta bajistas!

# En calc_score_short(), bull_bars se penaliza, pero cuenta bajistas (invertido)
```

**Impacto:** Las señales SHORT están invertidas. Se penalizan cuando hay pocas velas bajistas (momento alcista), cuando debería penalizarse lo opuesto.

---

### 🔴 ERROR #3: Condiciones TOO RESTRICTIVAS en `strategy.py`

**Archivo:** `strategy.py`, líneas 103-127

```python
# LONG: OK, acepta trend != down
if trend_1h != "down" and price >= sma * 0.97:
    # ... genera señales

# SHORT: ❌ DEMASIADO RESTRICTIVO
if trend_1h == "flat" and price <= sma * 1.03:  # Requiere EXACTAMENTE "flat"
    # ... pero casi nunca trend será exactamente "flat"
```

**Impacto:** SHORT casi nunca se activa porque requiere `trend_1h == "flat"` exactamente. Ver cálculo en `indicators.py`:

```python
def get_trend(basis_series: pd.Series, i: int) -> str:
    if i < TREND_LOOKBACK: return "flat"
    change_pct = (now - prev) / prev * 100
    if   change_pct >  TREND_THRESH: return "up"
    elif change_pct < -TREND_THRESH: return "down"
    else:                             return "flat"
```

Con `TREND_THRESH = 0.04` (4%), la banda de "flat" es muy estrecha.

---

### 🔴 ERROR #4: Sin datos desde BingX

**Archivo:** `bingx_api.py`, función `fetch_klines()`

```python
def fetch_klines(symbol: str, interval: str = "15m", limit: int = 300) -> list:
    for path in ("/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"):
        try:
            r = requests.get(...)
            c = r if isinstance(r, list) else r.get("data", [])
            if c:
                return c
        except Exception:
            continue
    return []  # ← Retorna lista vacía si falla
```

**Impacto:** Si hay error de red o API rechaza (por API key sin permiso TRADE), retorna `[]` silenciosamente. `main.py` luego ve `df.empty` y continúa sin advertencia clara.

---

## ✅ SOLUCIONES

### FIX #1: Corregir typo en `trader.py`

Buscar y reemplazar:
```python
# Línea ~61
return hours_passed >= REENTRY_COOL_DOWN
```

Por:
```python
return hours_passed >= REENTRY_COOLDOWN
```

---

### FIX #2: Invertir lógica de SHORT en `strategy.py`

Cambiar:
```python
bull_bars = momentum_bars(df["close"], i, lookback=5)
```

Por:
```python
# Contar velas ALCISTAS (inversión de momentum_bars)
bear_count = momentum_bars(df["close"], i, lookback=5)
bull_bars = 5 - bear_count  # Si hay 2 bajistas, hay 3 alcistas
```

---

### FIX #3: Relajar condición SHORT en `strategy.py`

Cambiar:
```python
if trend_1h == "flat" and price <= sma * 1.03:
```

Por:
```python
if trend_1h != "up" and price <= sma * 1.03:  # Cualquier cosa que NO sea alcista
```

---

### FIX #4: Diagnóstico mejorado en `bingx_api.py`

Cambiar:
```python
def fetch_klines(symbol: str, interval: str = "15m", limit: int = 300) -> list:
    for path in ("/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"):
        try:
            r = requests.get(...)
            c = r if isinstance(r, list) else r.get("data", [])
            if c:
                return c
        except Exception:
            continue
    return []
```

Por:
```python
def fetch_klines(symbol: str, interval: str = "15m", limit: int = 300) -> list:
    for path in ("/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"):
        try:
            r = requests.get(
                BASE + path,
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=15
            )
            data = r.json()
            
            # Verificar si hay error en respuesta
            if data.get("code") != 0:
                print(f"  [API] {symbol} {interval}: code={data.get('code')} {data.get('msg','')}")
                continue
                
            c = data if isinstance(data, list) else data.get("data", [])
            if c:
                return c
        except Exception as e:
            print(f"  [FETCH] {symbol} {interval}: {e}")
            continue
    return []
```

---

## 🔍 CÓMO VERIFICAR QUE ESTÁ FUNCIONANDO

### 1. Verificar que lee datos
En `main.py`, alrededor de línea 50:
```python
df = data_feed.get_df(sym, interval="1h", limit=300)
if df.empty:
    print(f"  {sym}: ⚠️  sin datos de BingX")
    continue
```

**Debería ver:**
```
RSR-USDT  P=0.00524  — sin señal
LINK-USDT  P=24.5  — sin señal
...
```

Si VE "sin datos de BingX" para TODO, entonces:
- BingX API está caída
- API key no tiene acceso de lectura
- Red no funciona

### 2. Verificar que genera indicadores
Añadir debug en `strategy.py` después de `add_indicators()`:
```python
print(f"  [{symbol}] RSI={r:.1f} trend={trend_1h} bias_4h={bias_4h}")
```

### 3. Verificar que genera señales
Debería ver:
```
[LINK-USDT] ✅ SEÑAL LONG score=65 rsi=28.5 rr=2.1 4h=neutral
```

---

## 📋 CHECKLIST ANTES DE SUBIR A RAILWAY

- [ ] Corregir `REENTRY_COOL_DOWN` → `REENTRY_COOLDOWN` en `trader.py`
- [ ] Invertir lógica de `bull_bars` en `strategy.py`
- [ ] Cambiar condición SHORT: `trend_1h != "up"` en lugar de `trend_1h == "flat"`
- [ ] Añadir debug en `fetch_klines()` para ver errores de API
- [ ] Ejecutar `python test_bingx.py` en Railway → debe mostrar balance
- [ ] Ejecutar `python test_telegram.py` en Railway → debe recibir mensaje
- [ ] Esperar 1 ciclo completo (~15 min) → debe ver logs en Railway

---

## 🎯 RESUMEN

| Problema | Causa | Fix |
|----------|-------|-----|
| SHORT no se activa | `trend_1h == "flat"` es muy restrictivo | Cambiar a `!= "up"` |
| SHORT lógica invertida | `bull_bars` cuenta bajistas | Invertir: `5 - bear_count` |
| Crash en re-entry | Typo: `REENTRY_COOL_DOWN` | Cambiar a `REENTRY_COOLDOWN` |
| Sin error si API falla | `fetch_klines()` silencioso | Añadir logs |

**Prioridad:** HACER LOS 4 FIXES ANTES DE SUBIR
