"""
QF×JP Bot v7.4 — BingX Client (MERGED v6.4 + v7.2)
═══════════════════════════════════════════════════════════════════════════════
Toma lo mejor de v6.4 y v7.2:

  DE v6.4:
    ✅ Retry HTTP (3 intentos con backoff) — evita fallos por red
    ✅ cancel_order con DELETE (v7.2 usaba POST incorrectamente → sin efecto)
    ✅ cancel_all_orders con DELETE (v7.2 usaba POST → error silencioso)
    ✅ Firma parseParam BingX oficial (sorted + timestamp al final)

  DE v7.2:
    ✅ .strip() en API key y secret (fix error 100001 "Signature verification")
    ✅ _get_real_position_side() — Hedge/One-Way auto-detección
    ✅ _extract_executed_qty() — qty real de BingX (fix error 110424)
    ✅ _safe_qty_for_sl() — qty segura para SL/TP
    ✅ sleep 1.2s post-entrada (fix race condition de posición)
    ✅ Fallback de error de positionSide y position not exist

  NUESTROS FIXES anteriores:
    ✅ Sin closePosition=true (fix error 10940)
    ✅ qty real siempre en place_stop_market_order
═══════════════════════════════════════════════════════════════════════════════
"""
import asyncio
import hashlib
import hmac
import logging
import math
import time
from urllib.parse import urlencode

import aiohttp
import config as C

log = logging.getLogger("bingx")


# ── Firma ─────────────────────────────────────────────────────────────────────

def _ts() -> int:
    return int(time.time() * 1000)


