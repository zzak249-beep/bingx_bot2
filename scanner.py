"""
QF×JP Bot #4 — Kotegawa Dip + Liquidez Lateral v1.4
═══════════════════════════════════════════════════════════════════════════════
v1.4 — Momentum Nexus como filtro anti-falling-knife
  Nuevo: integra momentum_nexus.py (adaptación del 'Momentum Nexus Heatmap
  [UAlgo]') como confirmación de calidad del dip. Usa las klines de 1H y 4H
  ya fetcheadas — sin llamada extra a la API.

  Score 0-100 combinando RSI + MFI + VZO (Volume Zone Oscillator) + CCI.
  El VZO es la pieza nueva respecto a lo que ya tenía el bot: mide si el
  VOLUMEN también es bajista, no solo el precio. Un RSI < 35 con VZO positivo
  = el dinero está fluyendo al alza aunque el precio haya caído = trampa.

  Umbrales:
    nexus_score(1H) < KOTE_NEXUS_OVERSOLD (26): dip confirmado por 4 indicadores
    nexus_score(4H) < KOTE_NEXUS_OVERSOLD:      el downtrend es real en 4H también
    nexus_score(4H) > KOTE_NEXUS_OVERBOUGHT(74): 4H en uptrend = dip superficial,
                                                 no es el tipo de dip de Kotegawa

  Caso real prevenido: ANIME, FLOCK, 0G — todos abiertos con precio lejos de
  MA25 pero con el 4H score > 50 (mercado no realmente oversold en 4H). El
  filtro los habría marcado como "dip superficial" y reducido la posición o
  bloqueado según KOTE_REQUIRE_NEXUS.

  Configurable:
    KOTE_NEXUS_ENABLED=true       (default false — activar gradualmente)
    KOTE_REQUIRE_NEXUS=false      (true = filtro duro, false = solo informativo)
    KOTE_NEXUS_OVERSOLD=26        (umbral oversold para 1H y 4H)
    KOTE_NEXUS_OVERBOUGHT=74      (umbral para detectar dip superficial)

v1.3 (sin cambios): Confluencia con rango de sesión NY open.
v1.2 (sin cambios): Divergencia alcista RSI vs precio.
v1.1 (sin cambios): KOTE_* desde config, DIAG, Fibonacci de swing.
═══════════════════════════════════════════════════════════════════════════════

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

# v1.4: Momentum Nexus — import opcional para no crashear si el archivo no está
try:
    from momentum_nexus import combined_score as _nexus_score, momentum_nexus_filter
    _NEXUS_AVAILABLE = True
except ImportError:
    _NEXUS_AVAILABLE = False
    logging.getLogger("kotegawa_scanner").warning(
        "momentum_nexus.py no encontrado — KOTE_NEXUS_ENABLED ignorado. "
        "Sube el archivo para activar el filtro anti-falling-knife."
    )

log = logging.getLogger("kotegawa_scanner")


# ── Helpers matemáticos ───────────────────────────────────────────────────────

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
    Zona dorada de Fibonacci del swing más reciente (61.8%-78.6% de retroceso).
    Reutiliza klines diarias ya fetcheadas — sin llamada extra a API.
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


# ── Divergencia alcista (v1.2) ────────────────────────────────────────────────

def _has_bullish_divergence(klines_1h: list, rsi_series: list,
                             lookback: int = 30, min_distance: int = 5) -> tuple[bool, str]:
    """
    Detecta divergencia alcista clásica entre precio y RSI en las últimas
    `lookback` velas de 1H.

    Condición: precio hace mínimos más bajos (lower low) pero el RSI hace
    mínimos más altos (higher low) — el momentum gira antes que el precio.

    Solo busca divergencias cuando el RSI actual está por debajo de 45
    (zona de sobreventa/debilidad) para evitar falsas señales en zona media.

    Returns:
        (True, descripción) si hay divergencia
        (False, "no_div") si no hay
    """
    n = min(len(klines_1h), len(rsi_series))
    if n < lookback + min_distance:
        return False, "no_div"

    # Valores recientes
    recent_lows = [klines_1h[i][3] for i in range(n - lookback, n)]   # low prices
    recent_rsi  = rsi_series[n - lookback:]

    curr_low = recent_lows[-1]
    curr_rsi = recent_rsi[-1]

    # Solo en zona débil/sobrevendida
    if curr_rsi > 45:
        return False, "no_div"

    # Buscar un mínimo anterior con: precio más alto (lower low en precio)
    # y RSI más bajo (higher low en RSI) — eso es divergencia alcista
    best_detail = ""
    for i in range(len(recent_lows) - 1 - min_distance, 0, -1):
        prev_low = recent_lows[i]
        prev_rsi = recent_rsi[i]

        # Precio hizo lower low (actual < anterior) pero RSI hizo higher low
        if curr_low < prev_low and curr_rsi > prev_rsi and prev_rsi < 50:
            detail = (
                f"div_alcista: price {prev_low:.6f}→{curr_low:.6f} (↓) "
                f"RSI {prev_rsi:.1f}→{curr_rsi:.1f} (↑) "
                f"dist={len(recent_lows)-1-i}bars"
            )
            return True, detail

    return False, "no_div"


# ── Rango de sesión NY open (v1.3) ────────────────────────────────────────────

def _session_range(klines_1h: list,
                   session_start_utc: int = 13,
                   session_end_utc:   int = 15) -> dict:
    """
    Detecta el HIGH y LOW de la ventana NY open usando las klines de 1H
    ya fetcheadas — sin llamada extra a la API.

    Default: 13:00-15:00 UTC = 09:00-11:00 ET (NY open).

    Posición del precio en el box (0%=low, 100%=high).
    Zona 0-30% = cerca del session low = zona óptima LONG FADE.

    Confluencia clave: si el swept_level coincide con session_low
    dentro de 0.5%, el barrido no es aleatorio — ocurre en un nivel
    institucional conocido, señal muy fuerte.
    """
    if not klines_1h:
        return {"valid": False, "label": "no_data"}

    now_s      = time.time()
    day_ago_ms = (now_s - 86400) * 1000

    session_bars = []
    for k in klines_1h:
        ts_ms = k[0]
        if ts_ms < day_ago_ms:
            continue
        hour_utc = int((ts_ms / 1000) % 86400 // 3600)
        if session_start_utc <= hour_utc < session_end_utc:
            session_bars.append(k)

    if not session_bars:
        return {
            "valid": False,
            "label": f"sin_bars_sesion({session_start_utc}-{session_end_utc}UTC)"
        }

    s_high  = max(k[2] for k in session_bars)
    s_low   = min(k[3] for k in session_bars)
    s_range = s_high - s_low

    if s_range <= 1e-12:
        return {"valid": False, "label": "session_range_cero"}

    curr    = klines_1h[-1][4]
    pct_pos = (curr - s_low) / s_range * 100
    near_low = pct_pos <= 30.0

    return {
        "valid":         True,
        "session_high":  s_high,
        "session_low":   s_low,
        "session_range": s_range,
        "pct_pos":       round(pct_pos, 1),
        "near_low":      near_low,
        "label": (
            f"NY_session H={s_high:.6f} L={s_low:.6f} "
            f"pos={pct_pos:.0f}% {'✅near_low' if near_low else ''}"
        ),
    }


# ── Detección del setup combinado ───────────────────────────────────────────

async def _detect_setup(client: BingXClient, symbol: str):
    """
    Retorna (setup_dict, "ok") si TODAS las condiciones se cumplen,
    o (None, reason_str) con la razón de fallo para diagnóstico.

    v1.2: añade detección de divergencia alcista opcional.
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
    require_div    = getattr(C, 'KOTE_REQUIRE_DIVERGENCE', False)
    div_lookback   = getattr(C, 'KOTE_DIV_LOOKBACK', 30)

    try:
        daily = await client.get_klines(symbol, "1d", 30)
        k1h   = await client.get_klines(symbol, "1h", max(60, div_lookback + 10))
        k_h4  = await client.get_klines(symbol, "4h", liq_lookback + 5)
    except Exception as e:
        log.debug("[%s] fetch error: %s", symbol, e)
        return None, "fetch_error"

    if len(daily) < 26 or len(k1h) < 22 or len(k_h4) < liq_lookback + 2:
        return None, "insufficient_data"

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

    src_dip   = last[3] if dip_uses_low else close
    dip_level = ma25 * (1 - dip_pct / 100)

    dip_ok = src_dip <= dip_level
    rsi_ok = (not use_rsi_filter) or rsi <= rsi_oversold
    bb_ok  = (not use_bb_filter)  or src_dip <= bb_lower

    if not dip_ok:
        return None, "dip_fail"
    if not rsi_ok:
        return None, "rsi_fail"
    if not bb_ok:
        return None, "bb_fail"

    # ── Bellsz: barrido de liquidez REQUERIDO ────────────────────────────────
    def _ssl(klines: list, lookback: int):
        window = klines[-lookback - 1:-1]
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
        return None, "sweep_fail"

    bull = close > open_
    if not bull:
        return None, "bull_fail"

    # ── Zona Fibonacci de swing ───────────────────────────────────────────────
    fib_zone = _swing_fib_zone(daily, getattr(C, 'KOTE_FIB_LOOKBACK', 20))
    fib_confluence = False
    if fib_zone:
        lo, hi = fib_zone
        fib_confluence = lo <= close <= hi
        if getattr(C, 'KOTE_REQUIRE_FIB', False) and not fib_confluence:
            return None, "fib_fail"

    # ── v1.2: Divergencia alcista (opcional) ─────────────────────────────────
    div_detected, div_detail = _has_bullish_divergence(
        k1h, rsi_series, lookback=div_lookback
    )

    if require_div and not div_detected:
        return None, "div_fail"

    # ── v1.3: Confluencia con rango de sesión NY open ─────────────────────────
    session_start = getattr(C, 'KOTE_SESSION_START_UTC', 13)
    session_end   = getattr(C, 'KOTE_SESSION_END_UTC', 15)
    require_sess  = getattr(C, 'KOTE_REQUIRE_SESSION', False)

    sess = _session_range(k1h, session_start, session_end)

    # Confluencia máxima: el barrido de Bellsz coincide con el session low
    sweep_on_session_low = False
    if sess["valid"] and swept_level:
        margin_pct = abs(swept_level - sess["session_low"]) / max(sess["session_low"], 1e-9)
        sweep_on_session_low = margin_pct < 0.005   # dentro del 0.5%

    # near_low: precio en la zona baja del rango de sesión (0-30%)
    session_confluence = sess.get("near_low", False) or sweep_on_session_low

    if require_sess and not session_confluence:
        return None, "session_fail"

    # ── v1.4: Momentum Nexus — confirmación anti-falling-knife ───────────────
    # Usa klines de 1H y 4H ya fetcheadas — sin API extra.
    nexus_score_1h  = 50.0
    nexus_score_4h  = 50.0
    nexus_ok        = True
    nexus_label     = ""

    if getattr(C, 'KOTE_NEXUS_ENABLED', False) and _NEXUS_AVAILABLE:
        n_oversold  = getattr(C, 'KOTE_NEXUS_OVERSOLD', 26.0)
        n_overbought = getattr(C, 'KOTE_NEXUS_OVERBOUGHT', 74.0)
        require_nx  = getattr(C, 'KOTE_REQUIRE_NEXUS', False)

        nexus_score_1h = _nexus_score(k1h)
        nexus_score_4h = _nexus_score(k_h4)

        # Clasificación del dip
        dip_1h_confirmed = nexus_score_1h < n_oversold
        htf_4h_bullish   = nexus_score_4h > n_overbought  # dip superficial = 4H no está oversold
        htf_4h_confirmed = nexus_score_4h < n_oversold

        if htf_4h_bullish:
            # 4H aún alcista = el dip es superficial, Kotegawa pide que sea de días
            nexus_ok    = not require_nx
            nexus_label = (
                f"⚠️ nexus_4H={nexus_score_4h:.0f} (OB) — dip superficial "
                f"{'BLOQUEADO' if not nexus_ok else 'advertencia'}"
            )
            if require_nx:
                return None, "nexus_4h_overbought"
        elif dip_1h_confirmed and htf_4h_confirmed:
            nexus_ok    = True
            nexus_label = (
                f"✅ nexus_1H={nexus_score_1h:.0f} 4H={nexus_score_4h:.0f} "
                f"— oversold confirmado en ambos TF (máxima confluencia)"
            )
        elif dip_1h_confirmed:
            nexus_ok    = True
            nexus_label = (
                f"🟡 nexus_1H={nexus_score_1h:.0f} 4H={nexus_score_4h:.0f} "
                f"— oversold en 1H, 4H neutral"
            )
        else:
            nexus_ok    = not require_nx
            nexus_label = (
                f"⚠️ nexus_1H={nexus_score_1h:.0f} 4H={nexus_score_4h:.0f} "
                f"— 1H no confirmado {'BLOQUEADO' if not nexus_ok else ''}"
            )
            if require_nx:
                return None, "nexus_1h_not_oversold"

    atr_1h = _atr(k1h, 14)[-1]

    return {
        "entry":          close,
        "ma25":           ma25,
        "bb_basis":       bb_basis,
        "swept_level":    swept_level,
        "atr":            atr_1h,
        "dip_pct":        (ma25 - close) / ma25 * 100,
        "rsi":            rsi,
        "fib_confluence": fib_confluence,
        "div_detected":         div_detected,
        "div_detail":           div_detail,
        "session_confluence":   session_confluence,
        "sweep_on_session_low": sweep_on_session_low,
        "session_label":        sess.get("label", ""),
        "nexus_score_1h":       round(nexus_score_1h, 1),   # v1.4
        "nexus_score_4h":       round(nexus_score_4h, 1),   # v1.4
        "nexus_label":          nexus_label,                 # v1.4
    }, "ok"


