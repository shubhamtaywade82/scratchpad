#!/usr/bin/env python3
"""Round 2: fix funding mapping, test asymmetric/conditional shorts, grid-search the LS family."""
import json, math, statistics as st
from datetime import datetime, timezone

D = json.load(open('/workspace/data/SOLUSDT-futures.json'))
K = D['klines']['1d']
C=[k['close'] for k in K]; H=[k['high'] for k in K]; L=[k['low'] for k in K]
T=[datetime.fromtimestamp(k['openTime']/1e3, tz=timezone.utc) for k in K]
N=len(K)
ret=[0.0]+[C[i]/C[i-1]-1 for i in range(1,N)]

# daily funding: sum of settlements whose fundingTime falls on that calendar day
fund_by_day={}
for f in D['funding']:
    day=datetime.fromtimestamp(f['fundingTime']/1e3, tz=timezone.utc).strftime('%Y-%m-%d')
    fund_by_day[day]=fund_by_day.get(day,0)+float(f['fundingRate'])
fday=[fund_by_day.get(t.strftime('%Y-%m-%d'),0.0) for t in T]   # funding received by a LONG per day
print('daily-sum funding: mean %+.4f%% median %+.4f%% p5 %.4f%% p95 %.4f%% min %+.3f%% max %+.3f%%' % (
    st.mean(fday)*100, st.median(fday)*100, sorted(fday)[int(.05*N)], sorted(fday)[int(.95*N)], min(fday)*100, max(fday)*100))

def sma(x,n):
    o=[None]*len(x); s=0
    for i,v in enumerate(x):
        s+=v
        if i>=n: s-=x[i-n]
        if i>=n-1: o[i]=s/n
    return o
def ema(x,n):
    k=2/(n+1); o=[x[0]]
    for v in x[1:]: o.append(o[-1]+k*(v-o[-1]))
    return o
def rsi(x,n=14):
    o=[None]*len(x); g=l=0
    for i in range(1,len(x)):
        ch=x[i]-x[i-1]; up=max(ch,0); dn=max(-ch,0)
        if i<=n: g+=up; l+=dn
        else: g=(g*(n-1)+up)/n; l=(l*(n-1)+dn)/n
        if i>=n: o[i]=100-100/(1+(g/l if l>0 else 1e9))
    return o

sma200=sma(C,200); R=rsi(C)
mom30=[0]*N
for i in range(30,N): mom30[i]=C[i]/C[i-30]-1
mom90=[0]*N
for i in range(90,N): mom90[i]=C[i]/C[i-90]-1
roll_vol=[None]*N
for i in range(30,N): roll_vol[i]=st.pstdev(ret[i-29:i+1])*math.sqrt(365)
FEE=0.0007

def bt(exposure,label,fund=True):
    eq=1.0; peak=1.0; mdd=0.0; curve=[1.0]; prev=0.0; trades=0
    long_pnl=short_pnl=0.0; ndays_l=ndays_s=0
    for i in range(N-1):
        w=exposure[i] if exposure[i] is not None else prev
        pnl=w*ret[i+1]-abs(w-prev)*FEE
        f=-w*fday[i+1] if fund else 0.0
        eq*=(1+pnl+f)
        if w>0: long_pnl+=pnl; ndays_l+=1
        elif w<0: short_pnl+=pnl; ndays_s+=1
        if w!=prev: trades+=1
        prev=w
        peak=max(peak,eq); mdd=min(mdd,eq/peak-1); curve.append(eq)
    dr=[curve[i]/curve[i-1]-1 for i in range(1,len(curve))]
    sh=st.mean(dr)/st.pstdev(dr)*math.sqrt(365) if st.pstdev(dr)>0 else 0
    print('%-52s tot %+7.0f%% CAGR %+6.1f%% MDD %6.1f%% Sharpe %5.2f tr %4d | longPnL %+6.0f%% shortPnL %+6.0f%% (%3dd/%3dd)'%(
        label,(eq-1)*100,(eq**(365.25/N)-1)*100,mdd*100,sh,trades,long_pnl*100,short_pnl*100,ndays_l,ndays_s))
    return (eq-1)*100, mdd*100, sh

gate=lambda i: (1 if C[i]>sma200[i] else -1) if sma200[i] else 0
LONGONLY=[(1 if gate(i)==1 else 0) for i in range(N)]
print('\n== SHORT VARIANTS (added to long-only gate; funding included) ==')
bt([gate(i) for i in range(N)], 'LS symmetric always-in')
bt([(min(0,gate(i)*-1*-1) if False else (-1 if gate(i)==-1 and mom30[i]<-0.10 else (1 if gate(i)==1 else 0))) for i in range(N)],
   'LS: short only if <SMA200 & 30dmom<-10%')
bt([(-1 if (gate(i)==-1 and mom90[i]<-0.10) else (1 if gate(i)==1 else 0)) for i in range(N)],
   'LS: short only if <SMA200 & 90dmom<-10%')
bt([(-1 if (gate(i)==-1 and R[i] and R[i]<45) else (1 if gate(i)==1 else 0)) for i in range(N)],
   'LS: short only if <SMA200 & RSI<45 (not oversold)')
# half-size short variants
for s in (0.25,0.5,0.75):
    bt([(s*gate(i) if gate(i)==-1 else 1) for i in range(N)], 'LS short size %.2fx' % s)
# short sized by vol target too
vt=[]
for i in range(N):
    g=gate(i)
    if g==0 or roll_vol[i] is None: vt.append(0 if g==0 and i>30 else g); continue
    w=min(1.5,0.40/roll_vol[i])
    vt.append(w if g==1 else -w*s if False else -w*0.5)
bt(vt,'vol-target LS (long full VT, short 0.5x VT)')

print('\n== FUNDING-AWARE SHORT SIZING (avoid short when we would pay funding) ==')
# when funding negative, shorts PAY funding -> shrink short
med_f=st.median(list(fund_by_day.values()))
def fund_adj_short(i, base_size):
    f=fday[i]
    if f<0:  # shorts pay
        return -base_size*max(0.25, 1+ (f*3*365))  # scale down harshly at very neg funding
    return -base_size
bt([ (fund_adj_short(i,1) if gate(i)==-1 else 1) for i in range(N)], 'LS funding-scaled short, mom-free')
bt([ (fund_adj_short(i,1) if (gate(i)==-1 and mom30[i]<-0.10) else (1 if gate(i)==1 else 0)) for i in range(N)],
   'BEST CANDIDATE: long gate + mom-gated funding-scaled short')

print('\n== sanity: no funding cost on either side ==')
bt(LONGONLY,'long-only gate (funding ON)',True)
bt(LONGONLY,'long-only gate (funding OFF)',False)
