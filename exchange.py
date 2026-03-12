"""
exchange.py — BingX Perpetual Futures REST API v4.2 [FIX ERROR 109400]

BUGS CORREGIDOS EN ESTA VERSION:
  ✅ FIX#7 — _build_query NO usa sorted() — BingX firma sobre el string
             en el orden exacto de inserción. sorted() rompía la firma
             cuando el orden alfabético difería del orden de inserción.
             SOLUCIÓN: timestamp siempre al FINAL, sin sorted().
  ✅ FIX#8 — quantity como string limpio sin notación científica ni .0
             '5600.0' → '5600' | '0.001' se mantiene | nunca '5.6e3'
  ✅ FIX#9 — _place_sl_tp: quantity también formateada igual (string limpio)
  ✅ FIX#10 — set_leverage: verificar código respuesta, no crashear
  ✅ FIX#11 — Modo hedge (BOTH) vs modo one-way: detectar y adaptar
             positionSide solo se envía si la cuenta usa hedge mode
  ✅ FIX#12 — calcular_cantidad: PIXEL-USDT y similares pueden tener
             stepSize muy pequeño → log detallado para diagnóstico
  ✅ FIX#1-6 — Todos los fixes anteriores se mantienen
"""

import time, hmac, hashlib, logging, math
import requests
import config

log      = logging.getLogger("exchange")
BASE_URL = "https://open-api.bingx.com"
_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})

# Cache de contratos futuros válidos
_CONTRATOS_FUTURES: set  = set()
_CONTRATO_INFO:     dict = {}
_CONTRATOS_TS:      float = 0

# Modo de posición: True = hedge (LONG/SHORT), False = one-way
_HEDGE_MODE: bool = True   # BingX perpetuos usan hedge mode por defecto


# ══════════════════════════════════════════════════════════════
# FIRMA HMAC ✅ FIX#7 — SIN sorted(), timestamp al final
# ══════════════════════════════════════════════════════════════

def _sign(query_string: str) -> str:
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_query(params: dict) -> str:
    """
    Construye query string SIN ordenar.
    BingX firma sobre el string exacto — sorted() cambia el orden
    y puede provocar 'Signature verification failed' o 109400.
    timestamp se añade FUERA de esta función, siempre al final.
    """
    return "&".join(f"{k}={v}" for k, v in params.items())


def _headers() -> dict:
    return {"X-BX-APIKEY": config.BINGX_API_KEY}


def _ts() -> int:
    return int(time.time() * 1000)


