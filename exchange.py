"""
exchange.py — BingX Perpetual Futures REST API v2.1 [FIXED]
Correcciones:
  ✅ HMAC firma correcta (digestmod explícito)
  ✅ SL y TP como órdenes separadas STOP_MARKET / TAKE_PROFIT_MARKET
  ✅ Manejo robusto de errores en todas las llamadas
  ✅ cancelar_ordenes_abiertas() para limpiar SL/TP al cerrar
"""

import time, hmac, hashlib, logging
import requests
import config

log = logging.getLogger("exchange")
BASE_URL = "https://open-api.bingx.com"


# ══════════════════════════════════════════════════════════════
# FIRMA HMAC-SHA256  ✅ CORREGIDA
# ══════════════════════════════════════════════════════════════

def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def _headers() -> dict:
    return {
        "X-BX-APIKEY": config.BINGX_API_KEY,
        "Content-Type": "application/json",
    }

def _ts() -> int:
    return int(time.time() * 1000)

def _get(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    try:
        r = requests.get(BASE_URL + path, params=params, headers=_headers(), timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"GET {path}: {e}")
        return {}

def _post(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    try:
        r = requests.post(BASE_URL + path, params=params, headers=_headers(), timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"POST {path}: {e}")
        return {}


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
    try:
        res = requests.get(
            BASE_URL + "/openApi/swap/v2/quote/price",
            params={"symbol": symbol}, timeout=8,
        ).json()
        return float(res.get("data", {}).get("price", 0) or 0)
    except Exception as e:
        log.error(f"get_precio {symbol}: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════
# VELAS
# ══════════════════════════════════════════════════════════════

def get_candles(symbol: str, interval: str = "5m", limit: int = 200) -> list:
    interval_map = {
        "1m":"1","3m":"3","5m":"5","15m":"15","30m":"30",
        "1h":"60","2h":"120","4h":"240","1d":"1440",
    }
    iv = interval_map.get(interval, "5")
    try:
        res = requests.get(
            BASE_URL + "/openApi/swap/v3/quote/klines",
            params={"symbol": symbol, "interval": iv, "limit": limit},
            timeout=15,
        ).json()
        candles = []
        for c in res.get("data", []):
            candles.append({
                "ts":     int(c[0]),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            })
        candles.sort(key=lambda x: x["ts"])
        return candles
    except Exception as e:
        log.error(f"get_candles {symbol}: {e}")
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
# APALANCAMIENTO
# ══════════════════════════════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        for side in ("LONG", "SHORT"):
            _post("/openApi/swap/v2/trade/leverage", {
                "symbol": symbol, "side": side, "leverage": leverage,
            })
        return True
    except Exception as e:
        log.error(f"set_leverage {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# CALCULAR CANTIDAD — FIJA EN USDT
# ══════════════════════════════════════════════════════════════

def calcular_cantidad(symbol: str, trade_usdt: float, precio: float) -> float:
    """qty = (trade_usdt × leverage) / precio"""
    if precio <= 0 or trade_usdt <= 0:
        return 0.0
    qty = (trade_usdt * config.LEVERAGE) / precio
    return round(qty, 4)


# ══════════════════════════════════════════════════════════════
# SL / TP COMO ÓRDENES SEPARADAS  ✅ NUEVO — BingX perpetuos
# Las órdenes de mercado en BingX NO aceptan stopLoss/takeProfit
# inline. Hay que colocar órdenes separadas tipo STOP_MARKET y
# TAKE_PROFIT_MARKET después de abrir la posición.
# ══════════════════════════════════════════════════════════════

def _colocar_sl(symbol: str, qty: float, lado: str, sl: float) -> bool:
    """Coloca Stop Loss como orden STOP_MARKET separada."""
    if config.MODO_DEMO or sl <= 0:
        return True
    try:
        side     = "SELL" if lado == "LONG" else "BUY"
        pos_side = lado
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     qty,
            "stopPrice":    round(sl, 8),
            "workingType":  "MARK_PRICE",
        }
        res = _post("/openApi/swap/v2/trade/order", params)
        if res.get("code", 0) != 0:
            log.error(f"SL order {symbol}: {res.get('msg')}")
            return False
        log.info(f"SL colocado {symbol} @ {sl:.6f}")
        return True
    except Exception as e:
        log.error(f"_colocar_sl {symbol}: {e}")
        return False

def _colocar_tp(symbol: str, qty: float, lado: str, tp: float) -> bool:
    """Coloca Take Profit como orden TAKE_PROFIT_MARKET separada."""
    if config.MODO_DEMO or tp <= 0:
        return True
    try:
        side     = "SELL" if lado == "LONG" else "BUY"
        pos_side = lado
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": pos_side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     qty,
            "stopPrice":    round(tp, 8),
            "workingType":  "MARK_PRICE",
        }
        res = _post("/openApi/swap/v2/trade/order", params)
        if res.get("code", 0) != 0:
            log.error(f"TP order {symbol}: {res.get('msg')}")
            return False
        log.info(f"TP colocado {symbol} @ {tp:.6f}")
        return True
    except Exception as e:
        log.error(f"_colocar_tp {symbol}: {e}")
        return False

def cancelar_ordenes_abiertas(symbol: str) -> bool:
    """Cancela todas las órdenes abiertas de un símbolo (SL/TP pendientes)."""
    if config.MODO_DEMO:
        return True
    try:
        params = {"symbol": symbol}
        res = _post("/openApi/swap/v2/trade/allOpenOrders", params)
        if res.get("code", 0) != 0:
            log.warning(f"cancelar_ordenes {symbol}: {res.get('msg')}")
        return True
    except Exception as e:
        log.error(f"cancelar_ordenes {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# ABRIR LONG  ✅ CORREGIDO — sin SL/TP inline, usa órdenes separadas
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] ABRIR LONG {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    set_leverage(symbol, config.LEVERAGE)

    # 1. Orden de mercado principal (SIN stopLoss/takeProfit inline)
    params = {
        "symbol":       symbol,
        "side":         "BUY",
        "positionSide": "LONG",
        "type":         "MARKET",
        "quantity":     qty,
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    # 2. Colocar SL y TP como órdenes separadas
    time.sleep(0.5)  # pequeña pausa para que BingX registre la posición
    _colocar_sl(symbol, eqty, "LONG", sl)
    _colocar_tp(symbol, eqty, "LONG", tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT  ✅ CORREGIDO — sin SL/TP inline, usa órdenes separadas
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] ABRIR SHORT {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}

    set_leverage(symbol, config.LEVERAGE)

    params = {
        "symbol":       symbol,
        "side":         "SELL",
        "positionSide": "SHORT",
        "type":         "MARKET",
        "quantity":     qty,
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)

    time.sleep(0.5)
    _colocar_sl(symbol, eqty, "SHORT", sl)
    _colocar_tp(symbol, eqty, "SHORT", tp)

    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN  ✅ Cancela SL/TP pendientes antes de cerrar
# ══════════════════════════════════════════════════════════════

def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        precio = get_precio(symbol)
        return {"precio_salida": precio}

    # Cancelar SL/TP pendientes para evitar órdenes fantasma
    cancelar_ordenes_abiertas(symbol)
    time.sleep(0.3)

    side     = "SELL" if lado == "LONG" else "BUY"
    pos_side = lado
    params   = {
        "symbol":       symbol,
        "side":         side,
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty,
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
