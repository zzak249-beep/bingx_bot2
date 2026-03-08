# Ejecutar cada hora (automático, sin parar)
# Presiona Ctrl+C para detener

$cycle = 0
while ($true) {
    $cycle++
    Write-Host "`n🔄 CICLO #$cycle - $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Cyan
    Write-Host ("="*70) -ForegroundColor Cyan
    
    python bingx_api_supertrend.py --preset balanced --interval 1h
    
    Write-Host "`n⏳ Próximo análisis en 1 hora..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3600
}
