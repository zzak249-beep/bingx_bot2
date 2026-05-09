"""
Telegram Bot: notificaciones de trades y estado del bot.
"""

import logging
import httpx

log = logging.getLogger("Telegram")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self.base    = f"https://api.telegram.org/bot{token}"

    async def send(self, text: str):
        url = f"{self.base}/sendMessage"
        payload = {
            "chat_id":    self.chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    async def send_trade_closed(self, symbol: str, direction: str, pnl: float, entry: float, exit_price: float):
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} *TRADE CERRADO*\n"
            f"Par: `{symbol}` {direction}\n"
            f"Entry: `{entry:.4f}` → Exit: `{exit_price:.4f}`\n"
            f"PnL: `{pnl:+.2f} USDT`"
        )
        await self.send(msg)