# ── Loop principal ────────────────────────────────────────────────────────────

def _new_diag():
    return {"counts": Counter(), "setups_found": 0}


async def _process_symbol(symbol, client, risk, pos_mgr, diag, journal=None):
    if pos_mgr.is_trading(symbol):
        diag["counts"]["already_trading"] += 1
        return

    result = await _detect_setup(client, symbol)
    setup, reason = result if isinstance(result, tuple) else (result, "ok")

    if setup is None:
        diag["counts"][reason] += 1
        return

    diag["setups_found"] += 1
    entry = setup["entry"]
    atr   = setup["atr"] if setup["atr"] > 0 else entry * 0.01

    sl = setup["swept_level"] - atr * getattr(C, 'KOTE_SL_ATR_BUFFER', 0.5)

    targets = sorted(t for t in (setup["bb_basis"], setup["ma25"]) if t > entry)
    if not targets:
        diag["counts"]["sin_objetivo_valido"] += 1
        return
    tp1 = targets[0]
    tp2 = targets[-1] if len(targets) > 1 else targets[0] * 1.01

    # ── v1.2: info de divergencia en logs ────────────────────────────────────
    div_str = ""
    if setup["div_detected"]:
        div_str = f" 📐DIV={setup['div_detail']}"
    else:
        div_str = " (sin div)"

    # ── v1.3: info de sesión NY en logs ──────────────────────────────────────
    sess_str = ""
    if setup["sweep_on_session_low"]:
        sess_str = " 🏛️SWEEP@SESSION_LOW"
    elif setup["session_confluence"]:
        sess_str = " 🏛️near_session_low"

    log.info(
        "[%s] 🎯 SETUP Kotegawa+Liquidez v1.4 — entry=%.6f dip=%.1f%% rsi=%.1f "
        "barrido=%.6f fib=%s%s%s nexus=1H:%.0f/4H:%.0f SL=%.6f TP1=%.6f TP2=%.6f",
        symbol, entry, setup["dip_pct"], setup["rsi"],
        setup["swept_level"], setup["fib_confluence"],
        div_str, sess_str,
        setup["nexus_score_1h"], setup["nexus_score_4h"],
        sl, tp1, tp2,
    )

    if C.MODE == "SIGNAL":
        fib_txt  = "✅ zona dorada" if setup["fib_confluence"] else "❌ fuera"
        div_txt  = f"✅ {setup['div_detail']}" if setup["div_detected"] else "❌ sin divergencia"
        sess_txt = (
            "🏛️ ✅ SWEEP EN SESSION LOW"
            if setup["sweep_on_session_low"] else
            "🏛️ ✅ cerca del low de sesión"
            if setup["session_confluence"] else
            f"🏛️ ❌ {setup['session_label']}"
        )
        nexus_txt = setup["nexus_label"] if setup["nexus_label"] else "—"
        await tg.send(
            f"🎯 *SETUP* — `{symbol}` LONG (Kotegawa+Liquidez v1.4)\n"
            f"Entry: `{entry:.6f}` | Dip: `{setup['dip_pct']:.1f}%` bajo MA25\n"
            f"RSI: `{setup['rsi']:.1f}` | Barrido: `{setup['swept_level']:.6f}`\n"
            f"Fibonacci: {fib_txt}\n"
            f"Divergencia: {div_txt}\n"
            f"Sesión NY: {sess_txt}\n"
            f"Nexus: {nexus_txt}\n"
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
            await risk.release_reservation()
            return

        dir_ok, dir_reason = risk.direction_allowed("LONG")
        if not dir_ok:
            diag["counts"]["correlation_blocked"] += 1
            await risk.release_reservation()
            return

        try:
            balance = await client.get_balance()
        except Exception as e:
            log.error("[%s] get_balance error: %s", symbol, e)
            await risk.release_reservation()
            return
        if balance < 5.0:
            balance = C.CAPITAL

        qty = risk.kelly_position_size(balance, entry, sl, score=70.0, tier="STD", symbol=symbol)
        if qty <= 0:
            await risk.release_reservation()
            return

        results = await client.open_trade(
            symbol=symbol, direction="LONG", quantity=qty,
            sl_price=sl, tp1_price=tp1, tp2_price=tp2,
        )
        entry_resp = results.get("entry", {})
        if entry_resp.get("code", -1) != 0:
            log.error("[%s] Entrada rechazada: %s", symbol, entry_resp)
            await risk.release_reservation()
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
            filter_tags = {}
            if setup["div_detected"]:
                filter_tags["bullish_divergence"] = setup["div_detail"]
            if setup["fib_confluence"]:
                filter_tags["fib_zone"] = "golden_zone"
            journal.on_open(
                symbol=symbol, direction="LONG", tier="STD", score=70.0,
                filter_tags={"kotegawa_liquidez": f"dip={setup['dip_pct']:.1f}%", **filter_tags},
            )

    except Exception as e:
        log.error("[%s] _process_symbol error: %s", symbol, e)
    finally:
        if not trade_confirmed:
            await risk.release_reservation()


async def scan_loop(client, risk, pos_mgr, complement=None, journal=None):
    """Drop-in para main.py. `complement` ignorado — este bot no tiene master."""
    log.info(
        "Kotegawa+Liquidez Scanner v1.2 | Modo=%s | dip_pct=%.1f rsi_ovs=%.1f | "
        "div=%s fib=%s",
        C.MODE,
        getattr(C, 'KOTE_DIP_PCT', 20.0),
        getattr(C, 'KOTE_RSI_OVERSOLD', 24.0),
        "req" if getattr(C, 'KOTE_REQUIRE_DIVERGENCE', False) else "info",
        "req" if getattr(C, 'KOTE_REQUIRE_FIB', False) else "off",
    )

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
            await asyncio.sleep(0.3)

        elapsed = time.time() - start
        top5 = diag["counts"].most_common(5)
        log.info(
            "Iter %d | %d símbolos | %d setups | %.1fs | %s",
            iteration, len(symbols), diag["setups_found"], elapsed,
            " | ".join(f"{k}={v}" for k, v in top5) if top5 else "—",
        )

        await asyncio.sleep(max(0.0, getattr(C, 'KOTE_SCAN_INTERVAL', 900) - elapsed))
