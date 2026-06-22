"""
QF×JP Bot #4 — Kotegawa Dip + Liquidez Lateral (bot INDEPENDIENTE)
═══════════════════════════════════════════════════════════════════════════
Tesis: comprar dips estadísticamente estirados (Kotegawa: precio lejos de
su media de 25 DÍAS) SOLO cuando coinciden con un catalizador concreto
(Bellsz: barrido de liquidez en H1/H4/Diario — un nivel real se rompió por
mecha y el precio cerró de vuelta dentro). Una cosa es la condición
estadística ("está barato"), la otra es la confirmación de evento
("alguien cazó los stops ahí y el precio reaccionó") — combinadas dan más
que cada una sola.

DISTINTO de tus 3 bots scalpers (renewed-love/joyful-art/zesty):
  - Timeframe de análisis: 1h (no 3m) — la media de 25 días es lenta por
    diseño, no tiene sentido cazarla en velas de minutos.
  - Holds de DÍAS, no minutos — MAX_HOLD_MINUTES debe configurarse muy
    alto en este bot (ver notas de config al final del módulo).
  - LONG-ONLY — el Kotegawa original no tiene versión short, y no se
    inventó una; comprar dips es la tesis, no se fuerza un short
    equivalente sin base.
  - Leverage más bajo recomendado — holds largos = más exposición a
    movimientos multi-día, no a favor de apalancamiento alto.
  - TP es un PRECIO de reversión (a la media de 25 días o a la banda
    media de Bollinger), no un múltiplo fijo de ATR — encaja con la tesis
    de mean-reversion real en vez de forzar tu sistema de TP1/TP2 por ATR.

Reutiliza bingx_client.py, position_manager.py, risk_manager.py y
trade_journal.py SIN MODIFICAR — la gestión de riesgo, sizing y SL/trailing
ya están validados, no hace falta reinventarlos para este bot. Esto es un
reemplazo directo de scanner.py — main.py no necesita cambios más allá de
quitar el complement_engine (este bot no copia de ningún master).

CONFIRMACIÓN REQUERIDA, NO OPCIONAL: el barrido de liquidez es un
REQUISITO duro para entrar, no un boost de score — sin él, esto es solo
"comprar barato y esperar", una tesis más débil. Ver _detect_setup().
═══════════════════════════════════════════════════════════════════════════
"""
import asyncio
import logging
import time
from collections import Counter

import config as C
from bingx_client import BingXClient
from risk_manager import RiskManager
from position_manager import PositionManager, OpenTrade
import telegram_client as tg

log = logging.getLogger("kotegawa_scanner")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sma(values: list, period: int) -> list:
    out = []
    for i in range(len(values)):
        lo = max(0, i - period + 1)
        w = values[lo:i + 1]
        out.append(sum(w) / len(w))
    return out


def _stdev(values: list, period: int) -> list:
    out = []
    for i in range(len(values)):
        lo = max(0, i - period + 1)
        w = values[lo:i + 1]
        mu = sum(w) / len(w)
        out.append((sum((v - mu) ** 2 for v in w) / len(w)) ** 0.5)
    return out


def _rma(values: list, period: int) -> list:
    n = len(values)
    out = [0.0] * n
    if n == 0:
        return out
    alpha = 1.0 / period
    for i in range(n):
        out[i] = (sum(values[:i + 1]) / (i + 1)) if i < period else (out[i - 1] + alpha * (values[i] - out[i - 1]))
    return out


def _rsi(closes: list, period: int) -> list:
    n = len(closes)
    gains  = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains[i]  = max(ch, 0.0)
        losses[i] = max(-ch, 0.0)
    up, down = _rma(gains, period), _rma(losses, period)
    out = []
    for i in range(n):
        if down[i] == 0:
            out.append(100.0)
        elif up[i] == 0:
            out.append(0.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + up[i] / down[i]))
    return out


