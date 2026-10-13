# v4b: INTRADAY + SWING long/short, multiplicative (compounding) equity, fixed leverage per entry.
import json, math, statistics as st, random
from bisect import bisect_right
FEE=0.0005; SLIP=0.0003
PER={'15m':96,'1h':24,'4h':6,'1d':1}

def load():
    i=json.load(open('data/SOLUSDT-intraday.json'))['klines']
    f=json.load(open('data/SOLUSDT-futures.json'))['funding']
    conv=lambda rows:[dict(t=r['openTime'],o=r['open'],h=r['high'],l=r['low'],c=r['close'],v=r['volume']) for r in rows]
    bars={tf:conv(i[tf]) for tf in ['15m','1h','4h','1d']}
    fr=sorted((x['fundingTime'],float(x['fundingRate'])) for x in f)
    return bars,fr

def atr(bars,n=14):
    out=[None]*len(bars); trs=[]
    for i,b in enumerate(bars):
        pc=bars[i-1]['c'] if i else b['c']
        trs.append(max(b['h']-b['l'],abs(b['h']-pc),abs(b['l']-pc)))
        if len(trs)>n: trs.pop(0)
        if i>=n-1: out[i]=sum(trs)/n
    return out

def rsi(bars,n=14):
    out=[None]*len(bars); ag=al=0.0
    for i in range(1,len(bars)):
        ch=bars[i]['c']-bars[i-1]['c']; g=max(ch,0); l=max(-ch,0)
        if i<=n: ag+=g/n; al+=l/n
        else:
            ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n
            out[i]=100-100/(1+(ag/al if al>1e-12 else 1e9))
    return out

def ema(vals,n):
    out=[None]*len(vals); k=2/(n+1); e=None
    for i,v in enumerate(vals): e=v if e is None else v*k+e*(1-k); out[i]=e
    return out

def donch(bars,n):
    hi=[None]*len(bars); lo=[None]*len(bars); mid=[None]*len(bars)
    for i in range(n,len(bars)):
        w=bars[i-n:i]; hi[i]=max(b['h'] for b in w); lo[i]=min(b['l'] for b in w); mid[i]=(hi[i]+lo[i])/2
    return hi,lo,mid

def donch_stateful(bars,n):
    hi,lo,mid=donch(bars,n); state=0; sig=[0]*len(bars)
    for i in range(len(bars)):
        if hi[i] is None: continue
        c=bars[i]['c']
        if c>hi[i]: state=1
        elif c<lo[i]: state=-1
        elif state==1 and c<mid[i]: state=0
        elif state==-1 and c>mid[i]: state=0
        sig[i]=state
    return sig

def ema_cross_stateful(bars,f,s):
    cl=[b['c'] for b in bars]; ef=ema(cl,f); es=ema(cl,s); state=0; sig=[0]*len(bars)
    for i in range(1,len(bars)):
        state=1 if ef[i]>es[i] else -1
        sig[i]=state
    return sig

def rsi_mr_stateful(bars,n,lo_t,hi_t,exit_t=50):
    r=rsi(bars,n); state=0; sig=[0]*len(bars)
    for i in range(len(bars)):
        if r[i] is None: continue
        if r[i]<lo_t: state=1
        elif r[i]>hi_t: state=-1
        elif state==1 and r[i]>=exit_t: state=0
        elif state==-1 and r[i]<=exit_t: state=0
        sig[i]=state
    return sig

