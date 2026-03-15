import requests, time

print('Descargando BTC...')
end = int(time.time() * 1000)
start = end - 60 * 86400000

c1h = [{'ts':int(x[0]),'high':float(x[2]),'low':float(x[3])} for x in requests.get('https://api.binance.com/api/v3/klines', params={'symbol':'BTCUSDT','interval':'1h','limit':200}, timeout=15).json()]
c5  = [{'ts':int(x[0]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4])} for x in requests.get('https://api.binance.com/api/v3/klines', params={'symbol':'BTCUSDT','interval':'5m','startTime':start,'endTime':end,'limit':1000}, timeout=15).json()]

print(f'Velas: 5m={len(c5)} 1h={len(c1h)}')

purgas_l = purgas_s = 0
for i in range(60, len(c5)):
    c = c5[i]
    ts = c['ts']
    m = c['close'] * 0.005
    hist = [x for x in c1h if x['ts'] < ts]
    if len(hist) < 15:
        continue
    zona = hist[-(35):-5]
    if not zona:
        continue
    bsl = max(x['high'] for x in zona)
    ssl = min(x['low']  for x in zona)
    if c['low'] <= ssl + m and c['close'] > ssl:
        purgas_l += 1
    if c['high'] >= bsl - m and c['close'] < bsl:
        purgas_s += 1

print(f'Purgas LONG : {purgas_l}')
print(f'Purgas SHORT: {purgas_s}')
print(f'Total       : {purgas_l + purgas_s}')
if purgas_l + purgas_s > 0:
    print('FIX FUNCIONA - hay purgas detectadas')
else:
    print('SIGUE SIN PURGAS')