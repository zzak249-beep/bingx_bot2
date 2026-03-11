"""
config_pares.py — Lista de pares prioritarios a monitorear
Formato BingX perpetuos: "XXX-USDT"
Estos pares siempre se escanean primero (independientemente del scanner dinámico).
"""

PARES = [
    # ── Majors ─────────────────────────────
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "BNB-USDT",
    "XRP-USDT",

    # ── DeFi / L2 ──────────────────────────
    "ARB-USDT",
    "OP-USDT",
    "LINK-USDT",
    "AVAX-USDT",
    "DOT-USDT",
    "NEAR-USDT",
    "ATOM-USDT",
    "SUI-USDT",
    "APT-USDT",
    "INJ-USDT",
    "TIA-USDT",

    # ── Alto volumen en BingX ───────────────
    "DOGE-USDT",
    "LTC-USDT",
    "ADA-USDT",
    "TON-USDT",
    "PEPE-USDT",
    "WIF-USDT",
]