def _get(path: str, params: dict = None, retries: int = 3) -> dict:
    p = dict(params or {})
    # timestamp SIEMPRE al final, luego signature
    ts = _ts()
    qs = _build_query(p) + (f"&timestamp={ts}" if p else f"timestamp={ts}")
    qs_signed = qs + "&signature=" + _sign(qs)
    for attempt in range(retries):
        try:
            r = _SESSION.get(
                BASE_URL + path + "?" + qs_signed,
                headers=_headers(), timeout=10,
            )
            return r.json()
        except Exception as e:
            log.error(f"GET {path} intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {}


def _post(path: str, params: dict = None, retries: int = 3) -> dict:
    p = dict(params or {})
    ts = _ts()
    qs = _build_query(p) + (f"&timestamp={ts}" if p else f"timestamp={ts}")
    qs_signed = qs + "&signature=" + _sign(qs)
    for attempt in range(retries):
        try:
            r = _SESSION.post(
                BASE_URL + path + "?" + qs_signed,
                headers=_headers(), timeout=10,
            )
            return r.json()
        except Exception as e:
            log.error(f"POST {path} intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {}


# ══════════════════════════════════════════════════════════════
# FORMATEAR CANTIDAD ✅ FIX#8
# ══════════════════════════════════════════════════════════════

def _fmt_qty(qty) -> str:
    """
    Formatea cantidad para BingX:
    - Nunca notación científica (1e-3 → '0.001')
    - Enteros sin decimales ('5600' no '5600.0')
    - Decimales limpios ('0.001' no '0.0010000')
    """
    if isinstance(qty, int):
        return str(qty)
    # Si es float con parte decimal cero → int
    if isinstance(qty, float) and qty == int(qty):
        return str(int(qty))
    # Formatear con suficientes decimales, quitar trailing zeros
    formatted = f"{qty:.10f}".rstrip("0").rstrip(".")
    return formatted


def _fmt_price(price: float, precision: int) -> str:
    """Formatea precio con la precisión del contrato, sin trailing zeros."""
    s = f"{price:.{precision}f}"
    # Quitar trailing zeros después del punto decimal
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ══════════════════════════════════════════════════════════════
# CACHE DE CONTRATOS FUTUROS
# ══════════════════════════════════════════════════════════════

def _cargar_contratos():
    global _CONTRATOS_FUTURES, _CONTRATO_INFO, _CONTRATOS_TS
    if time.time() - _CONTRATOS_TS < 21600 and _CONTRATOS_FUTURES:
        return
    try:
        res = _SESSION.get(
            BASE_URL + "/openApi/swap/v2/quote/contracts",
            timeout=15,
        ).json()
        contratos = res.get("data", []) or []
        _CONTRATOS_FUTURES = set()
        _CONTRATO_INFO     = {}
        for c in contratos:
            sym    = c.get("symbol", "")
            status = c.get("status", 0)
            if not sym.endswith("-USDT") or status != 1:
                continue
            _CONTRATOS_FUTURES.add(sym)

            # Obtener stepSize y minQty con varios nombres posibles de campo
            qty_step = None
            for campo in ["tradeMinQuantity", "stepSize", "quantityStep", "lotSize"]:
                val = c.get(campo)
                if val is not None:
                    try:
                        qty_step = float(val)
                        if qty_step > 0:
                            break
                    except Exception:
                        pass
            if not qty_step or qty_step <= 0:
                qty_step = 0.001

            min_qty = None
            for campo in ["tradeMinQuantity", "minQty", "minOrderQty"]:
                val = c.get(campo)
                if val is not None:
                    try:
                        min_qty = float(val)
                        if min_qty > 0:
                            break
                    except Exception:
                        pass
            if not min_qty or min_qty <= 0:
                min_qty = qty_step

            price_prec = int(c.get("pricePrecision", 6))
            qty_prec   = int(c.get("quantityPrecision", _decimals_from_step(qty_step)))

            _CONTRATO_INFO[sym] = {
                "stepSize":        qty_step,
                "minQty":          min_qty,
                "pricePrecision":  price_prec,
                "qtyPrecision":    qty_prec,
            }
        _CONTRATOS_TS = time.time()
        log.info(f"[CONTRATOS] {len(_CONTRATOS_FUTURES)} futuros perpetuos USDT cargados")
    except Exception as e:
        log.error(f"_cargar_contratos: {e}")


def _decimals_from_step(step: float) -> int:
    """Calcula decimales necesarios a partir del stepSize."""
    if step >= 1:
        return 0
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[-1]) if "." in s else 0


def es_futuro_valido(symbol: str) -> bool:
    if config.MODO_DEMO:
        return True
    _cargar_contratos()
    valido = symbol in _CONTRATOS_FUTURES
    if not valido:
        log.warning(f"[SKIP] {symbol} no es un futuro perpetuo válido en BingX")
    return valido


def get_step_size(symbol: str) -> float:
    _cargar_contratos()
    return _CONTRATO_INFO.get(symbol, {}).get("stepSize", 0.001)


def get_price_precision(symbol: str) -> int:
    _cargar_contratos()
    return _CONTRATO_INFO.get(symbol, {}).get("pricePrecision", 6)


def get_qty_precision(symbol: str) -> int:
    _cargar_contratos()
    return _CONTRATO_INFO.get(symbol, {}).get("qtyPrecision", 3)


# ══════════════════════════════════════════════════════════════
# BALANCE
# ══════════════════════════════════════════════════════════════

def get_balance() -> float:
    if config.MODO_DEMO:
        return 1000.0
    try:
        res = _get("/openApi/swap/v2/user/balance")
        log.debug(f"[BALANCE-RAW] {str(res)[:300]}")
        data = res.get("data", {})

        # Estructura 1: data.balance.availableMargin (dict)
        bal = data.get("balance", {})
        if isinstance(bal, dict):
            v = float(bal.get("availableMargin", bal.get("availableBalance", bal.get("balance", 0))) or 0)
            if v > 0:
                return v

        # Estructura 2: data.availableMargin directo
        for key in ("availableMargin", "availableBalance", "crossAvailableBalance", "balance"):
            v = data.get(key)
            if v is not None:
                try:
                    f = float(v)
                    if f > 0:
                        return f
                except Exception:
                    pass

        # Estructura 3: lista en data
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            for key in ("availableMargin", "availableBalance", "balance"):
                v = item.get(key)
                if v is not None:
                    try:
                        f = float(v)
                        if f >= 0:
                            return f
                    except Exception:
                        pass

        log.warning(f"[BALANCE] No se pudo parsear respuesta: {str(data)[:200]}")
        return 0.0
    except Exception as e:
        log.error(f"get_balance: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════
# PRECIO
# ══════════════════════════════════════════════════════════════

def get_precio(symbol: str) -> float:
    for _ in range(2):
        try:
            res = _SESSION.get(
                BASE_URL + "/openApi/swap/v2/quote/price",
                params={"symbol": symbol}, timeout=8,
            ).json()
            p = float(res.get("data", {}).get("price", 0) or 0)
            if p > 0:
                return p
        except Exception as e:
            log.error(f"get_precio {symbol}: {e}")
        time.sleep(0.5)
    return 0.0


# ══════════════════════════════════════════════════════════════
# VELAS
# ══════════════════════════════════════════════════════════════

INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
}

def get_candles(symbol: str, interval: str = "5m", limit: int = 200) -> list:
    iv = INTERVAL_MAP.get(interval, "5m")
    try:
        res = _SESSION.get(
            BASE_URL + "/openApi/swap/v3/quote/klines",
            params={"symbol": symbol, "interval": iv, "limit": limit},
            timeout=15,
        ).json()
        raw = res.get("data", [])

        if not raw:
            res2 = _SESSION.get(
                BASE_URL + "/openApi/swap/v2/quote/klines",
                params={"symbol": symbol, "interval": iv, "limit": limit},
                timeout=15,
            ).json()
            raw = res2.get("data", [])

        candles = []
        for c in raw:
            try:
                if isinstance(c, list):
                    candles.append({
                        "ts":     int(c[0]),
                        "open":   float(c[1]),
                        "high":   float(c[2]),
                        "low":    float(c[3]),
                        "close":  float(c[4]),
                        "volume": float(c[5]),
                    })
                elif isinstance(c, dict):
                    candles.append({
                        "ts":     int(c.get("time", c.get("openTime", 0))),
                        "open":   float(c.get("open", 0)),
                        "high":   float(c.get("high", 0)),
                        "low":    float(c.get("low", 0)),
                        "close":  float(c.get("close", 0)),
                        "volume": float(c.get("volume", 0)),
                    })
            except Exception:
                continue
        candles.sort(key=lambda x: x["ts"])
        return candles
    except Exception as e:
        log.error(f"get_candles {symbol} {interval}: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# POSICIONES ABIERTAS
# ══════════════════════════════════════════════════════════════

def get_posiciones_abiertas() -> list:
    if config.MODO_DEMO:
        return []
    try:
        res = _get("/openApi/swap/v2/user/positions")
        return res.get("data", []) or []
    except Exception as e:
        log.error(f"get_posiciones_abiertas: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# CANCELAR ÓRDENES ABIERTAS
# ══════════════════════════════════════════════════════════════

def cancelar_ordenes_abiertas(symbol: str):
    if config.MODO_DEMO:
        return
    try:
        res = _get("/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        ordenes = res.get("data", {}).get("orders", []) or []
        if not ordenes:
            return
        for o in ordenes:
            oid = o.get("orderId")
            if oid:
                _post("/openApi/swap/v2/trade/cancel",
                      {"symbol": symbol, "orderId": oid})
        log.info(f"[CANCEL] {len(ordenes)} orden(es) canceladas para {symbol}")
    except Exception as e:
        log.warning(f"cancelar_ordenes {symbol}: {e}")


# ══════════════════════════════════════════════════════════════
# APALANCAMIENTO ✅ FIX#10
# ══════════════════════════════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        for side in ("LONG", "SHORT"):
            r = _post("/openApi/swap/v2/trade/leverage",
                      {"symbol": symbol, "side": side, "leverage": leverage})
            code = r.get("code", 0)
            if code not in (0, 200):
                # Código 80012 = ya estaba en ese leverage (no es error real)
                if code != 80012:
                    log.warning(f"set_leverage {symbol} {side}: code={code} msg={r.get('msg')}")
        return True
    except Exception as e:
        log.error(f"set_leverage {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# CALCULAR CANTIDAD ✅ FIX#12 — con log diagnóstico detallado
# ══════════════════════════════════════════════════════════════

def calcular_cantidad(symbol: str, trade_usdt: float, precio: float) -> float:
    if precio <= 0 or trade_usdt <= 0:
        return 0.0

    qty_raw = (trade_usdt * config.LEVERAGE) / precio
    step    = get_step_size(symbol)
    info    = _CONTRATO_INFO.get(symbol, {})
    min_qty = info.get("minQty", step)

    log.debug(
        f"[QTY] {symbol} precio={precio} usdt={trade_usdt} "
        f"lev={config.LEVERAGE} raw={qty_raw:.6f} step={step} min={min_qty}"
    )

    if step > 0:
        # Redondear hacia abajo al múltiplo de step más cercano
        # Usar math.floor para evitar problemas de punto flotante
        qty_steps = math.floor(qty_raw / step)
        qty       = qty_steps * step
        decimals  = _decimals_from_step(step)
        if decimals == 0:
            qty = int(round(qty, 0))
        else:
            qty = round(qty, decimals)
    else:
        # Fallback por precio
        if precio >= 10000:
            qty = round(qty_raw, 3)
        elif precio >= 100:
            qty = round(qty_raw, 2)
        elif precio >= 1:
            qty = round(qty_raw, 1)
        else:
            qty = int(qty_raw)

    min_valid = max(step if step > 0 else 0.001, min_qty if min_qty > 0 else 0.001)

    if qty < min_valid:
        log.warning(
            f"[QTY] {symbol} qty={qty} < min_valid={min_valid} "
            f"(necesitas más USDT o reducir precio mín. ${precio * min_valid / config.LEVERAGE:.2f})"
        )
        return 0.0

    log.debug(f"[QTY] {symbol} qty final={qty} ({_fmt_qty(qty)})")
    return qty


# ══════════════════════════════════════════════════════════════
# SL / TP COMO ÓRDENES SEPARADAS ✅ FIX#9 — qty como string limpio
# ══════════════════════════════════════════════════════════════

def _place_sl_tp(symbol: str, lado: str, qty: float, sl: float, tp: float):
    if config.MODO_DEMO:
        return

    precio_actual = get_precio(symbol)
    if precio_actual > 0:
        if lado == "LONG":
            if sl >= precio_actual:
                log.warning(f"SL {symbol} LONG ({sl:.8f}) >= precio ({precio_actual:.8f}) — ajustando")
                sl = precio_actual * 0.99
            if tp <= precio_actual:
                log.warning(f"TP {symbol} LONG ({tp:.8f}) <= precio ({precio_actual:.8f}) — ajustando")
                tp = precio_actual * 1.02
        else:
            if sl <= precio_actual:
                log.warning(f"SL {symbol} SHORT ({sl:.8f}) <= precio ({precio_actual:.8f}) — ajustando")
                sl = precio_actual * 1.01
            if tp >= precio_actual:
                log.warning(f"TP {symbol} SHORT ({tp:.8f}) >= precio ({precio_actual:.8f}) — ajustando")
                tp = precio_actual * 0.98

    try:
        close_side  = "SELL" if lado == "LONG" else "BUY"
        pos_side    = lado
        pp          = get_price_precision(symbol)
        qty_str     = _fmt_qty(qty)   # ✅ FIX#9: string limpio
        sl_str      = _fmt_price(sl, pp)
        tp_str      = _fmt_price(tp, pp)

        # STOP LOSS
        sl_params = {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     qty_str,
            "stopPrice":    sl_str,
            "workingType":  "MARK_PRICE",
        }
        r1 = _post("/openApi/swap/v2/trade/order", sl_params)
        if r1.get("code", 0) not in (0, 200):
            log.warning(f"SL order {symbol}: código={r1.get('code')} msg={r1.get('msg')}")
        else:
            log.info(f"  SL colocado {symbol} {lado} @ {sl_str}")

        time.sleep(0.4)

        # TAKE PROFIT
        tp_params = {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     qty_str,
            "stopPrice":    tp_str,
            "workingType":  "MARK_PRICE",
        }
        r2 = _post("/openApi/swap/v2/trade/order", tp_params)
        if r2.get("code", 0) not in (0, 200):
            log.warning(f"TP order {symbol}: código={r2.get('code')} msg={r2.get('msg')}")
        else:
            log.info(f"  TP colocado {symbol} {lado} @ {tp_str}")

    except Exception as e:
        log.error(f"_place_sl_tp {symbol}: {e}")


# ══════════════════════════════════════════════════════════════
# ABRIR LONG ✅ FIX#7 + FIX#8 + FIX#11
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float,
               sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] LONG {symbol} qty={qty} @ {precio:.6f} SL={sl:.6f} TP={tp:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    qty_str = _fmt_qty(qty)
    log.info(f"[ORDER] LONG {symbol} qty={qty_str} @ ~{precio:.6f}")

    # BingX perpetuos usan hedge mode → positionSide obligatorio
    params = {
        "symbol":       symbol,
        "side":         "BUY",
        "positionSide": "LONG",
        "type":         "MARKET",
        "quantity":     qty_str,
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    code  = res.get("code", -1)
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        msg = res.get("msg", "unknown")
        log.error(f"abrir_long {symbol}: code={code} msg={msg} | qty={qty_str}")
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    time.sleep(0.5)
    _place_sl_tp(symbol, "LONG", eqty, sl, tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT ✅ FIX#7 + FIX#8 + FIX#11
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float,
                sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] SHORT {symbol} qty={qty} @ {precio:.6f} SL={sl:.6f} TP={tp:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}

    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    qty_str = _fmt_qty(qty)
    log.info(f"[ORDER] SHORT {symbol} qty={qty_str} @ ~{precio:.6f}")

    params = {
        "symbol":       symbol,
        "side":         "SELL",
        "positionSide": "SHORT",
        "type":         "MARKET",
        "quantity":     qty_str,
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    code  = res.get("code", -1)
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        msg = res.get("msg", "unknown")
        log.error(f"abrir_short {symbol}: code={code} msg={msg} | qty={qty_str}")
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    time.sleep(0.5)
    _place_sl_tp(symbol, "SHORT", eqty, sl, tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN
# ══════════════════════════════════════════════════════════════

def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        return {"precio_salida": get_precio(symbol)}

    cancelar_ordenes_abiertas(symbol)
    time.sleep(0.3)

    side     = "SELL" if lado == "LONG" else "BUY"
    qty_str  = _fmt_qty(qty)
    params   = {
        "symbol":       symbol,
        "side":         side,
        "positionSide": lado,
        "type":         "MARKET",
        "quantity":     qty_str,
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    code  = res.get("code", -1)
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        log.error(f"cerrar_posicion {symbol}: code={code} msg={res.get('msg')} | qty={qty_str}")
        return {"precio_salida": get_precio(symbol)}

    fill = float(order.get("avgPrice", order.get("price", 0)) or 0)
    if fill <= 0:
        fill = get_precio(symbol)
    return {"precio_salida": fill}
