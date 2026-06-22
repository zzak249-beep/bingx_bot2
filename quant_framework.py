"""
QF×JP — Framework de Evaluación Cuantitativa v1.0
═══════════════════════════════════════════════════════════════════════════════
Uso: python quant_framework.py --journal path/to/trades.json
O importa la clase QuantFramework y llámala desde trade_journal.py
═══════════════════════════════════════════════════════════════════════════════
"""
import math
import json
import sys
from typing import List, Dict


# ══════════════════════════════════════════════════════════════════════════════
# 1. TESIS DEL EDGE — qué hay que probar
# ══════════════════════════════════════════════════════════════════════════════
#
# El edge de Kotegawa+Liquidez descansa sobre DOS condiciones independientes:
#
#   A) Condición estadística: precio >= 8% bajo MA25 diaria + RSI <= 35
#      → identifica activos estirados frente a su media de largo plazo
#
#   B) Catalizador de evento: barrido de liquidez en H1/H4/D confirmado
#      → alguien cazó los stops y el precio reaccionó
#
# Hipótesis nula a rechazar: E[retorno] = 0 (los trades son ruido aleatorio)
# Hipótesis alternativa:     E[retorno] > 0 (existe un edge real positivo)
#
# Test estadístico:
#   t = (r̄ × √N) / σ  → requiere t > 2.0 para p < 0.05
#   N_min = (σ / r̄)² × 4  → trades mínimos para significancia
#
# Regla práctica: con WR~50% y RR~1.5, necesitas ≈120 trades para rechazar
# H₀ con 95% de confianza. Con 20 trades, cualquier Sharpe está en el ruido.
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# 2. MÉTRICAS BÁSICAS
# ══════════════════════════════════════════════════════════════════════════════

def basic_metrics(trades: List[Dict]) -> Dict:
    """
    Calcula métricas básicas desde una lista de trades.
    Cada trade debe tener al menos: {"pnl": float, "entry": float, "close": float}
    """
    if not trades:
        return {"error": "sin trades"}

    n = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses)) + 1e-9

    profit_factor = gross_win / gross_loss
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0

    # Racha máxima perdedora
    max_consec_loss = 0
    curr = 0
    for p in pnls:
        if p <= 0:
            curr += 1
            max_consec_loss = max(max_consec_loss, curr)
        else:
            curr = 0

    # Drawdown máximo
    equity = 0.0
    peak = 0.0
    trough = 0.0
    max_dd_usdt = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
            trough = equity
        if equity < trough:
            trough = equity
            max_dd_usdt = max(max_dd_usdt, peak - trough)
    max_dd = max_dd_usdt / max(abs(peak), 1.0)

    return {
        "n_trades": n,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 3),
        "avg_rr": round(avg_rr, 3),
        "expectancy_usdt": round(expectancy, 4),
        "avg_win_usdt": round(avg_win, 4),
        "avg_loss_usdt": round(avg_loss, 4),
        "gross_pnl": round(sum(pnls), 4),
        "max_consec_losses": max_consec_loss,
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. DEFLATED SHARPE RATIO
# ══════════════════════════════════════════════════════════════════════════════
#
# El Sharpe normal miente en tres casos:
#   (1) Pocos trades — infla el ratio por azar
#   (2) Distribución no normal — colas gordas distorsionan el resultado
#   (3) Overfitting de parámetros — el "mejor" backtest es siempre positivo
#
# Fórmulas:
#   SR* = SR × √T × (1 − γ₃×SR/6 + (γ₄−3)×SR²/24)
#   DSR = Φ(SR* × √(1−ρ̂) / √(1 + SR²/2))
#
#   Donde:
#     T  = número de observaciones (trades)
#     γ₃ = skewness de los retornos
#     γ₄ = kurtosis de los retornos
#     ρ̂  = autocorrelación lag-1
#     Φ  = CDF de la distribución normal estándar
#
# Interpretación:
#   DSR > 0.95  → edge confirmado estadísticamente
#   DSR 0.80-0.95 → prometedor, necesita más datos
#   DSR 0.60-0.80 → señal débil, posible ruido
#   DSR < 0.60  → probablemente ruido
# ══════════════════════════════════════════════════════════════════════════════

