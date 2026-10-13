# v4: INTRADAY + SWING long/short systems on SOLUSDT USD-M perp.
# Realistic microstructure: next-bar-open fills (signals computed at close i, executed at open i+1),
# 5 bps taker fee per side + 3 bps slippage on market fills, protective stops checked intra-bar
# (stop-priority when both stop & TP touched = conservative), funding accrued at every 8h boundary
# crossed while in position (real Binance funding history, longs pay positive rates).
# Validation: walk-forward OOS split, parameter perturbation, moving-block bootstrap of OOS returns.
import json, math, statistics as st, random
from bisect import bisect_right

FEE=0.0005; SLIP=0.0003
PER={'15m':96,'1h':24,'4h':6,'1d':1}

def load():
    i=json.load(open('data/SOLUSDT-intraday.json'))['klines']
    f=json.load(open('data/SOLUSDT-futures.json'))['funding']
    conv=lambda rows:[dict(t=r['openTime'],o=r['open'],h=r['high'],l=r['low'],c=r['close'],v=r['volume'],tb=r['takerBuyBaseVolume']) for r in rows]
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
    for i,v in enumerate(vals):
        e=v if e is None else v*k+e*(1-k); out[i]=e
    return out

def donch(bars,n):
    hi=[None]*len(bars); lo=[None]*len(bars); mid=[None]*len(bars)
    for i in range(n,len(bars)):
        w=bars[i-n:i]
        hi[i]=max(b['h'] for b in w); lo[i]=min(b['l'] for b in w); mid[i]=(hi[i]+lo[i])/2
    return hi,lo,mid

def rvol(bars,tf,n=20):
    out=[None]*len(bars); rets=[]
    for i in range(1,len(bars)):
        rets.append(math.log(bars[i]['c']/bars[i-1]['c']))
        if len(rets)>n: rets.pop(0)
        if len(rets)==n: out[i]=st.pstdev(rets)*math.sqrt(PER[tf]*365)
    return out

def vwip(bars):  # rolling session VWAP-ish: reset every 96 bars (24h) on given tf
    out=[None]*len(bars); pv=vv=0.0
    for i,b in enumerate(bars):
        if i% (96 if PER.get('_') else 0 or 0)==0: pass
    return out

