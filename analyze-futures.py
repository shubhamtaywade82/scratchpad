#!/usr/bin/env python3
"""SOLUSDT USD-M PERPETUAL FUTURES — long AND short analysis.

Data: /workspace/data/SOLUSDT-futures.json (fetched via @nemesis-oss/binance-sdk USDMClient)
Rules (same discipline as v2, extended to shorts):
  - signal computed on close of bar t -> exposure applied at OPEN of bar t+1
  - taker fee 0.05% + slippage 0.02% per side = 0.07% on |turnover|
  - funding: paid/received on the position held across each 8h funding settlement,
    prorated by bars held (daily bars = 3 settlements/day). Long pays positive funding.
  - no leverage in P&L (1x gross); leverage noted separately for context.
"""
import json, math, statistics as st
from datetime import datetime, timezone

D = json.load(open('data/SOLUSDT-futures.json'))
K = D['klines']['1d']
C = [k['close'] for k in K]; O = [k['open'] for k in K]; H=[k['high'] for k in K]; L=[k['low'] for k in K]
V = [k['quoteAssetVolume'] for k in K]
T = [datetime.fromtimestamp(k['openTime']/1e3, tz=timezone.utc) for k in K]
N = len(K)

# ---- funding series mapped to days (3 settlements per day) ----
FR = [(f['fundingTime'], float(f['fundingRate'])) for f in D['funding']]
fund_by_day = {}
for ts, r in FR:
    day = datetime.fromtimestamp(ts/1e3, tz=timezone.utc).strftime('%Y-%m-%d')
    fund_by_day.setdefault(day, []).append(r)
fund_daily = []  # sum of 8h rates that landed on each candle's settlement day
for t in T:
    ds = t.strftime('%Y-%m-%d')
    fund_daily.append(sum(fund_by_day.get(ds, [])))
all_rates = [r for _, r in FR]

def sma(x, n):
    out=[None]*len(x); s=0
    for i,v in enumerate(x):
        s+=v
        if i>=n: s-=x[i-n]
        if i>=n-1: out[i]=s/n
    return out
def ema(x, n):
    k=2/(n+1); out=[x[0]]
    for v in x[1:]: out.append(out[-1]+k*(v-out[-1]))
    return out
def rsi(x, n=14):
    out=[None]*len(x); g=l=0
    for i in range(1,len(x)):
        ch=x[i]-x[i-1]; up=max(ch,0); dn=max(-ch,0)
        if i<=n: g+=up; l+=dn
        else:
            g=(g*(n-1)+up)/n; l=(l*(n-1)+dn)/n
        if i>=n: out[i]=100-100/(1+(g/l if l>0 else 1e9))
    return out
