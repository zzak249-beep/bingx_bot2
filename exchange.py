"""
exchange.py — BingX Perpetual Futures REST API v4.1 [FIXES CRÍTICOS]

BUGS CORREGIDOS:
  ✅ FIX#1 — Firma HMAC: params se copian antes de añadir timestamp/signature
             para evitar mutación y garantizar orden correcto
  ✅ FIX#2 — Validación de par futures ANTES de operar (evita "Signature
             verification failed" en pares que no existen como perpetuos)
  ✅ FIX#3 — qty mínima por par desde contractInfo (stepSize)
  ✅ FIX#4 — SL/TP como órdenes STOP_MARKET + TAKE_PROFIT_MARKET separadas
  ✅ FIX#5 — Cancelar órdenes abiertas de SL/TP antes de cerrar posición
  ✅ FIX#6 — Cache de contratos válidos para no llamar la API en cada ciclo
  ✅ Fallback v2 si v3 klines falla
  ✅ Retry con backoff exponencial
"""

import time, hmac, hashlib, logging
from functools import lru_cache
import requests
import config

log      = logging.getLogger("exchange")
BASE_URL = "https://open-api.bingx.com"
_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})

# Cache de contratos futuros válidos (se rellena una vez al arrancar)
_CONTRATOS_FUTURES: set  = set()
_CONTRATO_INFO:     dict = {}   # par → {stepSize, minQty, pricePrecision}
_CONTRATOS_TS:      float = 0


# ══════════════════════════════════════════════════════════════
# FIRMA HMAC — CORREGIDA  ✅ FIX#1
# ══════════════════════════════════════════════════════════════

def _sign(query_string: str) -> str:
    """
    Firma el query string EXACTAMENTE como BingX lo recibe.
    NUNCA pasar un dict — siempre pasar el string ya construido.
    """
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_query(params: dict) -> str:
    """Construye el query string con los parámetros ordenados."""
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


def _headers() -> dict:
    return {"X-BX-APIKEY": config.BINGX_API_KEY}


def _ts() -> int:
    return int(time.time() * 1000)


def _get(path: str, params: dict = None, retries: int = 3) -> dict:
    p = dict(params or {})
    p["timestamp"] = _ts()
    qs = _build_query(p)
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
    p["timestamp"] = _ts()
    qs = _build_query(p)
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
# CACHE DE CONTRATOS FUTUROS  ✅ FIX#2 + FIX#3
# ══════════════════════════════════════════════════════════════

def _cargar_contratos():
    """
    Carga todos los contratos de futuros perpetuos disponibles en BingX.
    Guarda stepSize y minQty para calcular cantidades válidas.
    Se refresca cada 6 horas.
    """
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
            # Precisión de cantidad
            qty_step  = float(c.get("tradeMinQuantity", c.get("stepSize", 0.001)) or 0.001)
            min_qty   = float(c.get("tradeMinQuantity", 0.001) or 0.001)
            price_prec = int(c.get("pricePrecision", 6))
            _CONTRATO_INFO[sym] = {
                "stepSize":       qty_step,
                "minQty":         min_qty,
                "pricePrecision": price_prec,
            }
        _CONTRATOS_TS = time.time()
        log.info(f"[CONTRATOS] {len(_CONTRATOS_FUTURES)} futuros perpetuos USDT cargados")
    except Exception as e:
        log.error(f"_cargar_contratos: {e}")


def es_futuro_valido(symbol: str) -> bool:
    """Verifica que el par existe como futuro perpetuo en BingX."""
    if config.MODO_DEMO:
        return True
    _cargar_contratos()
    valido = symbol in _CONTRATOS_FUTURES
    if not valido:
        log.warning(f"[SKIP] {symbol} no es un futuro perpetuo válido en BingX")
    return valido


def get_step_size(symbol: str) -> float:
    """Devuelve el tamaño mínimo de paso de cantidad para el par."""
    _cargar_contratos()
    info = _CONTRATO_INFO.get(symbol, {})
    return info.get("stepSize", 0.001)


def get_price_precision(symbol: str) -> int:
    _cargar_contratos()
    info = _CONTRATO_INFO.get(symbol, {})
    return info.get("pricePrecision", 6)


# ══════════════════════════════════════════════════════════════
# BALANCE
# ══════════════════════════════════════════════════════════════

def get_balance() -> float:
    if config.MODO_DEMO:
        return 1000.0
    try:
        res = _get("/openApi/swap/v2/user/balance")
        bal = res.get("data", {}).get("balance", {})
        return float(bal.get("availableMargin", bal.get("balance", 0)) or 0)
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
# VELAS — formato corregido
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
            # Fallback v2
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
# CANCELAR ÓRDENES ABIERTAS (SL/TP pendientes)  ✅ FIX#5
# ══════════════════════════════════════════════════════════════

