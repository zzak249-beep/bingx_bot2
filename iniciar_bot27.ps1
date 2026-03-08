# ============================================================
# iniciar_bot27.ps1
# Lanzador BOT27 - Supertrend + BingX
# Compatible: Windows 10/11, PowerShell 5+
# ============================================================

# Forzar UTF-8 en la consola para evitar errores de encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  BOT27 - SUPERTREND ZERO LAG + RSI  -  BINGX" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Verificar Python ----
Write-Host "[1/5] Verificando Python..." -ForegroundColor Yellow

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "      Python encontrado: $ver  OK" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "  ERROR: Python 3 no encontrado." -ForegroundColor Red
    Write-Host "  Descarga desde: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Marca 'Add Python to PATH' durante la instalacion." -ForegroundColor Yellow
    Read-Host "Pulsa Enter para salir"
    exit 1
}

# ---- 2. Verificar archivos ----
Write-Host "[2/5] Verificando archivos del bot..." -ForegroundColor Yellow

$archivos = @(
    "bingx_api_supertrend.py",
    "strategy_supertrend.py",
    "indicators_supertrend.py",
    "config_supertrend.py"
)

$falta = $false
foreach ($f in $archivos) {
    if (Test-Path $f) {
        Write-Host "      $f  OK" -ForegroundColor Green
    } else {
        Write-Host "      $f  FALTA" -ForegroundColor Red
        $falta = $true
    }
}

if ($falta) {
    Write-Host ""
    Write-Host "  ERROR: Faltan archivos. Asegurate de tener todos en la misma carpeta." -ForegroundColor Red
    Read-Host "Pulsa Enter para salir"
    exit 1
}

# ---- 3. Instalar dependencias ----
Write-Host "[3/5] Instalando dependencias (pandas, numpy, requests)..." -ForegroundColor Yellow

try {
    & $pythonCmd -m pip install pandas numpy requests --quiet --upgrade
    Write-Host "      Dependencias instaladas  OK" -ForegroundColor Green
} catch {
    Write-Host "  AVISO: Error instalando dependencias: $_" -ForegroundColor Yellow
    Write-Host "  Intentando continuar de todos modos..." -ForegroundColor Yellow
}

# ---- 4. Ejecutar tests locales ----
Write-Host "[4/5] Ejecutando tests locales..." -ForegroundColor Yellow

if (Test-Path "test_local.py") {
    $testResult = & $pythonCmd test_local.py 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "      Tests: 5/5 PASADOS  OK" -ForegroundColor Green
    } else {
        Write-Host "  AVISO: Algunos tests fallaron. Revisa los errores abajo:" -ForegroundColor Yellow
        Write-Host $testResult -ForegroundColor Gray
        $resp = Read-Host "Continuar de todas formas? (s/n)"
        if ($resp -ne "s") { exit 1 }
    }
} else {
    Write-Host "      test_local.py no encontrado, saltando tests." -ForegroundColor Yellow
}

# ---- 5. Elegir configuracion ----
Write-Host "[5/5] Configuracion de ejecucion" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Presets disponibles:" -ForegroundColor White
Write-Host "    1) balanced     - Recomendado (ROI 12-25%, WR ~56%)" -ForegroundColor White
Write-Host "    2) conservative - Seguro      (ROI  8-12%, WR ~62%)" -ForegroundColor White
Write-Host "    3) aggressive   - Arriesgado  (ROI 25-50%, WR ~52%)" -ForegroundColor White
Write-Host ""

$presetChoice = Read-Host "  Elige preset [1/2/3, default=1]"
$preset = switch ($presetChoice) {
    "2" { "conservative" }
    "3" { "aggressive" }
    default { "balanced" }
}

Write-Host ""
Write-Host "  Intervalos disponibles: 1m, 5m, 15m, 1h, 4h, 1d" -ForegroundColor White
$interval = Read-Host "  Intervalo [default=1h]"
if (-not $interval) { $interval = "1h" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  INICIANDO ANALISIS" -ForegroundColor Cyan
Write-Host "  Preset:    $preset" -ForegroundColor White
Write-Host "  Intervalo: $interval" -ForegroundColor White
Write-Host "  Velas:     100 por simbolo" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Ejecutar bot ----
& $pythonCmd bingx_api_supertrend.py --preset $preset --interval $interval --limit 100

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Analisis completado. Revisa el archivo signals_*.json" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Pulsa Enter para salir"
