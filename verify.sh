#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# VERIFICACIÓN PRE-DEPLOYMENT — SATY ELITE v13
# UTBot · WaveTrend · Bj Bot R:R · BB+RSI · SMI · Score 16pts
# ═══════════════════════════════════════════════════════════════

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   CHECKLIST DE VERIFICACIÓN — SATY ELITE v13               ║"
echo "║   UTBot · WaveTrend · Bj Bot · BB+RSI · Score: 16 pts      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

# ─────────────────────────────────────────────────────────────
# 1. Archivos del proyecto
# ─────────────────────────────────────────────────────────────
echo "━━━ 1. ARCHIVOS DEL PROYECTO ━━━"

FILES=("bot.py" "requirements.txt" "Procfile" "railway.toml" "runtime.txt")
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file existe"
    else
        echo -e "${RED}✗${NC} $file NO ENCONTRADO"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# ─────────────────────────────────────────────────────────────
# 2. Contenido de archivos críticos
# ─────────────────────────────────────────────────────────────
echo "━━━ 2. CONTENIDO DE ARCHIVOS ━━━"

if grep -q "worker: python bot.py" Procfile 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Procfile configurado correctamente"
else
    echo -e "${RED}✗${NC} Procfile incorrecto o no encontrado"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "startCommand = \"python bot.py\"" railway.toml 2>/dev/null; then
    echo -e "${GREEN}✓${NC} railway.toml configurado correctamente"
else
    echo -e "${RED}✗${NC} railway.toml incorrecto"
    ERRORS=$((ERRORS + 1))
fi

REQUIRED_PACKAGES=("ccxt" "pandas" "numpy" "requests")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if grep -q "$package" requirements.txt 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $package en requirements.txt"
    else
        echo -e "${RED}✗${NC} $package NO ENCONTRADO en requirements.txt"
        ERRORS=$((ERRORS + 1))
    fi
done

if grep -q "python-3.11" runtime.txt 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Python 3.11 especificado en runtime.txt"
else
    echo -e "${YELLOW}⚠${NC} Verificar versión Python en runtime.txt"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 3. Verificar versión v13
# ─────────────────────────────────────────────────────────────
echo "━━━ 3. VERSIÓN DEL BOT ━━━"

if grep -q "v13" bot.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} bot.py es versión 13"
else
    echo -e "${YELLOW}⚠${NC} No se detecta versión 13 en bot.py"
fi

# Verificar indicadores nuevos de v13
V13_INDICATORS=("calc_utbot" "calc_wavetrend" "calc_bb" "calc_rr_targets" "UTBOT_KEY" "WT_CHAN_LEN" "BB_PERIOD" "RNR")
for indicator in "${V13_INDICATORS[@]}"; do
    if grep -q "$indicator" bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $indicator encontrado (v13)"
    else
        echo -e "${RED}✗${NC} $indicator NO encontrado — verifica que es v13"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# ─────────────────────────────────────────────────────────────
# 4. Variables de entorno — checklist manual
# ─────────────────────────────────────────────────────────────
echo "━━━ 4. VARIABLES DE ENTORNO (Checklist Manual) ━━━"
echo ""
echo "En Railway → Variables → RAW Editor, configura:"
echo ""
echo "  OBLIGATORIAS:"
echo "  □ BINGX_API_KEY           → Tu API Key de BingX"
echo "  □ BINGX_API_SECRET        → Tu API Secret de BingX"
echo "  □ TELEGRAM_BOT_TOKEN      → Token de @BotFather"
echo "  □ TELEGRAM_CHAT_ID        → Tu Chat ID o Chat ID grupo"
echo ""
echo "  GENERALES (defaults optimizados):"
echo "  □ FIXED_USDT=8            USDT por trade"
echo "  □ MAX_OPEN_TRADES=12      Trades máximos"
echo "  □ MIN_SCORE=5             Score mínimo 0-16 (¡ahora es /16!)"
echo "  □ MAX_DRAWDOWN=15         Circuit breaker %"
echo "  □ DAILY_LOSS_LIMIT=8      Pérdida diaria máxima %"
echo "  □ BTC_FILTER=true         Filtro tendencia BTC"
echo ""
echo "  NUEVAS v13 — INDICADORES:"
echo "  □ UTBOT_KEY_VALUE=10      UTBot sensibilidad (↓=más señales)"
echo "  □ UTBOT_ATR_PERIOD=10     UTBot periodo ATR"
echo "  □ WT_CHAN_LEN=9           WaveTrend channel length"
echo "  □ WT_AVG_LEN=12           WaveTrend average length"
echo "  □ WT_OB=60                WaveTrend sobrecompra"
echo "  □ WT_OS=-60               WaveTrend sobreventa"
echo "  □ RNR=2.0                 Risk to Reward ratio"
echo "  □ RISK_MULT=1.0           Buffer ATR para SL"
echo "  □ RR_EXIT=0.5             % TP2 para trail (0=inmediato)"
echo "  □ BB_PERIOD=20            Bollinger Bands periodo"
echo "  □ BB_STD=2.0              Bollinger Bands desviaciones"
echo "  □ BB_RSI_OB=65            RSI máximo para BB buy"
echo "  □ TRADE_EXPIRE_BARS=0     Barras máx por trade (0=OFF)"
echo "  □ MIN_PROFIT_PCT=0.0      Profit mín para salir por señal"
echo ""

