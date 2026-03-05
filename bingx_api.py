import os, hmac, hashlib, time, requests, json
from urllib.parse import urlencode

# ══════════════════════════════════════════════════════
# bingx_api.py v13.0 — BUGS CORREGIDOS:
#
# BUG 1: Credenciales leídas en import (vacías en Railway)
#         → FIX: leer os.getenv() en cada llamada
#
# BUG 2: stopLoss/takeProfit formato incorrecto
#         → BingX requiere JSON object, no string price
#
# BUG 3: POST enviaba params como query string
#         → BingX firma en query string pero body vacío OK
#
# BUG 4: Sin validación de qty mínima por par
#         → FIX: obtener stepSize del exchange
# ══════════════════════════════════════════════════════

BASE = "https://open-api.bingx.com"


def _key():    return os.getenv("BINGX_API_KEY",    "")
def _secret(): return os.getenv("BINGX_API_SECRET", "")
def _lev():    return int(os.getenv("LEVERAGE", 2))


def _sign(params: dict) -> str:
    """Firma HMAC-SHA256. Lee secret en tiempo de ejecución."""
    secret = _secret()
    if not secret:
        raise ValueError("BINGX_API_SECRET no configurado en Railway Variables")
    query = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _headers() -> dict:
    key = _key()
    if not key:
        raise ValueError("BINGX_API_KEY no configurado en Railway Variables")
    return {"X-BX-APIKEY": key, "Content-Type": "application/json"}


def _get(path: str, params: dict = None) -> dict:
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(p)
    r = requests.get(BASE + path, params=p, headers=_headers(), timeout=12)
    r.raise_for_status()
    return r.json()


def _post(path: str, params: dict = None) -> dict:
    """
    BingX: firma va en query string, body puede ir vacío.
    Usamos params= (query string) que es lo que BingX espera.
    """
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(p)
    r = requests.post(BASE + path, params=p, headers=_headers(), timeout=12)
    r.raise_for_status()
    return r.json()


# ─── Diagnóstico ───────────────────────────────────────
def diagnose() -> dict:
    """
    Comprueba credenciales y permisos.
    Llama desde test_bingx.py para ver exactamente qué falla.
    """
    results = {}

    # 1. Credenciales configuradas
    results["api_key_set"]    = bool(_key())
    results["api_secret_set"] = bool(_secret())
    if not results["api_key_set"] or not results["api_secret_set"]:
        results["error"] = "Faltan credenciales en Railway Variables"
        return results

    # 2. Conectividad y firma
    try:
        data = _get("/openApi/swap/v2/user/balance")
        results["connection"] = "OK"
        results["raw_balance"] = data
        bal = ((data.get("data") or {}).get("balance") or {})
        results["balance_usdt"] = float(bal.get("availableMargin", 0))
        results["has_funds"] = results["balance_usdt"] > 0
    except Exception as e:
        results["connection"] = f"ERROR: {e}"
        err_str = str(e)
        if "100004" in err_str or "Permission denied" in err_str:
            results["error"] = (
                "API KEY SIN PERMISO DE TRADE\n"
                "→ BingX → API Management → elimina esta key\n"
                "→ Crea nueva key con permiso TRADE activado\n"
                "→ Actualiza BINGX_API_KEY y BINGX_API_SECRET en Railway"
            )
        elif "Signature" in err_str or "100001" in err_str:
            results["error"] = "Firma inválida — revisa BINGX_API_SECRET"
        else:
            results["error"] = err_str
        return results

    # 3. Test de precio (no requiere permisos)
    try:
        p = get_price("BTC-USDT")
        results["price_test"] = f"BTC=${p:,.0f}" if p > 0 else "ERROR"
    except Exception as e:
        results["price_test"] = f"ERROR: {e}"

    return results


# ─── Balance ───────────────────────────────────────────
def get_balance() -> float:
    try:
        data = _get("/openApi/swap/v2/user/balance")
        bal  = ((data.get("data") or {}).get("balance") or {})
        return float(bal.get("availableMargin", 0))
    except Exception as e:
        print(f"[API] get_balance: {e}")
        return 0.0


# ─── Precio ────────────────────────────────────────────
def get_price(symbol: str) -> float:
    try:
        r = requests.get(
            BASE + "/openApi/swap/v2/quote/price",
            params={"symbol": symbol}, timeout=8
        ).json()
        return float((r.get("data") or {}).get("price", 0))
    except Exception as e:
        print(f"[API] get_price {symbol}: {e}")
        return 0.0


# ─── Info del contrato (para qty mínima) ───────────────
_contract_cache = {}

