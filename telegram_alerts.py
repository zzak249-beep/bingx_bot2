"""
telegram_alerts.py v2 - Notificaciones + Comandos de control
"""
import requests
import logging
import threading
from datetime import datetime

log = logging.getLogger('bot27')


class TelegramBot:
    URL     = "https://api.telegram.org/bot{token}/sendMessage"
    UPD_URL = "https://api.telegram.org/bot{token}/getUpdates"

    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = str(chat_id)
        self._last_update_id = 0
        self._callbacks = {}   # comando -> funcion

    def send(self, text: str) -> bool:
        try:
            r = requests.post(self.URL.format(token=self.token),
                json={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'},
                timeout=10)
            return r.status_code == 200
        except Exception as e:
            log.warning(f"Telegram send error: {e}")
            return False

    def register_command(self, command: str, callback):
        """Registra una funcion para responder a un comando de Telegram."""
        self._callbacks[command.lower()] = callback

    def start_polling(self):
        """Inicia escucha de comandos en hilo separado."""
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        log.info("Telegram polling iniciado")

    def _poll_loop(self):
        while True:
            try:
                r = requests.get(
                    self.UPD_URL.format(token=self.token),
                    params={'offset': self._last_update_id + 1, 'timeout': 30},
                    timeout=35)
                if r.status_code == 200:
                    updates = r.json().get('result', [])
                    for upd in updates:
                        self._last_update_id = upd['update_id']
                        msg = upd.get('message', {})
                        text = msg.get('text', '').strip().lower()
                        chat = str(msg.get('chat', {}).get('id', ''))
                        if chat == self.chat_id and text.startswith('/'):
                            cmd = text.split()[0][1:]
                            if cmd in self._callbacks:
                                try:
                                    resp = self._callbacks[cmd]()
                                    self.send(resp)
                                except Exception as e:
                                    log.error(f"Comando /{cmd} error: {e}")
            except Exception as e:
                log.warning(f"Telegram poll error: {e}")
                import time; time.sleep(10)

    # ---- Mensajes predefinidos ----

    def startup(self, preset, interval, symbols, balance, dry_run):
        mode = "SIMULACION" if dry_run else "LIVE REAL"
        self.send(
            f"<b>BOT27 INICIADO [{mode}]</b>\n"
            f"Preset: {preset} | Intervalo: {interval}\n"
            f"Simbolos: {symbols} | Balance: <b>{balance:.2f} USDT</b>\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Comandos disponibles:\n"
            f"/status - Estado actual\n"
            f"/balance - Ver balance\n"
            f"/trades - Trades abiertos\n"
            f"/stats - Estadisticas de aprendizaje\n"
            f"/pause - Pausar trading\n"
            f"/resume - Reanudar trading"
        )

    def signal_alert(self, symbol, signal, confidence, rsi,
                     price, sl, tp, reason, regime, divergence='none'):
        direction = "LONG ^" if signal == 1 else "SHORT v"
        sl_pct = abs(price-sl)/price*100
        tp_pct = abs(tp-price)/price*100
        div_txt = f"\nDivergencia: {divergence}" if divergence != 'none' else ""
        self.send(
            f"<b>SENAL {direction}</b>\n"
            f"Par: <b>{symbol}</b> | {regime}\n"
            f"Conf: {confidence}% | RSI: {rsi:.1f}{div_txt}\n"
            f"Precio: {price:.6f}\n"
            f"SL: {sl:.6f} (-{sl_pct:.1f}%) | TP: {tp:.6f} (+{tp_pct:.1f}%)\n"
            f"Razon: {reason}"
        )

    def trade_opened(self, result: dict):
        dr = " [DRY RUN]" if result.get('dry_run') else ""
        self.send(
            f"<b>TRADE ABIERTO{dr}</b>\n"
            f"{result['direction']} {result['symbol']}\n"
            f"Size: {result['size']} USDT | Entrada: {result['price']:.6f}\n"
            f"SL: {result['sl']:.6f} | TP: {result['tp']:.6f}\n"
            f"Balance: {result['balance']:.2f} USDT"
        )

    def trade_closed(self, symbol, direction, pnl_pct, pnl_usdt, result):
        tag = "WIN" if result == 'WIN' else "LOSS"
        self.send(
            f"<b>TRADE CERRADO [{tag}]</b>\n"
            f"{direction} {symbol}\n"
            f"PnL: <b>{pnl_pct:+.2f}% ({pnl_usdt:+.2f} USDT)</b>"
        )

    def cycle_summary(self, cycle, long_c, short_c, neutral_c, balance, summary, risk_status=None):
        risk_txt = ""
        if risk_status:
            risk_txt = f"\nPnL hoy: {risk_status['daily_pnl']:+.2f} USDT"
            if risk_status['trading_halted']:
                risk_txt += " [PAUSADO]"
        self.send(
            f"<b>Ciclo #{cycle}</b>\n"
            f"LONG: {long_c} | SHORT: {short_c} | NEUTRAL: {neutral_c}\n"
            f"Balance: {balance:.2f} USDT{risk_txt}\n"
            f"WR: {summary.get('wr',0)}% ({summary.get('total',0)} trades)\n"
            f"PnL total: {summary.get('total_pnl',0):+.2f} USDT"
        )

    def learning_update(self, params, wr, avg_pnl):
        self.send(
            f"<b>PARAMETROS ACTUALIZADOS</b>\n"
            f"WR reciente: {wr:.0%} | Avg PnL: {avg_pnl:+.2f}%\n"
            f"min_confidence: {params['min_confidence']}\n"
            f"risk_pct: {params['risk_pct']}% | leverage: {params['leverage']}\n"
            f"sl_mult: {params['sl_mult']} | tp_mult: {params['tp_mult']}"
        )

    def daily_report(self, balance, summary, risk_status):
        self.send(
            f"<b>REPORTE DIARIO BOT27</b>\n"
            f"{'='*25}\n"
            f"Balance: {balance:.2f} USDT\n"
            f"PnL hoy: {risk_status['daily_pnl']:+.2f} USDT\n"
            f"Trades totales: {summary.get('total',0)}\n"
            f"Win Rate: {summary.get('wr',0)}%\n"
            f"PnL total: {summary.get('total_pnl',0):+.2f} USDT\n"
            f"Blacklist: {len(summary.get('blacklist',[]))} pares\n"
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )

    def error(self, msg):
        self.send(f"<b>ERROR BOT27</b>\n{msg}\n{datetime.now().strftime('%H:%M:%S')}")

    def risk_halt(self, daily_pnl, balance):
        self.send(
            f"<b>TRADING PAUSADO</b>\n"
            f"Limite de perdida diaria alcanzado\n"
            f"PnL hoy: {daily_pnl:+.2f} USDT\n"
            f"Balance: {balance:.2f} USDT\n"
            f"Se reanuda automaticamente manana."
        )
