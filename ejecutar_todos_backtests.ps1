# Script Master PowerShell para ejecutar todos los backtests

Write-Host "`n╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Cyan
Write-Host "║  🤖 BOT BACKTESTING SUITE - Script Master PowerShell           ║" -ForegroundColor Cyan
Write-Host "║  Ejecuta backtests simulados + históricos                      ║" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Verificar Python
Write-Host "🔍 Verificando Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python no encontrado. Instala desde https://www.python.org/" -ForegroundColor Red
    exit
}

# Menú
Write-Host "`n═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Selecciona qué backtests ejecutar:" -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "1. Backtests SIMULADOS (6 escenarios, recomendado)" -ForegroundColor Green
Write-Host "2. Backtests HISTÓRICOS (si tienes CSV con trades)" -ForegroundColor Green
Write-Host "3. AMBOS (completo)" -ForegroundColor Green
Write-Host "0. Salir" -ForegroundColor Red

$opcion = Read-Host "Opción (1-3, 0 para salir)"

if ($opcion -eq "0") { exit }

# OPCIÓN 1: Backtests simulados
if ($opcion -eq "1" -or $opcion -eq "3") {
    Write-Host "`n" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "🧪 Ejecutando BACKTESTS SIMULADOS..." -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "(Simula 12 meses con 6 escenarios diferentes)" -ForegroundColor Gray
    Write-Host ""
    
    if (Test-Path "backtester_agresivo.py") {
        python backtester_agresivo.py
        Write-Host "`n✅ Backtests simulados completados" -ForegroundColor Green
        Write-Host "📊 Resultados en: backtest_results.json" -ForegroundColor Green
    } else {
        Write-Host "❌ backtester_agresivo.py no encontrado" -ForegroundColor Red
    }
}

# OPCIÓN 2: Backtests históricos
if ($opcion -eq "2" -or $opcion -eq "3") {
    Write-Host "`n" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "📈 Ejecutando BACKTESTS HISTÓRICOS..." -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    
    # Buscar archivo de datos
    $csvFiles = @(Get-ChildItem -Filter "*.csv" -ErrorAction SilentlyContinue)
    $jsonFiles = @(Get-ChildItem -Filter "*.json" -ErrorAction SilentlyContinue)
    
    if ($csvFiles.Count -eq 0 -and $jsonFiles.Count -eq 0) {
        Write-Host "⚠️  No se encontró archivo de trades (CSV o JSON)" -ForegroundColor Yellow
        Write-Host "   Crea un archivo trades.csv con columnas: date,symbol,pnl,side" -ForegroundColor Yellow
        Read-Host "Presiona Enter para continuar"
    } else {
        # Seleccionar archivo
        Write-Host "`nArchivos disponibles:" -ForegroundColor Yellow
        $allFiles = @($csvFiles + $jsonFiles)
        for ($i = 0; $i -lt $allFiles.Count; $i++) {
            Write-Host "  $($i+1). $($allFiles[$i].Name)" -ForegroundColor Green
        }
        
        $fileIndex = [int](Read-Host "Selecciona archivo (número)") - 1
        
        if ($fileIndex -ge 0 -and $fileIndex -lt $allFiles.Count) {
            $dataFile = $allFiles[$fileIndex].FullName
            Write-Host "`n▶ Procesando $($allFiles[$fileIndex].Name)..." -ForegroundColor Cyan
            
            if (Test-Path "backtester_historico.py") {
                python backtester_historico.py --data $dataFile
                Write-Host "`n✅ Backtests históricos completados" -ForegroundColor Green
                Write-Host "📊 Resultados en: backtest_historico.json" -ForegroundColor Green
            } else {
                Write-Host "❌ backtester_historico.py no encontrado" -ForegroundColor Red
            }
        }
    }
}

# Resumen final
Write-Host "`n" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "📋 RESUMEN" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan

if (Test-Path "backtest_results.json") {
    Write-Host "✅ backtest_results.json - Backtests simulados" -ForegroundColor Green
}
if (Test-Path "backtest_historico.json") {
    Write-Host "✅ backtest_historico.json - Backtests históricos" -ForegroundColor Green
}

Write-Host "`n" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "PRÓXIMOS PASOS:" -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "1. 📖 Lee PLAN_AGRESIVO_MAXIMA_RENTABILIDAD.md" -ForegroundColor Green
Write-Host "2. 🎯 Elige qué opción implementar (1, 2 o 3)" -ForegroundColor Green
Write-Host "3. 💻 Implementa los cambios en tu bot" -ForegroundColor Green
Write-Host "4. 🚀 Deploy a Railway" -ForegroundColor Green
Write-Host "5. ✅ Validar en PAPER mode 1 semana" -ForegroundColor Green
Write-Host "6. 🔴 Cambiar a LIVE cuando confíes" -ForegroundColor Green

Write-Host "`nPulsaEnter para terminar..."
Read-Host
