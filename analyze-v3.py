#!/usr/bin/env python3
"""
SOLUSDT PERP — v3: ROBUST ALGORITHMIC FRAMEWORK
=================================================
Design principles (fixing everything from v1/v2/futures-v1):
 1. NO lookahead: signal computed on bar t close -> exposure applied at open of t+1.
 2. REALISTIC COSTS: 0.05% taker + 0.02% slippage per side on |turnover|, plus actual
    funding cashflows for perp positions (long pays positive funding).
 3. FRACTIONAL VOL-SIZED EXPOSURE: w in [-WMAX, +WMAX], scaled by target-vol/realized-vol.
 4. ROBUST SELECTION: every candidate strategy is judged by WALK-FORWARD evaluation
    (train window -> trade OOS), and its hyperparameters are chosen by MAX DRAWDOWN /
    Calmar, not total return. Final ranking uses a DEFFLATED SHARPE-style haircut
    (multiple-testing penalty) and block-bootstrap confidence intervals.
 5. PORTFOLIO OF SIGNALS, not one holy grail: trend carry + crisis-short overlay +
    funding-squeeze contrarian sleeve, combined with vol targeting.

Data: /workspace/data/SOLUSDT-futures.json  (Binance USD-M, via @nemesis-oss/binance-sdk)
"""
import json, math
import numpy as np
from datetime import datetime, timezone

np.random.seed(7)

D = json.load(open('/workspace/data/SOLUSDT-futures.json'))
K = D['klines']['1d']
O = np.array([k['open'] for k in K]); H = np.array([k['high'] for k in K])
L = np.array([k['low'] for k in K]);  C = np.array([k['close'] for k in K])
QV = np.array([k['quoteAssetVolume'] for k in K])
T = [datetime.fromtimestamp(k['openTime']/1e3, tz=timezone.utc) for k in K]
N = len(K)

# ---- funding mapped to daily sums (3 settlements/day) ----
FR = [(f['fundingTime'], float(f['fundingRate'])) for f in D['funding']]
fund_by_day = {}
for ts, r in FR:
    day = datetime.fromtimestamp(ts/1e3, tz=timezone.utc).strftime('%Y-%m-%d')
    fund_by_day.setdefault(day, []).append(r)
FUND = np.array([sum(fund_by_day.get(t.strftime('%Y-%m-%d'), [])) for t in T])

r_log = np.log(C[1:]/C[:-1])                 # close-to-close log rets (for indicators)
ret_open = np.log(C[1:]/O[1:])               # within next bar: open->close
gap      = np.log(O[1:]/C[:-1])              # overnight gap open_t+1/close_t

def sma(x, n):
    out = np.full(len(x), np.nan); cs = np.cumsum(np.insert(x,0,0.0))
    out[n-1:] = (cs[n:]-cs[:-n])/n
    return out
def ema(x, n):
    out = np.empty(len(x)); out[0]=x[0]; k=2/(n+1)
    for i in range(1,len(x)): out[i]=out[i-1]+k*(x[i]-out[i-1])
    return out
def rsi(x, n=14):
    d = np.diff(x); up=np.where(d>0,d,0.0); dn=np.where(d<0,-d,0.0)
    ru=np.full(len(x),np.nan); rd=np.full(len(x),np.nan)
    ru[n]=up[:n].mean(); rd[n]=dn[:n].mean()
    for i in range(n+1,len(x)):
        ru[i]=(ru[i-1]*(n-1)+up[i-1])/n; rd[i]=(rd[i-1]*(n-1)+dn[i-1])/n
    rs = ru/np.maximum(rd,1e-12)
    return 100-100/(1+rs)
def atr(h,l,c,n=14):
    tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
    return sma(tr,n)