def atr(h,l,c,n=14):
    trs=[h[0]-l[0]]
    for i in range(1,len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return ema(trs, n)

ret = [0.0]+[C[i]/C[i-1]-1 for i in range(1,N)]
sma200 = sma(C,200); e20=ema(C,20); e50=ema(C,50); e200=ema(C,200)
R = rsi(C); A = atr(H,L,C)
vol_ann = lambda r: st.pstdev(r)*math.sqrt(365)
roll_vol = [None]*N
for i in range(N):
    if i>=30:
        w=[r for r in ret[i-29:i+1]]
        roll_vol[i]=vol_ann(w)

print('='*72)
print('SOLUSDT USD-M PERPETUAL FUTURES — LONG & SHORT ANALYSIS')
print('bars=%d  %s -> %s  last close=%.2f' % (N, T[0].date(), T[-1].date(), C[-1]))
print('='*72)

# ---------- FUNDING STATS ----------
APR = [r*3*365 for r in all_rates]  # 8h rate -> annualized
med_f = st.median(all_rates); mean_f = st.mean(all_rates)
p80 = sorted(all_rates)[int(.8*len(all_rates))]; p20 = sorted(all_rates)[int(.2*len(all_rates))]
pos = sum(1 for r in all_rates if r>0)/len(all_rates)
extreme_hi = max(all_rates); extreme_lo = min(all_rates)
recent = all_rates[-90:]  # last 30 days
print('\n-- FUNDING (every 8h, %d observations) --' % len(all_rates))
print('median %.4f%% (%.1f%% APR ann.) | mean %.4f%% (%.1f%% APR)' % (med_f*100, med_f*3*365*100, mean_f*100, mean_f*3*365*100))
print('positive funding share: %.0f%% | p20 %.4f%% | p80 %.4f%% | min %.4f%% max %.4f%%' % (pos*100,p20*100,p80*100,extreme_lo*100,extreme_hi*100))
print('last 30d: median %.4f%% (%.1f%% APR), current premiumIndex-based last rate %.4f%%' % (st.median(recent)*100, st.median(recent)*3*365*100, all_rates[-1]*100))
if D.get('live'):
    pi=D['live'].get('premiumIndex') or {}
    oi=D['live'].get('openInterest') or {}
    tk=D['live'].get('ticker24hr') or {}
    print('LIVE: mark=%.4f index=%.4f nextFundingRate=%.4f%% | OI=%.0f SOL ($%.1fM) | 24h vol=$%.0fM chg=%.1f%%' % (
        float(pi.get('markPrice',0)), float(pi.get('indexPrice',0)), float(pi.get('lastFundingRate',0))*100,
        float(oi.get('openInterest',0)), float(oi.get('openInterest',0))*float(pi.get('markPrice',0))/1e6,
        float(tk.get('quoteVolume',0))/1e6, float(tk.get('priceChangePercent',0))))

# ---------- FUNDING AS SIGNAL: forward returns after extreme funding ----------
fd = {T[i].strftime('%Y-%m-%d'): fund_daily[i] for i in range(N)}
def fwd_after(cond, horizon, sign_desc):
    idx=[i for i in range(N-horizon) if cond(i)]
    if len(idx)<10: return None
    fw=[C[i+horizon]/C[i]-1 for i in idx]
    m=st.mean(fw); win=sum(1 for x in fw if x>0)/len(fw)
    return len(idx), m, win
print('\n-- FUNDING AS CONTRARIAN SIGNAL (daily-sum funding vs forward return) --')
for name, cond in [('long-crowded (funding >= p80)', lambda i: fd[T[i].strftime("%Y-%m-%d")]>=p80*3),
                   ('short-crowded (funding <= p20)', lambda i: fd[T[i].strftime("%Y-%m-%d")]<=p20*3),
                   ('deep negative (funding < -0.05%/8h avg)', lambda i: fd[T[i].strftime("%Y-%m-%d")]<-0.0015)]:
    for hz in (3,7,14,30):
        r_=fwd_after(cond,hz,name)
        if r_: print('%s -> fwd %2dd: mean %+6.2f%%  win %+3.0f%%  (n=%d)' % (name,hz,r_[1]*100,r_[2]*100,r_[0]))

# ---------- STRATEGY BACKTESTS (long/short) ----------
FEE=0.0007  # taker+slippage one way
def backtest(exposure, label, funding_on=True):
    """exposure[i] in [-1.5, 1.5]: decided at close of bar i, applied open i+1."""
    eq=1.0; peak=1.0; mdd=0.0; curve=[1.0]; trades=0; longs=shorts=0
    prev=0.0
    for i in range(N-1):
        w=exposure[i]
        if w is None: w=prev
        pnl = w*(C[i+1]/O[i+1]-1)                      # enter at open, mark to next close approx: use open->close of i+1? 
        # more precise: hold from open(i+1) to open(i+2). We approximate with daily close-to-close shifted:
        pnl = w*(C[i+1]/C[i]-1)                         # signal at close i traded over close i -> i+1 minus cost on turnover
        turn=abs(w-prev)
        cost=turn*FEE
        fnd = 0.0
        if funding_on:
            fnd = -w*fd[T[i+1].strftime('%Y-%m-%d')]   # long pays positive funding
        eq *= (1+pnl-cost+fnd)
        if w!=prev and pnl!=0: 
            trades+=1
            if w>prev: longs+=1
            elif w<prev and w<0: shorts+=1
        prev=w
        peak=max(peak,eq); mdd=min(mdd,eq/peak-1); curve.append(eq)
    yrs=N/365.25
    cagr=eq**(1/yrs)-1
    dr=[curve[i]/curve[i-1]-1 for i in range(1,len(curve))]
    sharpe=(st.mean(dr)/st.pstdev(dr)*math.sqrt(365)) if st.pstdev(dr)>0 else 0
    worst_roll=min((sum(dr[i:i+30]) for i in range(len(dr)-30)), default=0)
    print('%-46s tot %+7.0f%% CAGR %+6.1f%% MDD %6.1f%% Sharpe %5.2f trades %4d' % (label,(eq-1)*100,cagr*100,mdd*100,sharpe,trades))
    return dict(total=(eq-1)*100, cagr=cagr*100, mdd=mdd*100, sharpe=sharpe, trades=trades)

print('\n-- BACKTESTS (signal@close t -> hold t->t+1, fee 0.07%/side, funding included) --')
base = backtest([0]*N, 'no-trade (cash)')
bh   = backtest([1]*N, 'buy & hold 1x long')
sh   = backtest([-1]*N, 'hold 1x short (static)')

res={}
res['LS_sma']=backtest([1 if sma200[i] and C[i]>sma200[i] else (-1 if sma200[i] else 0) for i in range(N)],
                        'regime gate: long >SMA200 / short <SMA200')
res['LS_sma_nof']=backtest([1 if sma200[i] and C[i]>sma200[i] else (-1 if sma200[i] else 0) for i in range(N)],
                        '   same, WITHOUT funding (sanity)', funding_on=False)
res['EMA_cross']=backtest([1 if e20[i]>e200[i] else -1 for i in range(N)], 'EMA20/200 cross long/short')
res['MACD']=None
# MACD classic
macd=[e12-e26 for e12,e26 in zip(ema(C,12),ema(C,26))]
sig=ema(macd,9); hist=[m-s for m,s in zip(macd,sig)]
res['MACD']=backtest([1 if hist[i]>0 else -1 for i in range(N)], 'MACD hist sign long/short')
res['RSI_revert_LS']=backtest([(1 if R[i] and R[i]<30 else (-1 if R[i] and R[i]>70 else 0)) for i in range(N)],
                        'RSI mean-revert LS (<30 long, >70 short)')
res['FUND_contrarian']=backtest([(1 if fd[T[i].strftime("%Y-%m-%d")]<-0.0009 else (-1 if fd[T[i].strftime("%Y-%m-%d")]>0.0024 else 0)) for i in range(N)],
                        'funding contrarian (deep-neg->long, hot->short)')
res['FUND+gate']=backtest([(max(-1,min(1,(1 if (sma200[i] and C[i]>sma200[i]) else -1)*(0.5 if fd[T[i].strftime("%Y-%m-%d")]>0.0024 else 1)))) for i in range(N)],
                        'regime gate, half-size when crowded')
# vol-targeted long/short
vt=[]
for i in range(N):
    sg = 1 if (sma200[i] and C[i]>sma200[i]) else (-1 if sma200[i] else 0)
    w = 0.4/roll_vol[i] if roll_vol[i] and roll_vol[i]>0.05 else sg
    vt.append(max(-1.5,min(1.5,w*sg if sg!=0 else 0)))
res['VT_LS']=backtest(vt,'vol-target 40% + SMA200 gate, LS')

# short-only crisis filter: short only when below SMA200 AND 30d momentum negative
mom30=[C[i]/C[i-30]-1 for i in range(N)]
res['SHORT_crisis']=backtest([(-1 if (sma200[i] and C[i]<sma200[i] and mom30[i]<-0.10) else 0) for i in range(N)],
                        'short-only: <SMA200 & 30d mom <-10%')
res['LONG_gate_only']=backtest([(1 if (sma200[i] and C[i]>sma200[i]) else 0) for i in range(N)],
                        'long-only gate (v2 best, w/ funding)')

# ---------- LONG VS SHORT CONTRIBUTION ----------
print('\n-- WHERE THE RETURN COMES FROM (regime gate LS) --')
lw=sr=0.0; nl=ns=0
prev=0
for i in range(N-1):
    w=1 if (sma200[i] and C[i]>sma200[i]) else -1
    pnl=w*(C[i+1]/C[i]-1)
    if w>0: lw+=pnl; nl+=1
    else: sr+=pnl; ns+=1
print('long days: %d contribution %+.0f%% | short days: %d contribution %+.0f%%' % (nl, lw*100, ns, sr*100))

# yearly breakdown of LS regime strategy
print('\n-- YEARLY: buy&hold vs LS-regime-gate (approx, close-to-close) --')
yrs=sorted(set(t.year for t in T))
for y in yrs:
    ii=[i for i in range(N-1) if T[i].year==y]
    if not ii: continue
    bh_y=(prod:=1)
    for i in ii: bh_y*= (1+ret[i+1])
    ls_y=1.0
    for i in ii:
        w=1 if (sma200[i] and C[i]>sma200[i]) else -1
        ls_y*= (1+w*ret[i+1]-abs(0)*FEE)
    print('%d: B&H %+8.1f%%   LS-gate %+8.1f%%' % (y,(bh_y-1)*100,(ls_y-1)*100))

# ---------- OI & crowd snapshot (30d window) ----------
print('\n-- OPEN INTEREST & CROWD (last ~30d, Binance history limit) --')
oi=D['oi1h']
if oi:
    oiv=[float(x['sumOpenInterestValue']) for x in oi]
    print('OI value now $%.0fM | 30d change %+.1f%% | 30d range $%.0fM–$%.0fM' % (oiv[-1]/1e6,(oiv[-1]/oiv[0]-1)*100,min(oiv)/1e6,max(oiv)/1e6))
tp=D['topPos']; ta=D['topAcct']; tk=D['taker']
if tp: print('top-trader POSITION L/S: %.2f (latest) avg30d %.2f' % (float(tp[-1]['longShortRatio']), st.mean([float(x['longShortRatio']) for x in tp])))
if ta: print('top-trader ACCOUNT L/S: %.2f | global ACCOUNT L/S: %.2f | taker buy/sell: %.2f' % (
    float(ta[-1]['longShortRatio']), float(D['globalAcct'][-1]['longShortRatio']) if D['globalAcct'] else 0, float(tk[-1]['buySellRatio']) if tk else 0))
