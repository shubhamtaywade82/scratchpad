#!/usr/bin/env python3
"""SOLUSDT historical data analysis — indicators, stats, backtests."""
import json, math, statistics as st
from datetime import datetime, timezone

with open('data/SOLUSDT-klines.json') as f:
    blob = json.load(f)

def load(iv):
    ks = blob['data'][iv]
    return {
        't': [k['openTime'] for k in ks],
        'o': [float(k['open']) for k in ks],
        'h': [float(k['high']) for k in ks],
        'l': [float(k['low']) for k in ks],
        'c': [float(k['close']) for k in ks],
        'v': [float(k['volume']) for k in ks],
        'qv': [float(k['quoteAssetVolume']) for k in ks],
        'tb': [float(k['takerBuyBaseVolume']) for k in ks],
        'n': len(ks),
    }

D = {iv: load(iv) for iv in ['1d', '4h', '1h']}

def date(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')

def sma(xs, p):
    out = [None]*len(xs); s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= p: s -= xs[i-p]
        if i >= p-1: out[i] = s/p
    return out

def ema(xs, p):
    k = 2/(p+1); out = []; prev = None
    for x in xs:
        prev = x if prev is None else x*k + prev*(1-k)
        out.append(prev)
    return out

def rsi(closes, p=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[:p])/p; al = sum(losses[:p])/p
    out = [None]*p
    rs = ag/al if al else float('inf')
    out.append(100 - 100/(1+rs))
    for i in range(p, len(gains)):
        ag = (ag*(p-1)+gains[i])/p; al = (al*(p-1)+losses[i])/p
        rs = ag/al if al else float('inf')
        out.append(100 - 100/(1+rs))
    return out  # aligned with closes index

def atr(d, p=14):
    h,l,c = d['h'], d['l'], d['c']
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1,len(c))]
    a = sum(trs[:p])/p; out=[None]*p+[a]
    for tr in trs[p:]:
        a = (a*(p-1)+tr)/p; out.append(a)
    return out

def macd(closes):
    e12, e26 = ema(closes,12), ema(closes,26)
    line = [a-b for a,b in zip(e12,e26)]
    sig = ema(line,9)
    hist = [a-b for a,b in zip(line,sig)]
    return line, sig, hist

def boll(closes, p=20, m=2):
    mid = sma(closes,p); up=[]; lo=[]
    for i in range(len(closes)):
        if mid[i] is None: up.append(None); lo.append(None); continue
        w = closes[max(0,i-p+1):i+1]
        sd = st.pstdev(w)
        up.append(mid[i]+m*sd); lo.append(mid[i]-m*sd)
    return mid, up, lo

def yearly_returns(t, c):
    years = {}
    for ts, cl in zip(t, c):
        y = date(ts)[:4]; years.setdefault(y, [cl])
        years[y].append(cl)
    out = {}
    for y in sorted(years):
        v = years[y]; out[y] = (v[-1]/v[0]-1)*100
    return out

def max_drawdown(c):
    peak = c[0]; mdd = 0; trough_at = 0; peak_at = 0; cur_peak_at = 0
    for i,x in enumerate(c):
        if x > peak: peak = x; cur_peak_at = i
        dd = x/peak - 1
        if dd < mdd: mdd = dd; trough_at = i; peak_at = cur_peak_at
    return mdd*100, peak_at, trough_at

def ann_vol(closes, per_year):
    rets = [math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]
    return st.pstdev(rets)*math.sqrt(per_year)*100

def sharpe(closes, per_year):
    rets = [closes[i]/closes[i-1]-1 for i in range(1,len(closes))]
    m = st.mean(rets); s = st.pstdev(rets)
    return (m/s)*math.sqrt(per_year) if s else 0

PER_YEAR = {'1d':365, '4h':365*6, '1h':365*24}

print('='*70)
print(f"SOLUSDT ANALYSIS — fetched {blob['fetchedAt']}")
for iv in ['1d','4h','1h']:
    d = D[iv]
    print(f"{iv}: {d['n']} candles  {date(d['t'][0])} -> {date(d['t'][-1])}")
print('='*70)

d = D['1d']; c = d['c']; t = d['t']; last = c[-1]
print('\n--- PRICE / RETURNS (daily) ---')
print(f"Last close: ${last:.2f}")
for lbl, n in [('7d',7),('30d',30),('90d',90),('180d',180),('365d',365)]:
    print(f"Return {lbl}: {(c[-1]/c[-1-n]-1)*100:+.1f}%")
hi52 = max(c[-365:]); lo52 = min(c[-365:])
print(f"52w High ${hi52:.2f} ({(last/hi52-1)*100:+.1f}% from high), 52w Low ${lo52:.2f} ({(last/lo52-1)*100:+.1f}% from low)")
ath = max(c); print(f"All-time(period) high ${ath:.2f} on {date(t[c.index(ath)])}")
atl = min(c); print(f"All-time(period) low ${atl:.2f} on {date(t[c.index(atl)])}")
print('\nYearly returns:')
for y,r in yearly_returns(t,c).items(): print(f"  {y}: {r:+.1f}%")

