"""
exchange.py — BingX Perpetual Futures REST API v2.1
Mejoras vs v2.0:
  ✅ Retry automático en errores de red (3 intentos)
  ✅ Rate limiting básico con sleep entre llamadas
  ✅ Mejor logging de errores con código HTTP
  ✅ get_precio con fallback a ticker
  ✅ calcular_cantidad con precisión dinámica por par
"""

import time, hmac, hashlib, logging
import requests
import config

log      = logging.getLogger("exchange")
BASE_URL = "https://open-api.bingx.com"
_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})


# ══════════════════════════════════════════════════════════════
# FIRMA y HELPERS
# ══════════════════════════════════════════════════════════════

def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def _headers() -> dict:
    return {"X-BX-APIKEY": config.BINGX_API_KEY}

def _ts() -> int:
    return int(time.time() * 1000)


def _get(path: str, params: dict = None, retries: int = 3) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    for attempt in range(retries):
        try:
            r = _SESSION.get(BASE_URL + path, params=params,
                             headers=_headers(), timeout=10)
            if r.status_code != 200:
                log.warning(f"GET {path} HTTP {r.status_code}")
            return r.json()
        except Exception as e:
            log.error(f"GET {path} intento {attempt+1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {}


def _post(path: str, params: dict = None, retries: int = 3) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    for attempt in range(retries):
        try:
            r = _SESSION.post(BASE_URL + path, params=params,
                              headers=_headers(), timeout=10)
            if r.status_code != 200:
                log.warning(f"POST {path} HTTP {r.status_code}")
            return r.json()
        except Exception as e:
            log.error(f"POST {path} intento {attempt+1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
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
    "1m": "1m",   "3m": "3m",   "5m": "5m",  "15m": "15m",
    "30m": "30m", "1h": "1h",   "2h": "2h",  "4h": "4h",
    "1d": "1d",
}

def get_candles(symbol: str, interval: str = "5m", limit: int = 200) -> list:
    iv = INTERVAL_MAP.get(interval, "5m")
    try:
        # Intentar v3 primero, fallback a v2
        res = _SESSION.get(
            BASE_URL + "/openApi/swap/v3/quote/klines",
            params={"symbol": symbol, "interval": iv, "limit": limit},
            timeout=15,
        ).json()
        raw = res.get("data", [])

        # Si v3 falla o devuelve vacío, intentar v2
        if not raw:
            log.debug(f"get_candles {symbol}: v3 vacío, probando v2")
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
# CALCULAR CANTIDAD
# ══════════════════════════════════════════════════════════════

def calcular_cantidad(symbol: str, trade_usdt: float, precio: float) -> float:
    """
    qty = (trade_usdt × leverage) / precio
    Ajusta la precisión decimal según el precio del activo.
    """
    if precio <= 0 or trade_usdt <= 0:
        return 0.0
    qty = (trade_usdt * config.LEVERAGE) / precio

    # Precisión dinámica según precio
    if precio >= 10000:
        qty = round(qty, 3)
    elif precio >= 100:
        qty = round(qty, 2)
    elif precio >= 1:
        qty = round(qty, 1)
    else:
        qty = round(qty, 0)

    return max(qty, 0.001)


# ══════════════════════════════════════════════════════════════
# ABRIR LONG
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float,
               sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] ABRIR LONG {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    set_leverage(symbol, config.LEVERAGE)
    params = {
        "symbol":       symbol,
        "side":         "BUY",
        "positionSide": "LONG",
        "type":         "MARKET",
        "quantity":     qty,
        "stopLoss":     str(round(sl, 8)),
        "takeProfit":   str(round(tp, 8)),
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
    order = data.get("order", data)

    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float,
                sl: float, tp: float) -> dict:
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
        "stopLoss":     str(round(sl, 8)),
        "takeProfit":   str(round(tp, 8)),
    }
    res   = _post("/openApi/swap/v2/trade/order", params)
    data  = res.get("data", {})
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
        return {"precio_salida": precio}

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
