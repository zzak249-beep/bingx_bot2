"""
Momentum Nexus — QF×JP adaptation of 'Momentum Nexus Heatmap [UAlgo]'
═══════════════════════════════════════════════════════════════════════════════
Combina 4 osciladores en un score 0-100 normalizado:

  Score = (RSI×9 + MFI×9 + (VZO+100)×4.5 + CCI + 450) / 3600 × 100

  RSI  (0-100)    — momentum de precio clásico, peso 9
  MFI  (0-100)    — money flow (precio × volumen), peso 9
  VZO  (-100/100) — Volume Zone Oscillator: % del volumen que es alcista,
                    peso efectivo 4.5 (el mismo que MFI pero con volumen)
  CCI  (~-350/350) — Canal de materias primas normalizado, peso ~1

Ventaja vs usar solo RSI: el VZO captura si el volumen fluye en la dirección
correcta — una señal con RSI bajo pero VZO positivo es trampa bajista.

Umbrales:
  Score < 26  → oversold  → boost LONG  (hay presión compradora acumulada)
  Score > 74  → overbought → boost SHORT (hay presión vendedora acumulada)

Confirmación HTF (4H por defecto):
  Ambos TFs en oversold  → confluencia máxima LONG  (+8 pts)
  Ambos TFs en overbought → confluencia máxima SHORT (+8 pts)
  TFs opuestos            → señal débil             (-4 pts)

Integración en scanner.py:
    from momentum_nexus import momentum_nexus_filter

    # Dentro de _process_symbol(), después de vol_regime:
    if getattr(C, 'MOMENTUM_NEXUS_ENABLED', False):
        mn_boost, mn_reason, mn_block = momentum_nexus_filter(
            k3m, k4h, sig.direction,
            oversold=getattr(C, 'MN_OVERSOLD', 26.0),
            overbought=getattr(C, 'MN_OVERBOUGHT', 74.0),
        )
        if mn_block:
            diag["counts"]["mn_block"] += 1
            return None
        if mn_boost != 0:
            sig.score = max(0.0, min(sig.score + mn_boost, 100.0))
            sig.tier  = score_to_tier(sig.score)
            diag["counts"][f"mn_boost_{mn_boost:+.0f}"] += 1
═══════════════════════════════════════════════════════════════════════════════
"""
import logging

log = logging.getLogger("momentum_nexus")


# ── Helpers matemáticos ───────────────────────────────────────────────────────

def _ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _rma(values: list, period: int) -> list:
    n = len(values)
    out = [0.0] * n
    if n == 0:
        return out
    alpha = 1.0 / period
    for i in range(n):
        out[i] = (sum(values[:i+1]) / (i+1)) if i < period else \
                 (out[i-1] + alpha * (values[i] - out[i-1]))
    return out


def _rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 2:
        return 50.0
    n = len(closes)
    gains  = [max(closes[i] - closes[i-1], 0.0) for i in range(1, n)]
    losses = [max(closes[i-1] - closes[i], 0.0) for i in range(1, n)]
    up   = _rma(gains,  period)
    down = _rma(losses, period)
    u, d = up[-1], down[-1]
    if d < 1e-12:
        return 100.0
    if u < 1e-12:
        return 0.0
    return 100.0 - 100.0 / (1.0 + u / d)


def _mfi(klines: list, period: int = 14) -> float:
    """Money Flow Index — precio típico × volumen."""
    if len(klines) < period + 2:
        return 50.0
    tp    = [(k[2] + k[3] + k[4]) / 3.0 for k in klines]
    vols  = [k[5] for k in klines]
    pos_flow = 0.0
    neg_flow = 0.0
    for i in range(len(tp) - period, len(tp)):
        raw_mf = tp[i] * vols[i]
        if i > 0 and tp[i] > tp[i-1]:
            pos_flow += raw_mf
        elif i > 0:
            neg_flow += raw_mf
    if neg_flow < 1e-12:
        return 100.0
    mfr = pos_flow / neg_flow
    return 100.0 - 100.0 / (1.0 + mfr)


def _vzo(klines: list, period: int = 28) -> float:
    """
    Volume Zone Oscillator: 100 × EMA(signed_vol) / EMA(vol)

    signed_vol = +vol si alcista (open < close), -vol si bajista.
    Rango: -100 a +100.
    >0 → volumen neto alcista | <0 → volumen neto bajista.

    Diferencia clave vs CVD: VZO es auto-normalizado (%) y no acumulativo,
    por lo que no depende del período de historia disponible.
    """
    if len(klines) < period + 2:
        return 0.0
    signed = [k[5] if k[1] < k[4] else -k[5] for k in klines]
    vols   = [k[5] for k in klines]
    ema_s  = _ema(signed, period)
    ema_v  = _ema(vols, period)
    denom  = ema_v[-1]
    if denom < 1e-12:
        return 0.0
    return 100.0 * ema_s[-1] / denom


def _cci(klines: list, period: int = 28) -> float:
    """Commodity Channel Index."""
    if len(klines) < period:
        return 0.0
    recent = klines[-period:]
    tp     = [(k[2] + k[3] + k[4]) / 3.0 for k in recent]
    ma     = sum(tp) / len(tp)
    md     = sum(abs(v - ma) for v in tp) / len(tp)
    if md < 1e-12:
        return 0.0
    return (tp[-1] - ma) / (0.015 * md)


# ── Score compuesto ───────────────────────────────────────────────────────────

