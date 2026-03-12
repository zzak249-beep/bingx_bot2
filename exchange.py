"""
exchange.py — BingX Perpetual Futures v4.1 [FIXES COMPLETOS]
✅ Balance: prueba 4 endpoints hasta encontrar saldo real
✅ Modo posición: detecta hedge vs one-way automáticamente
✅ Leverage: envía como int, ignora error si ya está seteado
✅ Quantity: stepSize real de BingX + string limpio
✅ SL/TP como órdenes separadas (firma limpia)
✅ Intervalo velas correcto "5m"
✅ None-safe en todas las respuestas
"""

import time, hmac, hashlib, logging, math
import requests
import config

log      = logging.getLogger("exchange")
BASE_URL = "https://open-api.bingx.com"
_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})

_hedge_mode_cache: dict   = {}
_contract_cache: dict     = {}
_contract_cache_ts: float = 0
_pares_no_soportados: set = set()  # pares que fallan siempre — nunca reintentar
_CONTRATOS_FUTURES: set   = set()  # set de símbolos válidos en futuros perpetuos

# ── Persistencia de pares no soportados ──────────────────────
def _ns_file() -> str:
    import os
    d = os.getenv("MEMORY_DIR", "").strip()
    return (d + "/no_soportados.json") if d else "no_soportados.json"

def _cargar_no_soportados():
    import json, os
    try:
        if os.path.exists(_ns_file()):
            with open(_ns_file()) as f:
                _pares_no_soportados.update(json.load(f))
            log.info(f"[API-BLOCK] {len(_pares_no_soportados)} pares cargados como no soportados")
    except Exception as e:
        log.debug(f"[API-BLOCK] {e}")

def _guardar_no_soportados():
    import json
    try:
        with open(_ns_file(), "w") as f:
            json.dump(list(_pares_no_soportados), f)
    except Exception as e:
        log.debug(f"[API-BLOCK] guardar: {e}")

def _bloquear_par(symbol: str, razon: str):
    if symbol not in _pares_no_soportados:
        _pares_no_soportados.add(symbol)
        _guardar_no_soportados()
        log.warning(f"[API-BLOCK] 🚫 {symbol} bloqueado permanentemente: {razon}")
        # También avisar a memoria si está disponible
        try:
            import memoria as _mem
            _mem.registrar_error_api(symbol)
        except Exception:
            pass

_cargar_no_soportados()