print('\n--- VOLATILITY / RISK (daily) ---')
print(f"Annualized vol (365d): {ann_vol(c[-366:],365):.1f}% | (90d): {ann_vol(c[-91:],365):.1f}%")
mdd,pa,ta = max_drawdown(c)
print(f"Max drawdown over period: {mdd:.1f}% ({date(t[pa])} -> {date(t[ta])})")
mdd90,pa90,ta90 = max_drawdown(c[-90:])
print(f"Max drawdown last 90d: {mdd90:.1f}%")
print(f"Sharpe (365d, logret): {sharpe(c[-366:],365):.2f}")

print('\n--- TREND / MOMENTUM (daily) ---')
for p in [20,50,100,200]:
    s = sma(c,p)[-1]
    print(f"SMA{p}: ${s:.2f} — price is {(last/s-1)*100:+.1f}% vs SMA{p}")
e20, e50, e200 = ema(c,20)[-1], ema(c,50)[-1], ema(c,200)[-1]
print(f"EMA20 ${e20:.2f} | EMA50 ${e50:.2f} | EMA200 ${e200:.2f}")
print(f"Golden-cross state: EMA50 {'>' if e50>e200 else '<'} EMA200  ({'bullish' if e50>e200 else 'bearish'})")
r = rsi(c)[-1]; print(f"RSI(14): {r:.1f} {'(oversold)' if r<30 else '(overbought)' if r>70 else '(neutral)'}")
mline, msig, mhist = macd(c)
print(f"MACD: line {mline[-1]:+.2f}, signal {msig[-1]:+.2f}, hist {mhist[-1]:+.2f} ({'bullish' if mline[-1]>msig[-1] else 'bearish'})")
# recent MACD cross
cross = None
for i in range(len(c)-1, max(0,len(c)-60), -1):
    if (mline[i]-msig[i]) * (mline[i-1]-msig[i-1]) < 0:
        cross = ('bullish' if mline[i]>msig[i] else 'bearish', date(t[i]), i); break
if cross:
    ago = len(c)-1-cross[2]
    print(f"Last MACD cross ({ago} bars ago): {cross[0]} on {cross[1]}")
bm, bu, bl = boll(c)
pos = (last-bl[-1])/(bu[-1]-bl[-1])*100
print(f"Bollinger(20,2): ${bl[-1]:.2f} / ${bm[-1]:.2f} / ${bu[-1]:.2f} — %B = {pos:.0f}%")
a = atr(d)[-1]; print(f"ATR(14): ${a:.2f} ({a/last*100:.1f}% of price)")

print('\n--- VOLUME & ORDER FLOW ---')
v = d['v']; tbv = d['tb']
v30 = st.mean(v[-30:]); v90 = st.mean(v[-90:])
print(f"Avg daily volume: 30d {v30:,.0f} SOL vs 90d {v90:,.0f} SOL ({(v30/v90-1)*100:+.1f}%)")
qavg = st.mean(d['qv'][-30:])
print(f"Avg daily quote volume (30d): ${qavg/1e6:,.1f}M")
tbr = sum(tbv[-30:])/sum(v[-30:])*100
tbr90 = sum(tbv[-90:])/sum(v[-90:])*100
print(f"Taker-buy ratio: 30d {tbr:.1f}% | 90d {tbr90:.1f}% ({'buy' if tbr>50 else 'sell'} pressure)")

print('\n--- 4H TIMEFRAME ---')
d4 = D['4h']; c4 = d4['c']
r4 = rsi(c4)[-1]; e50_4 = ema(c4,50)[-1]; e200_4 = ema(c4,200)[-1]
_,_,h4 = macd(c4)
print(f"Price ${c4[-1]:.2f} | RSI(14) {r4:.1f} | EMA50 {'>' if e50_4>e200_4 else '<'} EMA200 | MACD hist {h4[-1]:+.2f}")
print(f"vs SMA20: {(c4[-1]/sma(c4,20)[-1]-1)*100:+.1f}% | vs SMA200: {(c4[-1]/sma(c4,200)[-1]-1)*100:+.1f}%")

print('\n--- 1H TIMEFRAME ---')
d1 = D['1h']; c1 = d1['c']
r1 = rsi(c1)[-1]; _,_,h1 = macd(c1)
v1avg = st.mean(d1['qv'][-24:])
print(f"Price ${c1[-1]:.2f} | RSI(14) {r1:.1f} | MACD hist {h1[-1]:+.2f} | avg hourly quote vol ${v1avg/1e6:,.1f}M")

# Support/resistance via swing points on daily
print('\n--- KEY LEVELS (daily swings, last 180d) ---')
seg = c[-180:]; tseg = t[-180:]
sup=[]; res=[]
for i in range(2, len(seg)-2):
    if seg[i] == min(seg[i-2:i+3]): sup.append((seg[i], tseg[i]))
    if seg[i] == max(seg[i-2:i+3]): res.append((seg[i], tseg[i]))
