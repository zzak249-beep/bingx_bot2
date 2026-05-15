"""
test_bingx.py — Prueba directa de la API BingX
Ejecutar en Railway como: python test_bingx.py
Muestra EXACTAMENTE qué devuelve BingX en cada paso.
"""
import asyncio, hashlib, hmac, os, time, urllib.parse
import httpx

API_KEY    = os.environ["BINGX_API_KEY"]
API_SECRET = os.environ["BINGX_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
BASE = "https://open-api.bingx.com"

def sign(params):
    q = urllib.parse.urlencode(sorted(params.items()))
    return hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

def headers():
    return {"X-BX-APIKEY": API_KEY, "Content-Type": "application/json"}

async def tg(text):
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000], "parse_mode": "Markdown"})

async def api_get(path, params=None):
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = sign(p)
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as c:
        r = await c.get(path, params=p, headers=headers())
        return r.status_code, r.json()

async def api_post(path, params):
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = sign(p)
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as c:
        r = await c.post(path, params=p, headers=headers())
        return r.status_code, r.json()

async def main():
    results = ["🔬 *TEST DIRECTO BINGX*\n━━━━━━━━━━━━━━━━━━━━\n"]

    # 1. Balance
    print("Testing balance...")
    code, d = await api_get("/openApi/swap/v2/user/balance")
    results.append(f"*1. Balance* HTTP={code} code={d.get('code')}")
    results.append(f"`{str(d.get('data',''))[:300]}`\n")

    # 2. Posicion mode (detectar si es one-way o hedge)
    print("Testing position mode...")
    code, d = await api_get("/openApi/swap/v2/trade/positionMode")
    results.append(f"*2. PositionMode* HTTP={code} code={d.get('code')}")
    results.append(f"`{str(d)[:300]}`\n")

    # 3. Precio BTC actual
    print("Getting BTC price...")
    code, d = await api_get("/openApi/swap/v2/quote/price", {"symbol": "BTC-USDT"})
    btc_price = 0
    if d.get("code") == 0:
        btc_price = float(d.get("data", {}).get("price", 0))
    results.append(f"*3. BTC precio:* `{btc_price:.2f}`\n")

    # 4. Test leverage
    print("Testing leverage...")
    code, d = await api_post("/openApi/swap/v2/trade/leverage",
                              {"symbol": "BTC-USDT", "side": "LONG", "leverage": "2"})
    results.append(f"*4. Leverage* HTTP={code} code={d.get('code')} msg={d.get('msg','')[:100]}")
    results.append(f"`{str(d)[:200]}`\n")

    # 5. Test orden MÍNIMA con ONE-WAY (positionSide=BOTH)
    # IMPORTANTE: qty mínima BTC = 0.001
    if btc_price > 0:
        sl = round(btc_price * 0.99, 2)
        tp = round(btc_price * 1.025, 2)
        print(f"Testing order BTC price={btc_price} sl={sl} tp={tp}...")
        code, d = await api_post("/openApi/swap/v2/trade/order", {
            "symbol":       "BTC-USDT",
            "side":         "BUY",
            "positionSide": "BOTH",
            "type":         "MARKET",
            "quantity":     "0.001",
            "stopLoss":     str(sl),
            "takeProfit":   str(tp),
        })
        results.append(f"*5. Orden BUY BOTH* HTTP={code} code={d.get('code')}")
        results.append(f"msg=`{d.get('msg','ok')}`")
        results.append(f"`{str(d)[:300]}`\n")

        if d.get("code") != 0:
            # Intentar SIN SL/TP por si ese es el problema
            print("Retrying without SL/TP...")
            code2, d2 = await api_post("/openApi/swap/v2/trade/order", {
                "symbol":       "BTC-USDT",
                "side":         "BUY",
                "positionSide": "BOTH",
                "type":         "MARKET",
                "quantity":     "0.001",
            })
            results.append(f"*5b. Sin SL/TP* HTTP={code2} code={d2.get('code')}")
            results.append(f"msg=`{d2.get('msg','ok')}`\n")

            if d2.get("code") == 0:
                results.append("✅ *FUNCIONA SIN SL/TP* — el problema es el formato de SL/TP")
                # Cerrar la posición abierta
                await asyncio.sleep(2)
                code3, d3 = await api_post("/openApi/swap/v2/trade/order", {
                    "symbol":       "BTC-USDT",
                    "side":         "SELL",
                    "positionSide": "BOTH",
                    "type":         "MARKET",
                    "quantity":     "0.001",
                    "reduceOnly":   "true",
                })
                results.append(f"*Cierre test:* code={d3.get('code')} msg={d3.get('msg','')}")
            else:
                results.append(f"❌ *Falla también sin SL/TP* — problema de permisos API o balance")
    else:
        results.append("❌ No se pudo obtener precio BTC")

    # 6. Verificar permisos API
    print("Checking API permissions...")
    code, d = await api_get("/openApi/swap/v2/user/income/assetList")
    results.append(f"\n*6. Permisos API* HTTP={code} code={d.get('code')}")

    await tg("\n".join(results))
    print("Test completo — revisa Telegram")

asyncio.run(main())