# ─────────────────────────────────────────────────────────────
# 5. Sintaxis Python
# ─────────────────────────────────────────────────────────────
echo "━━━ 5. SINTAXIS PYTHON ━━━"
if command -v python3 &> /dev/null; then
    if python3 -m py_compile bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} bot.py sin errores de sintaxis"
    else
        echo -e "${RED}✗${NC} bot.py tiene errores de sintaxis"
        python3 -m py_compile bot.py
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${YELLOW}⚠${NC} Python3 no disponible para verificar sintaxis"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 6. Estructura del código v13
# ─────────────────────────────────────────────────────────────
echo "━━━ 6. ESTRUCTURA DEL CÓDIGO ━━━"

CRITICAL_IMPORTS=("import ccxt" "import pandas" "import numpy" "import requests")
for import_line in "${CRITICAL_IMPORTS[@]}"; do
    if grep -q "$import_line" bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $import_line encontrado"
    else
        echo -e "${RED}✗${NC} $import_line NO encontrado"
        ERRORS=$((ERRORS + 1))
    fi
done

KEY_FUNCTIONS=("def main()" "def calc_smi" "def calc_utbot" "def calc_wavetrend" "def calc_bb" "def calc_rr_targets" "def confluence_score" "def manage_trade" "def open_trade")
for fn in "${KEY_FUNCTIONS[@]}"; do
    if grep -q "$fn" bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $fn definida"
    else
        echo -e "${RED}✗${NC} $fn NO encontrada"
        ERRORS=$((ERRORS + 1))
    fi
done

if grep -q "os.environ.get" bot.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Variables de entorno implementadas"
fi

# Verificar score 16
if grep -q "16" bot.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Score de 16 puntos detectado"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 7. Checklist GitHub/Railway/BingX
# ─────────────────────────────────────────────────────────────
echo "━━━ 7. PRE-DEPLOY CHECKLIST ━━━"
echo ""
echo "  □ Repositorio GitHub creado como PRIVADO"
echo "  □ Código pusheado al repositorio"
echo "  □ NO hay claves API en el código"
echo "  □ Railway: Variables OBLIGATORIAS configuradas"
echo "  □ Railway: Build completado sin errores"
echo "  □ Railway: Logs muestran 'SATY ELITE v13'"
echo "  □ Telegram: Mensaje de arranque recibido"
echo "  □ BingX: API Key con Read+Trade (sin Withdraw)"
echo "  □ BingX: Balance disponible en Perpetual Futures"
echo ""

# ─────────────────────────────────────────────────────────────
# RESUMEN
# ─────────────────────────────────────────────────────────────
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   RESUMEN DE VERIFICACIÓN                                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ VERIFICACIÓN AUTOMÁTICA EXITOSA${NC}"
    echo -e "  Todos los archivos y funciones de v13 detectados"
    echo ""
    echo -e "${YELLOW}⚠ COMPLETA LOS CHECKLISTS MANUALES ANTES DE DEPLOYAR${NC}"
    echo ""
    echo "Próximos pasos:"
    echo "  1. Configura las 4 variables OBLIGATORIAS en Railway"
    echo "  2. Verifica que el repositorio sea PRIVADO"
    echo "  3. Deploy desde Railway conectando el repo GitHub"
    echo "  4. Revisa logs: 'SATY ELITE v13 — FULL STRATEGY EDITION'"
    echo "  5. Verifica mensaje de arranque en Telegram"
    echo ""
    echo "  ⚡ RECORDATORIO v13: MIN_SCORE es sobre 16 (no 12)"
    echo "     Configura MIN_SCORE=5 para empezar balanceado"
else
    echo -e "${RED}✗ ERRORES DETECTADOS: $ERRORS${NC}"
    echo -e "  Revisa los errores arriba antes de deployar"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  SATY ELITE v13 — UTBot · WaveTrend · Bj Bot · BB+RSI · SMI"
echo "═══════════════════════════════════════════════════════════════"