def cancelar_ordenes_abiertas(symbol: str):
    """
    Cancela todas las órdenes abiertas del par (SL/TP pendientes).
    Necesario antes de cerrar manualmente la posición para evitar
    que queden órdenes huérfanas.
    """
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
# APALANCAMIENTO
# ══════════════════════════════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        _post("/openApi/swap/v2/trade/leverage",
              {"symbol": symbol, "side": "LONG",  "leverage": leverage})
        _post("/openApi/swap/v2/trade/leverage",
              {"symbol": symbol, "side": "SHORT", "leverage": leverage})
        return True
    except Exception as e:
        log.error(f"set_leverage {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# CALCULAR CANTIDAD — respeta stepSize del contrato  ✅ FIX#3
# ══════════════════════════════════════════════════════════════

def calcular_cantidad(symbol: str, trade_usdt: float, precio: float) -> float:
    """
    Calcula la cantidad respetando el stepSize del contrato.
    CRÍTICO: BingX rechaza '5600.0' — debe ser '5600' para tokens enteros.
    La función devuelve int cuando stepSize es entero (≥1), float si es decimal.
    """
    if precio <= 0 or trade_usdt <= 0:
        return 0.0

    qty_raw  = (trade_usdt * config.LEVERAGE) / precio
    step     = get_step_size(symbol)
    min_qty  = _CONTRATO_INFO.get(symbol, {}).get("minQty", step)

    if step > 0:
        # Redondear hacia abajo al múltiplo de step más cercano
        qty = (int(qty_raw / step)) * step

        # Determinar decimales reales del step
        step_str  = f"{step:.10f}".rstrip("0")
        if "." in step_str:
            decimals = len(step_str.split(".")[-1])
        else:
            decimals = 0

        if decimals == 0:
            # Token entero (stepSize=1, 10, 100...) → qty debe ser int sin decimales
            qty = int(round(qty, 0))
        else:
            qty = round(qty, decimals)
    else:
        # Fallback por precio cuando no hay info de contrato
        if precio >= 10000:
            qty = round(qty_raw, 3)
        elif precio >= 100:
            qty = round(qty_raw, 2)
        elif precio >= 1:
            qty = round(qty_raw, 1)
        else:
            qty = int(qty_raw)  # tokens muy baratos → siempre entero

    min_valid = max(step if step > 0 else 0.001, min_qty if min_qty > 0 else 0.001)
    return qty if qty >= min_valid else 0.0


# ══════════════════════════════════════════════════════════════
# SL / TP COMO ÓRDENES SEPARADAS  ✅ FIX#4
# ══════════════════════════════════════════════════════════════

def _place_sl_tp(symbol: str, lado: str, qty: float, sl: float, tp: float):
    """
    Coloca SL (STOP_MARKET) y TP (TAKE_PROFIT_MARKET) como órdenes separadas.
    Valida que SL/TP sean precios razonables antes de enviar.
    """
    if config.MODO_DEMO:
        return
    # Validar SL y TP antes de enviar
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
        close_side = "SELL" if lado == "LONG" else "BUY"
        pos_side   = lado
        pp         = get_price_precision(symbol)

        # STOP LOSS
        sl_params = {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     qty,
            "stopPrice":    str(round(sl, pp)),
            "workingType":  "MARK_PRICE",
        }
        r1 = _post("/openApi/swap/v2/trade/order", sl_params)
        if r1.get("code", 0) != 0:
            log.warning(f"SL order {symbol}: código={r1.get('code')} msg={r1.get('msg')}")
        else:
            log.info(f"  SL colocado {symbol} {lado} @ {sl:.{pp}f}")

        time.sleep(0.4)

        # TAKE PROFIT
        tp_params = {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     qty,
            "stopPrice":    str(round(tp, pp)),
            "workingType":  "MARK_PRICE",
        }
        r2 = _post("/openApi/swap/v2/trade/order", tp_params)
        if r2.get("code", 0) != 0:
            log.warning(f"TP order {symbol}: código={r2.get('code')} msg={r2.get('msg')}")
        else:
            log.info(f"  TP colocado {symbol} {lado} @ {tp:.{pp}f}")

    except Exception as e:
        log.error(f"_place_sl_tp {symbol}: {e}")


# ══════════════════════════════════════════════════════════════
# ABRIR LONG  ✅ FIX#1 + FIX#2 + FIX#4
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float,
               sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] LONG {symbol} qty={qty} @ {precio:.6f} SL={sl:.6f} TP={tp:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    # Verificar que es un futuro válido ANTES de intentar operar
    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    params = {
        "symbol":       symbol,
        "side":         "BUY",
        "positionSide": "LONG",
        "type":         "MARKET",
        "quantity":     str(qty),   # ← string para evitar formato float
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        msg = res.get("msg", "unknown")
        log.error(f"abrir_long {symbol}: code={res.get('code')} msg={msg}")
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    time.sleep(0.5)
    _place_sl_tp(symbol, "LONG", eqty, sl, tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT  ✅ FIX#1 + FIX#2 + FIX#4
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float,
                sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] SHORT {symbol} qty={qty} @ {precio:.6f} SL={sl:.6f} TP={tp:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}

    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    params = {
        "symbol":       symbol,
        "side":         "SELL",
        "positionSide": "SHORT",
        "type":         "MARKET",
        "quantity":     str(qty),   # ← string
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        msg = res.get("msg", "unknown")
        log.error(f"abrir_short {symbol}: code={res.get('code')} msg={msg}")
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    time.sleep(0.5)
    _place_sl_tp(symbol, "SHORT", eqty, sl, tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN  ✅ FIX#5
# ══════════════════════════════════════════════════════════════

def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        return {"precio_salida": get_precio(symbol)}

    # Cancelar SL/TP pendientes para evitar órdenes huérfanas
    cancelar_ordenes_abiertas(symbol)
    time.sleep(0.3)

    side     = "SELL" if lado == "LONG" else "BUY"
    pos_side = lado
    params   = {
        "symbol":       symbol,
        "side":         side,
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     str(qty),
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        log.error(f"cerrar_posicion {symbol}: {res.get('msg')}")
        return {"precio_salida": get_precio(symbol)}

    fill = float(order.get("avgPrice", order.get("price", 0)) or 0)
    if fill <= 0:
        fill = get_precio(symbol)
    return {"precio_salida": fill}
