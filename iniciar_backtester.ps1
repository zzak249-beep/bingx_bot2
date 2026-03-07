# Script simple que funciona desde cualquier carpeta

Write-Host "`n🚀 Iniciando Backtester...`n" -ForegroundColor Cyan

# Encontrar el archivo backtester_agresivo.py
$backtesterPath = "backtester_agresivo.py"

# Si no está en carpeta actual, buscar en carpetas comunes
if (-Not (Test-Path $backtesterPath)) {
    Write-Host "⏳ Buscando archivo en carpetas..." -ForegroundColor Yellow
    
    $carpetasComunes = @(
        "$env:USERPROFILE\Downloads\",
        "$env:USERPROFILE\Descargas\",
        ".\",
        "..\",
        "$env:USERPROFILE\Desktop\bot-backtesting\"
    )
    
    foreach ($carpeta in $carpetasComunes) {
        if (Test-Path "$carpeta$backtesterPath") {
            Set-Location $carpeta
            Write-Host "✅ Encontrado en: $(Get-Location)" -ForegroundColor Green
            $backtesterPath = "backtester_agresivo.py"
            break
        }
    }
}

# Verificar Python
Write-Host "`n🔍 Verificando Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ $pythonVersion`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Python no instalado. Descárgalo de https://www.python.org/" -ForegroundColor Red
    exit
}

# Verificar archivo
if (-Not (Test-Path $backtesterPath)) {
    Write-Host "❌ backtester_agresivo.py no encontrado" -ForegroundColor Red
    Write-Host "`nIntenta esto:" -ForegroundColor Yellow
    Write-Host "  1. Navega a la carpeta donde descargaste los archivos" -ForegroundColor Gray
    Write-Host "  2. Abre PowerShell en esa carpeta (clic derecho > Open PowerShell)" -ForegroundColor Gray
    Write-Host "  3. Ejecuta: python backtester_agresivo.py" -ForegroundColor Gray
    exit
}

# Ejecutar
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "📊 Ejecutando backtester..." -ForegroundColor Cyan
Write-Host "   (Esto toma ~1 minuto)" -ForegroundColor Gray
Write-Host "═══════════════════════════════════════════════════════════════`n" -ForegroundColor Cyan

python $backtesterPath

Write-Host "`n" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "✅ Backtester completado!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green

# Intentar abrir resultados
if (Test-Path "backtest_results.json") {
    Write-Host "`n📊 Abriendo resultados..." -ForegroundColor Cyan
    notepad backtest_results.json
}

Write-Host "`n🎯 Próximos pasos:" -ForegroundColor Yellow
Write-Host "  1. Lee PLAN_AGRESIVO_MAXIMA_RENTABILIDAD.md" -ForegroundColor Gray
Write-Host "  2. Elige qué opción implementar" -ForegroundColor Gray
Write-Host "  3. Implementa los cambios" -ForegroundColor Gray
Write-Host "  4. Deploy a Railway`n" -ForegroundColor Gray
