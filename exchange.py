"""
exchange.py — BingX Perpetual Futures REST API
Firma HMAC-SHA256 según documentación oficial BingX
"""

import time, hmac, hashlib, urllib.parse, logging
import requests
import config

log = logging.getLogger("exchange")

BASE_URL = "https://open-api.bingx.com"

# ── FIRMA ─────────────────────────────────────────────────────

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
        r = requests.get(
            BASE_URL + path,
            params=params,
            headers=_headers(),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        log.error(f"GET {path}: {e}")
        return {}

def _post(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    try:
        r = requests.post(
            BASE_URL + path,
            params=params,
            headers=_headers(),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        log.error(f"POST {path}: {e}")
        return {}

def _delete(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    try:
        r = requests.delete(
            BASE_URL + path,
            params=params,
            headers=_headers(),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        log.error(f"DELETE {path}: {e}")
        return {}


# ══════════════════════════════════════════════════════════════
# BALANCE
# ══════════════════════════════════════════════════════════════

def get_balance() -> float:
    if config.MODO_DEMO:
        return 100.0
    try:
        res = _get("/openApi/swap/v2/user/balance")
        data = res.get("data", {})
        bal  = data.get("balance", {})
        return float(bal.get("availableMargin", bal.get("balance", 0)) or 0)
    except Exception as e:
        log.error(f"get_balance: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════
# PRECIO ACTUAL
# ══════════════════════════════════════════════════════════════

def get_precio(symbol: str) -> float:
    try:
        res = requests.get(
            BASE_URL + "/openApi/swap/v2/quote/price",
            params={"symbol": symbol},
            timeout=8,
        ).json()
        p = res.get("data", {}).get("price", 0)
        return float(p or 0)
    except Exception as e:
        log.error(f"get_precio {symbol}: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════
# VELAS (OHLCV)
# ══════════════════════════════════════════════════════════════

def get_candles(symbol: str, interval: str = "5m", limit: int = 200) -> list:
    """
    Devuelve lista de dicts:
    [{"open": float, "high": float, "low": float, "close": float,
      "volume": float, "ts": int}, ...]
    ordenado del más antiguo al más reciente
    """
    # BingX usa minutos numéricos: 1, 3, 5, 15, 30, 60, 120, 240, 1440
    interval_map = {
        "1m": "1", "3m": "3", "5m": "5", "15m": "15",
        "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "1440",
    }
    iv = interval_map.get(interval, "5")
    try:
        res = requests.get(
            BASE_URL + "/openApi/swap/v3/quote/klines",
            params={"symbol": symbol, "interval": iv, "limit": limit},
            timeout=15,
        ).json()
        raw = res.get("data", [])
        candles = []
        for c in raw:
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
# CONFIGURAR APALANCAMIENTO
# ══════════════════════════════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        res = _post("/openApi/swap/v2/trade/leverage", {
            "symbol":     symbol,
            "side":       "LONG",
            "leverage":   leverage,
        })
        _post("/openApi/swap/v2/trade/leverage", {
            "symbol":     symbol,
            "side":       "SHORT",
            "leverage":   leverage,
        })
        return True
    except Exception as e:
        log.error(f"set_leverage {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# CALCULAR CANTIDAD
# ══════════════════════════════════════════════════════════════

def calcular_cantidad(symbol: str, balance: float, precio: float) -> float:
    """
    Calcula qty basado en % riesgo del balance.
    qty = (balance × riesgo_pct / 100 × leverage) / precio
    """
    if precio <= 0:
        return 0.0
    capital = balance * (config.RIESGO_PCT / 100) * config.LEVERAGE
    qty     = capital / precio
    return round(qty, 4)


# ══════════════════════════════════════════════════════════════
# ABRIR LONG
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] ABRIR LONG {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    set_leverage(symbol, config.LEVERAGE)

    params = {
        "symbol":         symbol,
        "side":           "BUY",
        "positionSide":   "LONG",
        "type":           "MARKET",
        "quantity":       qty,
        "stopLoss":       str(round(sl, 8)),
        "takeProfit":     str(round(tp, 8)),
        "stopLossEntrust": "false",  # SL de mercado
    }
    res = _post("/openApi/swap/v2/trade/order", params)
    data = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}

    fill  = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty  = float(order.get("executedQty", qty) or qty)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] ABRIR SHORT {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}

    set_leverage(symbol, config.LEVERAGE)

    params = {
        "symbol":         symbol,
        "side":           "SELL",
        "positionSide":   "SHORT",
        "type":           "MARKET",
        "quantity":       qty,
        "stopLoss":       str(round(sl, 8)),
        "takeProfit":     str(round(tp, 8)),
        "stopLossEntrust": "false",
    }
    res = _post("/openApi/swap/v2/trade/order", params)
    data = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN
# ══════════════════════════════════════════════════════════════

def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        precio = get_precio(symbol)
        log.info(f"[DEMO] CERRAR {lado} {symbol} qty={qty} @ {precio:.6f}")
        return {"precio_salida": precio}

    side        = "SELL" if lado == "LONG" else "BUY"
    pos_side    = lado  # "LONG" o "SHORT"

    params = {
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
        precio = get_precio(symbol)
        return {"precio_salida": precio}

    fill = float(order.get("avgPrice", order.get("price", 0)) or 0)
    if fill <= 0:
        fill = get_precio(symbol)
    return {"precio_salida": fill}


# ══════════════════════════════════════════════════════════════
# CERRAR TODAS LAS POSICIONES (emergency)
# ══════════════════════════════════════════════════════════════

def cerrar_todas() -> int:
    if config.MODO_DEMO:
        return 0
    cerradas = 0
    try:
        posiciones = get_posiciones_abiertas()
        for p in posiciones:
            qty  = abs(float(p.get("positionAmt", 0) or 0))
            sym  = p.get("symbol", "")
            lado = "LONG" if float(p.get("positionAmt", 0) or 0) > 0 else "SHORT"
            if qty > 0 and sym:
                cerrar_posicion(sym, qty, lado)
                cerradas += 1
    except Exception as e:
        log.error(f"cerrar_todas: {e}")
    return cerradas
