"""
scanner_pares.py — Obtiene todos los pares de BingX perpetuos
Filtra por volumen mínimo para evitar pares sin liquidez.
Cache de 1 hora para no saturar la API.
"""

import requests, logging, time
try:
    import memoria as _memoria
except ImportError:
    _memoria = None

log      = logging.getLogger("scanner")
BASE_URL = "https://open-api.bingx.com"

VOLUMEN_MIN_24H = 500_000  # $500K mínimo


def get_todos_los_pares(volumen_min: float = VOLUMEN_MIN_24H) -> list:
    """
    Devuelve lista de símbolos con suficiente liquidez, ordenados por volumen.
    """
    try:
        res = requests.get(
            BASE_URL + "/openApi/swap/v2/quote/contracts",
            timeout=15,
        ).json()

        contratos = res.get("data", [])
        if not contratos:
            log.error("No se obtuvieron contratos de BingX")
            return _pares_fallback()

        simbolos = [
            c["symbol"] for c in contratos
            if c.get("symbol", "").endswith("-USDT")
            and c.get("status", 1) == 1
        ]

        log.info(f"[SCANNER] {len(simbolos)} contratos USDT activos encontrados")

        # Filtrar por volumen
        try:
            res2    = requests.get(
                BASE_URL + "/openApi/swap/v2/quote/ticker",
                timeout=20,
            ).json()
            tickers = res2.get("data", [])

            volumen_por_par = {
                t.get("symbol", ""): float(
                    t.get("quoteVolume", t.get("volume", 0)) or 0
                )
                for t in tickers
            }

            pares_filtrados = [
                s for s in simbolos
                if volumen_por_par.get(s, 0) >= volumen_min
            ]
            pares_filtrados.sort(
                key=lambda s: volumen_por_par.get(s, 0),
                reverse=True,
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
    log.warning("[SCANNER] Usando lista de respaldo (100 pares)")
    return [
        "BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT",
        "DOGE-USDT","ADA-USDT","AVAX-USDT","LINK-USDT","DOT-USDT",
        "ARB-USDT","OP-USDT","NEAR-USDT","LTC-USDT","ATOM-USDT",
        "SUI-USDT","APT-USDT","INJ-USDT","TIA-USDT","MATIC-USDT",
        "TON-USDT","PEPE-USDT","WIF-USDT","BONK-USDT","JUP-USDT",
        "SEI-USDT","FTM-USDT","RUNE-USDT","AAVE-USDT","UNI-USDT",
        "CRV-USDT","MKR-USDT","SNX-USDT","COMP-USDT","1INCH-USDT",
        "LDO-USDT","BLUR-USDT","IMX-USDT","RNDR-USDT","FIL-USDT",
        "AR-USDT","ICP-USDT","FLOW-USDT","THETA-USDT","VET-USDT",
        "EOS-USDT","XLM-USDT","ALGO-USDT","HBAR-USDT","EGLD-USDT",
        "SAND-USDT","MANA-USDT","AXS-USDT","GALA-USDT","ENJ-USDT",
        "CHZ-USDT","ROSE-USDT","ZIL-USDT","ONE-USDT","KAVA-USDT",
        "ETC-USDT","BCH-USDT","NEO-USDT","WAVES-USDT","IOTA-USDT",
        "ZRX-USDT","BAT-USDT","ANKR-USDT","WOO-USDT","MAGIC-USDT",
        "GMX-USDT","DYDX-USDT","BERA-USDT","ONDO-USDT","POPCAT-USDT",
        "PNUT-USDT","GOAT-USDT","MOODENG-USDT","ACT-USDT","PI-USDT",
        "GRASS-USDT","KAITO-USDT","ZEC-USDT","XMR-USDT","DASH-USDT",
    ]


# ── Cache ─────────────────────────────────────────────────────

_cache_pares = []
_cache_ts    = 0
_CACHE_TTL   = 3600  # 1 hora


def get_pares_cached(volumen_min: float = VOLUMEN_MIN_24H) -> list:
    global _cache_pares, _cache_ts
    if time.time() - _cache_ts > _CACHE_TTL or not _cache_pares:
        _cache_pares = get_todos_los_pares(volumen_min)
        _cache_ts    = time.time()
        log.info(f"[SCANNER] Cache actualizada: {len(_cache_pares)} pares")
        # Filtrar pares eliminados por aprendizaje (memoria)
    if _memoria:
        _cache_pares = _memoria.filtrar_pares(_cache_pares)

    # Filtrar pares que fallaron en API (exchange)
    try:
        import exchange as _ex
        ns = _ex.get_pares_no_soportados()
        if ns:
            antes = len(_cache_pares)
            _cache_pares = [p for p in _cache_pares if p not in ns]
            log.debug(f"[SCANNER] {antes - len(_cache_pares)} pares bloqueados por API eliminados")
    except Exception:
        pass

    return _cache_pares
