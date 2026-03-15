# ================================================================
# instalar_y_backtest.ps1
# Ejecutar desde la carpeta donde esta backtest_bellsz.py
# ================================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  BACKTEST BELLSZ - Setup y Ejecucion" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Carpeta actual del script
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $carpeta -or $carpeta -eq "") { $carpeta = (Get-Location).Path }
Write-Host "  Carpeta: $carpeta" -ForegroundColor DarkGray
Write-Host ""

# PASO 1: Buscar backtest_bellsz.py
Write-Host "[1/4] Buscando backtest_bellsz.py..." -ForegroundColor Yellow
$backtest = Join-Path $carpeta "backtest_bellsz.py"
if (-not (Test-Path $backtest)) {
    $backtest = Join-Path (Get-Location).Path "backtest_bellsz.py"
}
if (-not (Test-Path $backtest)) {
    Write-Host "  ERROR: backtest_bellsz.py no encontrado." -ForegroundColor Red
    Write-Host "  Pon instalar_y_backtest.ps1 en la misma carpeta que backtest_bellsz.py" -ForegroundColor Yellow
    Read-Host "Pulsa Enter para salir"
    exit 1
}
Write-Host "  OK: $backtest" -ForegroundColor Green

# PASO 2: Buscar Python
Write-Host ""
Write-Host "[2/4] Buscando Python..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ("$ver" -match "Python 3") {
            Write-Host "  OK: $ver  (comando: $cmd)" -ForegroundColor Green
            $pythonCmd = $cmd
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "  Python no encontrado. Intentando instalar con winget..." -ForegroundColor Yellow
    try {
        winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
        $pythonCmd = "python"
        Write-Host "  Python instalado." -ForegroundColor Green
    } catch {
        Write-Host "  ERROR: Instala Python manualmente desde https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "  Marca 'Add Python to PATH' al instalar." -ForegroundColor Yellow
        Read-Host "Pulsa Enter para salir"
        exit 1
    }
}

# PASO 3: Instalar requests
Write-Host ""
Write-Host "[3/4] Verificando libreria requests..." -ForegroundColor Yellow
$check = & $pythonCmd -c "import requests; print('ok')" 2>&1
if ("$check" -ne "ok") {
    Write-Host "  Instalando requests..." -ForegroundColor Yellow
    & $pythonCmd -m pip install requests --quiet
    Write-Host "  requests instalado." -ForegroundColor Green
} else {
    Write-Host "  requests OK" -ForegroundColor Green
}

# PASO 4: Ejecutar
Write-Host ""
Write-Host "[4/4] Lanzando backtest..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Tardara 5-25 minutos segun tu conexion." -ForegroundColor DarkYellow
Write-Host "  Resultado en: backtest_bellsz_results.json" -ForegroundColor DarkYellow
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$t0 = Get-Date
Set-Location $carpeta
& $pythonCmd $backtest

$mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Finalizado en $mins minutos" -ForegroundColor Green
$json = Join-Path $carpeta "backtest_bellsz_results.json"
if (Test-Path $json) {
    Write-Host "  Resultados guardados en: $json" -ForegroundColor Green
}
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Pulsa Enter para cerrar"
