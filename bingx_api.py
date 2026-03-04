import hmac, hashlib, time, requests
from urllib.parse import urlencode
from config import BINGX_API_KEY, BINGX_API_SECRET, LEVERAGE

# ══════════════════════════════════════════════════════
# bingx_api.py — Wrapper autenticado para BingX Perpetual
# ══════════════════════════════════════════════════════

BASE = "https://open-api.bingx.com"


def _sign(params: dict) -> str:
    query = urlencode(sorted(params.items()))
    return hmac.new(
        BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()


def _headers() -> dict:
    return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}


def _get(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    r = requests.get(BASE + path, params=params, headers=_headers(), timeout=10)
    return r.json()


def _post(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    r = requests.post(BASE + path, params=params, headers=_headers(), timeout=10)
    return r.json()


# ── Balance ────────────────────────────────────────────
def get_balance() -> float:
    """Retorna balance disponible en USDT. 0.0 si error."""
    try:
        data = _get("/openApi/swap/v2/user/balance")
        # La respuesta tiene data.balance.availableMargin
        bal = (data.get("data") or {}).get("balance", {})
        return float(bal.get("availableMargin", 0))
    except Exception as e:
        print(f"[API] get_balance error: {e}")
        return 0.0


# ── Precio actual ──────────────────────────────────────
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


# ── Configurar apalancamiento ──────────────────────────
def set_leverage(symbol: str, leverage: int = LEVERAGE) -> bool:
    try:
        r = _post("/openApi/swap/v2/trade/leverage", {
            "symbol": symbol,
            "side": "LONG",
            "leverage": leverage,
        })
        _post("/openApi/swap/v2/trade/leverage", {
            "symbol": symbol,
            "side": "SHORT",
            "leverage": leverage,
        })
        return True
    except Exception as e:
        print(f"[API] set_leverage {symbol}: {e}")
        return False


# ── Abrir orden ────────────────────────────────────────
def open_order(symbol: str, side: str, qty: float,
               sl_price: float, tp_price: float) -> dict:
    """
    side: "long" | "short"
    qty: cantidad en la moneda base (ej: 0.001 BTC)
    Retorna dict con orderId o error.
    """
    pos_side  = "LONG"  if side == "long"  else "SHORT"
    order_side = "BUY"  if side == "long"  else "SELL"

    params = {
        "symbol":           symbol,
        "side":             order_side,
        "positionSide":     pos_side,
        "type":             "MARKET",
        "quantity":         round(qty, 6),
        "stopLoss":         str(round(sl_price, 6)),
        "takeProfit":       str(round(tp_price, 6)),
    }
    try:
        return _post("/openApi/swap/v2/trade/order", params)
    except Exception as e:
        return {"error": str(e)}


# ── Cerrar posición ────────────────────────────────────
def close_position(symbol: str, side: str, qty: float) -> dict:
    """Cierra posición existente con orden market."""
    pos_side   = "LONG"  if side == "long"  else "SHORT"
    order_side = "SELL"  if side == "long"  else "BUY"
    params = {
        "symbol":       symbol,
        "side":         order_side,
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     round(qty, 6),
    }
    try:
        return _post("/openApi/swap/v2/trade/order", params)
    except Exception as e:
        return {"error": str(e)}


# ── Posiciones abiertas ────────────────────────────────
def get_open_positions() -> list:
    """Retorna lista de posiciones abiertas."""
    try:
        data = _get("/openApi/swap/v2/user/positions")
        return (data.get("data") or [])
    except Exception as e:
        print(f"[API] get_open_positions error: {e}")
        return []


# ── Klines (velas) ─────────────────────────────────────
def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200) -> list:
    """Retorna lista de velas raw (no autenticado)."""
    endpoints = [
        "/openApi/swap/v3/quote/klines",
        "/openApi/swap/v2/quote/klines",
    ]
    for path in endpoints:
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
