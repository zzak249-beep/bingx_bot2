import os, sys, time, hmac, hashlib, json
import numpy as np
import requests
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("Bot")

API_KEY    = os.getenv("BINGX_API_KEY", "")
API_SECRET = os.getenv("BINGX_SECRET_KEY", "")
BASE_URL   = "https://open-api.bingx.com"

def _request(method, path, params=None):
    p = params or {}
    p["timestamp"] = int(time.time() * 1000)
    query = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
    p["signature"] = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    try:
        url = f"{BASE_URL}{path}"
        r = requests.request(method, url, params=p, headers={"X-BX-APIKEY": API_KEY})
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def main():
    log.info("🚀 Bot iniciado correctamente...")
    while True:
        log.info("Escaneando mercado...")
        # Aquí va tu lógica de VWAP
        time.sleep(60)

if __name__ == "__main__":
    main()
