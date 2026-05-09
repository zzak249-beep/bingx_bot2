"""
BingX Perpetual Futures REST client
Docs: https://bingx-api.github.io/docs/
"""

import hashlib
import hmac
import time
import urllib.parse
import logging
from typing import Optional

import httpx

log = logging.getLogger("BingXClient")

BASE_URL = "https://open-api.bingx.com"


class BingXClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=15)

    def _sign(self, params: dict) -> str:
        query = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    def _headers(self) -> dict:
        return {
            "X-BX-APIKEY": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)
        r = await self.client.get(path, params=params, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"BingX error {data['code']}: {data.get('msg')}")
        return data

    async def _post(self, path: str, payload: dict) -> dict:
        payload["timestamp"] = int(time.time() * 1000)
        payload["signature"] = self._sign(payload)
        r = await self.client.post(path, params=payload, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"BingX error {data['code']}: {data.get('msg')}")
        return data

    # ─── Market data ──────────────────────────────────────────────
    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        """Retorna lista de velas OHLCV como dicts."""
        data = await self._get(
            "/openApi/swap/v3/quote/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
        # BingX retorna: [time, open, high, low, close, volume, ...]
        candles = []
        for c in data["data"]:
            candles.append({
                "time":   int(c[0]),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            })
        return candles

    async def get_price(self, symbol: str) -> float:
        data = await self._get("/openApi/swap/v2/quote/price", {"symbol": symbol})
        return float(data["data"]["price"])

    async def get_balance(self) -> float:
        """Retorna balance USDT disponible."""
        data = await self._get("/openApi/swap/v2/user/balance")
        for asset in data["data"]["balance"]:
            if asset["asset"] == "USDT":
                return float(asset["availableMargin"])
        return 0.0

    async def get_position(self, symbol: str) -> Optional[dict]:
        data = await self._get("/openApi/swap/v2/user/positions", {"symbol": symbol})
        positions = data.get("data", [])
        if positions:
            return positions[0]
        return None

    # ─── Orders ───────────────────────────────────────────────────
    async def place_order(
        self,
        symbol: str,
        side: str,          # "BUY" | "SELL"
        position_side: str, # "LONG" | "SHORT"
        qty: float,
        order_type: str = "MARKET",
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None,
        reduce_only: bool = False,
    ) -> dict:
        payload = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         order_type,
            "quantity":     str(qty),
            "reduceOnly":   str(reduce_only).lower(),
        }
        if price:
            payload["price"] = str(price)
        if stop_loss:
            payload["stopLoss"] = str(stop_loss)
        if take_profit:
            payload["takeProfit"] = str(take_profit)

        log.info(f"Placing order: {payload}")
        return await self._post("/openApi/swap/v2/trade/order", payload)

    async def close_position(self, symbol: str, position: dict) -> dict:
        side          = "SELL" if float(position["positionAmt"]) > 0 else "BUY"
        position_side = "LONG" if float(position["positionAmt"]) > 0 else "SHORT"
        qty           = abs(float(position["positionAmt"]))
        return await self.place_order(symbol, side, position_side, qty, reduce_only=True)

    async def set_leverage(self, symbol: str, leverage: int):
        await self._post("/openApi/swap/v2/trade/leverage", {
            "symbol":   symbol,
            "side":     "LONG",
            "leverage": str(leverage),
        })
        await self._post("/openApi/swap/v2/trade/leverage", {
            "symbol":   symbol,
            "side":     "SHORT",
            "leverage": str(leverage),
        })
        log.info(f"Leverage {leverage}x set for {symbol}")