def get_contract_info(symbol: str) -> dict:
    """Retorna stepSize y minQty para el símbolo."""
    if symbol in _contract_cache:
        return _contract_cache[symbol]
    try:
        r = requests.get(
            BASE + "/openApi/swap/v2/quote/contracts",
            timeout=10
        ).json()
        for c in (r.get("data") or []):
            if c.get("symbol") == symbol:
                info = {
                    "stepSize": float(c.get("tradeMinQuantity", 0.001)),
                    "minQty":   float(c.get("tradeMinQuantity", 0.001)),
                    "pricePrecision": int(c.get("pricePrecision", 4)),
                    "quantityPrecision": int(c.get("quantityPrecision", 3)),
                }
                _contract_cache[symbol] = info
                return info
    except Exception as e:
        print(f"[API] get_contract_info {symbol}: {e}")
    return {"stepSize": 0.001, "minQty": 0.001, "pricePrecision": 4, "quantityPrecision": 3}


def _round_qty(symbol: str, qty: float) -> float:
    """Redondea qty al stepSize del contrato."""
    info = get_contract_info(symbol)
    step = info["stepSize"]
    min_qty = info["minQty"]
    qty_rounded = round(int(qty / step) * step, 8)
    return max(qty_rounded, min_qty)


def _round_price(symbol: str, price: float) -> float:
    info = get_contract_info(symbol)
    prec = info["pricePrecision"]
    return round(price, prec)


# ─── Apalancamiento ────────────────────────────────────
def set_leverage(symbol: str, leverage: int = None) -> bool:
    lev = leverage or _lev()
    try:
        for side in ("LONG", "SHORT"):
            _post("/openApi/swap/v2/trade/leverage", {
                "symbol": symbol, "side": side, "leverage": lev
            })
        return True
    except Exception as e:
        print(f"[API] set_leverage {symbol}: {e}")
        return False


# ─── Abrir orden con SL/TP ─────────────────────────────
def open_order(symbol: str, side: str, qty: float,
               sl_price: float, tp_price: float) -> dict:
    """
    BUG FIX: stopLoss y takeProfit requieren JSON object en BingX,
    no un string de precio directo.

    side: "long" | "short"
    """
    pos_side   = "LONG"  if side == "long"  else "SHORT"
    order_side = "BUY"   if side == "long"  else "SELL"

    qty_r = _round_qty(symbol, qty)
    sl_r  = _round_price(symbol, sl_price)
    tp_r  = _round_price(symbol, tp_price)

    if qty_r <= 0:
        return {"error": f"qty inválida: {qty} → {qty_r}"}

    # BingX formato correcto para SL/TP en perpetual swap
    sl_obj = json.dumps({"type": "STOP_MARKET",  "stopPrice": str(sl_r), "price": str(sl_r),  "workingType": "MARK_PRICE"})
    tp_obj = json.dumps({"type": "TAKE_PROFIT_MARKET", "stopPrice": str(tp_r), "price": str(tp_r), "workingType": "MARK_PRICE"})

    params = {
        "symbol":       symbol,
        "side":         order_side,
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty_r,
        "stopLoss":     sl_obj,
        "takeProfit":   tp_obj,
    }

    print(f"  [API] open_order {symbol} {side} qty={qty_r} sl={sl_r} tp={tp_r}")
    try:
        result = _post("/openApi/swap/v2/trade/order", params)
        code = result.get("code", -1)
        if code == 0:
            order_id = (result.get("data") or {}).get("order", {}).get("orderId", "?")
            print(f"  [API] ✅ orden abierta  orderId={order_id}")
        else:
            print(f"  [API] ❌ error código {code}: {result.get('msg','')}")
        return result
    except Exception as e:
        print(f"  [API] exception: {e}")
        return {"error": str(e), "code": -1}


# ─── Cerrar posición ───────────────────────────────────
def close_position(symbol: str, side: str, qty: float) -> dict:
    pos_side   = "LONG"  if side == "long"  else "SHORT"
    order_side = "SELL"  if side == "long"  else "BUY"
    qty_r = _round_qty(symbol, qty)
    params = {
        "symbol":       symbol,
        "side":         order_side,
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty_r,
    }
    print(f"  [API] close_position {symbol} {side} qty={qty_r}")
    try:
        result = _post("/openApi/swap/v2/trade/order", params)
        code = result.get("code", -1)
        if code == 0:
            print(f"  [API] ✅ posición cerrada")
        else:
            print(f"  [API] ❌ error al cerrar: {result.get('msg','')}")
        return result
    except Exception as e:
        return {"error": str(e)}


# ─── Posiciones abiertas ───────────────────────────────
def get_open_positions() -> list:
    try:
        data = _get("/openApi/swap/v2/user/positions")
        return data.get("data") or []
    except Exception as e:
        print(f"[API] get_open_positions: {e}")
        return []


# ─── Klines públicas ───────────────────────────────────
def fetch_klines(symbol: str, interval: str = "1h", limit: int = 300) -> list:
    for path in ("/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"):
        try:
            r = requests.get(
                BASE + path,
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=15,
            ).json()
            c = r if isinstance(r, list) else r.get("data", [])
            if c:
                return c
        except Exception:
            continue
    return []