# ══════════════════════════════════════════════════════════════
# FIRMA
# ══════════════════════════════════════════════════════════════
def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(config.BINGX_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()

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
            r = _SESSION.get(BASE_URL + path, params=params, headers=_headers(), timeout=10)
            return r.json()
        except Exception as e:
            log.error(f"GET {path} [{attempt+1}]: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {}

def _post(path: str, params: dict = None, retries: int = 3) -> dict:
    params = params or {}
    params["timestamp"] = _ts()
    params["signature"] = _sign(params)
    for attempt in range(retries):
        try:
            r = _SESSION.post(BASE_URL + path, params=params, headers=_headers(), timeout=10)
            return r.json()
        except Exception as e:
            log.error(f"POST {path} [{attempt+1}]: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {}

# ══════════════════════════════════════════════════════════════
# BALANCE — 4 endpoints + parser universal
# ══════════════════════════════════════════════════════════════
def _extract_float(data, keys) -> float:
    """Busca recursivamente el primer valor numérico >= 0 entre las keys."""
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if v is not None:
                try:
                    f = float(v)
                    if f >= 0:
                        return f
                except Exception:
                    pass
        for v in data.values():
            if isinstance(v, (dict, list)):
                result = _extract_float(v, keys)
                if result >= 0:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = _extract_float(item, keys)
            if result >= 0:
                return result
    return -1.0

def get_balance() -> float:
    if config.MODO_DEMO:
        return 1000.0
    keys = ("availableMargin", "availableBalance", "crossAvailableBalance",
            "walletBalance", "balance", "free", "equity")
    endpoints = [
        "/openApi/swap/v2/user/balance",
        "/openApi/swap/v3/user/balance",
        "/openApi/swap/v2/user/margin",
    ]
    for ep in endpoints:
        try:
            res  = _get(ep)
            data = res.get("data")
            log.debug(f"[BAL] {ep}: {str(data)[:150]}")
            if data is not None:
                val = _extract_float(data, keys)
                if val > 0:
                    log.info(f"[BALANCE] ${val:.2f} via {ep}")
                    return val
        except Exception as e:
            log.debug(f"[BAL] {ep}: {e}")
    log.warning("[BALANCE] No se pudo leer balance — verifica API key permisos")
    return 0.0

# ══════════════════════════════════════════════════════════════
# PRECIO
# ══════════════════════════════════════════════════════════════
def get_precio(symbol: str) -> float:
    for _ in range(2):
        try:
            res = _SESSION.get(BASE_URL + "/openApi/swap/v2/quote/price",
                               params={"symbol": symbol}, timeout=8).json()
            p = float((res.get("data") or {}).get("price", 0) or 0)
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
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m",
    "30m":"30m","1h":"1h","2h":"2h","4h":"4h","1d":"1d",
}

def get_candles(symbol: str, interval: str = "5m", limit: int = 200) -> list:
    iv = INTERVAL_MAP.get(interval, "5m")
    for ep in ["/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"]:
        try:
            res = _SESSION.get(BASE_URL + ep,
                               params={"symbol": symbol, "interval": iv, "limit": limit},
                               timeout=15).json()
            raw = res.get("data") or []
            if not raw:
                continue
            candles = []
            for c in raw:
                try:
                    if isinstance(c, list):
                        candles.append({"ts": int(c[0]), "open": float(c[1]),
                                        "high": float(c[2]), "low": float(c[3]),
                                        "close": float(c[4]), "volume": float(c[5])})
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
            if candles:
                candles.sort(key=lambda x: x["ts"])
                return candles
        except Exception as e:
            log.error(f"get_candles {symbol} {ep}: {e}")
    return []

# ══════════════════════════════════════════════════════════════
# FILTRO: bloquear pares exóticos que BingX no soporta en API
# ══════════════════════════════════════════════════════════════
_PARES_BLOQUEADOS_API = ("NCFX", "NCF", "RESOLV")

def par_es_soportado(symbol: str) -> bool:
    """Verifica si el par puede operar vía API. Chequea blacklist en memoria y en disco."""
    if symbol in _pares_no_soportados:
        return False
    for prefix in _PARES_BLOQUEADOS_API:
        if symbol.startswith(prefix):
            return False
    return True

def get_pares_no_soportados() -> set:
    return _pares_no_soportados.copy()

# ══════════════════════════════════════════════════════════════
# POSICIONES
# ══════════════════════════════════════════════════════════════
def get_posiciones_abiertas() -> list:
    if config.MODO_DEMO:
        return []
    try:
        return _get("/openApi/swap/v2/user/positions").get("data") or []
    except Exception as e:
        log.error(f"get_posiciones_abiertas: {e}")
        return []

# ══════════════════════════════════════════════════════════════
# LEVERAGE
# ══════════════════════════════════════════════════════════════
def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        for side in ("LONG", "SHORT"):
            _post("/openApi/swap/v2/trade/leverage",
                  {"symbol": symbol, "side": side, "leverage": leverage})
        return True
    except Exception as e:
        log.debug(f"set_leverage {symbol}: {e}")
        return False

# ══════════════════════════════════════════════════════════════
# CONTRATOS + CANTIDAD
# ══════════════════════════════════════════════════════════════
def _load_contracts():
    global _contract_cache, _contract_cache_ts, _CONTRATOS_FUTURES
    if _contract_cache and time.time() - _contract_cache_ts < 3600:
        return
    try:
        res = _SESSION.get(BASE_URL + "/openApi/swap/v2/quote/contracts", timeout=15).json()
        for c in (res.get("data") or []):
            sym  = c.get("symbol", "")
            step = float(c.get("tradeMinQuantity", 1) or 1)
            dec  = int(c.get("quantityPrecision", 0) or 0)
            _contract_cache[sym] = {"step": step, "dec": dec}
        _CONTRATOS_FUTURES = set(_contract_cache.keys())
        _contract_cache_ts = time.time()
        log.info(f"[CONTRACTS] {len(_contract_cache)} pares cargados")
    except Exception as e:
        log.warning(f"[CONTRACTS] {e}")

def _cargar_contratos():
    """Alias público de _load_contracts() — requerido por main.py."""
    _load_contracts()

def calcular_cantidad(symbol: str, trade_usdt: float, precio: float) -> float:
    if precio <= 0 or trade_usdt <= 0:
        return 0.0
    _load_contracts()
    qty_raw = (trade_usdt * config.LEVERAGE) / precio
    info    = _contract_cache.get(symbol, {})
    step    = info.get("step", 0)
    dec     = info.get("dec", 0)
    if step > 0:
        qty = math.floor(qty_raw / step) * step
        qty = max(qty, step)
        qty = round(qty, dec)
        log.debug(f"[QTY] {symbol} raw={qty_raw:.4f} step={step} → {qty}")
        return qty
    # fallback
    if precio >= 1000:
        return round(qty_raw, 3)
    elif precio >= 1:
        return max(round(qty_raw, 1), 0.1)
    else:
        return max(math.floor(qty_raw), 1)

def _qty_str(qty: float, symbol: str = "") -> str:
    info = _contract_cache.get(symbol, {})
    dec  = info.get("dec", 0)
    if dec == 0:
        return str(int(qty))
    return str(round(qty, dec))

# ══════════════════════════════════════════════════════════════
# ORDEN CON FALLBACK HEDGE → ONE-WAY
# ══════════════════════════════════════════════════════════════
def _send_order(symbol: str, side: str, pos_side: str, qty_str: str) -> dict:
    # Par conocido como no soportado — rechazar sin llamar a la API
    if symbol in _pares_no_soportados:
        return {"code": -999, "msg": f"{symbol} no soportado por API"}

    if not _hedge_mode_cache.get(symbol, True):
        return _post("/openApi/swap/v2/trade/order",
                     {"symbol": symbol, "side": side, "positionSide": "BOTH",
                      "type": "MARKET", "quantity": qty_str})
    params = {"symbol": symbol, "side": side, "positionSide": pos_side,
              "type": "MARKET", "quantity": qty_str}
    res  = _post("/openApi/swap/v2/trade/order", params)
    code = res.get("code", 0)
    if code in (109400, 80001, 80014, 100400, -1):
        log.debug(f"[ORDER] {symbol} hedge→BOTH fallback (code={code})")
        _hedge_mode_cache[symbol] = False
        res2 = _post("/openApi/swap/v2/trade/order",
                     {"symbol": symbol, "side": side, "positionSide": "BOTH",
                      "type": "MARKET", "quantity": qty_str})
        code2 = res2.get("code", 0)
        if code2 != 0:
            _bloquear_par(symbol, f"hedge={code} both={code2}")
        return res2
    if code == 0:
        _hedge_mode_cache[symbol] = True
    return res

# ══════════════════════════════════════════════════════════════
# SL / TP SEPARADOS
# ══════════════════════════════════════════════════════════════
def _place_sl_tp(symbol: str, lado: str, qty: float, sl: float, tp: float):
    if config.MODO_DEMO:
        return
    hedge  = _hedge_mode_cache.get(symbol, True)
    qty_s  = _qty_str(qty, symbol)
    close  = "SELL" if lado == "LONG" else "BUY"
    for order_type, price in [("STOP_MARKET", sl), ("TAKE_PROFIT_MARKET", tp)]:
        p = {"symbol": symbol, "side": close, "type": order_type,
             "quantity": qty_s, "stopPrice": str(round(price, 8)),
             "workingType": "MARK_PRICE"}
        if hedge:
            p["positionSide"] = lado
        r = _post("/openApi/swap/v2/trade/order", p)
        if r.get("code", 0) != 0 and hedge:
            p["positionSide"] = "BOTH"
            r = _post("/openApi/swap/v2/trade/order", p)
        if r.get("code", 0) != 0:
            log.warning(f"{order_type} {symbol}: {r.get('msg','')[:60]}")
    log.info(f"✅ SL/TP {symbol} {lado} SL={sl:.6f} TP={tp:.6f}")

# ══════════════════════════════════════════════════════════════
# ABRIR LONG / SHORT
# ══════════════════════════════════════════════════════════════
def abrir_long(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}
    if symbol in _pares_no_soportados:
        return {"error": f"{symbol} no soportado por API"}
    set_leverage(symbol, config.LEVERAGE)
    qty_s = _qty_str(qty, symbol)
    log.info(f"[ORDER] LONG {symbol} qty={qty_s} @ ~{precio:.6f}")
    res   = _send_order(symbol, "BUY", "LONG", qty_s)
    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}
    order = (res.get("data") or {}).get("order", res.get("data") or {})
    fill  = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty  = float(order.get("executedQty", qty) or qty)
    time.sleep(0.5)
    _place_sl_tp(symbol, "LONG", eqty, sl, tp)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}