# cluster levels within 1.5%
def cluster(pts):
    pts = sorted(pts); out=[]
    for p,ts in pts:
        if out and abs(p-out[-1][0])/out[-1][0] < 0.015:
            out[-1] = ((out[-1][0]+p)/2, ts, out[-1][2]+1)
        else: out.append((p, ts, 1))
    return [x for x in out if x[2]>=2] or out
below = [x for x in cluster(sup) if x[0] < last][-4:]
above = [x for x in cluster(res) if x[0] > last][:4]
print("Support:", ', '.join(f"${p:.2f}({date(ts)})" for p,ts,_ in below) or 'none')
print("Resistance:", ', '.join(f"${p:.2f}({date(ts)})" for p,ts,_ in above) or 'none')

# Simple backtests on daily data
print('\n--- BACKTESTS (daily, long-only, next-bar-open entry, fees 0.1%) ---')
FEE = 0.001
def bt(signals, o, c, t):
    """signals[i] = desired position (1/0) decided at close of bar i, entered at open i+1"""
    pos = 0; eq = 1.0; curve=[1.0]; trades=[]; entry=None
    for i in range(len(c)-1):
        if pos == 0 and signals[i] == 1:
            pos = 1; entry = o[i+1]; eq *= (1-FEE)
        elif pos == 1 and signals[i] == 0:
            eq *= o[i+1]/entry * (1-FEE); pos = 0
            trades.append(eq/ (curve[-1]) )  # rough
            entry=None
        if pos == 1:
            curve.append(curve[-1]*o[i+1]/ (entry if entry and i==0 else (o[i+1] if entry is None else o[i+1])))
        # simpler mark-to-market below
    # recompute properly: mark to close
    return None

def backtest(sig, d, warmup):
    o,c,t = d['o'],d['c'],d['t']
    eq = 1.0; exposure_days = 0; peak=1.0; mdd=0.0; wins=0; losses=0; ntr=0
    pos=0; entry_px=None; pend=0
    for i in range(warmup, len(c)):
        # execute pending decision at this bar's open
        if pend != pos:
            if pend==1:
                pos=1; entry_px=o[i]; eq*=(1-FEE); ntr+=1
            else:
                pos=0; eq*= (o[i]/entry_px)*(1-FEE)
                if o[i]>entry_px: wins+=1
                else: losses+=1
        pend = sig[i] if sig[i] is not None else pos
        if pos==1:
            mtm = eq*(c[i]/entry_px)
            exposure_days += 1
        else:
            mtm = eq
        peak=max(peak,mtm); mdd=min(mdd, mtm/peak-1)
        if i==len(c)-1 and pos==1:
            eq_final = eq*(c[i]/entry_px)*(1-FEE)
        else:
            eq_final = eq if pos==0 else eq*(c[i]/entry_px)
    total = eq_final-1
    yrs = (len(c)-warmup)/365
    cagr = (eq_final**(1/yrs)-1)*100 if eq_final>0 else -100
    return total*100, cagr, mdd*100, ntr, wins, losses, exposure_days/(len(c)-warmup)*100

cc = c
sm50 = sma(cc,50); sm200 = sma(cc,200)
sig_sma = [None]*len(cc)
for i in range(len(cc)):
    if sm50[i] and sm200[i]: sig_sma[i] = 1 if sm50[i]>sm200[i] else 0
sig_mom = [None]*len(cc)
for i in range(90,len(cc)): sig_mom[i] = 1 if cc[i]/cc[i-90]>1 else 0
e20l = ema(cc,20); e50l = ema(cc,50)
sig_ema = [None]*len(cc)
for i in range(len(cc)): sig_ema[i] = 1 if e20l[i]>e50l[i] else 0
rsil = rsi(cc)
sig_rsi = [None]*len(cc)
for i in range(len(cc)):
    if rsil[i] is None: continue
    if sig_rsi[i-1] is None or sig_rsi[i-1]==0: sig_rsi[i]= 1 if rsil[i]<30 else 0
    else: sig_rsi[i]= 0 if rsil[i]>55 else 1

bh_total = (cc[-1]/cc[200]-1)*100
bh_cagr = ((cc[-1]/cc[200])**(365/(len(cc)-200))-1)*100
print(f"Buy&Hold (since warmup): {bh_total:+.1f}% total, {bh_cagr:+.1f}% CAGR")
for name, sg, w in [('SMA50/200 trend', sig_sma, 200), ('20/50 EMA cross', sig_ema, 50), ('90d momentum', sig_mom, 90), ('RSI mean-revert', sig_rsi, 15)]:
    tot, cagr, mdd_, ntr, wins, losses, exp = backtest(sg, d, w)
    wr = wins/ntr*100 if ntr else 0
    print(f"{name:18s}: {tot:+8.1f}% total | {cagr:+7.1f}% CAGR | MDD {mdd_:6.1f}% | {ntr:3d} trades | win {wr:4.0f}% | time-in-mkt {exp:.0f}%")