# ---------------- event-driven backtester ----------------
def bt(bars, tf, fr, sig_fn, sl_atr=1.5, tp_atr=None, exit_mid=False, risk_frac=0.01, max_lev=3.0,
       vt=None, time_stop=None, fee=FEE, slip=SLIP, warmup=60):
    """sig_fn(bars,i)-> -1/0/+1 desired position change evaluated at CLOSE of bar i, executed OPEN of i+1.
       Stops/TPs checked intra-bar afterwards."""
    A=atr(bars); RV=rvol(bars,tf)
    cash=1.0; pos=0.0; ep=None; sl=None; tpx=None; eb=0
    eq=[1.0]; trades=[]
    n=len(bars)
    for i in range(warmup,n-1):
        o,h,l,c=[bars[j][k] for j,k in [(i+1,'o'),(i+1,'h'),(i+1,'l'),(i+1,'c')]]
        t0,t1=bars[i]['t'],bars[i+1]['t']
        # 1) funding across 8h boundaries while in position
        if pos!=0:
            k8=int(t1//28800000)-int(t0//28800000)
            if k8>0:
                j=bisect_right(fr,t1,key=lambda z:z[0])-1
                if j>=0: cash-=pos*fr[j][1]*k8
        # 2) intra-bar stop/tp on execution bar (use its H/L)
        if pos!=0:
            hit=None
            if pos>0 and sl is not None and l<=sl: hit=sl
            elif pos>0 and tpx is not None and h>=tpx: hit=tpx
            elif pos<0 and sl is not None and h>=sl: hit=sl
            elif pos<0 and tpx is not None and l<=tpx: hit=tpx
            if hit is not None:
                px=hit*(1-slip) if pos>0 else hit*(1+slip)
                pnl=pos*(px-ep)-abs(pos)*(fee+slip); cash+=pnl
                trades.append(dict(side=1 if pos>0 else -1,pnl=pnl,reason='stop',bars=i-eb)); pos=0; sl=tpx=None
        # 3) act on signal from close of bar i
        s=sig_fn(bars,i,A,RV)
        target=s
        if exit_mid and pos!=0:
            _,_,mid=donch(bars, sig_fn.__dict__.get('n',20))
        if pos!=0 and time_stop and i-eb>=time_stop and target==0:
            px=c*(1-slip) if pos>0 else c*(1+slip)
            pnl=pos*(px-ep)-abs(pos)*(fee+slip); cash+=pnl
            trades.append(dict(side=1 if pos>0 else -1,pnl=pnl,reason='time',bars=i-eb)); pos=0; sl=tpx=None; target=0
        if target!=0 and pos==0:
            a=A[i] or c*0.02
            lev=min(max_lev, (risk_frac*c)/(sl_atr*a/c)) if sl_atr else max_lev
            if vt and RV[i]: lev=min(lev,max(0.25,vt/RV[i]))
            lev=max(0.25,min(lev,max_lev))
            px=o*(1+(slip if target>0 else -slip))
            pos=target*lev; ep=px; eb=i+1; cash-=abs(pos)*fee
            sl=px-target*sl_atr*a if sl_atr else None
            tpx=px+target*tp_atr*a if tp_atr else None
        elif target==0 and pos!=0:
            px=o*(1-(slip if pos>0 else -slip))
            pnl=pos*(px-ep)-abs(pos)*(fee+slip); cash+=pnl
            trades.append(dict(side=1 if pos>0 else -1,pnl=pnl,reason='signal',bars=i-eb)); pos=0; sl=tpx=None
        elif target!=0 and pos!=0 and (target>0)!=(pos>0):
            # flip
            px=o*(1-(slip if pos>0 else -slip)); pnl=pos*(px-ep)-abs(pos)*(fee+slip); cash+=pnl
            trades.append(dict(side=1 if pos>0 else -1,pnl=pnl,reason='flip',bars=i-eb))
            a=A[i] or c*0.02
            lev=min(max_lev,(risk_frac*c)/(sl_atr*a/c))
            px=o*(1+(slip if target>0 else -slip))
            pos=target*lev; ep=px; eb=i+1; cash-=abs(pos)*fee
            sl=px-target*sl_atr*a; tpx=px+target*tp_atr*a if tp_atr else None
        eq.append(cash)
    while len(eq)<n-warmup: eq.append(eq[-1])
    return eq,trades

def stats(eq,trades,tf,seg_bars=None):
    rets=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    if not rets: return dict(total=0,sharpe=0,mdd=0,n=0,wr=0,pf=0)
    mu=st.fmean(rets); sd=st.pstdev(rets) or 1e-9
    sh=mu/sd*math.sqrt(PER[tf]*365)
    peak=-1e9; mdd=0
    for v in eq: peak=max(peak,v); mdd=min(mdd,v/peak-1)
    w=[t['pnl'] for t in trades if t['pnl']>0]; L=[t['pnl'] for t in trades if t['pnl']<=0]
    pf=sum(w)/-sum(L) if L and sum(L)<0 else float('inf')
    return dict(total=eq[-1]-1,sharpe=sh,mdd=mdd,n=len(trades),wr=len(w)/len(trades) if trades else 0,pf=pf,
                avgbars=st.fmean([t['bars'] for t in trades]) if trades else 0)

# ---------------- signal libraries ----------------
def mk_donchian(n, mid_exit=True):
    cache={}
    def fn(bars,i,A,RV):
        key=id(bars)
        if key not in cache: cache[key]=donch(bars,n)
        hi,lo,mid=cache[key]
        if hi[i] is None: return 0
        c=bars[i]['c']
        if c>hi[i]: return 1
        if c<lo[i]: return -1
        if mid_exit:
            if c<mid[i]: return 0 if _last(fn,key)==1 else None
        return None
    # simpler stateful version below
    return fn

def donchian_stateful(bars,n):
    hi,lo,mid=donch(bars,n)
    state=0; sig=[0]*len(bars)
    for i in range(len(bars)):
        if hi[i] is None: continue
        c=bars[i]['c']
        if c>hi[i]: state=1
        elif c<lo[i]: state=-1
        elif mid[i] is not None:
            if state==1 and c<mid[i]: state=0
            elif state==-1 and c>mid[i]: state=0
        sig[i]=state
    return sig

def ema_cross_stateful(bars,f,s):
    closes=[b['c'] for b in bars]; ef=ema(closes,f); es=ema(closes,s)
    state=0; sig=[0]*len(bars)
    for i in range(1,len(bars)):
        if ef[i]>es[i]: state=1
        elif ef[i]<es[i]: state=-1
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

def sig_from(sigarr):
    return lambda bars,i,A,RV: sigarr[i]

def wf_split(n,test_frac=0.4):
    cut=int(n*(1-test_frac)); return cut

def block_boot_sharpe(rets,tf,B=400,L=20,seed=7):
    rnd=random.Random(seed); per=PER[tf]*365; out=[]
    m=len(rets)
    for _ in range(B):
        s=[]
        while len(s)<m:
            st_i=rnd.randrange(m)
            s.extend(rets[st_i:min(st_i+L,m)])
        mu=st.fmean(s[:m]); sd=st.pstdev(s[:m]) or 1e-9
        out.append(mu/sd*math.sqrt(per))
    out.sort()
    return out[int(0.05*len(out))], st.fmean(out)

def fmt(name,s):
    return f"{name:<34} tot {s['total']*100:+8.1f}%  Sh {s['sharpe']:+5.2f}  MDD {s['mdd']*100:6.1f}%  n {s['n']:4d}  WR {s['wr']*100:4.1f}%  PF {s['pf']:5.2f}  hold {s['avgbars']:5.1f}b"

print("loading...")
bars,fr=load()

# ============ 1) INTRADAY on 15m (73 days) ============
B=bars['15m']; n=len(B); cut=wf_split(n)
print("\n=== INTRADAY 15m (train %db / OOS %db) ==="%(cut,n-cut))
configs=[
 ("Donchian20 mid-exit",      donchian_stateful(B,20),  dict(sl_atr=1.5)),
 ("Donchian48 mid-exit",      donchian_stateful(B,48),  dict(sl_atr=2.0)),
 ("EMA12/48 cross",           ema_cross_stateful(B,12,48), dict(sl_atr=2.0)),
 ("RSI7 MR 25/75",            rsi_mr_stateful(B,7,25,75), dict(sl_atr=1.2,tp_atr=1.2)),
 ("RSI14 MR 30/70",           rsi_mr_stateful(B,14,30,70), dict(sl_atr=1.5,tp_atr=1.5)),
]
for name,sig,kw in configs:
    fn=sig_from(sig)
    eq_tr,tr=bt(B,'15m',fr,fn,warmup=60,**kw)
    s_all=stats(eq_tr,tr,'15m')
    # OOS-only equity: rerun with signals zeroed before cut
    sig_oos=[0]*cut+sig[cut:]
    eq_o,tr_o=bt(B,'15m',fr,sig_from(sig_oos),warmup=60,**kw)
    s_oos=stats(eq_o,tr_o,'15m')
    print(fmt(name+" [all]",s_all)); print(fmt("   -> OOS only",s_oos))

# ============ 2) SWING on 1h (108 days) ============
B=bars['1h']; n=len(B); cut=wf_split(n)
print("\n=== SWING 1h (train %db / OOS %db) ==="%(cut,n-cut))
for name,sig,kw in [
 ("Donchian24 (~1d)", donchian_stateful(B,24), dict(sl_atr=2.0)),
 ("Donchian72 (~3d)", donchian_stateful(B,72), dict(sl_atr=2.5)),
 ("EMA10/50 cross",   ema_cross_stateful(B,10,50), dict(sl_atr=2.5)),
 ("RSI14 MR 30/70",   rsi_mr_stateful(B,14,30,70), dict(sl_atr=2.0,tp_atr=2.0)),
]:
    eq_tr,tr=bt(B,'1h',fr,sig_from(sig),warmup=100,**kw)
    sig_oos=[0]*cut+sig[cut:]
    eq_o,tr_o=bt(B,'1h',fr,sig_from(sig_oos),warmup=100,**kw)
    print(fmt(name+" [all]",stats(eq_tr,tr,'1h'))); print(fmt("   -> OOS only",stats(eq_o,tr_o,'1h')))

# ============ 3) SWING on 4h (450 days) ============
B=bars['4h']; n=len(B); cut=wf_split(n)
print("\n=== SWING 4h (train %db / OOS %db) ==="%(cut,n-cut))
res4={}
for name,sig,kw in [
 ("Donchian20 (~3.3d)", donchian_stateful(B,20), dict(sl_atr=2.0)),
 ("Donchian40 (~6.7d)", donchian_stateful(B,40), dict(sl_atr=2.5)),
 ("Donchian60 (~10d)",  donchian_stateful(B,60), dict(sl_atr=2.5)),
 ("EMA10/40 cross",     ema_cross_stateful(B,10,40), dict(sl_atr=2.5)),
 ("EMA20/80 cross",     ema_cross_stateful(B,20,80), dict(sl_atr=3.0)),
 ("RSI14 MR 30/70",     rsi_mr_stateful(B,14,30,70), dict(sl_atr=2.0,tp_atr=2.0)),
]:
    eq_tr,tr=bt(B,'4h',fr,sig_from(sig),warmup=120,**kw)
    sig_oos=[0]*cut+sig[cut:]
    eq_o,tr_o=bt(B,'4h',fr,sig_from(sig_oos),warmup=120,**kw)
    sa=stats(eq_tr,tr,'4h'); so=stats(eq_o,tr_o,'4h')
    res4[name]=(sa,so,eq_o,tr_o)
    print(fmt(name+" [all]",sa)); print(fmt("   -> OOS only",so))

# buy&hold benchmark on each tf over same windows
for tf in ['15m','1h','4h']:
    Bx=bars[tf]; r=[math.log(Bx[i]['c']/Bx[i-1]['c']) for i in range(1,len(Bx))]
    sh=st.fmean(r)/st.pstdev(r)*math.sqrt(PER[tf]*365)
    tot=math.exp(sum(r))-1
    print(f"B&H {tf}: total {tot*100:+.1f}% Sharpe {sh:.2f}")

# ============ 4) ensemble + bootstrap on best swing families ============
print("\n=== ENSEMBLES (averaged positions) & BOOTSTRAP ===")
def ens_sigs(bars,arrs):
    return [sum(a)/len(a) for a in zip(*arrs)]
B=bars['4h']; n=len(B); cut=wf_split(n)
ens=ens_sigs(B,[donchian_stateful(B,20),donchian_stateful(B,40),donchian_stateful(B,60)])
eq_e,tr_e=bt(B,'4h',fr,sig_from(ens),warmup=120,sl_atr=2.5,risk_frac=0.008,max_lev=2.5)
eq_o,_=bt(B,'4h',fr,sig_from([0]*cut+ens[cut:]),warmup=120,sl_atr=2.5,risk_frac=0.008,max_lev=2.5)
tr_o=None
print(fmt("Donchian ens 20/40/60 [all]",stats(eq_e,tr_e,'4h')))
rets=[eq_o[i]/eq_o[i-1]-1 for i in range(1,len(eq_o))]
lo,mean_bs=block_boot_sharpe(rets,'4h')
print(f"   OOS bootstrap Sharpe: mean {mean_bs:+.2f}, 5th pct {lo:+.2f}")

# perturbation: shift each Donchian param by +-20%
print("   Perturbation (4h Donchian n): ",end="")
for nn in [16,20,24,32,40,48,60,72]:
    s=donchian_stateful(B,nn)
    eqx,trx=bt(B,'4h',fr,sig_from(s),warmup=120,sl_atr=2.5)
    print(f"n{nn}:{stats(eqx,trx,'4h')['sharpe']:+.2f}",end=" ")
print()