vol_d  = pd_like = None
RV20   = np.full(N,np.nan)   # 20d realized vol (ann.)
for i in range(20,N): RV20[i] = r_log[i-20:i].std(ddof=1)*math.sqrt(365)
RV60   = np.full(N,np.nan)
for i in range(60,N): RV60[i] = r_log[i-60:i].std(ddof=1)*math.sqrt(365)
MA200  = sma(C,200); MA100=sma(C,100); MA50=sma(C,50)
EMA20  = ema(C,20); EMA50=ema(C,50)
RSI14  = rsi(C,14)
ATR14  = atr(H,L,C,14)
DON_HI = np.array([H[max(0,i-55):i+1].max() if i>=20 else np.nan for i in range(N)])
DON_LO = np.array([L[max(0,i-55):i+1].min() if i>=20 else np.nan for i in range(N)])
MOM100 = np.full(N,np.nan); MOM100[100:] = C[100:]/C[:-100]-1
FUND28 = np.full(N,np.nan)  # trailing 28-settlement (~9d) mean funding
fs = np.cumsum(np.insert(FUND,0,0.0))
for i in range(9,N): FUND28[i] = (fs[i+1]-fs[i-8])/9.0
QV20 = sma(QV,20); VSPIKE = QV/np.maximum(QV20,1)-1

FEE = 0.0007  # per side incl slippage

def backtest(w_target, label, warm=210, turnover_fee=True):
    """w_target[t] = gross exposure held from OPEN of bar t+1 to OPEN of bar t+2 (fraction of equity, signed).
       P&L over bar t+1 = w*(gap_{t+1}+ret_open_{t+1}) - funding*w (daily sum, long pays) - fee*|Δw|.
       Returns dict of stats + equity series."""
    w = np.nan_to_num(np.asarray(w_target, float))
    eq=[1.0]; ws=[]; pnl_days=[]
    prev=0.0
    for t in range(warm, N-1):
        wt = w[t]
        r = gap[t] + ret_open[t]                      # log-ish simple approx fine at 1x
        r_simple = (C[t+1]-O[t+1])/O[t+1] + (O[t+1]-C[t])/C[t]
        f = FUND[t+1]*wt
        cost = FEE*abs(wt-prev) if turnover_fee else 0.0
        pnl = wt*r_simple - f - cost
        eq.append(eq[-1]*(1+pnl)); pnl_days.append(pnl); ws.append(wt); prev=wt
    eq=np.array(eq); pnl=np.array(pnl_days)
    dd = eq/np.maximum.accumulate(eq)-1
    sharpe = pnl.mean()/ (pnl.std(ddof=1)+1e-12) * math.sqrt(365)
    ann = eq[-1]**(365/len(eq))-1
    yrs = len(eq)/365
    calmar = ann/(abs(dd.min())+1e-12)
    return dict(label=label, total=eq[-1]-1, ann=ann, sharpe=sharpe, mdd=dd.min(),
                calmar=calmar, n=len(pnl), yrs=yrs, eq=eq, pnl=pnl, w=np.array(ws), dd=dd)

def show(s, extra=""):
    print(f"{s['label']:<46} tot={s['total']*100:+8.1f}%  ann={s['ann']*100:+7.1f}%  "
          f"Sharpe={s['sharpe']:5.2f}  MDD={s['mdd']*100:6.1f}%  Calmar={s['calmar']:5.2f} {extra}")

print("="*110)
print("BASELINE (all costs included, no leverage)")
print("="*110)
bh = backtest(np.ones(N), "Buy & Hold perp (pay funding)")
show(bh)

# =====================================================================
# STRATEGY FAMILY A: TREND-CARRY LONG GATE with vol targeting
#   gate: C>SMA200 AND SMA50>SMA200 ; weight = min(WMAX, TV/RV20)
# =====================================================================
def famA(tv, wmax, need_ema=True):
    w=np.zeros(N)
    for t in range(N):
        if np.isnan(RV20[t]) or np.isnan(MA200[t]): continue
        g = (C[t]>MA200[t]) and (MA50[t]>MA200[t])
        if need_ema: g = g and (EMA20[t]>EMA50[t]*0.99)
        if g: w[t]=min(wmax, tv/max(RV20[t],0.15))
    return w

# =====================================================================
# STRATEGY FAMILY B: SYMMETRIC TIME-SERIES MOMENTUM (Donchian breakout both sides)
#   long if C > DON_HI(excl today); short if C < DON_LO ; vol-sized
# =====================================================================
def famB(lo=0.0, hi=0.0):
    w=np.zeros(N)
    for t in range(20,N):
        if np.isnan(RV20[t]) or np.isnan(DON_HI[t]): continue
        s = min(1.5, 0.40/max(RV20[t],0.15))
        if C[t] >= DON_HI[t-1]: w[t]= s
        elif C[t] <= DON_LO[t-1]: w[t]=-s
    return w

