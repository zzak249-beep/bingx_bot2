"""
GUA Bot v2 — Notificador Telegram (Multi-Par)
"""

from __future__ import annotations
import logging
from typing import Optional
import aiohttp
import config
from strategy import Signal

log = logging.getLogger("notifier")
_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
_MTAG = "🔴 LIVE" if config.MODE == "LIVE" else "🟡 SIGNAL"


class Notifier:

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _send(self, text: str) -> None:
        if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
            return
        try:
            s = await self._sess()
            async with s.post(_BASE, json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text, "parse_mode": "Markdown",
            }) as r:
                if r.status != 200:
                    log.error("Telegram %d: %s", r.status, await r.text())
        except Exception as e:
            log.error("Telegram: %s", e)

    async def send_signal(self, sig: Signal) -> None:
        em   = "📈" if sig.direction == "LONG" else "📉"
        bar  = "█" * int(sig.score*10) + "░" * (10 - int(sig.score*10))
        smcs = _smc(sig)
        vol  = "🌋 Alta" if sig.atr_pct >= 75 else ("🌊 Normal" if sig.atr_pct >= 40 else "😴 Baja")
        text = (
            f"{em} *{sig.symbol} {sig.direction}* {_MTAG}\n"
            f"────────────────────\n"
            f"📌 Precio: `{sig.price:.5f}`\n"
            f"🛡 SL:     `{sig.sl:.5f}`\n"
            f"🎯 TP1:    `{sig.tp1:.5f}`\n"
            f"🏆 TP2:    `{sig.tp2:.5f}`\n"
            f"────────────────────\n"
            f"📊 RSI: `{sig.rsi:.1f}` | ADX: `{sig.adx:.1f}`\n"
            f"📣 RVOL: `{sig.rvol:.2f}x` | {vol} (ATR `{sig.atr_pct:.0f}`)\n"
            f"💰 Funding: `{sig.funding:.4%}`\n"
            f"🌀 Squeeze: `{'activo' if sig.squeeze else 'libre'}`\n"
            f"────────────────────\n"
            f"{smcs}"
            f"⭐ Score: `{sig.score:.0%}` {bar}\n"
            f"────────────────────\n"
            f"🧠 *Razones:*\n{_fmt(sig.reason)}"
        )
        await self._send(text)

    async def send_entry(self, sig: Signal, qty: float, balance: float) -> None:
        em  = "🟢" if sig.direction == "LONG" else "🔴"
        sl_m = config.ATR_HIGHVOL_MULT if sig.atr_pct >= 75 else config.ATR_SL_MULT
        text = (
            f"{em} *ENTRADA {sig.direction}* — {sig.symbol}\n"
            f"────────────────────\n"
            f"📌 Entry:   `{sig.price:.5f}`\n"
            f"🛡 SL:      `{sig.sl:.5f}` (ATR×{sl_m})\n"
            f"🎯 TP1 50%: `{sig.tp1:.5f}`\n"
            f"🏆 TP2 50%: `{sig.tp2:.5f}`\n"
            f"────────────────────\n"
            f"📦 Qty: `{qty:.4f}` contratos\n"
            f"💵 Trade: `{config.TRADE_USDT:.0f} USDT` × `{config.LEVERAGE}x` = `{config.TRADE_USDT*config.LEVERAGE:.0f} USDT` notional\n"
            f"💰 Balance disp: `{balance:.2f} USDT`\n"
            f"⭐ Score: `{sig.score:.0%}` | ATR pct: `{sig.atr_pct:.0f}`\n"
            f"{_smc(sig)}"
            f"⚙️ Modo: {config.MODE}"
        )
        await self._send(text)

    async def send_tp(self, label: str, symbol: str, price: float,
                      pnl: float, partial: bool = False) -> None:
        sign = "+" if pnl >= 0 else ""
        tag  = "parcial (50%)" if partial else "total"
        text = (
            f"✅ *{label} — {tag}* {symbol}\n"
            f"📌 Cierre: `{price:.5f}`\n"
            f"💵 PnL: `{sign}{pnl:.4f} USDT`"
        )
        if partial:
            text += "\n🔄 SL → Breakeven | Trailing activado"
        await self._send(text)

    async def send_close(self, label: str, symbol: str, price: float,
                         pnl: float, is_sl: bool = False) -> None:
        em   = "❌" if is_sl else "✅"
        sign = "+" if pnl >= 0 else ""
        text = (
            f"{em} *{label}* — {symbol}\n"
            f"📌 Precio: `{price:.5f}`\n"
            f"💵 PnL: `{sign}{pnl:.4f} USDT`\n"
            f"⏱ Cooldown: `{config.COOLDOWN_MIN} min`"
        )
        await self._send(text)

    async def send_error(self, msg: str) -> None:
        await self._send(f"⚠️ *ERROR GUA Bot v2*\n```\n{msg}\n```")

    async def send_status(self, text: str) -> None:
        await self._send(f"🤖 *GUA Bot v2*\n{text}")

    async def send_startup(self) -> None:
        pairs = " · ".join(f"`{s}`" for s in config.SYMBOLS)
        text = (
            f"🚀 *GUA Bot v2 — Multi-Par*\n"
            f"────────────────────\n"
            f"📍 Pares ({len(config.SYMBOLS)}): {pairs}\n"
            f"⏱ TFs: `{config.INTERVAL}` · `{config.INTERVAL_TREND}` · `{config.INTERVAL_MACRO}`\n"
            f"💵 Trade fijo: `{config.TRADE_USDT:.0f} USDT` × `{config.LEVERAGE}x`\n"
            f"📊 Score mín: `{config.SCORE_THR:.0%}`\n"
            f"🔍 Sesión: `{'Filtrada' if config.SESSION_FILTER else 'Always'}`\n"
            f"⚙️ Modo: *{config.MODE}*\n"
            f"────────────────────\n"
            f"🆕 SMC · Squeeze · CVD · VWAP · RVOL · OI · Funding"
        )
        await self._send(text)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def _fmt(reason: str) -> str:
    return "\n".join(f"  • {p.strip()}" for p in reason.split("|") if p.strip())

def _smc(sig: Signal) -> str:
    tags = []
    if sig.liq_sweep: tags.append("🎣 LiqSweep")
    if sig.fvg_hit:   tags.append("📦 FVG")
    if sig.ob_hit:    tags.append("🧱 OB")
    if sig.bos   != "NONE": tags.append(f"⚡ BOS {sig.bos}")
    if sig.choch != "NONE": tags.append(f"🔄 CHoCH {sig.choch}")
    return ("🏷 SMC: " + " · ".join(tags) + "\n") if tags else ""
