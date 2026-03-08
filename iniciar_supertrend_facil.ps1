# Script ultra simple - Una línea es todo lo que necesitas

Write-Host "`n🚀 Iniciando Bot Supertrend con TODAS las monedas...`n" -ForegroundColor Cyan

python bingx_api_supertrend.py --preset balanced --interval 1h --limit 20

Write-Host "`n✅ Completado. Revisa signals_*.json para ver las señales`n" -ForegroundColor Green
