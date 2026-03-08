# Script automatizado - ejecuta Supertrend cada hora indefinidamente
# Con logging, estadísticas y notificaciones

param(
    [string]$Preset = "balanced",
    [int]$IntervalMinutes = 60,
    [switch]$Continuous = $true
)

# ═══════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════

$botVersion = "v2.0-OPTIMIZADO"
$startTime = Get-Date
$cycleCount = 0
$totalTrades = 0
$logFile = "supertrend_auto.log"

# Crear log
function Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    Add-Content -Path $logFile -Value $logMessage
    Write-Host $logMessage -ForegroundColor Cyan
}

Log "═══════════════════════════════════════════════════════════════"
Log "🤖 BOT SUPERTREND AUTOMATIZADO INICIADO"
Log "═══════════════════════════════════════════════════════════════"
Log "Versión: $botVersion"
Log "Preset: $Preset"
Log "Intervalo: $IntervalMinutes minutos"
Log "Modo: $(if ($Continuous) { 'CONTINUO (indefinido)' } else { 'UNA VEZ' })"

# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN
# ═══════════════════════════════════════════════════════════════

if (-not (Test-Path "bingx_api_supertrend.py")) {
    Log "❌ ERROR: bingx_api_supertrend.py no encontrado"
    exit
}

Log "✅ Archivo estrategia encontrado"
Log "✅ Sistema listo"
Log ""

# ═══════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════════

if ($Continuous) {
    Log "🔄 Modo continuo activado (Ctrl+C para detener)"
    Log ""
}

while ($true) {
    $cycleCount++
    $cycleStartTime = Get-Date
    
    # Header del ciclo
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
    Write-Host "║                                                        ║" -ForegroundColor Magenta
    Write-Host "║  📊 CICLO #$cycleCount - $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Magenta
    Write-Host "║                                                        ║" -ForegroundColor Magenta
    Write-Host "╚════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
    Write-Host ""
    
    Log ""
    Log "╔════════════════════════════════════════════════════════╗"
    Log "📊 CICLO #$cycleCount - $(Get-Date -Format 'HH:mm:ss')"
    Log "╚════════════════════════════════════════════════════════╝"
    
    # Ejecutar bot
    $output = & python bingx_api_supertrend.py --preset $Preset 2>&1
    
    # Parsear resultados
    foreach ($line in $output) {
        Write-Host $line
        Log $line
    }
    
    # Estadísticas del ciclo
    $cycleEndTime = Get-Date
    $cycleDuration = ($cycleEndTime - $cycleStartTime).TotalSeconds
    
    Log ""
    Log "✅ Ciclo completado en $([Math]::Round($cycleDuration, 1)) segundos"
    Log "📊 Total de ciclos completados: $cycleCount"
    
    # Si no es continuo, salir
    if (-not $Continuous) {
        Log ""
        Log "✅ Ejecución completada (modo única ejecución)"
        break
    }
    
    # Mostrar próximo ciclo
    $nextCycleTime = $cycleEndTime.AddMinutes($IntervalMinutes)
    
    Write-Host ""
    Write-Host "⏳ Próximo análisis en $IntervalMinutes minutos..." -ForegroundColor Yellow
    Write-Host "   A las: $($nextCycleTime.ToString('HH:mm:ss'))" -ForegroundColor Yellow
    Write-Host "   Presiona Ctrl+C para detener" -ForegroundColor Yellow
    Write-Host ""
    
    Log ""
    Log "⏳ Esperando $IntervalMinutes minutos hasta próximo análisis..."
    Log "   Próximo ciclo: $($nextCycleTime.ToString('HH:mm:ss'))"
    
    # Esperar
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}

# ═══════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════

$endTime = Get-Date
$totalDuration = ($endTime - $startTime).TotalSeconds

Log ""
Log "════════════════════════════════════════════════════════════"
Log "✅ SESIÓN COMPLETADA"
Log "════════════════════════════════════════════════════════════"
Log "Ciclos ejecutados: $cycleCount"
Log "Tiempo total: $([Math]::Round($totalDuration / 60, 1)) minutos"
Log "Duración promedio por ciclo: $([Math]::Round($totalDuration / $cycleCount, 1)) segundos"
Log ""
Log "📁 Log guardado en: $logFile"
Log "📁 Señales guardadas en: signals_*.json"
Log ""
Log "✅ Bot desactivado"