def _mean(vals):
    return sum(vals) / len(vals) if vals else 0.0

def _std(vals, ddof=1):
    if len(vals) < 2:
        return 1e-9
    mu = _mean(vals)
    var = sum((v - mu) ** 2 for v in vals) / (len(vals) - ddof)
    return math.sqrt(max(var, 1e-18))

def _skewness(vals):
    mu = _mean(vals)
    s = _std(vals)
    n = len(vals)
    if n < 3 or s < 1e-12:
        return 0.0
    return sum((v - mu) ** 3 for v in vals) / (n * s ** 3)

def _kurtosis(vals):
    """Kurtosis de Fisher (no exceso) — para distribución normal = 3.0"""
    mu = _mean(vals)
    s = _std(vals)
    n = len(vals)
    if n < 4 or s < 1e-12:
        return 3.0
    return sum((v - mu) ** 4 for v in vals) / (n * s ** 4)

def _autocorr_lag1(vals):
    if len(vals) < 3:
        return 0.0
    mu = _mean(vals)
    cov = sum((vals[i] - mu) * (vals[i-1] - mu) for i in range(1, len(vals)))
    var = sum((v - mu) ** 2 for v in vals)
    return cov / var if var > 1e-12 else 0.0

def _norm_cdf(x):
    """Aproximación de la CDF normal (Abramowitz & Stegun)"""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    d = 0.3989423 * math.exp(-x * x / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
    return 1 - p if sign > 0 else p

def deflated_sharpe(pnls: List[float], trades_per_year: float = 100) -> Dict:
    """
    Calcula el Deflated Sharpe Ratio sin dependencias externas.
    
    Args:
        pnls: lista de PnL por trade (en USDT o en %)
        trades_per_year: para anualizar el SR (default 100)
    
    Returns:
        dict con sr_anualizado, dsr, interpretacion y n_trades_for_significance
    """
    n = len(pnls)
    if n < 5:
        return {
            "dsr": 0.0,
            "sr_anualizado": 0.0,
            "n_trades": n,
            "nota": f"Insuficiente — tienes {n} trades, necesitas mínimo 5 para calcular DSR"
        }

    mu = _mean(pnls)
    s = _std(pnls)

    if s < 1e-12:
        return {"dsr": 1.0, "sr_anualizado": 999.0, "nota": "Varianza cero — revisa los datos"}

    sr_per_trade = mu / s
    sr_anual = sr_per_trade * math.sqrt(trades_per_year)

    g3 = _skewness(pnls)
    g4 = _kurtosis(pnls)
    rho = _autocorr_lag1(pnls)

    # SR ajustado por T, skewness y kurtosis
    sr_star = sr_per_trade * math.sqrt(n) * (
        1 - g3 * sr_per_trade / 6 + (g4 - 3) * sr_per_trade ** 2 / 24
    )

    # DSR: probabilidad de que el SR verdadero sea positivo
    denom = math.sqrt(1 + sr_per_trade ** 2 / 2) * math.sqrt(max(1 - rho, 0.01))
    dsr = _norm_cdf(sr_star / (denom + 1e-12))

    # Trades necesarios para significancia (t > 2.0)
    if mu > 1e-9:
        n_for_sig = int(math.ceil((s / mu) ** 2 * 4))
    else:
        n_for_sig = 9999

    if dsr > 0.95:
        interpret = "edge confirmado — considera escalar capital"
    elif dsr > 0.80:
        interpret = "prometedor — necesita más trades para confirmar"
    elif dsr > 0.60:
        interpret = "señal débil — revisar filtros antes de escalar"
    else:
        interpret = "probablemente ruido — no escalar"

    return {
        "n_trades": n,
        "sr_anualizado": round(sr_anual, 3),
        "sr_per_trade": round(sr_per_trade, 4),
        "dsr": round(dsr, 4),
        "skewness": round(g3, 3),
        "kurtosis_fisher": round(g4, 3),
        "autocorr_lag1": round(rho, 3),
        "n_trades_for_significance": n_for_sig,
        "months_to_significance": round(n_for_sig / max(trades_per_year / 12, 1), 1),
        "interpretacion": interpret,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. WALK-FORWARD ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
#
# Protocolo recomendado para Kotegawa+Liquidez:
#   - IS (in-sample, optimización):  6 meses
#   - OOS (out-of-sample, validación): 2 meses
#   - Step: 1 mes (rolling)
#   - Eficiencia mínima aceptable: SR_OOS / SR_IS > 0.70
#
# Parámetros a optimizar (por orden de impacto):
#   1. KOTE_DIP_PCT: rango 5%–15% (driver principal de señales)
#   2. KOTE_RSI_OVERSOLD: rango 25–45 (sensible al régimen de mercado)
#   3. KOTE_SL_ATR_BUFFER: rango 0.5–2.0 (riesgo de overfitting alto)
#
# Parámetros que NO hay que optimizar:
#   - MA period (25 días): es la tesis del Kotegawa original
#   - KOTE_LIQ_MARGIN_PCT: es definitorio del setup, no un parámetro libre
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward_analysis(trades: List[Dict],
                          is_window: int = 40,
                          oos_window: int = 15) -> Dict:
    """
    Walk-Forward Analysis simplificado sobre lista de trades.
    
    Args:
        trades: lista ordenada por fecha, cada elemento con "pnl"
        is_window: trades de entrenamiento por fold
        oos_window: trades de validación por fold
    
    Returns:
        dict con eficiencia WFA y diagnóstico
    """
    n = len(trades)
    step = oos_window
    folds = []
    i = 0

    while i + is_window + oos_window <= n:
        is_trades = trades[i: i + is_window]
        oos_trades = trades[i + is_window: i + is_window + oos_window]

        is_pnls = [t["pnl"] for t in is_trades]
        oos_pnls = [t["pnl"] for t in oos_trades]

        is_sr = _mean(is_pnls) / (_std(is_pnls) + 1e-9)
        oos_sr = _mean(oos_pnls) / (_std(oos_pnls) + 1e-9)
        efficiency = oos_sr / (is_sr + 1e-9) if is_sr > 0 else 0.0

        folds.append({
            "fold": len(folds) + 1,
            "is_trades": len(is_trades),
            "oos_trades": len(oos_trades),
            "is_sr_pertrade": round(is_sr, 4),
            "oos_sr_pertrade": round(oos_sr, 4),
            "efficiency": round(efficiency, 3),
            "is_profitable": oos_sr > 0,
        })
        i += step

    if not folds:
        return {
            "folds": [],
            "nota": f"Insuficiente — necesitas al menos {is_window + oos_window} trades para 1 fold WFA. Tienes {n}."
        }

    avg_eff = _mean([f["efficiency"] for f in folds])
    pct_profitable_oos = sum(1 for f in folds if f["is_profitable"]) / len(folds)

    if avg_eff > 0.70 and pct_profitable_oos > 0.70:
        wfa_verdict = "robusto — parámetros generalizan bien al OOS"
    elif avg_eff > 0.50:
        wfa_verdict = "moderado — hay overfitting parcial, revisar parámetros"
    else:
        wfa_verdict = "débil — overfitting severo o edge inestable"

    return {
        "folds": folds,
        "avg_efficiency": round(avg_eff, 3),
        "pct_oos_profitable": round(pct_profitable_oos, 3),
        "wfa_verdict": wfa_verdict,
        "n_folds": len(folds),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. DETECCIÓN DE DECAIMIENTO DEL EDGE
# ══════════════════════════════════════════════════════════════════════════════
#
# El edge puede decaer por:
#   1. Más participantes ejecutando la misma estrategia
#   2. Cambio de régimen de mercado (bear flat vs bull volátil)
#   3. Cambio de microestructura en BingX (liquidez, spreads)
#
# Alertas basadas en ventana rolling de N trades:
#   - Verde:  WR_rolling > 45% y PF_rolling > 1.2
#   - Amarillo: WR_rolling 35-45% o PF_rolling 0.9-1.2
#   - Rojo:   WR_rolling < 35% o PF_rolling < 0.9 → pausar bot
# ══════════════════════════════════════════════════════════════════════════════

def check_edge_decay(trades: List[Dict], window: int = 20) -> Dict:
    """
    Detecta decaimiento del edge sobre una ventana rolling de trades recientes.
    
    Args:
        trades: lista de trades con "pnl"
        window: cuántos trades recientes analizar
    
    Returns:
        dict con status (OK/YELLOW/RED) y métricas
    """
    if len(trades) < window:
        return {
            "status": "INSUFFICIENT",
            "nota": f"Necesitas {window} trades para el análisis. Tienes {len(trades)}.",
            "n_trades": len(trades),
        }

    recent = trades[-window:]
    pnls = [t["pnl"] for t in recent]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    wr = len(wins) / window
    gross_win = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) + 1e-9
    pf = gross_win / gross_loss

    # Comparar con histórico completo (si hay suficiente)
    hist_wr = sum(1 for t in trades if t["pnl"] > 0) / len(trades)
    delta_wr = wr - hist_wr

    if wr < 0.35 or pf < 0.90:
        status = "RED"
        accion = "PAUSAR BOT — revisar condiciones de mercado y parámetros"
    elif wr < 0.45 or pf < 1.20:
        status = "YELLOW"
        accion = "Monitoreo aumentado — no escalar capital"
    else:
        status = "OK"
        accion = "Edge saludable — operación normal"

    return {
        "status": status,
        "accion": accion,
        "window": window,
        "wr_rolling": round(wr, 4),
        "pf_rolling": round(pf, 3),
        "wr_historico": round(hist_wr, 4),
        "delta_wr_vs_historico": round(delta_wr, 4),
        "n_trades_total": len(trades),
        "n_trades_recientes": window,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. EXPECTATIVA Y TRADES NECESARIOS PARA SIGNIFICANCIA
# ══════════════════════════════════════════════════════════════════════════════

def expectancy_analysis(win_rate: float,
                        avg_win_usdt: float,
                        avg_loss_usdt: float,
                        trades_per_month: int = 8) -> Dict:
    """
    Calcula expectativa y trades necesarios para confirmar el edge.
    
    Parámetros actuales de zesty-reverence (estimados):
        win_rate = 0.45 (estimado, pendiente de datos reales)
        avg_win_usdt ≈ riesgo × RR
        avg_loss_usdt ≈ riesgo (KOTE_SL_ATR_BUFFER × ATR × qty)
    """
    expectancy = win_rate * avg_win_usdt - (1 - win_rate) * avg_loss_usdt
    monthly_pnl = expectancy * trades_per_month
    profit_factor = (win_rate * avg_win_usdt) / ((1 - win_rate) * avg_loss_usdt + 1e-9)

    # Trades para t-test con p < 0.05 (t > 2.0)
    # Asumiendo σ ≈ sqrt(WR*(1-WR)) × (avg_win + avg_loss)
    sigma_approx = math.sqrt(win_rate * (1 - win_rate)) * (avg_win_usdt + avg_loss_usdt)
    if expectancy > 1e-6:
        n_sig = int(math.ceil((sigma_approx / expectancy) ** 2 * 4))
    else:
        n_sig = 9999

    months_to_sig = math.ceil(n_sig / max(trades_per_month, 1))

    return {
        "expectancy_per_trade": round(expectancy, 4),
        "monthly_pnl_estimated": round(monthly_pnl, 2),
        "profit_factor": round(profit_factor, 3),
        "n_trades_for_significance": n_sig,
        "months_to_significance": months_to_sig,
        "edge_positive": expectancy > 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. REPORTE COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def full_report(trades: List[Dict], trades_per_year: float = 100) -> None:
    """
    Imprime el reporte cuantitativo completo en consola.
    
    Formato esperado de trades:
    [
        {"pnl": 0.45, "symbol": "ANIME-USDT", "direction": "LONG",
         "entry": 0.002762, "close": 0.002800, "hold_minutes": 120},
        ...
    ]
    """
    print("\n" + "═" * 70)
    print("QF×JP — REPORTE CUANTITATIVO Kotegawa+Liquidez")
    print("═" * 70)

    pnls = [t["pnl"] for t in trades]

    # 1. Básicas
    print("\n── MÉTRICAS BÁSICAS ──")
    m = basic_metrics(trades)
    for k, v in m.items():
        print(f"  {k:<30} {v}")

    # 2. DSR
    print("\n── DEFLATED SHARPE RATIO ──")
    dsr = deflated_sharpe(pnls, trades_per_year)
    for k, v in dsr.items():
        print(f"  {k:<30} {v}")

    # 3. Decay check
    print("\n── DECAIMIENTO DEL EDGE (últimos 20 trades) ──")
    decay = check_edge_decay(trades, window=min(20, len(trades)))
    for k, v in decay.items():
        print(f"  {k:<30} {v}")

    # 4. WFA (si hay suficientes trades)
    if len(trades) >= 55:
        print("\n── WALK-FORWARD ANALYSIS ──")
        wfa = walk_forward_analysis(trades)
        print(f"  verdict: {wfa['wfa_verdict']}")
        print(f"  avg_efficiency: {wfa['avg_efficiency']}")
        print(f"  pct_oos_profitable: {wfa['pct_oos_profitable']}")
        for f in wfa["folds"]:
            print(f"  fold {f['fold']}: IS_SR={f['is_sr_pertrade']:.4f} OOS_SR={f['oos_sr_pertrade']:.4f} eff={f['efficiency']:.3f}")
    else:
        print(f"\n── WALK-FORWARD — insuficiente (tienes {len(trades)}, necesitas 55) ──")

    print("\n" + "═" * 70)
    print("PRÓXIMOS HITOS:")
    n = len(trades)
    milestones = [10, 30, 60, 120]
    for ms in milestones:
        status = "✅" if n >= ms else f"⏳ faltan {ms - n}"
        print(f"  {ms:>4} trades — {status}")
    print("═" * 70 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS DE RIESGO — tabla de referencia para zesty-reverence
# ══════════════════════════════════════════════════════════════════════════════
RISK_PARAMS = {
    # Límites operativos
    "MAX_DAILY_LOSS_PCT":       0.05,   # 5% del capital = 9.7 USDT sobre 194
    "MAX_DRAWDOWN_BEFORE_STOP": 0.15,   # 15% = pausar manualmente y revisar
    "MAX_OPEN_TRADES":          5,      # 5 posiciones simultáneas máximo
    "POSITION_SIZE_MAX_PCT":    0.10,   # no más del 10% del capital por trade

    # Alertas de decaimiento
    "DECAY_WIN_RATE_YELLOW":    0.45,   # WR rolling < 45% = alerta
    "DECAY_WIN_RATE_RED":       0.35,   # WR rolling < 35% = pausar
    "DECAY_PF_YELLOW":          1.20,   # PF rolling < 1.2 = alerta
    "DECAY_PF_RED":             0.90,   # PF rolling < 0.9 = pausar

    # Umbrales de validación estadística
    "DSR_CONFIDENCE_THRESHOLD": 0.80,   # DSR > 0.80 para considerar escalar capital
    "WFA_EFFICIENCY_MINIMUM":   0.70,   # OOS SR / IS SR > 0.70

    # Kotegawa específico
    "KOTE_DIP_PCT_CURRENT":     8.0,    # umbral actual
    "KOTE_RSI_OVERSOLD_CURRENT": 35.0, # umbral actual
    "KOTE_SL_ATR_BUFFER_REC":   1.5,   # recomendado para hold de días
    "BREAKEVEN_ATR_MULT_REC":   3.0,   # recomendado (trail no activa demasiado pronto)
}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — uso desde línea de comandos
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            trades = json.load(f)
        full_report(trades)
    else:
        # Ejemplo con datos sintéticos para verificar que funciona
        import random
        random.seed(42)
        fake_trades = []
        for _ in range(25):
            win = random.random() < 0.47
            pnl = random.uniform(0.1, 0.6) if win else random.uniform(-0.4, -0.05)
            fake_trades.append({"pnl": round(pnl, 4), "symbol": "TEST-USDT", "direction": "LONG"})

        print("\n[modo demo — 25 trades sintéticos]")
        full_report(fake_trades, trades_per_year=100)

        print("Uso real:")
        print("  python quant_framework.py tu_journal.json")
        print("\nFormato JSON esperado:")
        print('  [{"pnl": 0.45, "symbol": "ANIME-USDT", "direction": "LONG"}, ...]')
