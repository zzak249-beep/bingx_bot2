#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# VERIFICACIÓN PRE-DEPLOYMENT - SATY ELITE v11
# ═══════════════════════════════════════════════════════════════

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   CHECKLIST DE VERIFICACIÓN - SATY ELITE v11               ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# ─────────────────────────────────────────────────────────────
# 1. Verificar archivos del proyecto
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
# 2. Verificar contenido de archivos críticos
# ─────────────────────────────────────────────────────────────
echo "━━━ 2. CONTENIDO DE ARCHIVOS ━━━"

# Verificar Procfile
if grep -q "worker: python bot.py" Procfile 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Procfile configurado correctamente"
else
    echo -e "${RED}✗${NC} Procfile incorrecto o no encontrado"
    ERRORS=$((ERRORS + 1))
fi

# Verificar railway.toml
if grep -q "startCommand = \"python bot.py\"" railway.toml 2>/dev/null; then
    echo -e "${GREEN}✓${NC} railway.toml configurado correctamente"
else
    echo -e "${RED}✗${NC} railway.toml incorrecto"
    ERRORS=$((ERRORS + 1))
fi

# Verificar requirements.txt
REQUIRED_PACKAGES=("ccxt" "pandas" "numpy" "requests")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if grep -q "$package" requirements.txt 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $package en requirements.txt"
    else
        echo -e "${RED}✗${NC} $package NO ENCONTRADO en requirements.txt"
        ERRORS=$((ERRORS + 1))
    fi
done

# Verificar runtime.txt
if grep -q "python-3.11" runtime.txt 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Python 3.11 especificado en runtime.txt"
else
    echo -e "${YELLOW}⚠${NC} Verificar versión Python en runtime.txt"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 3. Verificar variables de entorno (simulación)
# ─────────────────────────────────────────────────────────────
echo "━━━ 3. VARIABLES DE ENTORNO (Checklist Manual) ━━━"
echo ""
echo "En Railway, asegúrate de configurar estas variables OBLIGATORIAS:"
echo ""
echo "  □ BINGX_API_KEY       → Tu API Key de BingX"
echo "  □ BINGX_API_SECRET    → Tu API Secret de BingX"
echo "  □ TELEGRAM_BOT_TOKEN  → Token de @BotFather"
echo "  □ TELEGRAM_CHAT_ID    → Tu Chat ID (o del grupo)"
echo ""
echo "Variables OPCIONALES (tienen valores por defecto):"
echo ""
echo "  □ FIXED_USDT          → USDT por trade (def: 8)"
echo "  □ MAX_OPEN_TRADES     → Trades máximos (def: 12)"
echo "  □ MIN_SCORE           → Score mínimo (def: 4)"
echo "  □ MAX_DRAWDOWN        → Circuit breaker % (def: 15)"
echo "  □ DAILY_LOSS_LIMIT    → Pérdida diaria % (def: 8)"
echo "  □ MIN_VOLUME_USDT     → Volumen mín 24h (def: 100000)"
echo "  □ TOP_N_SYMBOLS       → Pares a escanear (def: 300)"
echo "  □ MAX_SPREAD_PCT      → Spread máx % (def: 1.0)"
echo "  □ BTC_FILTER          → Filtro BTC (def: true)"
echo "  □ COOLDOWN_MIN        → Pausa post-cierre (def: 20)"
echo "  □ BLACKLIST           → Pares excluidos (def: vacío)"
echo ""

# ─────────────────────────────────────────────────────────────
# 4. Verificar sintaxis Python
# ─────────────────────────────────────────────────────────────
echo "━━━ 4. SINTAXIS PYTHON ━━━"
if command -v python3 &> /dev/null; then
    if python3 -m py_compile bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} bot.py sin errores de sintaxis"
    else
        echo -e "${RED}✗${NC} bot.py tiene errores de sintaxis"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${YELLOW}⚠${NC} Python3 no disponible para verificar sintaxis"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 5. Verificar estructura del código
# ─────────────────────────────────────────────────────────────
echo "━━━ 5. ESTRUCTURA DEL CÓDIGO ━━━"

# Verificar imports críticos
CRITICAL_IMPORTS=("import ccxt" "import pandas" "import numpy" "import requests")
for import_line in "${CRITICAL_IMPORTS[@]}"; do
    if grep -q "$import_line" bot.py 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $import_line encontrado"
    else
        echo -e "${RED}✗${NC} $import_line NO encontrado"
        ERRORS=$((ERRORS + 1))
    fi
done

# Verificar función main
if grep -q "def main()" bot.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Función main() definida"
else
    echo -e "${RED}✗${NC} Función main() NO encontrada"
    ERRORS=$((ERRORS + 1))
fi

# Verificar lectura de variables de entorno
if grep -q "os.environ.get" bot.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Lectura de variables de entorno implementada"
else
    echo -e "${RED}✗${NC} No se detecta lectura de variables de entorno"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 6. Checklist Git/GitHub
# ─────────────────────────────────────────────────────────────
echo "━━━ 6. GIT/GITHUB (Checklist Manual) ━━━"
echo ""
echo "Antes de deployar en Railway:"
echo ""
echo "  □ Repositorio creado en GitHub"
echo "  □ Repositorio configurado como PRIVADO"
echo "  □ .gitignore creado (opcional, para archivos locales)"
echo "  □ Código pusheado al repositorio"
echo "  □ Verificar que NO hay claves API en el código"
echo ""

# ─────────────────────────────────────────────────────────────
# 7. Checklist Railway
# ─────────────────────────────────────────────────────────────
echo "━━━ 7. RAILWAY (Checklist Manual) ━━━"
echo ""
echo "En Railway:"
echo ""
echo "  □ Proyecto creado desde GitHub repo"
echo "  □ Variables de entorno configuradas"
echo "  □ Build completado exitosamente"
echo "  □ Service estado: Running"
echo "  □ Logs muestran: 'SATY ELITE v11 — REAL MONEY'"
echo "  □ Logs muestran: 'Exchange conectado ✓'"
echo "  □ Recibido mensaje de Telegram de arranque"
echo ""

# ─────────────────────────────────────────────────────────────
# 8. Checklist BingX
# ─────────────────────────────────────────────────────────────
echo "━━━ 8. BINGX (Checklist Manual) ━━━"
echo ""
echo "Verificar en BingX:"
echo ""
echo "  □ API Key creada con permisos Read + Trade"
echo "  □ Withdraw permission DESACTIVADO"
echo "  □ IP whitelist configurada (o vacía si no es posible)"
echo "  □ Balance disponible en cuenta Perpetual Futures"
echo "  □ Modo de cuenta: Hedge Mode (recomendado) o One-Way"
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
    echo -e "  Todos los archivos y estructura correctos"
    echo ""
    echo -e "${YELLOW}⚠ COMPLETA LOS CHECKLISTS MANUALES ANTES DE DEPLOYAR${NC}"
    echo ""
    echo "Próximos pasos:"
    echo "  1. Configura las 4 variables OBLIGATORIAS en Railway"
    echo "  2. Verifica que el repositorio sea PRIVADO"
    echo "  3. Deploy desde Railway conectando el repo GitHub"
    echo "  4. Monitorea los logs en Railway"
    echo "  5. Verifica mensaje de arranque en Telegram"
else
    echo -e "${RED}✗ ERRORES DETECTADOS: $ERRORS${NC}"
    echo -e "  Revisa los errores arriba antes de deployar"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