def _sign(params: dict) -> str:
    """
    Firma parseParam oficial BingX:
      sorted(params) → key=val&key=val → &timestamp=xxx → HMAC-SHA256
    .strip() en secret key para eliminar espacios/newlines invisibles
    que Railway puede añadir al copiar variables de entorno (fix 100001).
    """
    sorted_keys = sorted(params.keys())
    parts       = [f"{k}={params[k]}" for k in sorted_keys]
    payload     = "&".join(parts)
    key         = C.BINGX_SECRET_KEY.strip()
    return hmac.new(
        key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _api_key() -> str:
    return C.BINGX_API_KEY.strip()


# ── Cliente HTTP ──────────────────────────────────────────────────────────────

class BingXClient:
    BASE = C.BINGX_BASE_URL

    def __init__(self):
        self._session:        aiohttp.ClientSession | None = None
        self._precision_map:  dict[str, int]   = {}
        self._min_qty_map:    dict[str, float] = {}
        self._step_map:       dict[str, float] = {}
        log.info("BingXClient v7.4 — merged (retry + Hedge + strip + real_qty)")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── HTTP primitives con retry ─────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None,
                   signed: bool = True) -> dict:
        """GET con 3 intentos y backoff exponencial."""
        base = dict(params or {})
        for attempt in range(3):
            try:
                s   = await self._get_session()
                p   = dict(base)
                ts  = _ts()
                p["timestamp"]  = ts
                p["recvWindow"] = 10000
                p["signature"]  = _sign(p)
                headers = {"X-BX-APIKEY": _api_key()} if signed else {}
                async with s.get(f"{self.BASE}{path}", params=p,
                                 headers=headers) as r:
                    return await r.json(content_type=None)
            except Exception as e:
                if attempt == 2:
                    log.error("GET %s error: %s", path, e)
                    raise
                await asyncio.sleep(1.5 ** attempt)
        return {}

    async def _post(self, path: str, params: dict) -> dict:
        """POST con 3 intentos y backoff exponencial."""
        for attempt in range(3):
            try:
                s  = await self._get_session()
                p  = dict(params)
                p["timestamp"]  = _ts()
                p["recvWindow"] = 10000
                p["signature"]  = _sign(p)
                async with s.post(f"{self.BASE}{path}", params=p,
                                  headers={"X-BX-APIKEY": _api_key()}) as r:
                    return await r.json(content_type=None)
            except Exception as e:
                if attempt == 2:
                    log.error("POST %s error: %s", path, e)
                    raise
                await asyncio.sleep(1.5 ** attempt)
        return {}

    async def _delete(self, path: str, params: dict) -> dict:
        """DELETE con 3 intentos y backoff exponencial."""
        for attempt in range(3):
            try:
                s  = await self._get_session()
                p  = dict(params)
                p["timestamp"]  = _ts()
                p["recvWindow"] = 10000
                p["signature"]  = _sign(p)
                async with s.delete(f"{self.BASE}{path}", params=p,
                                    headers={"X-BX-APIKEY": _api_key()}) as r:
                    return await r.json(content_type=None)
            except Exception as e:
                if attempt == 2:
                    log.error("DELETE %s error: %s", path, e)
                    raise
                await asyncio.sleep(1.5 ** attempt)
        return {}

    # ── Redondeo y precisión ──────────────────────────────────────────────────

    def _round_qty(self, symbol: str, qty: float) -> float:
        step = self._step_map.get(symbol, 0)
        if step > 0:
            qty       = math.floor(qty / step) * step
            precision = max(0, round(-math.log10(step)))
            qty       = round(qty, precision)
        else:
            precision = self._precision_map.get(symbol, 4)
            qty       = math.floor(qty * 10**precision) / 10**precision
        min_qty = self._min_qty_map.get(symbol, 0)
        return max(qty, min_qty) if qty > 0 else 0.0

    def _safe_qty_for_sl(self, symbol: str, qty: float) -> float:
        """Qty segura para SL/TP garantizando qty_sl ≤ qty_real_ejecutada."""
        step = self._step_map.get(symbol, 0)
        if step > 0:
            qty       = math.floor(qty / step) * step
            precision = max(0, round(-math.log10(step)))
            qty       = round(qty, precision)
        else:
            precision = self._precision_map.get(symbol, 4)
            qty       = round(qty * 0.9999, precision)
        min_qty = self._min_qty_map.get(symbol, 0)
        return max(qty, min_qty) if qty > 0 else 0.0

    def _extract_executed_qty(self, entry_resp: dict, fallback_qty: float) -> float:
        """
        Extrae qty REAL ejecutada de la respuesta BingX (fix error 110424).
        BingX puede ejecutar con qty ligeramente diferente al cálculo local.
        """
        try:
            data  = entry_resp.get("data", {})
            order = data.get("order", data)
            for field in ("executedQty", "origQty", "quantity"):
                val = order.get(field, "")
                if val and str(val) not in ("", "0", "0.0"):
                    extracted = float(val)
                    if extracted > 0:
                        return extracted
        except Exception:
            pass
        return self._safe_qty_for_sl("", fallback_qty)

    def _parse_error(self, resp: dict) -> str:
        if not isinstance(resp, dict):
            return ""
        return str(resp.get("msg", resp.get("message", ""))).lower()

    # ── positionSide auto-detección (Hedge / One-Way) ─────────────────────────

    async def _get_real_position_side(self, symbol: str, direction: str) -> str:
        """
        Lee positionSide real de BingX:
          Hedge Mode  → LONG o SHORT
          One-Way     → BOTH
        Si no encuentra posición → usa direction (correcto para Hedge).
        """
        try:
            positions = await self.get_open_positions()
            for p in positions:
                if p.get("symbol") != symbol:
                    continue
                ps = p.get("positionSide", "")
                if ps in ("LONG", "SHORT", "BOTH"):
                    return ps
        except Exception as e:
            log.debug("[%s] _get_real_position_side error: %s", symbol, e)
        return direction

    # ── Símbolos ──────────────────────────────────────────────────────────────

    async def get_all_symbols(self) -> list[str]:
        data = await self._get("/openApi/swap/v2/quote/contracts", signed=False)
        raw  = data.get("data", [])
        if isinstance(raw, dict):
            raw = raw.get("contracts", raw.get("list", []))
        if not isinstance(raw, list):
            raw = []

        symbols      = []
        vol_map:     dict[str, float] = {}
        vol_detected = 0

        _bad_prefixes = ("BEAR", "BULL", "PUMP", "NCS")

        for item in raw:
            if not isinstance(item, dict):
                continue
            sym = item.get("symbol", "")
            if not sym:
                continue
            if "-" not in sym and sym.endswith("USDT"):
                sym = sym[:-4] + "-USDT"
            if not sym.endswith("-USDT"):
                continue
            if sym in C.BLACKLIST:
                continue
            base_coin = sym.replace("-USDT", "")
            if any(base_coin.startswith(p) for p in _bad_prefixes):
                continue

            self._precision_map[sym] = int(item.get("volumePrecision",    item.get("quantityPrecision", 4)) or 4)
            self._min_qty_map[sym]   = float(item.get("tradeMinQuantity", item.get("minOrderQty", 0)) or 0)
            self._step_map[sym]      = float(item.get("qtyStep",          item.get("stepSize", 0)) or 0)

            vol_raw = (
                item.get("volume24h") or item.get("vol24h") or
                item.get("quoteVolume") or item.get("tradeAmt") or 0
            )
            vol = float(vol_raw) if vol_raw else 0.0
            if vol > 0:
                vol_detected += 1
            vol_map[sym] = vol
            symbols.append(sym)

        # Enriquecer desde /ticker si contracts no tiene volumen
        if vol_detected == 0 and symbols:
            log.info("contracts sin volumen → enriqueciendo con /ticker")
            try:
                td = await self._get("/openApi/swap/v2/quote/ticker", signed=False)
                for t in (td.get("data", []) or []):
                    s  = t.get("symbol", "")
                    if "-" not in s and s.endswith("USDT"):
                        s = s[:-4] + "-USDT"
                    qv = float(t.get("quoteVolume", 0) or t.get("volume", 0) or 0)
                    if s in vol_map:
                        vol_map[s] = qv
                        if qv > 0:
                            vol_detected += 1
            except Exception as e:
                log.warning("ticker fallback error: %s", e)

        if vol_detected > 0 and C.MIN_VOLUME_USDT > 0:
            symbols = [s for s in symbols if vol_map.get(s, 0) >= C.MIN_VOLUME_USDT]

        symbols.sort(key=lambda s: vol_map.get(s, 0), reverse=True)
        if C.TOP_N_SYMBOLS > 0:
            symbols = symbols[:C.TOP_N_SYMBOLS]

        log.info("get_all_symbols: %d símbolos (raw=%d, con_vol=%d)",
                 len(symbols), len(raw), vol_detected)
        return symbols

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        data = await self._get(
            "/openApi/swap/v3/quote/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            signed=False,
        )
        raw = data.get("data", [])
        if isinstance(raw, dict):
            raw = raw.get("klines", [])
        result = []
        for c in raw:
            try:
                if isinstance(c, dict):
                    result.append([
                        int(c.get("time",   c.get("openTime", 0))),
                        float(c.get("open",  c.get("o", 0))),
                        float(c.get("high",  c.get("h", 0))),
                        float(c.get("low",   c.get("l", 0))),
                        float(c.get("close", c.get("c", 0))),
                        float(c.get("volume", c.get("v", 0))),
                    ])
                elif isinstance(c, (list, tuple)) and len(c) >= 6:
                    result.append([int(c[0]), float(c[1]), float(c[2]),
                                   float(c[3]), float(c[4]), float(c[5])])
            except Exception:
                continue
        return sorted(result, key=lambda x: x[0])

    async def get_ticker(self, symbol: str) -> dict:
        data = await self._get("/openApi/swap/v2/quote/ticker",
                               {"symbol": symbol}, signed=False)
        raw = data.get("data", {})
        if isinstance(raw, list):
            return raw[0] if raw else {}
        return raw if isinstance(raw, dict) else {}

    async def get_order_book(self, symbol: str, limit: int = 10) -> dict:
        data = await self._get("/openApi/swap/v2/quote/depth",
                               {"symbol": symbol, "limit": limit}, signed=False)
        raw = data.get("data", data)
        if isinstance(raw, dict):
            return {"bids": raw.get("bids", []), "asks": raw.get("asks", [])}
        return {"bids": [], "asks": []}

    async def get_funding_rate(self, symbol: str) -> float:
        try:
            data = await self._get("/openApi/swap/v2/quote/fundingRate",
                                   {"symbol": symbol}, signed=False)
            raw = data.get("data", {})
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            return float(raw.get("fundingRate", 0) or 0)
        except Exception:
            return 0.0

    # ── Cuenta ────────────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        data = await self._get("/openApi/swap/v3/user/balance",
                               {"currency": "USDT"})
        raw = data.get("data", {})

        def _extract(d: dict) -> float:
            avail  = float(d.get("availableMargin", 0) or 0)
            equity = float(d.get("equity",          0) or 0)
            if avail > 0:
                return avail
            if equity > 0:
                return equity
            return 0.0

        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, dict) and a.get("asset", "") == "USDT":
                    return _extract(a)
            for a in raw:
                if isinstance(a, dict) and ("availableMargin" in a or "equity" in a):
                    return _extract(a)
            return 0.0
        if isinstance(raw, dict):
            bal = raw.get("balance", raw)
            if isinstance(bal, list):
                for a in bal:
                    if isinstance(a, dict) and a.get("asset", "") == "USDT":
                        return _extract(a)
            if isinstance(bal, dict):
                return _extract(bal)
        return 0.0

    async def get_open_positions(self) -> list:
        data = await self._get("/openApi/swap/v2/user/positions")
        positions = data.get("data", [])
        if not isinstance(positions, list):
            return []
        return [p for p in positions if float(p.get("positionAmt", 0) or 0) != 0]

    async def get_open_orders(self, symbol: str) -> list:
        data = await self._get("/openApi/swap/v2/trade/openOrders",
                               {"symbol": symbol})
        return data.get("data", {}).get("orders", [])

    # ── Apalancamiento ────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int,
                            side: str = "LONG") -> bool:
        results = await asyncio.gather(
            self._post("/openApi/swap/v2/trade/leverage",
                       {"symbol": symbol, "side": "LONG", "leverage": leverage}),
            self._post("/openApi/swap/v2/trade/leverage",
                       {"symbol": symbol, "side": "SHORT", "leverage": leverage}),
            return_exceptions=True,
        )
        ok = True
        for s, r in zip(["LONG", "SHORT"], results):
            if isinstance(r, Exception):
                log.warning("[%s] set_leverage %s error: %s", symbol, s, r)
                ok = False
            elif isinstance(r, dict) and r.get("code", -1) != 0:
                log.warning("[%s] set_leverage %s: %s", symbol, s, r.get("code"))
        return ok

    # ── Órdenes ───────────────────────────────────────────────────────────────

    async def place_stop_market_order(
        self,
        symbol:        str,
        side:          str,
        quantity:      float,
        stop_price:    float,
        direction:     str = "LONG",
        order_type:    str = "STOP_MARKET",
    ) -> dict:
        qty     = self._round_qty(symbol, quantity)
        real_ps = await self._get_real_position_side(symbol, direction)

        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": real_ps,
            "type":         order_type,
            "stopPrice":    str(round(stop_price, 8)),
            "quantity":     str(qty),
            "workingType":  "MARK_PRICE",
            "priceProtect": "true",
        }
        log.debug("[%s] %s side=%s ps=%s stop=%.6f qty=%s",
                  symbol, order_type, side, real_ps, stop_price, qty)

        resp = await self._post("/openApi/swap/v2/trade/order", params)

        # Fallbacks automáticos por errores de positionSide
        if isinstance(resp, dict) and resp.get("code", -1) != 0:
            msg = self._parse_error(resp)
            if "positionside" in msg or "position side" in msg:
                log.warning("[%s] positionSide fallback → %s", symbol, direction)
                params["positionSide"] = direction
                resp = await self._post("/openApi/swap/v2/trade/order", params)
            elif "position not exist" in msg and real_ps != "BOTH":
                log.warning("[%s] position not exist → probando BOTH", symbol)
                params["positionSide"] = "BOTH"
                resp = await self._post("/openApi/swap/v2/trade/order", params)

        return resp if isinstance(resp, dict) else {"code": -1, "msg": str(resp)}

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        """DELETE correcto para cancelar orden individual."""
        return await self._delete(
            "/openApi/swap/v2/trade/order",
            {"symbol": symbol, "orderId": order_id},
        )

    async def cancel_all_orders(self, symbol: str) -> dict:
        """DELETE correcto para cancelar todas las órdenes de un símbolo."""
        return await self._delete(
            "/openApi/swap/v2/trade/allOpenOrders",
            {"symbol": symbol},
        )

    async def close_position_market(self, symbol: str, quantity: float,
                                     direction: str) -> dict:
        side    = "SELL" if direction == "LONG" else "BUY"
        qty     = self._round_qty(symbol, quantity)
        real_ps = await self._get_real_position_side(symbol, direction)

        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": real_ps,
            "type":         "MARKET",
            "quantity":     str(qty),
        }
        log.info("[%s] CLOSE MARKET ps=%s qty=%s", symbol, real_ps, qty)
        resp = await self._post("/openApi/swap/v2/trade/order", params)

        if isinstance(resp, dict) and resp.get("code", -1) != 0:
            msg = self._parse_error(resp)
            if "positionside" in msg or "position side" in msg:
                params["positionSide"] = direction
                resp = await self._post("/openApi/swap/v2/trade/order", params)
            elif "position not exist" in msg and real_ps != "BOTH":
                params["positionSide"] = "BOTH"
                resp = await self._post("/openApi/swap/v2/trade/order", params)

        return resp if isinstance(resp, dict) else {"code": -1}

    # ── open_trade completo ───────────────────────────────────────────────────

    async def open_trade(
        self,
        symbol:    str,
        direction: str,
        quantity:  float,
        sl_price:  float,
        tp1_price: float,
        tp2_price: float,
    ) -> dict:
        """
        Abre posición (MARKET) + SL + TP1(50%) + TP2(50%).
        Usa qty REAL ejecutada por BingX para SL/TP (fix error 110424).
        Sleep 1.2s post-entrada para dar tiempo a BingX a registrar posición.
        """
        qty       = self._round_qty(symbol, quantity)
        side_open = "BUY"  if direction == "LONG" else "SELL"
        side_cls  = "SELL" if direction == "LONG" else "BUY"
        results   = {}

        await self.set_leverage(symbol, C.LEVERAGE, direction)

        if not self._min_qty_map.get(symbol) or qty >= self._min_qty_map.get(symbol, 0):
            pass
        if qty <= 0:
            return {"entry": {"code": -1, "msg": "qty_zero"}}

        # ── Entrada ───────────────────────────────────────────────────────────
        entry_resp = await self._post("/openApi/swap/v2/trade/order", {
            "symbol":       symbol,
            "side":         side_open,
            "positionSide": direction,
            "type":         "MARKET",
            "quantity":     str(qty),
        })
        results["entry"] = entry_resp
        log.info("[%s] MARKET %s qty=%s → code=%s",
                 symbol, side_open, qty, entry_resp.get("code", "?"))

        if entry_resp.get("code", -1) != 0:
            return results

        # Extraer qty real ejecutada (fix 110424)
        real_qty = self._extract_executed_qty(entry_resp, qty)
        if abs(real_qty - qty) > qty * 0.001:
            log.info("[%s] qty ajustada: local=%.6f real_BingX=%.6f", symbol, qty, real_qty)
        qty = real_qty

        # Sleep post-entrada (fix race condition positionSide)
        await asyncio.sleep(1.2)

        # ── Split qty para TP1/TP2 ────────────────────────────────────────────
        step = self._step_map.get(symbol, 0)
        if step > 0:
            precision = max(0, round(-math.log10(step)))
        else:
            precision = self._precision_map.get(symbol, 4)
        factor     = 10 ** precision
        qty_half   = math.floor(qty / 2 * factor) / factor
        qty_remain = math.floor((qty - qty_half) * factor) / factor
        if qty_half + qty_remain > qty:
            qty_remain = math.floor((qty - qty_half) * factor) / factor

        # ── SL + TP1 + TP2 en paralelo ───────────────────────────────────────
        sl_r, tp1_r, tp2_r = await asyncio.gather(
            self.place_stop_market_order(symbol, side_cls, qty,        sl_price,  direction, "STOP_MARKET"),
            self.place_stop_market_order(symbol, side_cls, qty_half,   tp1_price, direction, "TAKE_PROFIT_MARKET"),
            self.place_stop_market_order(symbol, side_cls, qty_remain, tp2_price, direction, "TAKE_PROFIT_MARKET"),
            return_exceptions=True,
        )

        for label, r, price in [("SL", sl_r, sl_price), ("TP1", tp1_r, tp1_price), ("TP2", tp2_r, tp2_price)]:
            resp = r if isinstance(r, dict) else {"code": -1, "msg": str(r)}
            results[label.lower()] = resp
            if resp.get("code", -1) == 0:
                log.info("[%s] %s OK @ %.6f", symbol, label, price)
            else:
                log.error("[%s] %s FALLIDO: %s", symbol, label, resp)
                # Retry SL con qty_safe (nunca dejar posición sin protección)
                if label == "SL":
                    qty_safe = self._safe_qty_for_sl(symbol, qty)
                    if qty_safe != qty:
                        log.info("[%s] SL retry con qty_safe=%.6f", symbol, qty_safe)
                        resp2 = await self.place_stop_market_order(
                            symbol, side_cls, qty_safe, sl_price, direction, "STOP_MARKET"
                        )
                        results["sl"] = resp2
                        if resp2.get("code", -1) == 0:
                            log.info("[%s] SL OK (retry) @ %.6f", symbol, sl_price)
                        else:
                            log.error("[%s] SL FALLIDO (retry): %s", symbol, resp2)

        return results
