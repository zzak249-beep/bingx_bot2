import os, sys, time, traceback, hmac, hashlib, json
import numpy as np
import requests
from datetime import datetime
from dotenv import load_dotenv
import logging

# Configuración de Logs
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("AggressiveBot")

# --- CONFIGURACIÓN ---
API_KEY    = os.getenv("BINGX_API_KEY", "")
API_SECRET = os.getenv("BINGX_SECRET_KEY", "")
TG_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT    = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL   = "https://open-api.bingx.com"

# --- PARÁMETROS AGRESIVOS ---
MODO_DEMO      = os.getenv("MODO_DEMO", "false").lower() == "true"
LEVERAGE       = int(os.getenv("LEVERAGE", "10"))
MARGEN_USDT    = float(os.getenv("MARGEN_USDT", "15")) # Más capital por trade
MAX_POS        = int(os.getenv("MAX_POS", "5"))        # Más trades abiertos
LOOP_SECONDS   = 30 # Escaneo más rápido (cada 30s)

# --- ESTRATEGIA SENSITIVA ---
VWAP_STD_ENTRY = 1.5  # Entrada más agresiva que 2.0
EMA_PERIODO    = 9
ATR_PERIODO    = 14
SL_ATR_MULT    = 1.2  # Stop más ajustado
TP1_ATR_MULT   = 1.2  # TP rápido para asegurar
TP2_ATR_MULT   = 4.5  # Dejar correr el resto al máximo
TRAIL_DIST     = 0.8  # Trailing muy pegado al precio

def _sign(params):
    query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def _request(method, path, params=None):
    p = params or {}
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(p)
    headers = {"X-BX-APIKEY": API_KEY}
    try:
        r = requests.request(method, f"{BASE_URL}{path}", params=p, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"Error API: {e}")
        return {}

def get_klines(symbol):
    params = {"symbol": symbol, "interval": "15m", "limit": 50}
    res = _request("GET", "/openApi/swap/v3/quote/klines", params)
    return res.get("data", [])

def get_indicators(klines):
    # klines: [time, open, high, low, close, vol...]
    c = np.array([float(k[4]) for k in klines])
    h = np.array([float(k[2]) for k in klines])
    l = np.array([float(k[3]) for k in klines])
    v = np.array([float(k[5]) for k in klines])
    
    # VWAP con Bandas
    tp = (h + l + c) / 3
    vwap = np.sum(tp[-20:] * v[-20:]) / np.sum(v[-20:])
    std = np.std(tp[-20:])
    
    # EMA 9 (Filtro de impulso)
    ema = c[-1] * (2/10) + (c[-2] * (1 - 2/10))
    
    # ATR
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.mean(tr[-ATR_PERIODO:])
    
    return {
        "price": c[-1], "vwap": vwap, "std": std, "ema": ema, "atr": atr,
        "lower": vwap - (VWAP_STD_ENTRY * std),
        "upper": vwap + (VWAP_STD_ENTRY * std)
    }

def main():
    log.info(f"🔥 Bot AGRESIVO iniciado (Leverage {LEVERAGE}x)")
    pares = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "AVAX-USDT", "LINK-USDT", "NEAR-USDT"]
    
    while True:
        for par in pares:
            try:
                data = get_klines(par)
                if not data: continue
                ind = get_indicators(data)
                
                # Lógica de entrada agresiva
                # LONG si precio < banda inferior y EMA9 confirma rebote
                if ind["price"] <= ind["lower"] and ind["price"] > ind["ema"]:
                    log.info(f"🚀 SEÑAL LONG AGRESIVA: {par} a {ind['price']}")
                    # Aquí iría la función de abrir_orden()
                
                # SHORT si precio > banda superior y EMA9 confirma caída
                elif ind["price"] >= ind["upper"] and ind["price"] < ind["ema"]:
                    log.info(f"📉 SEÑAL SHORT AGRESIVA: {par} a {ind['price']}")
                    # Aquí iría la función de abrir_orden()
                    
            except Exception as e:
                log.error(f"Error procesando {par}: {e}")
        
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main()
