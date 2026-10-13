# v4c: intraday-specific hypotheses: time-of-day seasonality + vol-compression breakouts (NR) on 15m/1h
import json, math, statistics as st
from collections import defaultdict
exec(open('analyze-v4b.py').read().split("print(\"loading...\")")[0])  # reuse loaders/indicators/bt
bars,fr=load()

B=bars['15m']; n=len(B); cut=int(n*0.6)
# ---- time-of-day seasonality: mean hourly return by UTC hour over TRAIN, trade top/bottom hours in OOS
hret=defaultdict(list)
for i in range(1,n):
    h=(B[i]['t']//3600000)%24
    hret[h].append(math.log(B[i]['c']/B[i-1]['c']))
train_hours=defaultdict(list)
for i in range(1,cut):
    h=(B[i]['t']//3600000)%24
    train_hours[h].append(math.log(B[i]['c']/B[i-1]['c']))
mu={h:st.fmean(v) for h,v in train_hours.items()}
ranked=sorted(mu,key=lambda h:-mu[h])
top=set(ranked[:4]); bot=set(ranked[-4:])
sig=[0]*n
for i in range(cut,n):
    h=(B[i]['t']//3600000)%24
    # bar i signal -> executed at open of i+1; only trade bars fully inside hour h
    sig[i]= 1 if h in top else (-1 if h in bot else 0)
eqs,tr=bt(B,'15m',fr,[0]*cut+sig[cut:],warmup=cut)
s=stats(eqs,tr,'15m')
print("TOD long-top4/short-bot4 (OOS):", {k:round(v,3) if isinstance(v,float) else v for k,v in s.items()})
# also report full-sample per-hour means stability: split-half correlation
first_half={h:st.fmean([math.log(B[i]['c']/B[i-1]['c']) for i in range(1,n//2) if (B[i]['t']//3600000)%24==h] or [0]) for h in range(24)}
second_half={h:st.fmean([math.log(B[i]['c']/B[i-1]['c']) for i in range(n//2,n) if (B[i]['t']//3600000)%24==h] or [0]) for h in range(24)}
xs=[first_half[h] for h in range(24)]; ys=[second_half[h] for h in range(24)]
mx,my=st.fmean(xs),st.fmean(ys)
cov=sum((a-mx)*(b-my) for a,b in zip(xs,ys)); den=math.sqrt(sum((a-mx)**2 for a in xs)*sum((b-my)**2 for b in ys))
print(f"Split-half corr of hourly means: {cov/den:+.3f}")

# ---- NR (volatility compression) breakout on 15m: range of last 8 bars < q25 of trailing 96 -> trade next brk
rng=[None]*n
q=[]
for i in range(1,n):
    r=B[i]['h']-B[i]['l']; rng.append(None)
    win=[B[j]['h']-B[j]['l'] for j in range(max(0,i-96),i)]
    thr=sorted(win)[len(win)//4]
    last8=[B[j]['h']-B[j]['l'] for j in range(max(0,i-8),i)]
    brk_hi=max(B[j]['h'] for j in range(max(0,i-8),i)); brk_lo=min(B[j]['l'] for j in range(max(0,i-8),i))
    c=B[i]['c']
    if i<n-1:
        if sum(last8)/8 < thr:
            if c>brk_hi: q.append((i,1))
            elif c<brk_lo: q.append((i,-1))
sig=[0]*n
for i,d in q: sig[i]=d
eqs,tr=bt(B,'15m',fr,sig,warmup=100)
so=stats(eqs,tr,'15m')
print("NR-breakout all:",{k:round(v,3) if isinstance(v,float) else v for k,v in so.items()})
eqs,tr=bt(B,'15m',fr,[0]*cut+sig[cut:],warmup=100)
print("NR-breakout OOS:",{k:round(v,3) if isinstance(v,float) else v for k,v in stats(eqs,tr,'15m').items()})

# ---- swing trend with HTF filter: 4h Donchian40 gated by 1d EMA200 direction (use daily from futures file? use 4h*140 ~ daily proxy)
B=bars['4h']; n=len(B); cut=int(n*0.6)
cl=[b['c'] for b in B]; e200=ema(cl,200//1)  # 200 4h-bars ~ 33d
e50=ema(cl,50)
base=donch_stateful(B,40)
gated=[s if (s<=0 or (e200[i] and cl[i]>e200[i])) else 0 for i,s in enumerate(base)]
eqs,tr=bt(B,'4h',fr,gated,warmup=220)
print("D40 long-gated-by-EMA200 full:",{k:round(v,3) if isinstance(v,float) else v for k,v in stats(eqs,tr,'4h').items()})
eqs,tr=bt(B,'4h',fr,[0]*cut+gated[cut:],warmup=220)
print("   OOS:",{k:round(v,3) if isinstance(v,float) else v for k,v in stats(eqs,tr,'4h').items()})
# shorts gated by downtrend too
gated2=[s if ((s>0 and e200[i] and cl[i]>e200[i]) or (s<0 and e200[i] and cl[i]<e200[i])) else 0 for i,s in enumerate(base)]
eqs,tr=bt(B,'4h',fr,[0]*cut+gated2[cut:],warmup=220)
print("D40 both-sides EMA200-gated OOS:",{k:round(v,3) if isinstance(v,float) else v for k,v in stats(eqs,tr,'4h').items()})
