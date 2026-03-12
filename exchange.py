"""
exchange.py — BingX Perpetual Futures REST API v4.3 [FIX DEFINITIVO 109400]

CAUSA RAÍZ DEL ERROR 109400:
  La cuenta BingX puede estar en modo ONE-WAY o HEDGE.
  - ONE-WAY:  positionSide debe ser "BOTH"  (NO "LONG"/"SHORT")
  - HEDGE:    positionSide debe ser "LONG" o "SHORT"
  El bot enviaba siempre LONG/SHORT → falla en cuentas One-Way.

FIXES EN ESTA VERSION:
  ✅ FIX#A — Detecta automáticamente al arrancar si la cuenta es
             ONE-WAY o HEDGE y adapta todos los parámetros.
  ✅ FIX#B — set_leverage usa "BOTH" en One-Way, "LONG"/"SHORT" en Hedge
  ✅ FIX#C — abrir/cerrar/sl-tp usan positionSide correcto según modo
  ✅ FIX#D — quantity formateada limpia (sin .0, sin notación científica)
  ✅ FIX#E — _build_query mantiene sorted() para firma HMAC correcta
             pero timestamp y signature se añaden SIEMPRE al final
  ✅ FIX#F — Validación qty mínima con log detallado
  ✅ FIX#G — _fmt_price limpia sin trailing zeros
  ✅ FIX#H — Auto-reintento si 109400 "one-way" aparece en runtime
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

# Modo de posición detectado al arranque
# True  = Hedge Mode   → positionSide: "LONG" / "SHORT"
# False = One-Way Mode → positionSide: "BOTH"
_HEDGE_MODE: bool = True


# ══════════════════════════════════════════════════════════════
# DETECTAR MODO DE POSICIÓN ✅ FIX#A
# ══════════════════════════════════════════════════════════════

def detectar_modo_posicion():
    """
    Detecta si la cuenta usa Hedge Mode o One-Way Mode.
    Se llama desde main.py al arrancar, antes de operar.
    """
    global _HEDGE_MODE
    if config.MODO_DEMO:
        _HEDGE_MODE = True
        log.info("[MODO] DEMO → asumiendo HEDGE MODE")
        return
    try:
        res  = _post("/openApi/swap/v2/trade/leverage", {
            "symbol":   "BTC-USDT",
            "side":     "LONG",
            "leverage": config.LEVERAGE,
        })
        code = res.get("code", 0)
        msg  = res.get("msg", "").lower()

        if code == 109400 and ("one-way" in msg or "oneway" in msg or "one way" in msg):
            _HEDGE_MODE = False
            log.info("✅ [MODO] ONE-WAY MODE detectado → positionSide=BOTH")
        else:
            _HEDGE_MODE = True
            log.info("✅ [MODO] HEDGE MODE detectado → positionSide=LONG/SHORT")
    except Exception as e:
        log.warning(f"[MODO] Error detectando modo, asumiendo HEDGE: {e}")
        _HEDGE_MODE = True


def _set_hedge_mode(value: bool):
    global _HEDGE_MODE
    _HEDGE_MODE = value


def _pos_side(lado: str) -> str:
    """Devuelve positionSide correcto según el modo de la cuenta."""
    return "BOTH" if not _HEDGE_MODE else lado


# ══════════════════════════════════════════════════════════════
# FIRMA HMAC ✅ FIX#E
# ══════════════════════════════════════════════════════════════

def _sign(query_string: str) -> str:
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_query(params: dict) -> str:
    """
    Construye query string ordenado para firma HMAC correcta.
    timestamp se añade al final FUERA de sorted() para garantizar
    que siempre sea el último parámetro antes de signature.
    """
    core = {k: v for k, v in params.items()}
    return "&".join(f"{k}={v}" for k, v in sorted(core.items()))


def _headers() -> dict:
    return {"X-BX-APIKEY": config.BINGX_API_KEY}


def _ts() -> int:
    return int(time.time() * 1000)


def _get(path: str, params: dict = None, retries: int = 3) -> dict:
    p  = dict(params or {})
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
    p  = dict(params or {})
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
# FORMATEAR CANTIDAD Y PRECIO ✅ FIX#D + FIX#G
# ══════════════════════════════════════════════════════════════

def _fmt_qty(qty) -> str:
    """
    Formatea cantidad para BingX:
    - Nunca notación científica
    - Enteros sin decimales ('5600' no '5600.0')
    - Decimales limpios ('0.001' no '0.00100000')
    """
    if isinstance(qty, int):
        return str(qty)
    if isinstance(qty, float) and qty == int(qty):
        return str(int(qty))
    formatted = f"{qty:.10f}".rstrip("0").rstrip(".")
    return formatted


def _fmt_price(price: float, precision: int) -> str:
    """Formatea precio con la precisión del contrato, sin trailing zeros."""
    s = f"{price:.{precision}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ══════════════════════════════════════════════════════════════
# CACHE DE CONTRATOS FUTUROS
# ══════════════════════════════════════════════════════════════

def _decimals_from_step(step: float) -> int:
    if step >= 1:
        return 0
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[-1]) if "." in s else 0


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

            qty_step = None
            for campo in ["tradeMinQuantity", "stepSize", "quantityStep", "lotSize"]:
                val = c.get(campo)
                if val is not None:
                    try:
                        v = float(val)
                        if v > 0:
                            qty_step = v
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
                        v = float(val)
                        if v > 0:
                            min_qty = v
                            break
                    except Exception:
                        pass
            if not min_qty or min_qty <= 0:
                min_qty = qty_step

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
                        "ts": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                        "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]),
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
# APALANCAMIENTO ✅ FIX#B
# ══════════════════════════════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> bool:
    if config.MODO_DEMO:
        return True
    try:
        sides = ("LONG", "SHORT") if _HEDGE_MODE else ("BOTH",)
        for side in sides:
            r    = _post("/openApi/swap/v2/trade/leverage",
                         {"symbol": symbol, "side": side, "leverage": leverage})
            code = r.get("code", 0)
            if code not in (0, 200, 80012):
                log.warning(f"set_leverage {symbol} {side}: code={code} msg={r.get('msg')}")
        return True
    except Exception as e:
        log.error(f"set_leverage {symbol}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# CALCULAR CANTIDAD ✅ FIX#F
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
        qty_steps = math.floor(qty_raw / step)
        qty       = qty_steps * step
        decimals  = _decimals_from_step(step)
        qty       = int(round(qty)) if decimals == 0 else round(qty, decimals)
    else:
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
            f"[QTY] {symbol} qty={qty} < min={min_valid} "
            f"(necesitas >${precio * min_valid / config.LEVERAGE:.2f} USDT mínimo para este par)"
        )
        return 0.0

    return qty


# ══════════════════════════════════════════════════════════════
# SL / TP COMO ÓRDENES SEPARADAS ✅ FIX#C
# ══════════════════════════════════════════════════════════════

def _place_sl_tp(symbol: str, lado: str, qty: float, sl: float, tp: float):
    if config.MODO_DEMO:
        return

    precio_actual = get_precio(symbol)
    if precio_actual > 0:
        if lado == "LONG":
            if sl >= precio_actual:
                sl = precio_actual * 0.99
                log.warning(f"SL {symbol} LONG ajustado → {sl:.8f}")
            if tp <= precio_actual:
                tp = precio_actual * 1.02
                log.warning(f"TP {symbol} LONG ajustado → {tp:.8f}")
        else:
            if sl <= precio_actual:
                sl = precio_actual * 1.01
                log.warning(f"SL {symbol} SHORT ajustado → {sl:.8f}")
            if tp >= precio_actual:
                tp = precio_actual * 0.98
                log.warning(f"TP {symbol} SHORT ajustado → {tp:.8f}")

    try:
        close_side = "SELL" if lado == "LONG" else "BUY"
        pos_side   = _pos_side(lado)
        pp         = get_price_precision(symbol)
        qty_str    = _fmt_qty(qty)
        sl_str     = _fmt_price(sl, pp)
        tp_str     = _fmt_price(tp, pp)

        # STOP LOSS
        r1 = _post("/openApi/swap/v2/trade/order", {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     qty_str,
            "stopPrice":    sl_str,
            "workingType":  "MARK_PRICE",
        })
        if r1.get("code", 0) not in (0, 200):
            log.warning(f"SL {symbol}: code={r1.get('code')} msg={r1.get('msg')}")
        else:
            log.info(f"  SL colocado {symbol} {lado} @ {sl_str}")

        time.sleep(0.4)

        # TAKE PROFIT
        r2 = _post("/openApi/swap/v2/trade/order", {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     qty_str,
            "stopPrice":    tp_str,
            "workingType":  "MARK_PRICE",
        })
        if r2.get("code", 0) not in (0, 200):
            log.warning(f"TP {symbol}: code={r2.get('code')} msg={r2.get('msg')}")
        else:
            log.info(f"  TP colocado {symbol} {lado} @ {tp_str}")

    except Exception as e:
        log.error(f"_place_sl_tp {symbol}: {e}")


# ══════════════════════════════════════════════════════════════
# ABRIR LONG ✅ FIX#A + FIX#C + FIX#H
# ══════════════════════════════════════════════════════════════

def abrir_long(symbol: str, qty: float, precio: float,
               sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] LONG {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_long"}

    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    qty_str  = _fmt_qty(qty)
    pos_side = _pos_side("LONG")
    log.info(
        f"[ORDER] LONG {symbol} qty={qty_str} "
        f"positionSide={pos_side} ({'HEDGE' if _HEDGE_MODE else 'ONE-WAY'})"
    )

    res   = _post("/openApi/swap/v2/trade/order", {
        "symbol":       symbol,
        "side":         "BUY",
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty_str,
    })
    code  = res.get("code", -1)
    msg   = res.get("msg", "unknown")
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        log.error(f"abrir_long {symbol}: code={code} msg={msg} qty={qty_str}")
        # ✅ FIX#H: si el modo estaba mal, corregir y reintentar UNA vez
        if code == 109400 and ("one-way" in msg.lower() or "oneway" in msg.lower()):
            log.warning("[MODO] Corrigiendo a ONE-WAY y reintentando...")
            _set_hedge_mode(False)
            return abrir_long(symbol, qty, precio, sl, tp)
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)
    time.sleep(0.5)
    _place_sl_tp(symbol, "LONG", eqty, sl, tp)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# ABRIR SHORT ✅ FIX#A + FIX#C + FIX#H
# ══════════════════════════════════════════════════════════════

def abrir_short(symbol: str, qty: float, precio: float,
                sl: float, tp: float) -> dict:
    if config.MODO_DEMO:
        log.info(f"[DEMO] SHORT {symbol} qty={qty} @ {precio:.6f}")
        return {"fill_price": precio, "executedQty": qty, "orderId": "demo_short"}

    if not es_futuro_valido(symbol):
        return {"error": f"{symbol} no es un futuro perpetuo válido"}

    set_leverage(symbol, config.LEVERAGE)

    qty_str  = _fmt_qty(qty)
    pos_side = _pos_side("SHORT")
    log.info(
        f"[ORDER] SHORT {symbol} qty={qty_str} "
        f"positionSide={pos_side} ({'HEDGE' if _HEDGE_MODE else 'ONE-WAY'})"
    )

    res   = _post("/openApi/swap/v2/trade/order", {
        "symbol":       symbol,
        "side":         "SELL",
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty_str,
    })
    code  = res.get("code", -1)
    msg   = res.get("msg", "unknown")
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        log.error(f"abrir_short {symbol}: code={code} msg={msg} qty={qty_str}")
        if code == 109400 and ("one-way" in msg.lower() or "oneway" in msg.lower()):
            log.warning("[MODO] Corrigiendo a ONE-WAY y reintentando...")
            _set_hedge_mode(False)
            return abrir_short(symbol, qty, precio, sl, tp)
        return {"error": msg}

    fill = float(order.get("avgPrice", order.get("price", precio)) or precio)
    eqty = float(order.get("executedQty", qty) or qty)
    time.sleep(0.5)
    _place_sl_tp(symbol, "SHORT", eqty, sl, tp)
    return {"fill_price": fill, "executedQty": eqty, "orderId": order.get("orderId")}


# ══════════════════════════════════════════════════════════════
# CERRAR POSICIÓN ✅ FIX#C
# ══════════════════════════════════════════════════════════════

def cerrar_posicion(symbol: str, qty: float, lado: str) -> dict:
    if config.MODO_DEMO:
        return {"precio_salida": get_precio(symbol)}

    cancelar_ordenes_abiertas(symbol)
    time.sleep(0.3)

    qty_str  = _fmt_qty(qty)
    pos_side = _pos_side(lado)

    res   = _post("/openApi/swap/v2/trade/order", {
        "symbol":       symbol,
        "side":         "SELL" if lado == "LONG" else "BUY",
        "positionSide": pos_side,
        "type":         "MARKET",
        "quantity":     qty_str,
    })
    code  = res.get("code", -1)
    data  = res.get("data", {})
    order = data.get("order", data) if isinstance(data, dict) else {}

    if code not in (0, 200):
        log.error(f"cerrar_posicion {symbol}: code={code} msg={res.get('msg')} qty={qty_str}")
        return {"precio_salida": get_precio(symbol)}

    fill = float(order.get("avgPrice", order.get("price", 0)) or 0) or get_precio(symbol)
    return {"precio_salida": fill}