def _ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _atr(klines: list, period: int) -> list:
    tr = [klines[0][2] - klines[0][3]]
    for i in range(1, len(klines)):
        h, l, pc = klines[i][2], klines[i][3], klines[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return _rma(tr, period)


def _swing_fib_zone(daily_klines: list, lookback: int = 20):
    """
    Tercer ingrediente — distinto de fibonacci_mtf.py (ese mide un solo día
    con dirección inferida; esto mide un SWING de varios días, que es lo
    relevante para un dip-buy: ¿el dip cae en la zona dorada de retroceso
    desde el máximo reciente del swing? No necesita inferir dirección —
    el contexto ya es claro (buscamos pullback dentro de un swing), se
    mide siempre desde el swing high hacia el swing low.

    Reutiliza las klines diarias que _detect_setup() ya fetchea para la
    MA25 — sin llamada extra a la API.
    """
    window = daily_klines[-lookback:] if len(daily_klines) >= lookback else daily_klines
    if not window:
        return None
    swing_high = max(c[2] for c in window)
    swing_low  = min(c[3] for c in window)
    rng = swing_high - swing_low
    if rng <= 1e-12:
        return None
    zone_618 = swing_high - rng * 0.618
    zone_786 = swing_high - rng * 0.786
    return min(zone_618, zone_786), max(zone_618, zone_786)


# ── Detección del setup combinado ───────────────────────────────────────────

async def _detect_setup(client: BingXClient, symbol: str):
    """
    Retorna el setup (dict) si TODAS las condiciones se cumplen, None si no.
    Requiere: dip de Kotegawa (MA25 diaria + RSI + BB) Y barrido de
    liquidez Bellsz en H1/H4/D Y vela de confirmación alcista.

    FIX: toda lectura de C.KOTE_* usa getattr() con default — si falta
    una variable en Railway, usa el valor por defecto en vez de crashear.
    Mismo principio de seguridad que el resto de módulos de esta sesión.
    """
    liq_lookback   = getattr(C, 'KOTE_LIQ_LOOKBACK', 50)
    dip_uses_low   = getattr(C, 'KOTE_DIP_USES_LOW', True)
    rsi_len        = getattr(C, 'KOTE_RSI_LEN', 14)
    bb_len         = getattr(C, 'KOTE_BB_LEN', 20)
    bb_mult        = getattr(C, 'KOTE_BB_MULT', 2.0)
    dip_pct        = getattr(C, 'KOTE_DIP_PCT', 20.0)
    use_rsi_filter = getattr(C, 'KOTE_USE_RSI_FILTER', True)
    rsi_oversold   = getattr(C, 'KOTE_RSI_OVERSOLD', 24.0)
    use_bb_filter  = getattr(C, 'KOTE_USE_BB_FILTER', True)
    liq_margin_pct = getattr(C, 'KOTE_LIQ_MARGIN_PCT', 0.1)

    try:
        daily = await client.get_klines(symbol, "1d", 30)
        k1h   = await client.get_klines(symbol, "1h", 60)
        k_h4  = await client.get_klines(symbol, "4h", liq_lookback + 5)
    except Exception as e:
        log.debug("[%s] fetch error: %s", symbol, e)
        return None

    if len(daily) < 26 or len(k1h) < 22 or len(k_h4) < liq_lookback + 2:
        return None

    # ── Kotegawa: dip vs media de 25 días ────────────────────────────────────
    daily_closes = [c[4] for c in daily]
    ma25 = sum(daily_closes[-25:]) / 25

    closes_1h = [c[4] for c in k1h]
    rsi_series = _rsi(closes_1h, rsi_len)
    bb_basis_s = _sma(closes_1h, bb_len)
    bb_std_s   = _stdev(closes_1h, bb_len)

    last = k1h[-1]
    close, open_ = last[4], last[1]
    rsi      = rsi_series[-1]
    bb_basis = bb_basis_s[-1]
    bb_lower = bb_basis - bb_mult * bb_std_s[-1]

    src_dip   = last[3] if dip_uses_low else close   # low o close
    dip_level = ma25 * (1 - dip_pct / 100)

    dip_ok = src_dip <= dip_level
    rsi_ok = (not use_rsi_filter) or rsi <= rsi_oversold
    bb_ok  = (not use_bb_filter)  or src_dip <= bb_lower

    if not dip_ok:
        return None, "dip_fail"        # precio no está suficientemente bajo vs MA25
    if not rsi_ok:
        return None, "rsi_fail"        # RSI no está sobrevendido
    if not bb_ok:
        return None, "bb_fail"         # no está bajo la banda de Bollinger

    # ── Bellsz: barrido de liquidez REQUERIDO (no opcional) ──────────────────
    def _ssl(klines: list, lookback: int):
        window = klines[-lookback - 1:-1]   # excluye la vela actual
        return min(c[3] for c in window) if window else None

    ssl_h1 = _ssl(k1h,  liq_lookback)
    ssl_h4 = _ssl(k_h4, liq_lookback)
    ssl_d  = _ssl(daily, min(liq_lookback, len(daily) - 1))

    margin = close * liq_margin_pct / 100

    def _purga_alcista(ssl):
        if ssl is None or ssl <= 0:
            return False
        return last[3] <= ssl + margin and close > ssl

    swept_level = None
    for ssl, label in ((ssl_h1, "H1"), (ssl_h4, "H4"), (ssl_d, "D")):
        if _purga_alcista(ssl):
            swept_level = ssl
            break

    if swept_level is None:
        return None, "sweep_fail"      # no hay barrido de liquidez en ningún TF

    bull = close > open_
    if not bull:
        return None, "bull_fail"       # vela actual no es alcista

    # ── Tercer ingrediente: confluencia Fibonacci de swing ───────────────────
    # Configurable: KOTE_REQUIRE_FIB=true lo convierte en requisito duro
    # (descarta el setup si el dip no cae en la zona dorada del swing
    # reciente); False (default) lo deja como dato informativo en el log/
    # Telegram, sin bloquear — para que puedas observar cuánta diferencia
    # hace antes de comprometerte a exigirlo.
    fib_zone = _swing_fib_zone(daily, getattr(C, 'KOTE_FIB_LOOKBACK', 20))
    fib_confluence = False
    if fib_zone:
        lo, hi = fib_zone
        fib_confluence = lo <= close <= hi
        if getattr(C, 'KOTE_REQUIRE_FIB', False) and not fib_confluence:
            return None

    atr_1h = _atr(k1h, 14)[-1]

    return {
        "entry": close, "ma25": ma25, "bb_basis": bb_basis,
        "swept_level": swept_level, "atr": atr_1h,
        "dip_pct": (ma25 - close) / ma25 * 100, "rsi": rsi,
        "fib_confluence": fib_confluence,
    }, "ok"


# ── Loop principal ───────────────────────────────────────────────────────────

def _new_diag():
    return {"counts": Counter(), "setups_found": 0}


async def _process_symbol(symbol, client, risk, pos_mgr, diag, journal=None):
    if pos_mgr.is_trading(symbol):
        diag["counts"]["already_trading"] += 1
        return

    setup, reason = await _detect_setup(client, symbol)
    if setup is None:
        diag["counts"][reason] += 1
        return

    diag["setups_found"] += 1
    entry = setup["entry"]
    atr   = setup["atr"] if setup["atr"] > 0 else entry * 0.01

    # SL: bajo el nivel barrido, con un pequeño colchón de ATR — estilo SMC
    # (stop bajo la mecha que generó el barrido), no un múltiplo fijo
    # genérico como en los scalpers.
    sl = setup["swept_level"] - atr * getattr(C, 'KOTE_SL_ATR_BUFFER', 0.5)

    # TP: reversión a la media/banda — el más cercano de los dos es TP1,
    # el más lejano TP2. Ambos por encima de entry (LONG-only).
    targets = sorted(t for t in (setup["bb_basis"], setup["ma25"]) if t > entry)
    if not targets:
        diag["counts"]["sin_objetivo_valido"] += 1
        return
    tp1 = targets[0]
    tp2 = targets[-1] if len(targets) > 1 else targets[0] * 1.01

    log.info(
        "[%s] 🎯 SETUP Kotegawa+Liquidez — entry=%.6f dip=%.1f%% rsi=%.1f "
        "barrido=%.6f fib_zona_dorada=%s SL=%.6f TP1=%.6f TP2=%.6f",
        symbol, entry, setup["dip_pct"], setup["rsi"],
        setup["swept_level"], setup["fib_confluence"], sl, tp1, tp2,
    )

    if C.MODE == "SIGNAL":
        fib_txt = "✅ en zona dorada" if setup["fib_confluence"] else "fuera de zona dorada"
        await tg.send(
            f"🎯 *SETUP* — `{symbol}` LONG (Kotegawa+Liquidez)\n"
            f"Entry: `{entry:.6f}` | Dip: `{setup['dip_pct']:.1f}%` bajo MA25\n"
            f"RSI: `{setup['rsi']:.1f}` | Barrido en: `{setup['swept_level']:.6f}`\n"
            f"Fibonacci swing: {fib_txt}\n"
            f"SL: `{sl:.6f}` | TP1: `{tp1:.6f}` | TP2: `{tp2:.6f}`"
        )
        return

    # ── LIVE ─────────────────────────────────────────────────────────────────
    unrealized = await pos_mgr.get_unrealized_pnl()
    can, reason = await risk.can_trade(unrealized_pnl=unrealized)
    if not can:
        diag["counts"]["risk_blocked"] += 1
        return

    trade_confirmed = False
    try:
        sym_ok, sym_reason = risk.symbol_allowed(symbol)
        if not sym_ok:
            diag["counts"]["symbol_blocked"] += 1
            return

        dir_ok, dir_reason = risk.direction_allowed("LONG")
        if not dir_ok:
            diag["counts"]["correlation_blocked"] += 1
            return

        try:
            balance = await client.get_balance()
        except Exception as e:
            log.error("[%s] get_balance error: %s", symbol, e)
            return
        if balance < 5.0:
            balance = C.CAPITAL

        qty = risk.kelly_position_size(balance, entry, sl, score=70.0, tier="STD", symbol=symbol)
        if qty <= 0:
            return

        results = await client.open_trade(
            symbol=symbol, direction="LONG", quantity=qty,
            sl_price=sl, tp1_price=tp1, tp2_price=tp2,
        )
        entry_resp = results.get("entry", {})
        if entry_resp.get("code", -1) != 0:
            log.error("[%s] Entrada rechazada: %s", symbol, entry_resp)
            return

        order_id = str(
            entry_resp.get("data", {}).get("order", {}).get("orderId", "unknown")
            or entry_resp.get("data", {}).get("orderId", "unknown")
        )
        trade = OpenTrade(
            symbol=symbol, direction="LONG", entry=entry, sl=sl,
            tp1=tp1, tp2=tp2, qty=qty, atr=atr, order_id=order_id,
        )
        await pos_mgr.register_trade(trade)
        await tg.notify_trade_opened(
            type("S", (), {"symbol": symbol, "direction": "LONG", "entry": entry,
                           "sl": sl, "tp1": tp1, "tp2": tp2, "score": 70.0, "tier": "STD"})(),
            qty, order_id,
        )
        trade_confirmed = True

        if journal:
            journal.on_open(
                symbol=symbol, direction="LONG", tier="STD", score=70.0,
                filter_tags={"kotegawa_liquidez": f"dip={setup['dip_pct']:.1f}%"},
            )

    except Exception as e:
        log.error("[%s] _process_symbol error: %s", symbol, e)
    finally:
        if not trade_confirmed:
            await risk.release_reservation()


async def scan_loop(client, risk, pos_mgr, complement=None, journal=None):
    """
    Mismo nombre/firma que scanner.py — drop-in para main.py. `complement`
    se ignora a propósito: este bot no tiene master del que copiar.
    """
    log.info("Kotegawa+Liquidez Scanner v1.0 | Modo=%s | símbolos=%s",
             C.MODE, getattr(C, 'KOTE_SYMBOLS', 'TOP_N dinámico'))

    iteration = 0
    while True:
        start = time.time()
        iteration += 1
        diag = _new_diag()

        try:
            symbols = getattr(C, 'KOTE_SYMBOLS_LIST', None) or await client.get_all_symbols()
        except Exception as e:
            log.error("get_all_symbols error: %s", e)
            await asyncio.sleep(60)
            continue

        for symbol in symbols:
            try:
                await _process_symbol(symbol, client, risk, pos_mgr, diag, journal)
            except Exception as e:
                log.debug("[%s] error: %s", symbol, e)
            await asyncio.sleep(0.3)   # más espaciado — son menos símbolos, menos urgencia

        elapsed = time.time() - start
        top5 = diag["counts"].most_common(5)
        log.info("Iter %d | %d símbolos | %d setups | %.1fs | %s",
                 iteration, len(symbols), diag["setups_found"], elapsed,
                 " | ".join(f"{k}={v}" for k, v in top5) if top5 else "—")

        await asyncio.sleep(max(0.0, getattr(C, 'KOTE_SCAN_INTERVAL', 900) - elapsed))
