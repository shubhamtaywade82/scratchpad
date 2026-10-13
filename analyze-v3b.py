#!/usr/bin/env python3
# v3b: ensemble Donchian + volatility-scaled funding-carry short sleeve.
# Robustness: fixed simple params (no per-fold tuning), yearly stability, block bootstrap.
import json, math, numpy as np
from datetime import datetime, timezone
np.random.seed(11)

src = open('analyze-v3.py').read()
head = src.split('# =====================================================================\n# STRATEGY FAMILY A')[0]
tail_fns = src.split('# =====================================================================\n# STRATEGY FAMILY C')[0].split('# =====================================================================\n# STRATEGY FAMILY B')[1]
exec(head)                       # data prep, backtest(), show()
exec('# STRATEGY FAMILY B\n' + tail_fns.split('# Donchian needs exclusive prior high:')[1])  # famB2

def famB_ens(tv=0.40, wmax=1.5):
    sets=[(20,10),(40,15),(55,20),(80,25),(120,30)]
    return np.mean([famB2(e,x,tv,wmax) for e,x in sets],axis=0)

def famC_carry(thresh=0.0002, tv=0.40, wmax=1.5):
    """Volatility-scaled funding carry: trailing ~9d mean daily funding > thresh -> short perp
       (longs pay you). Full size with trend (bear), half size against trend (bull)."""
    w=np.zeros(N)
    sm=np.convolve(np.nan_to_num(FUND),np.ones(9)/9,'same')
    for t in range(210,N-1):
        if np.isnan(RV20[t]): continue
        s=min(wmax, tv/max(RV20[t],0.2))
        if sm[t]>thresh and C[t]<MA200[t]: w[t]=-s
        elif sm[t]>thresh and C[t]>MA200[t]: w[t]=-s*0.5
    return w

def famT(ts=0.7):
    """Classic TSMOM sign x vol-target (Moskowitz-Ooi-Pedersen style)."""
    w=np.zeros(N)
    mom=np.full(N,np.nan); mom[90:]=C[90:]/C[:-90]-1
    for t in range(210,N):
        if np.isnan(mom[t]) or np.isnan(RV20[t]): continue
        s=min(1.5, ts/max(RV20[t],0.15))
        w[t]=s if mom[t]>0 else -s
    return w

print("== IN-SAMPLE (fixed rules, no tuning) ==")
bh=backtest(np.ones(N),"Buy&Hold perp"); show(bh)
e=backtest(famB_ens(),"Donchian ENSEMBLE (5 sets avg)"); show(e)
c=backtest(famC_carry(),"Funding-CARRY short sleeve"); show(c)
tt=backtest(famT(),"TSMOM 90d vol-target"); show(tt)
comb=backtest(np.clip(famB_ens()+famC_carry()*0.5,-1.5,1.5),"ENSEMBLE + 0.5x carry"); show(comb)
comb2=backtest(np.clip(famB_ens()*0.6+0.4*famT()+famC_carry()*0.5,-1.5,1.5),"B+T+carry blend"); show(comb2)

def yearly(s):
    eq=s['eq']; out=[]
    yrs=[T[t].year for t in range(210,N-1)]
    cur=yrs[0]; start=0
    for i,y in enumerate(yrs+[None]):
        if y!=cur:
            out.append((cur, eq[min(i+1,len(eq)-1)-1]/eq[start]-1 if False else eq[i]/eq[start]-1)); cur=y; start=i
    return out
print("\nYearly returns:")
for name,s in [("B&H",bh),("Ensemble",e),("Carry",c),("TSMOM",tt),("Ens+Carry",comb)]:
    print(f"  {name:<10}", " ".join(f"{y}:{r*100:+.0f}%" for y,r in yearly(s)))

for name,s in [("Ensemble",e),("Carry",c),("TSMOM",tt),("Ens+Carry",comb)]:
    w=s['w']; print(f"{name}: time-long {(w>0.01).mean()*100:.0f}%  time-short {(w<-0.01).mean()*100:.0f}%  avg|w| {np.abs(w).mean():.2f}")

def blocks(pnl,nb,Lb):
    idx=[]
    while len(idx)<nb:
        ss=np.random.randint(0,len(pnl)-Lb); idx+=list(range(ss,ss+Lb))
    a=pnl[np.array(idx[:nb])]; eqq=np.cumprod(1+a)
    return eqq[-1]-1,(eqq/np.maximum.accumulate(eqq)-1).min()

for name,s in [("Ens+Carry",comb),("B&H",bh),("TSMOM",tt)]:
    pnl=s['pnl']; Lb=20; nb=len(pnl)//Lb
    bt,bm=zip(*[blocks(pnl,nb,Lb) for _ in range(3000)])
    bt=np.array(bt);bm=np.array(bm)
    print(f"\nBootstrap {name}: 1y median {np.median(bt)*100:+.1f}% 5-95% [{np.percentile(bt,5)*100:+.1f},{np.percentile(bt,95)*100:+.1f}] P(loss) {(bt<0).mean()*100:.0f}% | MDD med {np.median(bm)*100:.1f}% worst5% {np.percentile(bm,5)*100:.1f}%")

t=N-1
sm=np.convolve(np.nan_to_num(FUND),np.ones(9)/9,'same')
wE=famB_ens(); wC=famC_carry()
print(f"\nLIVE: fund9d={sm[t]*100:.3f}%/day (trigger>0.02) ; donchian w={wE[t]:+.2f}; carry w={wC[t]:+.2f}; composite w={np.clip(wE[t]+0.5*wC[t],-1.5,1.5):+.2f}")
mom=C[t]/C[t-90]-1
print(f"      TSMOM 90d mom={mom*100:+.1f}% -> w={famT()[t]:+.2f}; RV20={RV20[t]*100:.0f}%")
