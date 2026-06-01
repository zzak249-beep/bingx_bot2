"""
Telegram Notifier — Rich signal messages with inline keyboard
"""

import asyncio
import logging
import aiohttp
from typing import Optional
from src.engine import SignalResult, Signal

logger = logging.getLogger("telegram")

TG_API = "https://api.telegram.org/bot{token}"


def _emoji_score(score: int) -> str:
    if score >= 80: return "🔵"
    if score >= 68: return "🟡"
    if score >= 55: return "🟢"
    return "⚫"


def _emoji_signal(sig: Signal) -> str:
    return {
        Signal.LONG_SUP:   "⭐",
        Signal.LONG_FUEL:  "🔥",
        Signal.LONG_STD:   "📈",
        Signal.SHORT_SUP:  "⭐",
        Signal.SHORT_FUEL: "🔥",
        Signal.SHORT_STD:  "📉",
        Signal.PRE_LONG:   "⚡",
        Signal.PRE_SHORT:  "⚡",
        Signal.NONE:       "—",
    }.get(sig, "—")


def _direction(sig: Signal) -> str:
    if sig in (Signal.LONG_SUP, Signal.LONG_FUEL, Signal.LONG_STD, Signal.PRE_LONG):
        return "LONG"
    if sig in (Signal.SHORT_SUP, Signal.SHORT_FUEL, Signal.SHORT_STD, Signal.PRE_SHORT):
        return "SHORT"
    return "—"


def format_signal_message(r: SignalResult) -> str:
    e = _emoji_signal(r.signal)
    dir_ = _direction(r.signal)
    score = r.score_long if "LONG" in dir_ else r.score_short
    conv  = r.conviction_l if "LONG" in dir_ else r.conviction_s
    sl    = r.sl_long if "LONG" in dir_ else r.sl_short
    tp1   = r.tp1_long if "LONG" in dir_ else r.tp1_short
    tp2   = r.tp2_long if "LONG" in dir_ else r.tp2_short
    rr1   = r.rr1_long if "LONG" in dir_ else r.rr1_short
    rr2   = r.extras.get("rr2_long" if "LONG" in dir_ else "rr2_short", 0.0)

    # Asymmetry display
    asym_str = f"{r.asym_dir} {r.asymmetry:.2f}×" if r.asym_dir != "NEUTRAL" else "NEUTRAL"
    vai_bar  = "▓" * int(r.vai_score * 8) + "░" * (8 - int(r.vai_score * 8))

    # HTF alignment
    htf_l = r.htf_long
    htf_s = r.htf_short
    htf_str = f"{'✓' if r.extras.get('htf_bull') else '✗'}15m {'✓' if r.extras.get('htf2_bull') else '✗'}1h {'✓' if r.extras.get('mkt_bull') else '✗'}3m"

    # Structure
    choch = "CHoCH↑" if r.extras.get("choch_bull") else ("CHoCH↓" if r.extras.get("choch_bear") else "")
    bos   = "BoS↑" if r.extras.get("bos_bull") else ("BoS↓" if r.extras.get("bos_bear") else "")
    sweep = "SWP↑" if r.extras.get("liq_bull") else ("SWP↓" if r.extras.get("liq_bear") else "")
    struct_tags = " ".join(filter(None, [choch, bos, sweep])) or r.structure

    lines = [
        f"{e} <b>{r.signal.value}</b>  {_emoji_score(score)}",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>{r.symbol}</b>  @  <code>{r.close:.6g}</code>",
        f"",
        f"🎯 <b>SCORE {dir_}</b>: <code>{score}/100</code>   Conv: {conv}/12",
        f"⚡ <b>ASIMETRÍA VAI</b>: <code>{asym_str}</code>",
        f"   [{vai_bar}] {r.vai_score*100:.0f}%",
        f"🧭 <b>HTF 3TF</b>: {htf_str}  ({htf_l}L / {htf_s}S)",
        f"🏛 <b>Estructura</b>: {struct_tags}",
        f"",
        f"📐 <b>TRADE PLAN</b>",
        f"  💲 Entry:  <code>{r.close:.6g}</code>",
        f"  🛑 SL:     <code>{sl:.6g}</code>",
        f"  🎯 TP1:    <code>{tp1:.6g}</code>  R:R {rr1:.1f}×",
        f"  🏁 TP2:    <code>{tp2:.6g}</code>  R:R {rr2:.1f}×",
        f"  📦 Size:   <code>{r.pos_size:.4f}</code> u  (Kelly {r.kelly_f*100:.0f}%)",
        f"",
        f"📈 <b>FACTORES</b>",
        f"  ADX: {r.adx:.0f} [{r.regime}]   RSI: {r.rsi:.0f}",
        f"  CVD: {r.cvd_dir}   SQ: {r.squeeze}",
        f"  VWAP: {r.vwap_pos}   OI: {'CONF↑' if r.extras.get('oi_conf_long') else 'CONF↓' if r.extras.get('oi_conf_short') else '—'}",
        f"  ATR: {r.atr:.6g}",
        f"",
        f"{'⚠️ OI SQUEEZE — cuidado' if r.extras.get('oi_squeeze') else '✅ Sin squeeze OI'}",
        f"{'✅ Circuit OK' if r.circuit_ok else '🚨 CIRCUIT BREAKER activo'}",
        f"Entry 1m: {r.entry_wick}",
    ]
    return "\n".join(lines)


