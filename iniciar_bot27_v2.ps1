# ============================================================
# iniciar_bot27_v2.ps1 - BOT27 v2 Launcher
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  BOT27 v2 - SUPERTREND + APRENDIZAJE + 24/7" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Python ---
$py = $null
foreach ($cmd in @("python","python3","py")) {
    try { $v = & $cmd --version 2>&1; if ($v -match "Python 3") { $py = $cmd; break } } catch {}
}
if (-not $py) { Write-Host "ERROR: Python 3 no encontrado" -ForegroundColor Red; Read-Host; exit 1 }
Write-Host "[OK] Python: $(& $py --version 2>&1)" -ForegroundColor Green

# --- Dependencias ---
Write-Host "Instalando dependencias..." -ForegroundColor Yellow
& $py -m pip install pandas numpy requests python-dotenv --quiet --upgrade
Write-Host "[OK] Dependencias instaladas" -ForegroundColor Green

# --- .env ---
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host ""
        Write-Host "  IMPORTANTE: Edita el archivo .env con tus datos antes de continuar:" -ForegroundColor Yellow
        Write-Host "    BINGX_API_KEY, BINGX_SECRET_KEY" -ForegroundColor Yellow
        Write-Host "    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID" -ForegroundColor Yellow
        Write-Host ""
        $open = Read-Host "  Abrir .env en Notepad ahora? [s/n]"
        if ($open -eq "s") { notepad .env; Read-Host "  Pulsa Enter cuando hayas guardado el .env" }
    }
}

# --- Modo ---
Write-Host ""
Write-Host "  Selecciona modo de ejecucion:" -ForegroundColor White
Write-Host "    1) SIMULACION (DRY_RUN=true)  <- RECOMENDADO primero" -ForegroundColor Green
Write-Host "    2) LIVE REAL  (DRY_RUN=false) <- Solo si ya probaste en simulacion" -ForegroundColor Red
$modo = Read-Host "  [1/2, default=1]"

if ($modo -eq "2") {
    Write-Host ""
    Write-Host "  ADVERTENCIA: Vas a operar con DINERO REAL." -ForegroundColor Red
    Write-Host "  Asegurate de haber probado al menos 1 semana en simulacion." -ForegroundColor Red
    $confirm = Read-Host "  Escribir 'SI' para confirmar"
    if ($confirm -ne "SI") { Write-Host "Cancelado."; exit 0 }
    $env:DRY_RUN = "false"
} else {
    $env:DRY_RUN = "true"
}

# --- Preset ---
Write-Host ""
Write-Host "  Preset:" -ForegroundColor White
Write-Host "    1) balanced     (recomendado)" -ForegroundColor White
Write-Host "    2) conservative (mas seguro)" -ForegroundColor White
Write-Host "    3) aggressive   (mas trades)" -ForegroundColor White
$p = Read-Host "  [1/2/3, default=1]"
$env:PRESET = switch ($p) { "2" {"conservative"} "3" {"aggressive"} default {"balanced"} }

# --- Intervalo ---
Write-Host ""
$iv = Read-Host "  Intervalo [1h/4h/15m, default=1h]"
if (-not $iv) { $iv = "1h" }
$valid = @('1m','5m','15m','30m','1h','2h','4h','1d'); if ($valid -contains $iv) { $env:INTERVAL = $iv } else { $env:INTERVAL = '1h' }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  INICIANDO BOT27 v2" -ForegroundColor Cyan
Write-Host "  Modo:      $(if ($env:DRY_RUN -eq 'true') {'SIMULACION'} else {'LIVE REAL'})" -ForegroundColor $(if ($env:DRY_RUN -eq 'true') {'Green'} else {'Red'})
Write-Host "  Preset:    $($env:PRESET)" -ForegroundColor White
Write-Host "  Intervalo: $($env:INTERVAL)" -ForegroundColor White
Write-Host "  Ctrl+C para detener" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

& $py main_bot.py
