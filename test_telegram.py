#!/usr/bin/env python3
"""
test_telegram.py — Diagnóstico de Telegram
Ejecuta esto en Railway desde Logs > Run Command:
  python test_telegram.py
O localmente:
  TELEGRAM_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python test_telegram.py
"""
import os, requests, sys

print("=" * 50)
print("  DIAGNÓSTICO TELEGRAM")
print("=" * 50)

TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print(f"  TELEGRAM_TOKEN:   {'✅ configurado (' + TOKEN[:10] + '...)' if TOKEN else '❌ VACÍO'}")
print(f"  TELEGRAM_CHAT_ID: {'✅ configurado (' + CHAT_ID + ')' if CHAT_ID else '❌ VACÍO'}")

if not TOKEN:
    print("\n  ❌ FALTA TELEGRAM_TOKEN")
    print("  → Railway > tu proyecto > Settings > Variables")
    print("  → Añade: TELEGRAM_TOKEN = <token de @BotFather>")
    sys.exit(1)

if not CHAT_ID:
    print("\n  ❌ FALTA TELEGRAM_CHAT_ID")
    print("  → Obtener chat_id: envía /start a tu bot, luego visita:")
    print(f"  → https://api.telegram.org/bot{TOKEN[:20]}...../getUpdates")
    sys.exit(1)

# Test getMe
print("\n  Probando token con getMe...")
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
if r.status_code == 200 and r.json().get("ok"):
    bot_name = r.json()["result"].get("username","?")
    print(f"  ✅ Bot válido: @{bot_name}")
else:
    print(f"  ❌ Token inválido: {r.text[:200]}")
    sys.exit(1)

# Test sendMessage
print(f"\n  Enviando mensaje de prueba al chat {CHAT_ID}...")
r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={
    "chat_id": CHAT_ID,
    "text": "✅ TEST OK — Bot BB+RSI Elite conectado correctamente!\n"
            "Si ves este mensaje, Telegram funciona.",
}, timeout=10)

data = r.json()
if data.get("ok"):
    print("  ✅ MENSAJE ENVIADO — revisa tu Telegram ahora")
else:
    print(f"  ❌ Error enviando: {data}")
    print("\n  Causas comunes:")
    print("  1. CHAT_ID incorrecto (debe ser número negativo para grupos)")
    print("  2. Nunca enviaste /start al bot")
    print(f"  → Envía /start a @{bot_name} y vuelve a ejecutar")

print("=" * 50)
