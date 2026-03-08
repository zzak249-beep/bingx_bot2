<#
🤖 SCRIPT POWERSHELL: BOT SUPERTREND CON TODAS LAS MONEDAS DE BINGX

Uso:
  .\ejecutar_supertrend_bingx.ps1 -Preset balanced -Interval 1h

Presets: conservative, balanced, aggressive
Intervals: 1m, 5m, 15m, 1h, 4h, 1d
#>

param(
    [string]$Preset = "balanced",
    [string]$Interval = "1h",
    [int]$Limit = 20,
    [switch]$Continuous = $false
)

# ═══════════════════════════════════════════════════════════════
# COLORES Y FUNCIONES
# ═══════════════════════════════════════════════════════════════

function Write-Success { Write-Host $args[0] -ForegroundColor Green }
function Write-Error { Write-Host $args[0] -ForegroundColor Red }
function Write-Warning { Write-Host $args[0] -ForegroundColor Yellow }
function Write-Info { Write-Host $args[0] -ForegroundColor Cyan }

# ═══════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════

Write-Host "`n╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Cyan
Write-Host "║    🤖 BOT SUPERTREND - TODAS LAS MONEDAS DE BINGX              ║" -ForegroundColor Cyan
Write-Host "║    Descarga automáticamente TODO y ejecuta estrategia          ║" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN
# ═══════════════════════════════════════════════════════════════

Write-Info "🔍 Validando entorno..."

# Python
try {
    $pythonVersion = python --version 2>&1
    Write-Success "✅ Python: $pythonVersion"
} catch {
    Write-Error "❌ Python no instalado"
    exit
}

# Archivos necesarios
$requiredFiles = @(
    "bingx_api_supertrend.py",
    "strategy_supertrend.py",
    "indicators_supertrend.py",
    "config_supertrend.py"
)

foreach ($file in $requiredFiles) {
    if (-Not (Test-Path $file)) {
        Write-Error "❌ Falta archivo: $file"
        exit
    }
}

Write-Success "✅ Todos los archivos necesarios encontrados`n"

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

Write-Info "⚙️  Configuración:"
Write-Host "   Preset:    $Preset"
Write-Host "   Intervalo: $Interval"
Write-Host "   Velas:     $Limit"
Write-Host "   Continuo:  $(if ($Continuous) { 'Sí' } else { 'No' })`n"

# ═══════════════════════════════════════════════════════════════
# EJECUTAR
# ═══════════════════════════════════════════════════════════════

Write-Info "🚀 Iniciando bot Supertrend...`n"

# Una vez
$command = "python bingx_api_supertrend.py --preset $Preset --interval $Interval --limit $Limit"

if ($Continuous) {
    # Ejecutar continuamente
    Write-Info "🔄 Modo continuo (cada hora)"
    
    $cycle = 0
    while ($true) {
        $cycle++
        Write-Info "`n📊 CICLO #$cycle - $(Get-Date -Format 'HH:mm:ss')"
        Write-Host "━" * 70
        
        # Ejecutar
        Invoke-Expression $command
        
        # Esperar 1 hora
        Write-Info "`n⏳ Esperando 1 hora para el próximo análisis..."
        Write-Info "    (Presiona Ctrl+C para detener)"
        
        Start-Sleep -Seconds 3600
    }
} else {
    # Ejecutar una vez
    Invoke-Expression $command
}

# ═══════════════════════════════════════════════════════════════
# RESULTADOS
# ═══════════════════════════════════════════════════════════════

Write-Success "`n✅ Análisis completado"
Write-Info "📁 Resultados guardados en: signals_*.json"
Write-Info "📊 Log guardado en: bingx_supertrend.log`n"

Write-Info "Próximos pasos:"
Write-Host "  1. Revisar signals_*.json para ver señales"
Write-Host "  2. Implementar trading automático en BingX API"
Write-Host "  3. Usar TRADE_MODE='live' para dinero real`n"