def format_scan_summary(results: list, top_n: int = 5) -> str:
    """Summary message for scanner results"""
    strong = [r for r in results if r.signal not in (Signal.NONE, Signal.PRE_LONG, Signal.PRE_SHORT)]
    pre    = [r for r in results if r.signal in (Signal.PRE_LONG, Signal.PRE_SHORT)]

    lines = [
        "🤖 <b>QF×JP v3.4 — SCANNER</b>",
        f"📊 {len(results)} monedas analizadas",
        f"🔥 {len(strong)} señales activas  ⚡ {len(pre)} pre-alertas",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    for r in sorted(strong, key=lambda x: max(x.score_long, x.score_short), reverse=True)[:top_n]:
        dir_ = _direction(r.signal)
        score = r.score_long if "LONG" in dir_ else r.score_short
        e = _emoji_signal(r.signal)
        lines.append(f"{e} <b>{r.symbol}</b>  {r.signal.value}  [{score}/100]  R:R {r.rr1_long if 'LONG' in dir_ else r.rr1_short:.1f}×")

    if pre:
        lines.append("")
        lines.append("⚡ <b>Pre-alertas:</b>")
        for r in pre[:3]:
            dir_ = _direction(r.signal)
            score = r.score_long if "LONG" in dir_ else r.score_short
            lines.append(f"  • <b>{r.symbol}</b>  {r.signal.value}  [{score}]")

    return "\n".join(lines)


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self.base    = f"https://api.telegram.org/bot{token}"
        self._session: Optional[aiohttp.ClientSession] = None
        self._sent_signals: set = set()  # Dedup: symbol+signal

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _post(self, method: str, payload: dict) -> dict:
        session = await self._get_session()
        url = f"{self.base}/{method}"
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return {}

    async def send_message(self, text: str, parse_mode: str = "HTML",
                           disable_notification: bool = False) -> dict:
        return await self._post("sendMessage", {
            "chat_id":              self.chat_id,
            "text":                 text,
            "parse_mode":           parse_mode,
            "disable_notification": disable_notification,
        })

    async def send_signal(self, result: SignalResult) -> bool:
        """Send signal with deduplication (1 signal per symbol per direction)"""
        key = f"{result.symbol}:{result.signal.value}"
        if key in self._sent_signals:
            return False
        # Only deduplicate for 30 cycles (~5 min at 10s scan)
        self._sent_signals.add(key)
        if len(self._sent_signals) > 200:
            self._sent_signals = set(list(self._sent_signals)[-100:])

        msg = format_signal_message(result)
        await self.send_message(msg)
        logger.info(f"Signal sent: {result.symbol} {result.signal.value}")
        return True

    async def send_scan_summary(self, results: list):
        msg = format_scan_summary(results)
        await self.send_message(msg, disable_notification=True)

    async def send_alert(self, text: str):
        await self.send_message(f"🚨 <b>ALERTA</b>\n{text}")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
