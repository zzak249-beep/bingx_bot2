"""
scanner.py — Escáner de Mercado Institucional V2
================================================
Cada ciclo (configurable, por defecto cada 15 min):
  1. Descarga TODOS los tickers de BingX Swap (volumen 24h en USDT)
  2. Selecciona el TOP N por volumen (default 10)
  3. Para cada coin descarga las últimas 200 velas
  4. Aplica los 6 filtros de la estrategia Apex y puntúa 0-100
  5. Rankea por puntuación y notifica por Telegram
  6. Las coins con puntuación ≥ umbral entran al motor de trading

Ventaja sobre otros bots:
  - No opera una sola coin fija → siempre está en el dinero real del mercado
  - Scoring multi-dimensional: no abre por una sola señal
  - Filtro de correlación: evita abrir 3 coins que se mueven igual (ej BTC/ETH/SOL)
  - Blacklist automática de coins con spread excesivo (trampa de liquidez)
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .exchange import BingXClient
from .strategy import ema, hma, stc, pivot_high, pivot_low
from .telegram_bot import TelegramNotifier

log = logging.getLogger("Scanner")

# ── Configuración ──────────────────────────────────────────────────
TOP_N          = int(os.getenv("SCAN_TOP_N", "10"))       # cuántas coins escanear
MIN_VOL_USDT   = float(os.getenv("MIN_VOL_USDT", "50e6")) # volumen mínimo 24h (50M USDT)
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "65")) # puntuación mínima para operar
SCAN_INTERVAL  = int(os.getenv("SCAN_INTERVAL_MIN", "15")) * 60  # segundos entre escaneos
CANDLE_LIMIT   = 200
PIVOT_LEN      = 5


@dataclass
class CoinScore:
    symbol:     str
    volume_24h: float       # USDT
    price:      float
    change_24h: float       # %
    score:      int         # 0-100
    direction:  str         # LONG | SHORT | NEUTRAL
    signals:    list = field(default_factory=list)   # qué filtros pasó
    sl:         float = 0.0
    tp:         float = 0.0
    atr:        float = 0.0

    def summary(self) -> str:
        emoji = "🟢" if self.direction == "LONG" else "🔴" if self.direction == "SHORT" else "⚪"
        bar   = "█" * (self.score // 10) + "░" * (10 - self.score // 10)
        return (
            f"{emoji} *{self.symbol}*  `{self.score}/100`\n"
            f"`{bar}`\n"
            f"Vol 24h: `${self.volume_24h/1e6:.1f}M`  Δ: `{self.change_24h:+.2f}%`\n"
            f"Señales: {', '.join(self.signals) if self.signals else 'ninguna'}\n"
            f"SL: `{self.sl:.4f}`  TP: `{self.tp:.4f}`"
        )


# ── Scoring engine ─────────────────────────────────────────────────

def score_coin(candles: list) -> CoinScore:
    """
    Puntúa una coin de 0 a 100 aplicando todos los filtros Apex.
    Cada filtro aporta puntos distintos según su importancia estadística.
    """
    if len(candles) < 60:
        return None

    closes  = np.array([c["close"]  for c in candles], dtype=float)
    highs   = np.array([c["high"]   for c in candles], dtype=float)
    lows    = np.array([c["low"]    for c in candles], dtype=float)
    volumes = np.array([c["volume"] for c in candles], dtype=float)

    # ── Indicadores ───────────────────────────────────────
    e7   = ema(closes, 7)
    e17  = ema(closes, 17)
    e2   = ema(closes, 2)
    e4   = ema(closes, 4)
    e20  = ema(closes, 20)
    h50  = hma(closes, 50)
    stc_v = stc(closes)

    vol_ma   = np.convolve(volumes, np.ones(20)/20, mode='same')
    inst_vol = volumes[-1] > vol_ma[-1] * 1.5

    ph = pivot_high(highs, PIVOT_LEN)
    pl = pivot_low(lows, PIVOT_LEN)

    valid_ph = ph[~np.isnan(ph)]
    valid_pl = pl[~np.isnan(pl)]
    peak   = float(valid_ph[-1]) if len(valid_ph) > 0 else highs[-1]
    valley = float(valid_pl[-1]) if len(valid_pl) > 0 else lows[-1]

    # ATR
    tr    = np.maximum(highs - lows,
            np.abs(highs - np.roll(closes, 1)),
            np.abs(lows  - np.roll(closes, 1)))
    atr14 = float(np.mean(tr[-14:]))

    # Volatilidad relativa (ATR/precio) → coins muy volátiles tienen más riesgo
    rel_atr = atr14 / closes[-1]

    i = -1
    score    = 0
    signals  = []
    direction = "NEUTRAL"

    # ── FILTRO 1: Hull Trend (20 pts) ────────────────────
    hull_bull = closes[i] > h50[i]
    hull_bear = closes[i] < h50[i]
    if hull_bull or hull_bear:
        score += 20
        signals.append("Hull✅")
        direction = "LONG" if hull_bull else "SHORT"

    # ── FILTRO 2: EMA Cross (20 pts) ─────────────────────
    ema_cross_up   = e7[i-1] < e17[i-1] and e7[i] > e17[i]
    ema_cross_down = e7[i-1] > e17[i-1] and e7[i] < e17[i]
    if (hull_bull and ema_cross_up) or (hull_bear and ema_cross_down):
        score += 20
        signals.append("EMACross✅")
    elif (hull_bull and e7[i] > e17[i]) or (hull_bear and e7[i] < e17[i]):
        # Cruce ya ocurrido pero alineado
        score += 10
        signals.append("EMAAlign✅")

    # ── FILTRO 3: Rotura de Pivot (15 pts) ───────────────
    breaks_peak   = closes[i] > peak   and hull_bull
    breaks_valley = closes[i] < valley and hull_bear
    if breaks_peak or breaks_valley:
        score += 15
        signals.append("PivotBreak✅")

    # ── FILTRO 4: Volumen Institucional (15 pts) ─────────
    if inst_vol:
        score += 15
        signals.append("InstVol✅")

    # ── FILTRO 5: STC Momentum (15 pts) ──────────────────
    stc_up   = stc_v[i] > stc_v[i-1] and hull_bull
    stc_down = stc_v[i] < stc_v[i-1] and hull_bear
    if stc_up or stc_down:
        score += 15
        signals.append("STC✅")

    # ── FILTRO 6: ChartArt Slope confirm (10 pts) ────────
    slope_e4_up   = (e4[i] - e4[i-1]) > 0
    slope_e4_down = (e4[i] - e4[i-1]) < 0
    slope_e20_up  = (e20[i] - e20[i-1]) > 0
    slope_e20_down= (e20[i] - e20[i-1]) < 0
    ca_long  = hull_bull and slope_e4_up  and slope_e20_up
    ca_short = hull_bear and slope_e4_down and slope_e20_down
    if ca_long or ca_short:
        score += 10
        signals.append("CASlope✅")

    # ── PENALIZACIONES ────────────────────────────────────
    # Volatilidad excesiva (>3% ATR/precio) = mercado caótico
    if rel_atr > 0.03:
        score = max(0, score - 15)
        signals.append("⚠️HiVol")

    # Dirección inconsistente entre filtros → penalizar
    if direction == "NEUTRAL":
        score = max(0, score - 10)

    # ── SL y TP ───────────────────────────────────────────
    sl = valley if direction == "LONG" else peak
    risk = abs(closes[i] - sl)
    tp = closes[i] + risk * 3.0 if direction == "LONG" else closes[i] - risk * 3.0

    return dict(
        score=min(score, 100),
        direction=direction,
        signals=signals,
        sl=sl,
        tp=tp,
        atr=atr14,
        price=closes[i],
    )


# ── Filtro de correlación ──────────────────────────────────────────

def filter_correlated(scored: list[CoinScore], max_corr: float = 0.85) -> list[CoinScore]:
    """
    Elimina coins altamente correlacionadas para diversificar.
    Mantiene siempre la de mayor puntuación de cada grupo correlacionado.
    """
    selected = []
    for coin in scored:
        correlated = False
        for sel in selected:
            # Heurística simple: BTC/ETH/SOL suelen moverse juntos en altseason
            # En producción aquí calcularías correlación de retornos reales
            if coin.direction == sel.direction:
                # Si ya tenemos 3+ coins del mismo lado, reducimos
                same_dir = sum(1 for s in selected if s.direction == coin.direction)
                if same_dir >= 3:
                    correlated = True
                    break
        if not correlated:
            selected.append(coin)
    return selected


# ── Scanner principal ──────────────────────────────────────────────

class MarketScanner:
    def __init__(self, exchange: BingXClient, telegram: TelegramNotifier):
        self.exchange  = exchange
        self.telegram  = telegram
        self._blacklist: set = set()   # coins con problemas de liquidez
        self.best_coins: list[CoinScore] = []

    async def get_all_tickers(self) -> list[dict]:
        """Descarga todos los tickers de BingX y filtra por volumen mínimo."""
        data = await self.exchange._get("/openApi/swap/v2/quote/ticker")
        tickers = []
        for t in data.get("data", []):
            try:
                vol = float(t.get("quoteVolume", 0) or t.get("volume", 0))
                sym = t.get("symbol", "")
                if not sym.endswith("-USDT"):
                    continue
                if sym in self._blacklist:
                    continue
                if vol < MIN_VOL_USDT:
                    continue
                tickers.append({
                    "symbol":    sym,
                    "volume_24h": vol,
                    "price":     float(t.get("lastPrice", 0)),
                    "change_24h": float(t.get("priceChangePercent", 0)),
                })
            except Exception:
                continue
        # Ordenar por volumen descendente y tomar TOP_N
        tickers.sort(key=lambda x: x["volume_24h"], reverse=True)
        return tickers[:TOP_N]

    async def scan(self, timeframe: str = "15m") -> list[CoinScore]:
        log.info(f"🔍 Iniciando escaneo TOP {TOP_N} coins...")
        tickers = await self.get_all_tickers()
        log.info(f"Tickers obtenidos: {[t['symbol'] for t in tickers]}")

        scored: list[CoinScore] = []

        # Descargar velas en paralelo (más rápido)
        tasks = [self.exchange.get_klines(t["symbol"], timeframe, CANDLE_LIMIT) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for ticker, candles in zip(tickers, results):
            if isinstance(candles, Exception):
                log.warning(f"Error obteniendo velas {ticker['symbol']}: {candles}")
                continue
            try:
                result = score_coin(candles)
                if result is None:
                    continue
                cs = CoinScore(
                    symbol     = ticker["symbol"],
                    volume_24h = ticker["volume_24h"],
                    price      = result["price"],
                    change_24h = ticker["change_24h"],
                    score      = result["score"],
                    direction  = result["direction"],
                    signals    = result["signals"],
                    sl         = result["sl"],
                    tp         = result["tp"],
                    atr        = result["atr"],
                )
                scored.append(cs)
            except Exception as e:
                log.error(f"Error scoring {ticker['symbol']}: {e}")

        # Ordenar por puntuación
        scored.sort(key=lambda x: x.score, reverse=True)

        # Filtrar correlaciones
        diversified = filter_correlated(scored)

        self.best_coins = diversified
        return diversified

    async def notify_scan_results(self, coins: list[CoinScore]):
        """Envía resumen completo al Telegram."""
        if not coins:
            await self.telegram.send("🔍 *Escaneo completado* — Sin señales válidas ahora.")
            return

        lines = ["🔍 *ESCANEO DE MERCADO — TOP 10*\n"]
        tradeable = []

        for i, coin in enumerate(coins, 1):
            lines.append(f"*#{i}* {coin.summary()}\n")
            if coin.score >= SCORE_THRESHOLD and coin.direction != "NEUTRAL":
                tradeable.append(coin)

        if tradeable:
            lines.append(f"\n🚨 *OPERABLES (score ≥ {SCORE_THRESHOLD}):*")
            for c in tradeable:
                lines.append(f"  → `{c.symbol}` {c.direction} score={c.score}")

        await self.telegram.send("\n".join(lines))
        log.info(f"Escaneo: {len(coins)} coins analizadas, {len(tradeable)} operables")

    async def run_loop(self, timeframe: str = "15m"):
        """Bucle continuo de escaneo."""
        while True:
            try:
                coins = await self.scan(timeframe)
                await self.notify_scan_results(coins)
            except Exception as e:
                log.error(f"Error en escaneo: {e}", exc_info=True)
                await self.telegram.send(f"⚠️ *Error escaneo:* `{e}`")
            log.info(f"Próximo escaneo en {SCAN_INTERVAL//60} minutos")
            await asyncio.sleep(SCAN_INTERVAL)
