import requests, time

c1h = [{'ts':int(x[0]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4])} for x in requests.get('https://api.binance.com/api/v3/klines', params={'symbol':'BTCUSDT','interval':'1h','limit':200}, timeout=15).json()]

print(f"Total velas 1h: {len(c1h)}")
print(f"Precio actual BTC: {c1h[-1]['close']:.2f}")
print(f"Maximo ultimas 30 velas (zona -35:-5): {max(x['high'] for x in c1h[-35:-5]):.2f}")
print(f"Minimo ultimas 30 velas (zona -35:-5): {min(x['low']  for x in c1h[-35:-5]):.2f}")
print(f"Maximo ultimas 5 velas (excluidas): {max(x['high'] for x in c1h[-5:]):.2f}")
print(f"Minimo ultimas 5 velas (excluidas): {min(x['low']  for x in c1h[-5:]):.2f}")
print()

# Ver si el precio actual toca el nivel
bsl = max(x['high'] for x in c1h[-35:-5])
ssl = min(x['low']  for x in c1h[-35:-5])
precio = c1h[-1]['close']
margen = precio * 0.005

print(f"BSL (resistencia): {bsl:.2f}")
print(f"SSL (soporte):     {ssl:.2f}")
print(f"Precio actual:     {precio:.2f}")
print(f"Margen (0.5%):     {margen:.2f}")
print()
print(f"Precio cerca de SSL? {abs(precio - ssl) < margen*10:.0f} (diferencia: {abs(precio-ssl):.2f})")
print(f"Precio cerca de BSL? {abs(precio - bsl) < margen*10:.0f} (diferencia: {abs(precio-bsl):.2f})")
print()

# Contar cuantas velas 1h tocaron SSL o BSL en las 200 velas
toca_ssl = sum(1 for x in c1h if x['low'] <= ssl + margen)
toca_bsl = sum(1 for x in c1h if x['high'] >= bsl - margen)
cierra_sobre_ssl = sum(1 for x in c1h if x['low'] <= ssl + margen and x['close'] > ssl)
cierra_bajo_bsl  = sum(1 for x in c1h if x['high'] >= bsl - margen and x['close'] < bsl)

print(f"Velas que tocan SSL:              {toca_ssl}")
print(f"Velas que tocan SSL y cierran arriba (PURGA LONG): {cierra_sobre_ssl}")
print(f"Velas que tocan BSL:              {toca_bsl}")
print(f"Velas que tocan BSL y cierran abajo (PURGA SHORT): {cierra_bajo_bsl}")