"""
bingx_trader.py - Ejecucion de ordenes reales en BingX Perpetual Swap
Con gestion de riesgo adaptativa y SL/TP automaticos.
"""

import hashlib
import hmac
import time
import requests
import logging
from urllib.parse import urlencode

log = logging.getLogger('bot27')


class BingXTrader:
    BASE = "https://open-api.bingx.com"
    EP_BALANCE    = "/openApi/swap/v2/user/balance"
    EP_ORDER      = "/openApi/swap/v2/trade/order"
    EP_POSITION   = "/openApi/swap/v2/user/positions"
    EP_LEVERAGE   = "/openApi/swap/v2/trade/leverage"
    EP_CANCEL_ALL = "/openApi/swap/v2/trade/allOpenOrders"

    def __init__(self, api_key: str, secret_key: str,
                 risk_pct: float = 2.0, leverage: int = 3,
                 dry_run: bool = False):
        self.api_key    = api_key
        self.secret_key = secret_key
        self.risk_pct   = risk_pct
        self.leverage   = leverage
        self.dry_run    = dry_run
        self.session    = requests.Session()
        self.session.headers.update({'X-BX-APIKEY': api_key})

    def _sign(self, params: dict) -> str:
        query = urlencode(sorted(params.items()))
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _p(self, params: dict) -> dict:
        params['timestamp'] = int(time.time() * 1000)
        params['signature'] = self._sign(params)
        return params

    def _get(self, ep: str, params: dict = None) -> dict:
        try:
            r = self.session.get(self.BASE + ep, params=self._p(params or {}), timeout=10)
            return r.json()
        except Exception as e:
            log.error(f"GET {ep}: {e}")
            return {}

    def _post(self, ep: str, params: dict = None) -> dict:
        try:
            r = self.session.post(self.BASE + ep, params=self._p(params or {}), timeout=10)
            return r.json()
        except Exception as e:
            log.error(f"POST {ep}: {e}")
            return {}

    def get_balance(self) -> float:
        data = self._get(self.EP_BALANCE, {'currency': 'USDT'})
        try:
            return float(data['data']['balance']['availableMargin'])
        except Exception:
            log.error(f"Balance error: {data}")
            return 0.0

    def set_leverage(self, symbol: str, side: str):
        self._post(self.EP_LEVERAGE, {
            'symbol': symbol, 'side': side,
            'leverage': str(self.leverage)
        })

    def calc_size(self, balance: float, price: float, sl: float) -> float:
        risk_usdt = balance * (self.risk_pct / 100)
        sl_pct    = max(abs(price - sl) / price, 0.005)
        size      = (risk_usdt / sl_pct) * self.leverage
        max_size  = balance * self.leverage * 0.15
        return round(max(min(size, max_size), 5.0), 2)

    def open_position(self, symbol: str, signal: int,
                      price: float, sl: float, tp: float) -> dict:
        if signal not in (1, -1):
            return {'success': False, 'reason': 'Signal invalida'}

        balance = self.get_balance()
        if balance < 10:
            return {'success': False, 'reason': f'Balance insuficiente: {balance:.2f}'}

        size      = self.calc_size(balance, price, sl)
        direction = 'LONG' if signal == 1 else 'SHORT'
        side      = 'BUY'  if signal == 1 else 'SELL'
        sl_side   = 'SELL' if signal == 1 else 'BUY'

        log.info(f"Abriendo {direction} {symbol} | size:{size} | sl:{sl:.6f} | tp:{tp:.6f}")

        if self.dry_run:
            return {'success': True, 'dry_run': True, 'symbol': symbol,
                    'direction': direction, 'size': size, 'price': price,
                    'sl': sl, 'tp': tp, 'balance': balance}

        self.set_leverage(symbol, direction)

        # Orden principal
        res = self._post(self.EP_ORDER, {
            'symbol': symbol, 'side': side, 'positionSide': direction,
            'type': 'MARKET', 'quantity': str(size),
        })
        if res.get('code') != 0:
            log.error(f"Orden fallida: {res}")
            return {'success': False, 'reason': str(res)}

        order_id = res.get('data', {}).get('order', {}).get('orderId', '')

        # Stop Loss
        self._post(self.EP_ORDER, {
            'symbol': symbol, 'side': sl_side, 'positionSide': direction,
            'type': 'STOP_MARKET', 'quantity': str(size),
            'stopPrice': str(round(sl, 8)), 'workingType': 'MARK_PRICE',
        })

        # Take Profit
        self._post(self.EP_ORDER, {
            'symbol': symbol, 'side': sl_side, 'positionSide': direction,
            'type': 'TAKE_PROFIT_MARKET', 'quantity': str(size),
            'stopPrice': str(round(tp, 8)), 'workingType': 'MARK_PRICE',
        })

        return {'success': True, 'order_id': order_id, 'symbol': symbol,
                'direction': direction, 'size': size, 'price': price,
                'sl': sl, 'tp': tp, 'balance': balance}

    def get_open_positions(self) -> list:
        data = self._get(self.EP_POSITION, {})
        try:
            return [p for p in data.get('data', {}).get('positions', [])
                    if float(p.get('positionAmt', 0)) != 0]
        except Exception:
            return []

    def has_open_position(self, symbol: str) -> bool:
        return any(p.get('symbol') == symbol for p in self.get_open_positions())
