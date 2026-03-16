"""
scanner_smc.py — Escáner COMPLETO de pares BingX Perpetual Futures
===================================================================
Obtiene TODOS los pares -USDT disponibles, sin filtro de volumen mínimo.
Ordena por volumen 24h descendente para priorizar los más líquidos.
Cache de 30 minutos (antes 1h) para refrescar más seguido.
"""
import logging
import time
import requests

log = logging.getLogger("scanner_smc")

_cache: dict  = {"pares": [], "ts": 0, "todos": []}
_CACHE_TTL    = 1800   # 30 minutos
_blocked: set = set()  # pares que devuelven 0 velas consistentemente


# ──────────────────────────────────────────────────────────────
# API PÚBLICA
# ──────────────────────────────────────────────────────────────

def _get_ticker_bingx() -> list:
    """Obtiene todos los tickers de BingX swap perpetuos."""
    try:
        r = requests.get(
            "https://open-api.bingx.com/openApi/swap/v2/quote/ticker",
            timeout=20,
        )
        if r.status_code != 200:
            log.error(f"[SCAN] ticker HTTP {r.status_code}")
            return []
        data = r.json().get("data", []) or []
        log.debug(f"[SCAN] ticker raw: {len(data)} entradas")
        return data
    except Exception as e:
        log.error(f"[SCAN] ticker error: {e}")
        return []


# ──────────────────────────────────────────────────────────────
# OBTENER TODOS LOS PARES
# ──────────────────────────────────────────────────────────────

def get_todos_los_pares() -> list:
    """
    Retorna TODOS los pares -USDT de BingX Perpetual Futures
    ordenados por volumen 24h descendente.
    Sin filtro de volumen mínimo.
    """
    if time.time() - _cache["ts"] < _CACHE_TTL and _cache["todos"]:
        return _cache["todos"]

    data = _get_ticker_bingx()
    if not data:
        log.warning("[SCAN] API falló — usando fallback")
        return _fallback()

    # Construir lista con volumen
    pares_vol = []
    for t in data:
        sym = t.get("symbol", "")
        if not sym.endswith("-USDT"):
            continue
        if sym in _blocked:
            continue
        try:
            vol = float(t.get("quoteVolume", 0) or 0)
        except (ValueError, TypeError):
            vol = 0.0
        pares_vol.append((sym, vol))

    # Ordenar por volumen descendente
    pares_vol.sort(key=lambda x: x[1], reverse=True)
    pares = [p for p, _ in pares_vol]

    if pares:
        _cache["todos"] = pares
        _cache["ts"]    = time.time()
        log.info(f"[SCAN] {len(pares)} pares USDT totales (sin filtro de vol)")
    else:
        pares = _fallback()

    return pares


def get_pares_cached(vol_min_24h: float = 0) -> list:
    """
    Compatibilidad con el código existente.
    vol_min_24h se ignora — se devuelven TODOS los pares.
    """
    return get_todos_los_pares()


def bloquear_par_sin_velas(par: str):
    """Registra un par que devuelve 0 velas para excluirlo del scan."""
    _blocked.add(par)
    # Invalidar cache para que se reconstruya sin este par
    _cache["ts"] = 0
    log.info(f"[SCAN] {par} excluido del scan (sin velas en BingX 1m)")


def get_stats() -> dict:
    """Estadísticas del scanner para logging."""
    return {
        "total":    len(_cache.get("todos", [])),
        "bloqueados": len(_blocked),
        "cache_age": int(time.time() - _cache.get("ts", 0)),
    }


# ──────────────────────────────────────────────────────────────
# FALLBACK
# ──────────────────────────────────────────────────────────────

def _fallback() -> list:
    """
    Lista amplia de pares conocidos en BingX Perpetual Futures.
    Se usa cuando la API falla completamente.
    Ordenados aproximadamente por liquidez.
    """
    return [
        # Tier 1 — máxima liquidez
        "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
        "DOGE-USDT", "AVAX-USDT", "LINK-USDT", "MATIC-USDT", "DOT-USDT",
        # Tier 2 — alta liquidez
        "ARB-USDT", "OP-USDT", "NEAR-USDT", "APT-USDT", "SUI-USDT",
        "INJ-USDT", "TIA-USDT", "ATOM-USDT", "LTC-USDT", "BCH-USDT",
        "FIL-USDT", "RUNE-USDT", "ICP-USDT", "ETC-USDT", "CRV-USDT",
        "EGLD-USDT", "FTM-USDT", "ALGO-USDT", "VET-USDT", "SAND-USDT",
        # Tier 3 — media liquidez
        "MANA-USDT", "AXS-USDT", "CHZ-USDT", "ENJ-USDT", "1INCH-USDT",
        "SNX-USDT", "BAT-USDT", "ZIL-USDT", "STORJ-USDT", "LRC-USDT",
        "ANKR-USDT", "CELR-USDT", "COTI-USDT", "BAND-USDT", "WLD-USDT",
        "MINA-USDT", "FLOW-USDT", "ROSE-USDT", "KSM-USDT", "SKL-USDT",
        # Tier 4 — nuevos / meme
        "PEPE-USDT", "FLOKI-USDT", "BONK-USDT", "WIF-USDT", "SHIB-USDT",
        "BLUR-USDT", "GMX-USDT", "PENDLE-USDT", "JTO-USDT", "PYTH-USDT",
        "JUP-USDT", "RNDR-USDT", "SEI-USDT", "ORDI-USDT", "STX-USDT",
        "MEME-USDT", "CYBER-USDT", "ACE-USDT", "PIXEL-USDT", "ALT-USDT",
    ]
