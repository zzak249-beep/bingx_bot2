#!/usr/bin/env python3
"""
test_bingx.py — Diagnóstico de firma BingX
Añade este archivo al repo, Railway lo ejecutará y verás el resultado en Logs.
"""
import os, sys

print("\n" + "="*52)
print("  TEST FIRMA BINGX")
print("="*52)

key    = os.getenv("BINGX_API_KEY", "")
secret = os.getenv("BINGX_API_SECRET", "")

print(f"\n  API_KEY:    {'✅ ' + key[:8]+'...' if key else '❌ VACÍO'}")
print(f"  API_SECRET: {'✅ configurado' if secret else '❌ VACÍO'}")

if not key or not secret:
    print("\n  ❌ Añade las variables en Railway → Variables")
    sys.exit(1)

import bingx_api as api
result = api.test_signature()

print("\n  Resultado completo:", result)
print("="*52 + "\n")