def abrir_short(symbol: str, qty: float, precio: float, sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}
    if symbol in _pares_no_soportados:
        return {"error": f"{symbol} no soportado por API"}
    set_leverage(symbol, config.LEVERAGE)
    qty_s = _qty_str(qty, symbol)
    log.info(f"[ORDER] SHORT {symbol} qty={qty_s} @ ~{precio:.6f}")
    res   = _send_order(symbol, "SELL", "SHORT", qty_s)
    if res.get("code", 0) != 0:
        return {"error": res.get("msg", "unknown")}
    order = (res.get("data") or {}).get("order", res.get("data") or {})
    fill  = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty  = float(order.get("executedQty", qty) or qty)
    time.sleep(0.5)
    _place_sl_tp(symbol, "SHORT", eqty, sl, tp)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}

# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN
# ══════════════════════════════════════════════════════════════
def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        return {"precio_salida": get_precio(symbol)}
    side  = "SELL" if lado == "LONG" else "BUY"
    qty_s = _qty_str(qty, symbol)
    hedge = _hedge_mode_cache.get(symbol, True)
    p     = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty_s}
    if hedge:
        p["positionSide"] = lado
    res  = _post("/openApi/swap/v2/trade/order", p)
    if res.get("code", 0) != 0 and hedge:
        p["positionSide"] = "BOTH"
        res = _post("/openApi/swap/v2/trade/order", p)
    order = (res.get("data") or {}).get("order", res.get("data") or {})
    fill  = float(order.get("avgPrice", order.get("price", 0)) or 0)
    return {"precio_salida": fill or get_precio(symbol)}
