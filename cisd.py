"""
cisd.py — Detección de CISD + OB + FVG + Volumen para el bot de crowding.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, Optional


@dataclass
class CISDResult:
    bullish: bool = False
    bearish: bool = False
    score: int = 0
    cisd_price: Optional[float] = None
    has_ob: bool = False
    has_fvg: bool = False
    rel_vol: float = 0.0
    vol_spike: bool = False
    motivo: str = ""


def _body_pct(o, h, l, c):
    rng = h - l
    return abs(c - o) / rng * 100.0 if rng > 0 else 0.0


def _atr(velas, n=14):
    if len(velas) < n + 1:
        return 0.0
    trs = []
    for i in range(len(velas) - n, len(velas)):
        h, l, cp = velas[i]["h"], velas[i]["l"], velas[i - 1]["c"]
        trs.append(max(h - l, abs(h - cp), abs(l - cp)))
    return sum(trs) / len(trs) if trs else 0.0


def _rel_vol(velas, period=20):
    if len(velas) < period + 1:
        return 0.0
    vols = [v.get("v", 0.0) for v in velas[-(period + 1):]]
    if not vols or vols[-1] <= 0:
        return 0.0
    avg = sum(vols[:-1]) / period
    return vols[-1] / avg if avg > 0 else 0.0


def detectar_cisd(velas: Sequence[dict], min_consec=3, atr_mult=1.2,
                  body_pct_min=55.0, lookback=40) -> CISDResult:
    res = CISDResult()
    if len(velas) < lookback + 5:
        res.motivo = "pocas velas"
        return res

    atr = _atr(velas)
    rel = _rel_vol(velas)
    res.rel_vol = rel
    res.vol_spike = rel >= 2.0

    # CISD alcista
    cnt = 0
    ref_bull = None
    for i in range(1, min(lookback, len(velas) - 1)):
        idx = -1 - i
        if velas[idx]["c"] < velas[idx]["o"]:
            cnt += 1
        else:
            if cnt >= min_consec:
                try:
                    ref_bull = velas[idx + cnt]["o"]
                except Exception:
                    ref_bull = None
                break
            cnt = 0

    # CISD bajista
    cnt = 0
    ref_bear = None
    for i in range(1, min(lookback, len(velas) - 1)):
        idx = -1 - i
        if velas[idx]["c"] > velas[idx]["o"]:
            cnt += 1
        else:
            if cnt >= min_consec:
                try:
                    ref_bear = velas[idx + cnt]["o"]
                except Exception:
                    ref_bear = None
                break
            cnt = 0

    last = velas[-1]
    body = _body_pct(last["o"], last["h"], last["l"], last["c"])
    disp_bull = (last["c"] - last["o"]) > atr * atr_mult and body >= body_pct_min
    disp_bear = (last["o"] - last["c"]) > atr * atr_mult and body >= body_pct_min

    if ref_bull is not None and last["c"] > ref_bull and disp_bull:
        res.bullish = True
        res.cisd_price = ref_bull

    if ref_bear is not None and last["c"] < ref_bear and disp_bear:
        res.bearish = True
        res.cisd_price = ref_bear

    # FVG
    if len(velas) >= 3:
        if velas[-1]["l"] > velas[-3]["h"] or velas[-1]["h"] < velas[-3]["l"]:
            res.has_fvg = True

    # Order Block simple
    if len(velas) >= 2:
        if res.bullish and velas[-2]["c"] < velas[-2]["o"]:
            res.has_ob = True
        if res.bearish and velas[-2]["c"] > velas[-2]["o"]:
            res.has_ob = True

    score = 0
    if res.bullish or res.bearish:
        score += 1
    if res.has_ob:
        score += 1
    if res.has_fvg:
        score += 1
    if rel >= 1.5:
        score += 1
    if res.vol_spike:
        score += 1
    res.score = score

    if res.bullish:
        res.motivo = f"CISD BULL score={score}"
    elif res.bearish:
        res.motivo = f"CISD BEAR score={score}"
    else:
        res.motivo = "sin CISD"
    return res


def hay_retest(velas: Sequence[dict], cisd_price: float, is_bull: bool, max_bars: int = 12) -> bool:
    if cisd_price is None or len(velas) < 3:
        return False
    for v in velas[-max_bars:]:
        if is_bull and v["l"] <= cisd_price <= v["h"] and v["c"] > cisd_price:
            return True
        if not is_bull and v["l"] <= cisd_price <= v["h"] and v["c"] < cisd_price:
            return True
    return False