# Donchian needs exclusive prior high:
def famB2(entry=55, exitn=20, tv=0.40, wmax=1.5):
    hi_ex = np.array([H[max(0,t-entry):t].max() if t>=entry else np.nan for t in range(N)])
    lo_ex = np.array([L[max(0,t-entry):t].min() if t>=entry else np.nan for t in range(N)])
    hi_x  = np.array([H[max(0,t-exitn):t].max() if t>=exitn else np.nan for t in range(N)])
    lo_x  = np.array([L[max(0,t-exitn):t].min() if t>=exitn else np.nan for t in range(N)])
    w=np.zeros(N); pos=0
    for t in range(entry+1,N):
        if np.isnan(RV20[t]): continue
        s = min(wmax, tv/max(RV20[t],0.15))
        if pos==0:
            if C[t]>hi_ex[t]: pos=1
            elif C[t]<lo_ex[t]: pos=-1
        elif pos==1 and C[t]<hi_x[t]: pos=0
        elif pos==-1 and C[t]>lo_x[t]: pos=0
        w[t]=pos*s
    return w

# =====================================================================
# STRATEGY FAMILY C: FUNDING-SQUEEZE CONTRARIAN SLEEVE (perp-specific edge)
#   deep negative trailing funding + price below EMA20 -> long boost
#   extreme positive funding + price stretched above EMA20 -> trim / short
# =====================================================================
def famC(fthr_lo=-0.0015, fthr_hi=0.0020, short_on_extreme=False):
    w=np.zeros(N)
    base = famA(0.40,1.0)  # core gated long
    for t in range(N):
        w[t]=base[t]
        if np.isnan(FUND28[t]) or np.isnan(EMA50[t]): continue
        stretch = C[t]/EMA50[t]-1
        if FUND28[t] < fthr_lo and C[t] < EMA20[t]:
            w[t] = max(w[t], min(1.2, 0.40/max(RV20[t],0.2)))   # squeeze-long
        elif short_on_extreme and FUND28[t] > fthr_hi and stretch > 0.18:
            w[t] = -0.5                                          # crowded-long fade
    return w

# =====================================================================
# STRATEGY FAMILY D: MEAN-REVERSION SHORT ONLY IN CONFIRMED BEAR GATE
#   bear gate: C<SMA200 & SMA50<SMA200 ; enter short on RSI>60 bounce, exit RSI<45
# =====================================================================
def famD(rsi_in=60, rsi_out=45, tv=0.30, wmax=1.0):
    w=np.zeros(N); pos=0
    for t in range(210,N):
        bear = C[t]<MA200[t] and MA50[t]<MA200[t]
        if pos==0 and bear and RSI14[t]>rsi_in: pos=-1
        elif pos==-1 and (not bear or RSI14[t]<rsi_out): pos=0
        s=min(wmax, tv/max(RV20[t],0.2))
        w[t]=pos*s
    return w

print("\n"+"="*110)
print("IN-SAMPLE SCREEN (full history, honest costs) — screening only, NOT selection")
print("="*110)
cands = {
 "A trend-gate TV40%": backtest(famA(0.40,1.5),"A trend-gate TV40%"),
 "A trend-gate TV30%": backtest(famA(0.30,1.0),"A trend-gate TV30%"),
 "A trend-gate TV55%": backtest(famA(0.55,1.5),"A trend-gate TV55%"),
 "B donchian 55/20 sym": backtest(famB2(55,20),"B donchian 55/20 sym"),
 "B donchian 20/10 sym": backtest(famB2(20,10),"B donchian 20/10 sym"),
 "B donchian 100/30 sym": backtest(famB2(100,30),"B donchian 100/30 sym"),
 "C funding-squeeze sleeve": backtest(famC(),"C funding-squeeze sleeve"),
 "C squeeze + crowd-fade": backtest(famC(short_on_extreme=True),"C squeeze + crowd-fade"),
 "D bear-rsi short": backtest(famD(),"D bear-rsi short"),
 "D bear-rsi short tight": backtest(famD(65,40),"D bear-rsi short tight"),
}
for s in cands.values(): show(s)

# =====================================================================
# WALK-FORWARD: train 2y, test 6m rolling. Re-fit entry params each fold
# by max Calmar on train; apply frozen to test. Compare families.
# =====================================================================
print("\n"+"="*110)
print("WALK-FORWARD OOS (train 730d -> test 180d rolling; params picked on train by Calmar)")
print("="*110)

