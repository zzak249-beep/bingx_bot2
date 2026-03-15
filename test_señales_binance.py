import requests, time

LIQ_MARGEN   = 0.1
LIQ_LOOKBACK = 50
PARES = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
         "AVAXUSDT","DOGEUSDT","LINKUSDT","NEARUSDT","ARBUSDT",
         "AAVEUSDT","OPUSDT","INJUSDT","APTUSDT","SUIUSDT"]

def get_candles(sym, interval, limit=200):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol":sym,"interval":interval,"limit":limit}, timeout=12)
    return [{"ts":int(c[0]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"open":float(c[1]),"volume":float(c[5])}
            for c in r.json()]

def calc_ema(prices, period):
    if len(prices) < period: return None
    k = 2/(period+1); v = sum(prices[:period])/period
    for p in prices[period:]: v = p*k+v*(1-k)
    return v

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50.0
    d = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    ag = sum(max(x,0) for x in d[:period])/period
    al = sum(abs(min(x,0)) for x in d[:period])/period
    for x in d[period:]:
        ag=(ag*(period-1)+max(x,0))/period; al=(al*(period-1)+abs(min(x,0)))/period
    return 100.0 if al==0 else 100-100/(1+ag/al)

print("="*60)
print(f"  TEST PURGAS — LIQ_MARGEN={LIQ_MARGEN}% (Pine Script replica)")
print("="*60)

total_purgas = señales = 0
for sym in PARES:
    try:
        c5  = get_candles(sym, "5m",  200)
        c1h = get_candles(sym, "1h",  60)
        c4h = get_candles(sym, "4h",  60)
        c1d = get_candles(sym, "1d",  35)
        if len(c5) < 80: continue

        precio = c5[-1]["close"]
        c_act  = c5[-1]
        m = LIQ_MARGEN / 100

        # Niveles (lookahead_off = excluir última vela)
        def niv(candles):
            if len(candles) < 6: return 0,0
            rec = candles[:-1][-LIQ_LOOKBACK:]
            return max(x["high"] for x in rec), min(x["low"] for x in rec)

        bsl1,ssl1 = niv(c1h)
        bsl4,ssl4 = niv(c4h)
        bsld,ssld = niv(c1d)

        pa1 = ssl1>0 and c_act["low"]<=ssl1*(1+m) and c_act["close"]>ssl1
        pb1 = bsl1>0 and c_act["high"]>=bsl1*(1-m) and c_act["close"]<bsl1
        pa4 = ssl4>0 and c_act["low"]<=ssl4*(1+m) and c_act["close"]>ssl4
        pb4 = bsl4>0 and c_act["high"]>=bsl4*(1-m) and c_act["close"]<bsl4
        pad = ssld>0 and c_act["low"]<=ssld*(1+m) and c_act["close"]>ssld
        pbd = bsld>0 and c_act["high"]>=bsld*(1-m) and c_act["close"]<bsld

        purga_l = pa1 or pa4 or pad
        purga_s = pb1 or pb4 or pbd

        cl  = [c["close"] for c in c5]
        er  = calc_ema(cl, 9); el = calc_ema(cl, 21)
        rv  = calc_rsi(cl[-50:])
        bull = er and el and er > el*1.001
        bear = er and el and er < el*0.999
        rsi_ok = 30 < rv < 70

        # Contar purgas históricas últimas 200 velas
        ph_l = ph_s = 0
        for i in range(60, min(len(c5), 200)):
            ci = c5[i]; ts = ci["ts"]
            h1h = [x for x in c1h if x["ts"]<ts]
            h4h = [x for x in c4h if x["ts"]<ts]
            hdh = [x for x in c1d if x["ts"]<ts]
            if not h1h or not h4h or not hdh: continue
            b1s,s1s = max(x["high"] for x in h1h[-LIQ_LOOKBACK:]), min(x["low"] for x in h1h[-LIQ_LOOKBACK:])
            b4s,s4s = max(x["high"] for x in h4h[-LIQ_LOOKBACK:]), min(x["low"] for x in h4h[-LIQ_LOOKBACK:])
            bds,sds = max(x["high"] for x in hdh[-30:]),            min(x["low"] for x in hdh[-30:])
            if any([ci["low"]<=s1s*(1+m) and ci["close"]>s1s,
                    ci["low"]<=s4s*(1+m) and ci["close"]>s4s,
                    ci["low"]<=sds*(1+m) and ci["close"]>sds]): ph_l+=1
            if any([ci["high"]>=b1s*(1-m) and ci["close"]<b1s,
                    ci["high"]>=b4s*(1-m) and ci["close"]<b4s,
                    ci["high"]>=bds*(1-m) and ci["close"]<bds]): ph_s+=1

        d_ssl = min(abs(precio-ssl1)/precio*100, abs(precio-ssl4)/precio*100, abs(precio-ssld)/precio*100)
        d_bsl = min(abs(precio-bsl1)/precio*100, abs(precio-bsl4)/precio*100, abs(precio-bsld)/precio*100)

        estado = ""
        if purga_l: estado = "✅ PURGA LONG"
        elif purga_s: estado = "✅ PURGA SHORT"
        else: estado = f"⏳ dist SSL:{d_ssl:.2f}% BSL:{d_bsl:.2f}%"

        ema_str = "BULL" if bull else ("BEAR" if bear else "FLAT")
        base_ok = (purga_l and (bull or rsi_ok)) or (purga_s and (bear or rsi_ok))

        print(f"{sym:12s} {precio:>10.4f} | {estado:30s} | EMA:{ema_str} RSI:{rv:.0f} | hist L:{ph_l} S:{ph_s}")

        if purga_l or purga_s:
            total_purgas += 1
            if base_ok: señales += 1

        time.sleep(0.15)
    except Exception as e:
        print(f"{sym:12s} ERROR: {e}")

print("="*60)
print(f"  Purgas activas AHORA: {total_purgas}")
print(f"  Señales con confirmación: {señales}")
print()
if total_purgas == 0:
    print("  El mercado NO está en ningún nivel de liquidez ahora mismo.")
    print("  Las purgas ocurren ~3-8 veces/día por par en 5m.")
    print("  El bot detectará la próxima automáticamente.")
else:
    print("  ✅ HAY SEÑALES — el bot debería ejecutar")
print("="*60)