def combined_score(klines: list,
                   rsi_len: int = 14,
                   mfi_len: int = 14,
                   vzo_len: int = 28,
                   cci_len: int = 28) -> float:
    """
    Score 0-100 combinando RSI, MFI, VZO, CCI con los pesos del original.
    Fórmula idéntica al Pine Script de UAlgo.

    RSI peso 9, MFI peso 9, VZO peso 4.5 (efectivo), CCI peso ~1 (relativo).
    """
    closes = [k[4] for k in klines]
    rsi = _rsi(closes, rsi_len)
    mfi = _mfi(klines, mfi_len)
    vzo = _vzo(klines, vzo_len)
    cci = _cci(klines, cci_len)

    # Fórmula exacta del Pine Script
    raw = (rsi * 9 + mfi * 9 + (vzo + 100) * 4.5 + cci + 450) / 3600 * 100
    return max(0.0, min(100.0, round(raw, 2)))


# ── Filtro principal para scanner.py ─────────────────────────────────────────

def momentum_nexus_filter(
    klines_primary: list,
    klines_htf:     list,
    direction:      str   = "LONG",
    oversold:       float = 26.0,
    overbought:     float = 74.0,
    rsi_len:        int   = 14,
    mfi_len:        int   = 14,
    vzo_len:        int   = 28,
    cci_len:        int   = 28,
) -> tuple:
    """
    Filtro de confluencia momentum para scanner.py.

    Returns: (boost: float, reason: str, block: bool)

    Lógica:
      - score_primary (TF actual) y score_htf (4H por defecto)
      - Si ambos oversold  + direction==LONG  → boost máximo
      - Si ambos overbought + direction==SHORT → boost máximo
      - Si el HTF contradice el TF actual     → penalización
      - Si el HTF extremo contradice direction → bloqueo

    El bloqueo solo aplica en el caso más claro: HTF muy overbought (>80)
    con señal LONG, o HTF muy oversold (<20) con señal SHORT.
    """
    min_bars = max(rsi_len, mfi_len, vzo_len, cci_len) + 5

    score_p = 50.0
    if len(klines_primary) >= min_bars:
        score_p = combined_score(klines_primary, rsi_len, mfi_len, vzo_len, cci_len)

    score_h = 50.0
    if len(klines_htf) >= min_bars:
        score_h = combined_score(klines_htf, rsi_len, mfi_len, vzo_len, cci_len)

    primary_os  = score_p < oversold
    primary_ob  = score_p > overbought
    htf_os      = score_h < oversold
    htf_ob      = score_h > overbought

    boost = 0.0
    block = False

    if direction == "LONG":
        if primary_os and htf_os:
            # Confluencia máxima: ambos TFs oversold con señal LONG
            boost = 8.0
        elif primary_os and not htf_ob:
            # Primario oversold, HTF neutral
            boost = 4.0
        elif htf_ob:
            # HTF overbought con señal LONG = nadando contra la marea
            boost = -5.0
            if score_h > 82:
                block = True   # HTF muy overbought → bloqueo duro

    elif direction == "SHORT":
        if primary_ob and htf_ob:
            # Confluencia máxima: ambos TFs overbought con señal SHORT
            boost = 8.0
        elif primary_ob and not htf_os:
            # Primario overbought, HTF neutral
            boost = 4.0
        elif htf_os:
            # HTF oversold con señal SHORT = nadando contra la marea
            boost = -5.0
            if score_h < 18:
                block = True   # HTF muy oversold → bloqueo duro

    zone_p = "OS" if primary_os else ("OB" if primary_ob else "neutral")
    zone_h = "OS" if htf_os else ("OB" if htf_ob else "neutral")
    reason = (
        f"MN: {score_p:.0f}({zone_p}) HTF={score_h:.0f}({zone_h}) "
        f"dir={direction} boost={boost:+.0f}"
        f"{' ⛔BLOCK' if block else ''}"
    )

    log.debug("[momentum_nexus] %s", reason)
    return round(boost, 1), reason, block


# ── Test rápido ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import math

    def _fake_klines(n=100, trend=1):
        klines = []
        price = 100.0
        for i in range(n):
            price += trend * 0.3 + math.sin(i / 8) * 0.5
            o = price - 0.2
            c = price + 0.2 * trend
            h = max(o, c) + 0.3
            l = min(o, c) - 0.3
            vol = 1000 + i * 10 * (1 if c > o else 0.5)
            klines.append([i, o, h, l, c, vol])
        return klines

    # Test 1: tendencia alcista fuerte
    bull = _fake_klines(120, trend=1)
    s = combined_score(bull)
    print(f"Tendencia alcista → score={s:.1f} (esperado >60)")

    # Test 2: tendencia bajista fuerte
    bear = _fake_klines(120, trend=-1)
    s2 = combined_score(bear)
    print(f"Tendencia bajista → score={s2:.1f} (esperado <40)")

    # Test 3: filtro completo
    boost, reason, block = momentum_nexus_filter(bear, bear, "SHORT",
                                                  oversold=26, overbought=74)
    print(f"SHORT en bajista: boost={boost} block={block}")
    print(f"Reason: {reason}")

    boost2, reason2, block2 = momentum_nexus_filter(bear, bull, "SHORT",
                                                     oversold=26, overbought=74)
    print(f"\nSHORT en bajista (HTF alcista): boost={boost2} block={block2}")
    print(f"Reason: {reason2}")