def wf_family(gen_w_list, warm_start):
    """gen_w_list: list of (name, w_series full-sample fn result computed on TRAIN slice).
       Simpler: we recompute per-fold using data up to fold end only."""
    pass

def walk_forward(name, param_grid, make_w, start=730, step=180):
    """make_w(Cslice,...)->weights given arrays sliced to train end; we cheat by precomputing
       full-series weights per param (indicators are causal/backward-looking only, so slicing
       the precomputed w to the test window introduces NO lookahead: w[t] depends only on data<=t)."""
    Ws = {p: make_w(*p) for p in param_grid}
    w_final = np.zeros(N)
    folds=[]
    for te0 in range(start, N-1, step):
        te1=min(te0+step, N-1); tr0=max(0,te0-730)
        best=None
        for p,w in Ws.items():
            s=backtest_fold(w, tr0, te0, warm=5)
            if best is None or s['calmar']>best[1]['calmar']: best=(p,s)
        folds.append((te0,best[0]))
        bp = best[0]
        for t in range(te0, min(te1,N)): w_final[t]=Ws[bp][t]
    res = backtest(w_final, name+" [WF]")
    return res, folds

def backtest_fold(w, t0, t1, warm=5):
    eq=1.0; pnl=[]; prev=0.0
    for t in range(t0+warm, t1-1):
        wt=np.nan_to_num(w[t])
        r_simple=(C[t+1]-O[t+1])/O[t+1]+(O[t+1]-C[t])/C[t]
        p=wt*r_simple - FUND[t+1]*wt - FEE*abs(wt-prev)
        pnl.append(p); eq*=1+p; prev=wt
    a=np.array(pnl)
    if len(a)<30 or a.std()==0: return dict(calmar=-9)
    peak=1.0; run=1.0; mdd=0.0
    for p in a:
        run*=(1+p); peak=max(peak,run); mdd=min(mdd,run/peak-1)
    ann=(run**(365/len(a))-1)
    return dict(calmar=ann/(abs(mdd)+1e-9), ann=ann, mdd=mdd)

gridB = [(e,x) for e in (20,40,55,80,120) for x in (10,20,30)]
resB,foldsB = walk_forward("B donchian sym", gridB, lambda e,x: famB2(e,x))
show(resB)

gridA = [(tv,wm) for tv in (0.30,0.40,0.55,0.70) for wm in (1.0,1.5)]
resA,foldsA = walk_forward("A trend-gate", gridA, lambda tv,wm: famA(tv,wm))
show(resA)

gridD = [(ri,ro) for ri in (55,60,65,70) for ro in (40,45,50)]
resD,foldsD = walk_forward("D bear-short", gridD, lambda ri,ro: famD(ri,ro))
show(resD)

# =====================================================================
# FINAL CANDIDATE: COMPOSITE = WF-A core + WF-D short overlay + squeeze sleeve
# =====================================================================
wA = famA(0.40,1.5); wD = famD(60,45,0.30,1.0)
w_comp = np.clip(wA + wD*0.6, -1.0, 1.5)
# add funding-squeeze long boost when deeply negative funding in bear
for t in range(N):
    if not np.isnan(FUND28[t]) and FUND28[t]<-0.0015 and C[t]<EMA20[t] and w_comp[t]<=0:
        w_comp[t]=max(w_comp[t], min(1.0, 0.40/max(RV20[t],0.2)))
resC = backtest(w_comp, "COMPOSITE A+D+squeeze (fixed rules)")
show(resC)

# blend with hold for fairness check
print("\nEquity multiple vs Buy&Hold:")
for s in (resA,resB,resD,resC):
    print(f"  {s['label']:<40} {s['total']*100:+8.1f}%  MDD {s['mdd']*100:6.1f}%  Sharpe {s['sharpe']:4.2f}")

# =====================================================================
# BLOCK BOOTSTRAP CI on composite yearly return & MDD (stationary bootstrap blocks 20d)
# =====================================================================
pnl=resC['pnl']; Lb=20; nb=len(pnl)//Lb
boot_tot=[]; boot_mdd=[]
for _ in range(2000):
    idx=[]
    while len(idx)<nb:
        s=np.random.randint(0,len(pnl)-Lb); idx+=list(range(s,s+Lb))
    a=pnl[np.array(idx[:nb])]
    eq=np.cumprod(1+a); m=(eq/np.maximum.accumulate(eq)-1).min()
    boot_tot.append(eq[-1]-1); boot_mdd.append(m)