def bt(bars,tf,fr,sig,lev=1.0,sl_atr=None,tp_atr=None,time_stop=None,fee=FEE,slip=SLIP,warmup=60):
    """sig[i] in {-1,0,+1} decided at close of bar i -> executed at open of bar i+1. Compounding equity."""
    A=atr(bars) if sl_atr else None
    eq=1.0; pos=0; ep=None; sl=None; tpx=None; eb=0; eqs=[eq]; trades=[]
    n=len(bars)
    for i in range(warmup,n-1):
        nb=bars[i+1]; o,h,l,c=nb['o'],nb['h'],nb['l'],nb['c']
        t0,t1=bars[i]['t'],nb['t']
        # funding while holding across 8h boundaries
        if pos!=0:
            k=int(t1//28800000)-int(t0//28800000)
            if k>0:
                j=bisect_right(fr,t1,key=lambda z:z[0])-1
                if j>=0: eq*= (1 - pos*lev*fr[j][1]*k)
        # intra-bar stop/TP on the execution bar
        if pos!=0:
            hit=None
            if pos>0:
                if sl is not None and l<=sl: hit=sl
                elif tpx is not None and h>=tpx: hit=tpx
            else:
                if sl is not None and h>=sl: hit=sl
                elif tpx is not None and l<=tpx: hit=tpx
            if hit is not None:
                px=hit*(1-slip) if pos>0 else hit*(1+slip)
                eq*= (1+pos*lev*((px/ep)-1) - lev*(fee+slip))
                trades.append(dict(side=pos,pnl=pos*lev*((px/ep)-1)-lev*(fee+slip),reason='stop',bars=i-eb))
                pos=0; sl=tpx=None
        s=sig[i]
        if s==pos: 
            eqs.append(eq); continue
        # close old at open of next bar
        if pos!=0:
            px=o*(1-slip) if pos>0 else o*(1+slip)
            eq*= (1+pos*lev*((px/ep)-1) - lev*(fee+slip))
            trades.append(dict(side=pos,pnl=pos*lev*((px/ep)-1)-lev*(fee+slip),reason='signal',bars=i-eb)); sl=tpx=None
        # open new
        if s!=0:
            px=o*(1+slip) if s>0 else o*(1-slip)
            pos=s; ep=px; eb=i+1
            eq*= (1-lev*fee)
            a=A[i] if A and A[i] else None
            if sl_atr and a: sl=px-pos*sl_atr*a
            if tp_atr and a: tpx=px+pos*tp_atr*a
        else: pos=0
        eqs.append(eq)
    return eqs,trades

def stats(eqs,trades,tf):
    rets=[eqs[i]/eqs[i-1]-1 for i in range(1,len(eqs))]
    mu=st.fmean(rets); sd=st.pstdev(rets) or 1e-9
    sh=mu/sd*math.sqrt(PER[tf]*365)
    peak=-1e9; mdd=0
    for v in eqs: peak=max(peak,v); mdd=min(mdd,v/peak-1)
    w=[t['pnl'] for t in trades if t['pnl']>0]; L=[t['pnl'] for t in trades if t['pnl']<=0]
    pf=sum(w)/-sum(L) if L and sum(L)<0 else float('inf')
    longs=[t for t in trades if t['side']>0]; shorts=[t for t in trades if t['side']<0]
    def agg(ts): return (len(ts), st.fmean([t['pnl'] for t in ts])*100 if ts else 0)
    return dict(total=eqs[-1]-1,sharpe=sh,mdd=mdd,n=len(trades),wr=len(w)/len(trades) if trades else 0,pf=pf,
                hold=st.fmean([t['bars'] for t in trades]) if trades else 0,
                nl=longs and len(longs) or 0, avgL=agg(longs)[1], ns=len(shorts), avgS=agg(shorts)[1])

def fmt(name,s):
    return (f"{name:<30} tot {s['total']*100:+7.1f}% Sh {s['sharpe']:+5.2f} MDD {s['mdd']*100:6.1f}% "
            f"n {s['n']:4d} WR {s['wr']*100:4.1f}% PF {s['pf']:4.2f} hold {s['hold']:5.1f}b "
            f"| L:{s['nl']}({s['avgL']:+.2f}%) S:{s['ns']}({s['avgS']:+.2f}%)")

bars,fr=load()

def run_tf(tf,configs,lev=1.0):
    B=bars[tf]; n=len(B); cut=int(n*0.6)
    print(f"\n=== {tf} ({round(B[-1]['t']/864e5-B[0]['t']/864e5)}d, train {cut}b / OOS {n-cut}b), lev={lev} ===")
    out={}
    for name,sig,kw in configs:
        eqs,tr=bt(B,tf,fr,sig,lev=lev,**kw)
        sa=stats(eqs,tr,tf)
        eqo,tro=bt(B,tf,fr,[0]*cut+sig[cut:],lev=lev,**kw)
        so=stats(eqo,tro,tf)
        out[name]=(sa,so,eqo)
        print(fmt(name+" [full]",sa)); print(fmt("  ->OOS",so))
    # benchmarks
    r=[math.log(B[i]['c']/B[i-1]['c']) for i in range(1,n)]
    bh=st.fmean(r)/st.pstdev(r)*math.sqrt(PER[tf]*365)
    cut_r=r[cut:]
    print(f"B&H full Sharpe {bh:+.2f}; B&H OOS Sharpe {st.fmean(cut_r)/st.pstdev(cut_r)*math.sqrt(PER[tf]*365):+.2f}")
    return out

print("loading...")
intra=run_tf('15m',[
 ("Donchian20",      donch_stateful(bars['15m'],20), dict()),
 ("Donchian48",      donch_stateful(bars['15m'],48), dict()),
 ("Donchian20+SL1.5",donch_stateful(bars['15m'],20), dict(sl_atr=1.5)),
 ("EMA12/48",        ema_cross_stateful(bars['15m'],12,48), dict()),
 ("RSI7 MR 25/75",   rsi_mr_stateful(bars['15m'],7,25,75), dict(sl_atr=1.2,tp_atr=1.2)),
 ("RSI14 MR 30/70",  rsi_mr_stateful(bars['15m'],14,30,70), dict(sl_atr=1.5,tp_atr=1.5)),
])
sw1=run_tf('1h',[
 ("Donchian24 (~1d)", donch_stateful(bars['1h'],24), dict()),
 ("Donchian72 (~3d)", donch_stateful(bars['1h'],72), dict()),
 ("EMA10/50",         ema_cross_stateful(bars['1h'],10,50), dict()),
 ("RSI14 MR 30/70",   rsi_mr_stateful(bars['1h'],14,30,70), dict(sl_atr=2.0,tp_atr=2.0)),
])
sw4=run_tf('4h',[
 ("Donchian20 (~3.3d)", donch_stateful(bars['4h'],20), dict()),
 ("Donchian40 (~6.7d)", donch_stateful(bars['4h'],40), dict()),
 ("Donchian60 (~10d)",  donch_stateful(bars['4h'],60), dict()),
 ("EMA10/40",           ema_cross_stateful(bars['4h'],10,40), dict()),
 ("RSI14 MR 30/70",     rsi_mr_stateful(bars['4h'],14,30,70), dict(sl_atr=2.0,tp_atr=2.0)),
])

# ensembles (averaged fractional positions) — need fractional support: emulate via two runs? use blended sig scaled by lev
print("\n=== ENSEMBLES (fractional blended signals, lev=blended) ===")
def blend(arrs): return [sum(a)/len(a) for a in zip(*arrs)]
for tf,ns in [('4h',[20,40,60]),('1h',[24,72])]:
    B=bars[tf]; n=len(B); cut=int(n*0.6)
    ens=blend([donch_stateful(B,x) for x in ns])
    eqs,tr=bt(B,tf,fr,[round(s) for s in ens])  # sign of ensemble = direction
    eqo,tro=bt(B,tf,fr,[0]*cut+[round(s) for s in ens[cut:]])
    print(fmt(f"DonchianEns {tf} {ns} [full]",stats(eqs,tr,tf)))
    print(fmt("  ->OOS",stats(eqo,tro,tf)))

# perturbation robustness on 4h Donchian & 1h Donchian (OOS Sharpe across params)
print("\n=== PARAM PERTURBATION (OOS Sharpe) ===")
for tf,ns in [('4h',[16,20,24,32,40,48,60,72]),('1h',[16,24,36,48,72,96])]:
    B=bars[tf]; n=len(B); cut=int(n*0.6)
    line=[]
    for nn in ns:
        s=donch_stateful(B,nn)
        eqo,_=bt(B,tf,fr,[0]*cut+s[cut:])
        line.append(f"n{nn}:{stats(eqo,[],tf)['sharpe'] if False else ''}")
    # recompute properly
    line=[]
    for nn in ns:
        s=donch_stateful(B,nn)
        eqo,tro=bt(B,tf,fr,[0]*cut+s[cut:])
        line.append(f"n{nn}:{stats(eqo,tro,tf)['sharpe']:+.2f}")
    print(f"{tf} Donchian:", " ".join(line))

# bootstrap OOS Sharpe CIs for top candidates
def boot(eqs,tf,B_=600,L=20,seed=11):
    rnd=random.Random(seed); rets=[eqs[i]/eqs[i-1]-1 for i in range(1,len(eqs))]; m=len(rets); out=[]
    for _ in range(B_):
        s=[]
        while len(s)<m:
            i0=rnd.randrange(m); s.extend(rets[i0:i0+L])
        s=s[:m]; mu=st.fmean(s); sd=st.pstdev(s) or 1e-9
        out.append(mu/sd*math.sqrt(PER[tf]*365))
    out.sort(); return out[int(.05*B_)],out[int(.5*B_)],out[int(.95*B_)]
print("\n=== OOS BLOCK-BOOTSTRAP SHARPE (5/50/95 pct) ===")
for label,(sa,so,eqo),tf in [("15m Donchian48",intra["Donchian48"],'15m'),
                             ("15m RSI7MR",intra["RSI7 MR 25/75"],'15m'),
                             ("1h Donchian24",sw1["Donchian24 (~1d)"],'1h'),
                             ("1h RSI14MR",sw1["RSI14 MR 30/70"],'1h'),
                             ("4h Donchian40",sw4["Donchian40 (~6.7d)"],'4h'),
                             ("4h Donchian60",sw4["Donchian60 (~10d)"],'4h')]:
    lo,md,hi=boot(eqo,tf); print(f"{label:<18} {lo:+.2f} / {md:+.2f} / {hi:+.2f}")
