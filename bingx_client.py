"""
BingX Client v5.1 — Firma HMAC corregida (error 100001)

Causas del error 100001 resueltas:
  1. Timestamp en ms exacto (no segundos)
  2. Parámetros ordenados alfabéticamente antes de firmar
  3. Secret y query en bytes UTF-8 explícito
  4. GET: params en URL query string
  5. POST: params en query string (NO en body) — requisito BingX Swap v2
  6. Timeout aumentado a 20s para evitar timestamps expirados
"""
import asyncio
import hashlib
import hmac
import time
import logging
from urllib.parse import urlencode

import aiohttp

log = logging.getLogger("BingX")
BASE = "https://open-api.bingx.com"


class BingXClient:
    def __init__(self, api_key: str, secret: str):
        self.api_key = api_key.strip()   # quitar espacios accidentales
        self.secret  = secret.strip()
        self._session: aiohttp.ClientSession | None = None

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-BX-APIKEY": self.api_key},
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    def _sign(self, params: dict) -> str:
        """
        Firma HMAC-SHA256 correcta para BingX.
        - Ordenar parámetros alfabéticamente
        - urlencode sin quote_via (estándar)
        - hmac con secret en UTF-8
        """
        sorted_params = dict(sorted(params.items()))
        query_string  = urlencode(sorted_params)
        signature = hmac.new(
            self.secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _ts(self) -> int:
        """Timestamp en milisegundos — sincronizado con hora del sistema."""
        return int(time.time() * 1000)

    async def _get(self, path: str, params: dict = None, signed: bool = False):
        params = dict(params or {})
        if signed:
            params["timestamp"] = self._ts()
            params["signature"] = self._sign(params)
        sess = await self._sess()
        url  = BASE + path
        async with sess.get(url, params=params) as r:
            data = await r.json()
        if data.get("code") not in (0, "0"):
            raise RuntimeError(f"GET {path} [{data.get('code')}]: {data.get('msg', data)}")
        return data.get("data", data)

    async def _post(self, path: str, params: dict = None):
        """
        BingX Swap v2: los parámetros van en el QUERY STRING del POST,
        no en el body. La firma también se calcula sobre el query string.
        """
        params = dict(params or {})
        params["timestamp"] = self._ts()
        params["signature"] = self._sign(params)

        sess = await self._sess()
        url  = BASE + path
        # Parámetros en query string (no en json body)
        async with sess.post(url, params=params) as r:
            data = await r.json()
        if data.get("code") not in (0, "0"):
            raise RuntimeError(f"POST {path} [{data.get('code')}]: {data.get('msg', data)}")
        return data.get("data", data)

    # ── Mercado ─────────────────────────────────────────────

    async def get_all_tickers(self) -> list:
        data = await self._get("/openApi/swap/v2/quote/ticker")
        return data if isinstance(data, list) else []

    async def get_klines(self, symbol: str, interval: str, limit: int = 300) -> list:
        data = await self._get("/openApi/swap/v2/quote/klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })
        rows = []
        for k in (data if isinstance(data, list) else []):
            rows.append([
                int(k["time"]), float(k["open"]), float(k["high"]),
                float(k["low"]), float(k["close"]), float(k["volume"]),
            ])
        return sorted(rows, key=lambda x: x[0])

    async def get_ticker(self, symbol: str) -> dict:
        data = await self._get("/openApi/swap/v2/quote/ticker", {"symbol": symbol})
        t = data[0] if isinstance(data, list) else data
        return {
            "last"  : float(t.get("lastPrice", 0)),
            "bid"   : float(t.get("bidPrice",  0)),
            "ask"   : float(t.get("askPrice",  0)),
            "volume": float(t.get("volume",    0)),
            "quoteVolume": float(t.get("quoteVolume", 0)),
        }

    async def get_order_book(self, symbol: str, depth: int = 10) -> dict:
        try:
            data = await self._get("/openApi/swap/v2/quote/depth",
                                   {"symbol": symbol, "limit": depth})
            bids = [[float(x[0]), float(x[1])] for x in data.get("bids", [])]
            asks = [[float(x[0]), float(x[1])] for x in data.get("asks", [])]
            return {"bids": bids, "asks": asks}
        except Exception as e:
            log.warning(f"order_book {symbol}: {e}")
            return {"bids": [], "asks": []}

    async def get_funding_rate(self, symbol: str) -> dict:
        try:
            data = await self._get("/openApi/swap/v2/quote/premiumIndex",
                                   {"symbol": symbol})
            if isinstance(data, list): data = data[0]
            return {
                "funding_rate"     : float(data.get("lastFundingRate", 0)),
                "next_funding_time": int(data.get("nextFundingTime", 0)),
                "mark_price"       : float(data.get("markPrice", 0)),
            }
        except Exception as e:
            log.warning(f"funding_rate {symbol}: {e}")
            return {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0}

    async def get_open_interest(self, symbol: str) -> dict:
        try:
            data = await self._get("/openApi/swap/v2/quote/openInterest",
                                   {"symbol": symbol})
            if isinstance(data, list): data = data[0]
            return {
                "open_interest"      : float(data.get("openInterest", 0)),
                "open_interest_value": float(data.get("openInterestValue", 0)),
            }
        except Exception as e:
            log.warning(f"open_interest {symbol}: {e}")
            return {"open_interest": 0.0, "open_interest_value": 0.0}

    async def get_liquidation_orders(self, symbol: str, limit: int = 20) -> list:
        try:
            data = await self._get("/openApi/swap/v2/quote/forceOrders",
                                   {"symbol": symbol, "limit": limit})
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning(f"liquidations {symbol}: {e}")
            return []

    # ── Cuenta ──────────────────────────────────────────────

    async def get_balance(self) -> float:
        try:
            data = await self._get("/openApi/swap/v2/user/balance", signed=True)
            for asset in data.get("balance", []):
                if asset.get("asset") == "USDT":
                    return float(asset.get("availableMargin", 0))
            return 0.0
        except Exception as e:
            log.error(f"get_balance: {e}")
            return 0.0

    async def get_positions(self, symbol: str = "") -> list:
        try:
            p = {"symbol": symbol} if symbol else {}
            data = await self._get("/openApi/swap/v2/user/positions", p, signed=True)
            return data if isinstance(data, list) else []
        except Exception as e:
            log.error(f"get_positions: {e}")
            return []

    # ── Órdenes ─────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int, side: str = "LONG"):
        try:
            await self._post("/openApi/swap/v2/trade/leverage", {
                "symbol"  : symbol,
                "leverage": str(leverage),
                "side"    : side,
            })
        except Exception as e:
            log.warning(f"set_leverage {symbol}: {e}")

    async def place_limit_order(self, symbol: str, side: str, size: float,
                                 price: float, sl_price: float,
                                 tp_price: float = None,
                                 post_only: bool = True) -> dict | None:
        await self.set_leverage(symbol, 10, side)
        await asyncio.sleep(0.2)
        params = {
            "symbol"      : symbol,
            "side"        : "BUY" if side == "LONG" else "SELL",
            "positionSide": side,
            "type"        : "LIMIT",
            "quantity"    : f"{size:.4f}",
            "price"       : f"{price:.4f}",
            "timeInForce" : "GTX" if post_only else "GTC",
            "stopLossPrice": f"{sl_price:.4f}",
        }
        if tp_price:
            params["takeProfitPrice"] = f"{tp_price:.4f}"
        try:
            data = await self._post("/openApi/swap/v2/trade/order", params)
            log.info(f"LIMIT {symbol} {side} {size}@{price:.4f}")
            return data
        except Exception as e:
            log.error(f"limit_order {symbol}: {e}")
            return None

    async def place_market_order(self, symbol: str, side: str, size: float,
                                  sl_price: float,
                                  tp_price: float = None) -> dict | None:
        await self.set_leverage(symbol, 10, side)
        await asyncio.sleep(0.2)
        params = {
            "symbol"      : symbol,
            "side"        : "BUY" if side == "LONG" else "SELL",
            "positionSide": side,
            "type"        : "MARKET",
            "quantity"    : f"{size:.4f}",
            "stopLossPrice": f"{sl_price:.4f}",
        }
        if tp_price:
            params["takeProfitPrice"] = f"{tp_price:.4f}"
        try:
            data = await self._post("/openApi/swap/v2/trade/order", params)
            log.info(f"MARKET {symbol} {side} {size}")
            return data
        except Exception as e:
            log.error(f"market_order {symbol}: {e}")
            return None

    async def cancel_order(self, symbol: str, order_id: str):
        try:
            return await self._post("/openApi/swap/v2/trade/cancel", {
                "symbol" : symbol,
                "orderId": str(order_id),
            })
        except Exception as e:
            log.warning(f"cancel {symbol} {order_id}: {e}")

    async def get_order_status(self, symbol: str, order_id: str) -> dict | None:
        try:
            return await self._get("/openApi/swap/v2/trade/order", {
                "symbol" : symbol,
                "orderId": str(order_id),
            }, signed=True)
        except Exception as e:
            log.warning(f"order_status: {e}")
            return None

    async def close_position(self, symbol: str, side: str) -> dict | None:
        """Cierra posición con orden market reduce-only."""
        positions = await self.get_positions(symbol)
        size = 0.0
        for p in positions:
            if (p.get("positionSide") == side
                    and abs(float(p.get("positionAmt", 0))) > 0):
                size = abs(float(p["positionAmt"]))
                break

        if size == 0:
            log.warning(f"close_position: sin posición abierta {symbol} {side}")
            return None

        params = {
            "symbol"      : symbol,
            "side"        : "SELL" if side == "LONG" else "BUY",
            "positionSide": side,
            "type"        : "MARKET",
            "quantity"    : f"{size:.4f}",
            "reduceOnly"  : "true",
        }
        try:
            data = await self._post("/openApi/swap/v2/trade/order", params)
            log.info(f"CLOSE {symbol} {side} qty={size}")
            return data
        except Exception as e:
            log.error(f"close_position {symbol}: {e}")
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
