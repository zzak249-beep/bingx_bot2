"""
BingX Exchange Connector
Handles: market data, order execution, position management
"""

import asyncio
import hashlib
import hmac
import time
import logging
import aiohttp
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger("bingx")

BASE_URL = "https://open-api.bingx.com"


def _sign(params: dict, secret: str) -> str:
    query = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BingXClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = "https://open-api-vst.bingx.com" if testnet else BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-BX-APIKEY": self.api_key}
            )
        return self._session

    async def _request(self, method: str, path: str, params: dict = None, signed: bool = False) -> dict:
        session = await self._get_session()
        params  = params or {}

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = _sign(params, self.api_secret)

        url = self.base_url + path
        try:
            if method == "GET":
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    return await r.json()
            else:
                async with session.post(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    return await r.json()
        except Exception as e:
            logger.error(f"BingX request error {path}: {e}")
            return {"code": -1, "msg": str(e)}

    # ── MARKET DATA ──────────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        """
        interval: 1m, 3m, 5m, 15m, 1h, 4h, 1d
        Returns list of [timestamp, open, high, low, close, volume]
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        data = await self._request("GET", "/openApi/swap/v3/quote/klines", params)
        if data.get("code") != 0:
            logger.error(f"Klines error {symbol} {interval}: {data}")
            return []
        return data.get("data", [])

    async def get_all_symbols(self) -> list:
        """Returns list of perpetual swap symbols (USDT pairs only)"""
        data = await self._request("GET", "/openApi/swap/v2/quote/contracts")
        if data.get("code") != 0:
            return []
        symbols = []
        for item in data.get("data", []):
            sym = item.get("symbol", "")
            if sym.endswith("-USDT") and item.get("status") == 1:
                symbols.append(sym)
        return symbols

    async def get_ticker(self, symbol: str) -> dict:
        params = {"symbol": symbol}
        data = await self._request("GET", "/openApi/swap/v2/quote/ticker", params)
        return data.get("data", {})

    async def get_account_balance(self) -> float:
        data = await self._request("GET", "/openApi/swap/v2/user/balance", signed=True)
        if data.get("code") != 0:
            return 0.0
        for asset in data.get("data", {}).get("balance", []):
            if asset.get("asset") == "USDT":
                return float(asset.get("balance", 0))
        return 0.0

    async def get_positions(self) -> list:
        data = await self._request("GET", "/openApi/swap/v2/user/positions", signed=True)
        if data.get("code") != 0:
            return []
        return [p for p in data.get("data", []) if float(p.get("positionAmt", 0)) != 0]

    # ── ORDER MANAGEMENT ─────────────────────────────────────────────

    async def place_order(self, symbol: str, side: str, quantity: float,
                          order_type: str = "MARKET",
                          position_side: str = "LONG",
                          stop_loss: float = None,
                          take_profit: float = None) -> dict:
        """
        side: BUY / SELL
        position_side: LONG / SHORT
        """
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         order_type,
            "quantity":     str(round(quantity, 4)),
        }

        data = await self._request("POST", "/openApi/swap/v2/trade/order", params, signed=True)
        order_id = data.get("data", {}).get("order", {}).get("orderId")

        # Place SL/TP as separate orders
        if order_id and stop_loss:
            await self._place_sl(symbol, side, position_side, quantity, stop_loss)
        if order_id and take_profit:
            await self._place_tp(symbol, side, position_side, quantity, take_profit)

        return data

    async def _place_sl(self, symbol, side, pos_side, qty, sl_price):
        close_side = "SELL" if side == "BUY" else "BUY"
        params = {
            "symbol":       symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     str(round(qty, 4)),
            "stopPrice":    str(round(sl_price, 6)),
            "closePosition": "true",
        }
        return await self._request("POST", "/openApi/swap/v2/trade/order", params, signed=True)

    async def _place_tp(self, symbol, side, pos_side, qty, tp_price):
        close_side = "SELL" if side == "BUY" else "BUY"
        params = {
            "symbol":        symbol,
            "side":          close_side,
            "positionSide":  pos_side,
            "type":          "TAKE_PROFIT_MARKET",
            "quantity":      str(round(qty, 4)),
            "stopPrice":     str(round(tp_price, 6)),
            "closePosition": "true",
        }
        return await self._request("POST", "/openApi/swap/v2/trade/order", params, signed=True)

    async def close_position(self, symbol: str, position_side: str, quantity: float) -> dict:
        side = "SELL" if position_side == "LONG" else "BUY"
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         "MARKET",
            "quantity":     str(round(quantity, 4)),
        }
        return await self._request("POST", "/openApi/swap/v2/trade/order", params, signed=True)

    async def set_leverage(self, symbol: str, leverage: int, side: str = "LONG") -> dict:
        params = {"symbol": symbol, "side": side, "leverage": leverage}
        return await self._request("POST", "/openApi/swap/v2/trade/leverage", params, signed=True)

    async def cancel_all_orders(self, symbol: str) -> dict:
        params = {"symbol": symbol}
        return await self._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", params, signed=True)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