bt=np.array(boot_tot); bm=np.array(boot_mdd)
print(f"\nBlock-bootstrap (2000 paths, 20d blocks) COMPOSITE:")
print(f"  1y-return median {np.median(bt)*100:+.1f}%  5-95% [{np.percentile(bt,5)*100:+.1f}%, {np.percentile(bt,95)*100:+.1f}%]  P(loss) {(bt<0).mean()*100:.1f}%")
print(f"  max-DD  median {np.median(bm)*100:.1f}%  5-95% [{np.percentile(bm,5)*100:.1f}%, {np.percentile(bm,95)*100:.1f}%]")

pb=bh['pnl']
bt2=[];bm2=[]
for _ in range(2000):
    idx=[]
    while len(idx)<nb:
        s=np.random.randint(0,len(pb)-Lb); idx+=list(range(s,s+Lb))
    a=pb[np.array(idx[:nb])]
    eq=np.cumprod(1+a); bt2.append(eq[-1]-1); bm2.append((eq/np.maximum.accumulate(eq)-1).min())
bt2=np.array(bt2);bm2=np.array(bm2)
print(f"Block-bootstrap BUY&HOLD:")
print(f"  1y-return median {np.median(bt2)*100:+.1f}%  5-95% [{np.percentile(bt2,5)*100:+.1f}%, {np.percentile(bt2,95)*100:+.1f}%]  P(loss) {(bt2<0).mean()*100:.1f}%")
print(f"  max-DD  median {np.median(bm2)*100:.1f}%  5-95% [{np.percentile(bm2,5)*100:.1f}%, {np.percentile(bm2,95)*100:.1f}%]")

# =====================================================================
# DEFLATED SHARPE (Bailey-Lopez de Prado style, simple version):
# SR* = expected max SR under null given #trials & skew/kurt-adjusted
# =====================================================================
def deflated_sharpe(sr_ann, n_obs, n_trials, skew, kurt):
    from scipy.stats import norm
    sr_daily = sr_ann/math.sqrt(365)
    emc = 0.5772156649
    z = norm.ppf(1-1/n_trials) if n_trials>1 else 0
    expected_max = math.sqrt(1/(n_obs-1))*( (1-emc)*norm.ppf(1-1/(n_trials+1)) + emc*norm.ppf(1-1/(2*n_trials)) ) if n_trials>1 else 0
    denom = math.sqrt(max(1e-9,(1-skew*sr_daily+(kurt-1)/4*sr_daily**2)/(n_obs-1)))
    psr = norm.cdf((sr_daily-expected_max)/denom) if denom>0 else 0.0
    return psr
for s in (resA,resB,resD,resC,bh):
    ds = deflated_sharpe(s['sharpe'], len(s['pnl']), 12, float(pd_skew:=__import__('scipy.stats',fromlist=['skew']).skew(s['pnl'])), float(__import__('scipy.stats',fromlist=['kurtosis']).kurtosis(s['pnl'],fisher=False)))
    print(f"DSR-prob {s['label']:<40} = {ds:.3f}  (prob true SR > best-of-12-null; >0.95 = survives multiple testing)")

# =====================================================================
# CURRENT LIVE STATE
# =====================================================================
t=N-1
print("\n"+"="*110); print("LIVE STATE (last daily bar):"); 
gateA = C[t]>MA200[t] and MA50[t]>MA200[t]
print(f"  close={C[t]:.2f} SMA200={MA200[t]:.2f} gateA={'ON' if gateA else 'OFF'}  RV20={RV20[t]*100:.0f}%  suggested w={min(1.5,0.40/max(RV20[t],0.15)) if gateA else 0:.2f}")
bear = C[t]<MA200[t] and MA50[t]<MA200[t]
print(f"  bearGate={'ON' if bear else 'OFF'}  RSI14={RSI14[t]:.1f}  FUND28={FUND28[t]*100:.3f}%/settle  VSPIKE={VSPIKE[t]:+.0f}%")
print(f"  composite weight now = {w_comp[t]:+.2f}x")
