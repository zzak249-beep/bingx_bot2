"""
BingX Perpetual Futures API v2 — Compatible con Hedge Mode
"""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode
from typing import Optional
import aiohttp

logger = logging.getLogger("bingx")

class BingXClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://open-api.bingx.com"):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = base_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self.session = aiohttp.ClientSession(
            headers={"X-BX-APIKEY": self.api_key},
            timeout=aiohttp.ClientTimeout(total=15),
        )

    async def close(self):
        if self.session:
            await self.session.close()

    def _sign(self, params: dict) -> str:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(sorted(params.items()))
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return query + f"&signature={sig}"

    async def _get(self, path: str, params: dict = None, signed=False) -> dict:
        params = params or {}
        if signed:
            url = f"{self.base_url}{path}?{self._sign(params)}"
        else:
            url = f"{self.base_url}{path}" + (f"?{urlencode(params)}" if params else "")
        async with self.session.get(url) as r:
            data = await r.json()
            self._raise(data)
            return data

    async def _post(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}?{self._sign(params)}"
        async with self.session.post(url) as r:
            data = await r.json()
            self._raise(data)
            return data

    async def _delete(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}?{self._sign(params)}"
        async with self.session.delete(url) as r:
            data = await r.json()
            self._raise(data)
            return data

    def _raise(self, data: dict):
        if data.get("code", 0) != 0:
            raise RuntimeError(f"BingX API {data.get('code')}: {data.get('msg')}")

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        data = await self._get("/openApi/swap/v3/quote/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        candles = []
        for c in data.get("data", []):
            candles.append({
                "ts":    int(c["time"]),
                "open":  float(c["open"]),
                "high":  float(c["high"]),
                "low":   float(c["low"]),
                "close": float(c["close"]),
                "vol":   float(c["volume"]),
            })
        return candles

    async def get_ticker(self, symbol: str) -> float:
        data = await self._get("/openApi/swap/v2/quote/price", {"symbol": symbol})
        return float(data["data"]["price"])

    async def get_balance(self) -> float:
        data = await self._get("/openApi/swap/v2/user/balance", {}, signed=True)
        for asset in data.get("data", {}).get("balance", []):
            if asset.get("asset") == "USDT":
                return float(asset.get("availableMargin", 0))
        return 0.0

    async def set_leverage(self, symbol: str, leverage: int, side: str = "LONG"):
        # En Hedge Mode hay que setear LONG y SHORT por separado
        for s in ["LONG", "SHORT"]:
            try:
                await self._post("/openApi/swap/v2/trade/leverage", {
                    "symbol": symbol, "side": s, "leverage": leverage
                })
            except Exception as e:
                logger.warning(f"set_leverage {s}: {e}")

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED"):
        try:
            await self._post("/openApi/swap/v2/trade/marginType", {
                "symbol": symbol, "marginType": margin_type
            })
        except Exception:
            pass  # Ya configurado — ignorar

    async def place_market_order(self, symbol: str, side: str, quantity: float, position_side: str = "LONG") -> dict:
        """
        Hedge Mode: NUNCA enviar reduceOnly.
        side: BUY | SELL
        position_side: LONG | SHORT
        """
        params = {
            "symbol":       symbol,
            "side":         side,
            "type":         "MARKET",
            "quantity":     round(quantity, 4),
            "positionSide": position_side,
            # NO incluir reduceOnly — causa error 109400 en Hedge Mode
        }
        data = await self._post("/openApi/swap/v2/trade/order", params)
        return data.get("data", {})

    async def close_position(self, symbol: str, position_side: str, quantity: float) -> dict:
        """
        Cierre correcto en Hedge Mode:
        LONG abierto  → cerrar con SELL + positionSide=LONG
        SHORT abierto → cerrar con BUY  + positionSide=SHORT
        """
        close_side = "SELL" if position_side == "LONG" else "BUY"
        params = {
            "symbol":       symbol,
            "side":         close_side,
            "type":         "MARKET",
            "quantity":     round(quantity, 4),
            "positionSide": position_side,
            # SIN reduceOnly — Hedge Mode no lo acepta
        }
        data = await self._post("/openApi/swap/v2/trade/order", params)
        return data.get("data", {})

    async def get_positions(self, symbol: str = None) -> list:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._get("/openApi/swap/v2/user/positions", params, signed=True)
        return data.get("data", [])

    async def cancel_all_orders(self, symbol: str):
        try:
            await self._delete("/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
        except Exception:
            pass

    async def get_symbol_info(self, symbol: str) -> dict:
        data = await self._get("/openApi/swap/v2/quote/contracts")
        for s in data.get("data", []):
            if s.get("symbol") == symbol:
                return s
        return {}
