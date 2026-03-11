"""
scanner_pares.py — Obtiene TODOS los pares de futuros perpetuos de BingX
Filtra por volumen mínimo para evitar pares sin liquidez.
"""

import requests, logging, time

log = logging.getLogger("scanner")

BASE_URL = "https://open-api.bingx.com"

# Volumen mínimo en USDT en las últimas 24h para considerar el par
VOLUMEN_MIN_24H = 500_000   # $500K mínimo

def get_todos_los_pares(volumen_min: float = VOLUMEN_MIN_24H) -> list:
    """
    Devuelve lista de símbolos con suficiente liquidez.
    Ejemplo: ["BTC-USDT", "ETH-USDT", ...]
    """
    try:
        # 1. Obtener todos los contratos disponibles
        res = requests.get(
            BASE_URL + "/openApi/swap/v2/quote/contracts",
            timeout=15,
        ).json()

        contratos = res.get("data", [])
        if not contratos:
            log.error("No se obtuvieron contratos de BingX")
            return _pares_fallback()

        simbolos = []
        for c in contratos:
            sym = c.get("symbol", "")
            # Solo pares USDT
            if not sym.endswith("-USDT"):
                continue
            # Solo contratos activos
            if c.get("status", 1) != 1:
                continue
            simbolos.append(sym)

        log.info(f"[SCANNER] {len(simbolos)} contratos USDT encontrados")

        # 2. Filtrar por volumen (tickers 24h)
        try:
            res2 = requests.get(
                BASE_URL + "/openApi/swap/v2/quote/ticker",
                timeout=20,
            ).json()

            tickers = res2.get("data", [])
            volumen_por_par = {}
            for t in tickers:
                sym = t.get("symbol", "")
                vol = float(t.get("quoteVolume", t.get("volume", 0)) or 0)
                volumen_por_par[sym] = vol

            # Filtrar por volumen mínimo
            pares_filtrados = [
                s for s in simbolos
                if volumen_por_par.get(s, 0) >= volumen_min
            ]

            # Ordenar por volumen descendente (más líquidos primero)
            pares_filtrados.sort(
                key=lambda s: volumen_por_par.get(s, 0),
                reverse=True
            )

            log.info(
                f"[SCANNER] {len(pares_filtrados)} pares con volumen ≥ "
                f"${volumen_min:,.0f} (de {len(simbolos)} totales)"
            )
            return pares_filtrados

        except Exception as e:
            log.warning(f"[SCANNER] No se pudo filtrar por volumen: {e} — usando todos")
            return simbolos

    except Exception as e:
        log.error(f"[SCANNER] Error obteniendo pares: {e}")
        return _pares_fallback()


def _pares_fallback() -> list:
    """Lista de respaldo si falla la API."""
    log.warning("[SCANNER] Usando lista de respaldo (100 pares)")
    return [
        "BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT",
        "DOGE-USDT","ADA-USDT","AVAX-USDT","LINK-USDT","DOT-USDT",
        "ARB-USDT","OP-USDT","NEAR-USDT","LTC-USDT","ATOM-USDT",
        "SUI-USDT","APT-USDT","INJ-USDT","TIA-USDT","MATIC-USDT",
        "TON-USDT","PEPE-USDT","WIF-USDT","BONK-USDT","JUP-USDT",
        "SEI-USDT","STRK-USDT","MANTA-USDT","ALT-USDT","PIXEL-USDT",
        "FTM-USDT","RUNE-USDT","AAVE-USDT","UNI-USDT","CRV-USDT",
        "MKR-USDT","SNX-USDT","COMP-USDT","1INCH-USDT","LDO-USDT",
        "BLUR-USDT","IMX-USDT","RNDR-USDT","FIL-USDT","AR-USDT",
        "ICP-USDT","FLOW-USDT","THETA-USDT","VET-USDT","EOS-USDT",
        "XLM-USDT","ALGO-USDT","HBAR-USDT","EGLD-USDT","XTZ-USDT",
        "SAND-USDT","MANA-USDT","AXS-USDT","GALA-USDT","ENJ-USDT",
        "CHZ-USDT","ROSE-USDT","ZIL-USDT","ONE-USDT","KAVA-USDT",
        "CELO-USDT","QTUM-USDT","ZEC-USDT","DASH-USDT","XMR-USDT",
        "ETC-USDT","BCH-USDT","BSV-USDT","NEO-USDT","WAVES-USDT",
        "IOTA-USDT","ZRX-USDT","BAT-USDT","KNC-USDT","STORJ-USDT",
        "ANKR-USDT","HOT-USDT","SC-USDT","DGB-USDT","RVN-USDT",
        "WOO-USDT","MAGIC-USDT","GMX-USDT","DYDX-USDT","PERP-USDT",
        "BERA-USDT","PI-USDT","GRASS-USDT","KAITO-USDT","ONDO-USDT",
        "POPCAT-USDT","PNUT-USDT","GOAT-USDT","MOODENG-USDT","ACT-USDT",
    ]


# Cache para no llamar la API en cada ciclo
_cache_pares = []
_cache_ts    = 0
_CACHE_TTL   = 3600  # refrescar cada hora

def get_pares_cached(volumen_min: float = VOLUMEN_MIN_24H) -> list:
    global _cache_pares, _cache_ts
    if time.time() - _cache_ts > _CACHE_TTL or not _cache_pares:
        _cache_pares = get_todos_los_pares(volumen_min)
        _cache_ts    = time.time()
        log.info(f"[SCANNER] Cache actualizada: {len(_cache_pares)} pares")
    return _cache_pares
