"""
bingx_api_supertrend.py v2
- Descarga paralela con ThreadPoolExecutor (3x mas rapido)
- Rate limit handler (429 retry)
- Filtro de liquidez minima
"""
import requests
import time
import logging
import pandas as pd
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger('bot27')

MIN_VOLUME_USDT = 500_000   # Ignorar pares con < 500k USDT de volumen diario


class BingXAPI:
    BASE           = "https://open-api.bingx.com"
    SWAP_CONTRACTS = "/openApi/swap/v2/quote/contracts"
    SWAP_KLINES    = "/openApi/swap/v3/quote/klines"
    SWAP_TICKER    = "/openApi/swap/v2/quote/ticker"

    def __init__(self, timeout: int = 15, workers: int = 5):
        self.timeout = timeout
        self.workers = workers   # descargas paralelas
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})

    def _get(self, ep: str, params: dict = None, retries: int = 3) -> dict:
        url = self.BASE + ep
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    wait = 2 ** attempt
                    log.warning(f"Rate limit BingX, esperando {wait}s...")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                log.warning(f"Timeout {ep} (intento {attempt+1})")
            except Exception as e:
                log.warning(f"Error {ep}: {e}")
            time.sleep(0.5)
        return {}

    def get_swap_symbols(self) -> List[str]:
        log.info("Obteniendo simbolos SWAP...")
        data = self._get(self.SWAP_CONTRACTS)
        raw  = data.get('data', [])
        if isinstance(raw, list) and raw:
            syms = [s.get('symbol','') for s in raw if 'USDT' in s.get('symbol','')]
            if syms:
                log.info(f"Simbolos obtenidos: {len(syms)}")
                return syms
        log.warning("Usando lista de respaldo")
        return self._fallback()

    def filter_by_volume(self, symbols: List[str], min_volume: float = MIN_VOLUME_USDT) -> List[str]:
        """Filtra pares con poco volumen para evitar slippage."""
        log.info(f"Filtrando por volumen (min {min_volume/1e6:.1f}M USDT)...")
        data = self._get(self.SWAP_TICKER)
        if not data or 'data' not in data:
            return symbols
        tickers = {t.get('symbol'): t for t in data.get('data', [])}
        filtered = []
        for sym in symbols:
            t = tickers.get(sym, {})
            try:
                vol = float(t.get('quoteVolume', t.get('volume', 0)))
                if vol >= min_volume:
                    filtered.append(sym)
            except Exception:
                filtered.append(sym)  # sin datos = incluir igual
        log.info(f"Pares con suficiente liquidez: {len(filtered)}/{len(symbols)}")
        return filtered if filtered else symbols

    def _fallback(self) -> List[str]:
        return ["BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
                "ADA-USDT","AVAX-USDT","DOGE-USDT","DOT-USDT","LINK-USDT",
                "MATIC-USDT","UNI-USDT","ATOM-USDT","LTC-USDT","BCH-USDT",
                "FIL-USDT","APT-USDT","ARB-USDT","OP-USDT","SUI-USDT",
                "INJ-USDT","FET-USDT","PEPE-USDT","SHIB-USDT","WIF-USDT",
                "GRT-USDT","SAND-USDT","MANA-USDT","AXS-USDT","ENS-USDT",
                "LDO-USDT","AAVE-USDT","CRV-USDT","NEAR-USDT","RUNE-USDT",
                "IMX-USDT","GALA-USDT","GMT-USDT","FLOW-USDT","EGLD-USDT"]

    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> pd.DataFrame:
        data = self._get(self.SWAP_KLINES, {'symbol': symbol, 'interval': interval, 'limit': limit})
        if not data:
            return pd.DataFrame()
        raw = data.get('data', [])
        if isinstance(raw, dict):
            raw = raw.get('klines', [])
        if not raw:
            return pd.DataFrame()
        rows = []
        for k in raw:
            try:
                if isinstance(k, dict):
                    rows.append({'timestamp': pd.to_datetime(int(k.get('time', k.get('t',0))), unit='ms'),
                                 'open':float(k.get('open',k.get('o',0))), 'high':float(k.get('high',k.get('h',0))),
                                 'low':float(k.get('low',k.get('l',0))), 'close':float(k.get('close',k.get('c',0))),
                                 'volume':float(k.get('volume',k.get('v',0)))})
                elif isinstance(k, list) and len(k) >= 6:
                    rows.append({'timestamp':pd.to_datetime(int(k[0]),unit='ms'),
                                 'open':float(k[1]),'high':float(k[2]),'low':float(k[3]),
                                 'close':float(k[4]),'volume':float(k[5])})
            except Exception:
                continue
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values('timestamp').reset_index(drop=True)

    def get_market_data(self, symbols: List[str], interval: str = '1h',
                        limit: int = 100) -> Dict[str, pd.DataFrame]:
        """Descarga paralela con ThreadPool - mucho mas rapido que secuencial."""
        total  = len(symbols)
        result = {}
        log.info(f"Descargando {total} simbolos en paralelo [{interval}]...")

        def fetch(sym):
            df = self.get_klines(sym, interval, limit)
            time.sleep(0.05)  # mini delay para no saturar
            return sym, df

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(fetch, s): s for s in symbols}
            done = 0
            for fut in as_completed(futures):
                sym, df = fut.result()
                done += 1
                if not df.empty:
                    result[sym] = df
                    if done % 20 == 0:
                        print(f"  Descargados: {done}/{total} ({len(result)} OK)")

        log.info(f"Descargados: {len(result)}/{total}")
        return result
