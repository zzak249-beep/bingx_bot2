import os, hmac, hashlib, time, requests, json
from urllib.parse import urlencode

# ══════════════════════════════════════════════════════
# bingx_api.py v13.1
# FIX: Signature mismatch (error 100001)
#   → BingX requiere params SIN sorted()
#   → timestamp SIEMPRE al final antes de firmar
# ══════════════════════════════════════════════════════

BASE = "https://open-api.bingx.com"

def _key():    return os.getenv("BINGX_API_KEY",    "")
def _secret(): return os.getenv("BINGX_API_SECRET", "")
def _lev():    return int(os.getenv("LEVERAGE", 2))

def _sign(query_string: str) -> str:
    """Firma HMAC-SHA256. BingX requiere el query string SIN ordenar."""
    secret = _secret()
    if not secret:
        raise ValueError("BINGX_API_SECRET no configurado")
    return hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def _headers() -> dict:
    k = _key()
    if not k:
        raise ValueError("BINGX_API_KEY no configurado")
    return {
        "X-BX-APIKEY":  k,
        "Content-Type": "application/json",
    }

def _get(path: str, params: dict = None) -> dict:
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    qs = urlencode(p)                    # SIN sorted
    p["signature"] = _sign(qs)
    r = requests.get(BASE + path, params=p, headers=_headers(), timeout=12)
    r.raise_for_status()
    return r.json()

def _post(path: str, params: dict = None) -> dict:
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    qs = urlencode(p)                    # SIN sorted
    p["signature"] = _sign(qs)
    r = requests.post(BASE + path, params=p, headers=_headers(), timeout=12)
    r.raise_for_status()
    return r.json()

# ── Contratos ─────────────────────────────────────────
_contract_cache = {}

def get_contract_info(symbol: str) -> dict:
    if symbol in _contract_cache:
        return _contract_cache[symbol]
    try:
        r = requests.get(BASE + "/openApi/swap/v2/quote/contracts", timeout=10).json()
        for c in (r.get("data") or []):
            if c.get("symbol") == symbol:
                info = {
                    "stepSize":          float(c.get("tradeMinQuantity", 0.001)),
                    "minQty":            float(c.get("tradeMinQuantity", 0.001)),
                    "pricePrecision":    int(c.get("pricePrecision", 4)),
                    "quantityPrecision": int(c.get("quantityPrecision", 3)),
                }
                _contract_cache[symbol] = info
                return info
    except Exception as e:
        print(f"[API] contract_info {symbol}: {e}")
    return {"stepSize": 0.001, "minQty": 0.001, "pricePrecision": 4, "quantityPrecision": 3}

def _round_qty(symbol: str, qty: float) -> float:
    info = get_contract_info(symbol)
    step = info["stepSize"]
    q    = round(int(qty / step) * step, 8)
    return max(q, info["minQty"])

def _round_price(symbol: str, price: float) -> float:
    return round(price, get_contract_info(symbol)["pricePrecision"])

# ── Balance ───────────────────────────────────────────
def get_balance() -> float:
    try:
        data = _get("/openApi/swap/v2/user/balance")
        bal  = ((data.get("data") or {}).get("balance") or {})
        return float(bal.get("availableMargin", 0))
    except Exception as e:
        print(f"[API] get_balance: {e}")
        return 0.0

# ── Precio ────────────────────────────────────────────
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

# ── Apalancamiento ────────────────────────────────────
def set_leverage(symbol: str, leverage: int = None) -> bool:
    lev = leverage or _lev()
    try:
        for side in ("LONG", "SHORT"):
            _post("/openApi/swap/v2/trade/leverage",
                  {"symbol": symbol, "side": side, "leverage": lev})
        return True
    except Exception as e:
        print(f"[API] set_leverage {symbol}: {e}")
        return False

# ── Abrir orden ───────────────────────────────────────
def open_order(symbol: str, side: str, qty: float,
               sl_price: float, tp_price: float) -> dict:
    pos_side   = "LONG" if side == "long" else "SHORT"
    order_side = "BUY"  if side == "long" else "SELL"

    qty_r = _round_qty(symbol, qty)
    sl_r  = _round_price(symbol, sl_price)
    tp_r  = _round_price(symbol, tp_price)

    if qty_r <= 0:
        return {"code": -1, "msg": f"qty inválida: {qty}→{qty_r}"}

    sl_obj = json.dumps({
        "type": "STOP_MARKET",
        "stopPrice": str(sl_r),
        "price": str(sl_r),
        "workingType": "MARK_PRICE"
    })
    tp_obj = json.dumps({
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": str(tp_r),
        "price": str(tp_r),
        "workingType": "MARK_PRICE"
    })

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
        code   = result.get("code", -1)
        if code == 0:
            oid = (result.get("data") or {}).get("order", {}).get("orderId", "?")
            print(f"  [API] ✅ orden abierta orderId={oid}")
        else:
            print(f"  [API] ❌ code={code} {result.get('msg','')}")
        return result
    except Exception as e:
        print(f"  [API] exception: {e}")
        return {"code": -1, "msg": str(e)}

# ── Cerrar posición ───────────────────────────────────
def close_position(symbol: str, side: str, qty: float) -> dict:
    pos_side   = "LONG" if side == "long" else "SHORT"
    order_side = "SELL" if side == "long" else "BUY"
    qty_r = _round_qty(symbol, qty)
    try:
        return _post("/openApi/swap/v2/trade/order", {
            "symbol":       symbol,
            "side":         order_side,
            "positionSide": pos_side,
            "type":         "MARKET",
            "quantity":     qty_r,
        })
    except Exception as e:
        return {"code": -1, "msg": str(e)}

# ── Posiciones abiertas ───────────────────────────────
def get_open_positions() -> list:
    try:
        return _get("/openApi/swap/v2/user/positions").get("data") or []
    except Exception as e:
        print(f"[API] get_open_positions: {e}")
        return []

# ── Klines (sin autenticación) ────────────────────────
def fetch_klines(symbol: str, interval: str = "15m", limit: int = 300) -> list:
    for path in ("/openApi/swap/v3/quote/klines", "/openApi/swap/v2/quote/klines"):
        try:
            r = requests.get(BASE + path,
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=15).json()
            c = r if isinstance(r, list) else r.get("data", [])
            if c:
                return c
        except Exception:
            continue
    return []
