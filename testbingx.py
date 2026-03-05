#!/usr/bin/env python3
"""
test_bingx.py — Diagnóstico completo de BingX API
Sube al repo y verás el resultado en Railway > Logs
O ejecuta localmente:
  BINGX_API_KEY=xxx BINGX_API_SECRET=yyy python test_bingx.py
"""
import os, sys

print("\n" + "="*55)
print("  DIAGNÓSTICO BINGX API")
print("="*55)

KEY    = os.getenv("BINGX_API_KEY",    "")
SECRET = os.getenv("BINGX_API_SECRET", "")

print(f"\n  1. CREDENCIALES")
print(f"     API_KEY:    {'✅ ' + KEY[:8]+'...' if KEY    else '❌ VACÍO — añade en Railway > Variables'}")
print(f"     API_SECRET: {'✅ configurado' if SECRET else '❌ VACÍO — añade en Railway > Variables'}")

if not KEY or not SECRET:
    print("\n  ❌ Sin credenciales. No se puede continuar.")
    print("\n  SOLUCIÓN:")
    print("  Railway → tu proyecto → Variables → New Variable:")
    print("    BINGX_API_KEY    = (tu api key)")
    print("    BINGX_API_SECRET = (tu api secret)")
    print("    TRADE_MODE       = paper  (primero prueba, luego live)")
    sys.exit(1)

import bingx_api as api

print(f"\n  2. DIAGNÓSTICO COMPLETO")
result = api.diagnose()

if "error" in result:
    print(f"\n  ❌ ERROR DETECTADO:")
    for line in result["error"].split("\n"):
        print(f"     {line}")
    print(f"\n  Estado conexión: {result.get('connection', '?')}")
else:
    bal = result.get("balance_usdt", 0)
    print(f"     Conexión:   ✅ OK")
    print(f"     Balance:    ${bal:.2f} USDT")
    print(f"     Precio BTC: {result.get('price_test','?')}")
    if bal <= 0:
        print(f"\n  ⚠️  Balance $0 — el bot enviará señales pero no ejecutará órdenes")
        print(f"     Deposita USDT en tu cuenta BingX Perpetual Swap")
    else:
        print(f"\n  ✅ TODO CORRECTO — para activar trading real:")
        print(f"     Railway > Variables > TRADE_MODE = live")

print(f"\n  3. TEST DE PRECIO PÚBLICO (sin autenticación)")
import requests
try:
    for sym in ["BTC-USDT", "LINK-USDT", "RSR-USDT"]:
        r = requests.get(
            "https://open-api.bingx.com/openApi/swap/v2/quote/price",
            params={"symbol": sym}, timeout=8
        ).json()
        price = float((r.get("data") or {}).get("price", 0))
        print(f"     {sym:<20} ${price:.6g}")
except Exception as e:
    print(f"     ❌ {e}")

print(f"\n  4. INFO CONTRATO LINK-USDT")
try:
    info = api.get_contract_info("LINK-USDT")
    print(f"     stepSize:          {info['stepSize']}")
    print(f"     minQty:            {info['minQty']}")
    print(f"     pricePrecision:    {info['pricePrecision']}")
    print(f"     quantityPrecision: {info['quantityPrecision']}")
except Exception as e:
    print(f"     ❌ {e}")

print("="*55)
print("  Diagnóstico completado")
print("="*55 + "\n")
