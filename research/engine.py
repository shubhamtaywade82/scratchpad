"""Causal bar-level backtester for Binance USD-M SOLUSDT perpetuals.

Invariants (each one is covered by research/test_engine.py):
  1. A signal computed from data through the close of bar k-1 executes at the open of bar k.
  2. The initial protective stop is fixed at entry: entry_px -/+ sl_mult * ATR[k-1].
  3. Trailing (chandelier) stops only ratchet in the favourable direction and apply from the next bar.
  4. Gap-through: if the open of bar k is already beyond the stop, the fill is the open, not the stop.
  5. Intrabar: a stop touched by [low, high] of bar k fills at the stop level (stop-first, no optimistic ordering).
  6. Funding is charged on every 8h funding event that falls inside (T[k-1], T[k]] while a position is held.
  7. Equity is marked to market at every bar close, so drawdown includes open-trade losses.
  8. After a stop-out in direction d, re-entry in d is blocked until the signal leaves d.
"""
import bisect
import json
import math
import statistics as st
from dataclasses import dataclass, field
from typing import List, Optional

FEE = 0.0005    # Binance USD-M taker, per side
SLIP = 0.0003   # adverse slippage, per side
BARS_PER_YEAR = {'15m': 35040, '1h': 8760, '4h': 2190, '1d': 365}
DATA_PATH = 'data/SOLUSDT-intraday.json'
FUNDING_PATH = 'data/SOLUSDT-futures.json'


# ----------------------------------------------------------------------------- data

@dataclass
class Series:
    tf: str
    t: List[int]
    o: List[float]
    h: List[float]
    l: List[float]
    c: List[float]

    def __len__(self):
        return len(self.t)


_INTERVAL_MS = {'15m': 900_000, '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000}


def to_series(tf: str, rows: list) -> Series:
    """Build a Series from raw kline rows; rejects unsorted, duplicated or gapped bars."""
    rows = sorted(rows, key=lambda r: r['openTime'])
    t = [int(r['openTime']) for r in rows]
    step = _INTERVAL_MS[tf]
    for a, b in zip(t, t[1:]):
        if b - a != step:
            raise ValueError(f"{tf}: bar gap/duplicate between {a} and {b} (delta {b - a} != {step})")
    f = lambda k: [float(r[k]) for r in rows]
    s = Series(tf, t, f('open'), f('high'), f('low'), f('close'))
    for i in range(len(s)):
        if not (s.l[i] <= min(s.o[i], s.c[i]) and s.h[i] >= max(s.o[i], s.c[i]) and s.l[i] > 0):
            raise ValueError(f"{tf}: malformed OHLC at index {i}")
    return s


def load_klines(tf: str, path: str = DATA_PATH) -> Series:
    return to_series(tf, json.load(open(path))['klines'][tf])


def load_funding(path: str = FUNDING_PATH):
    rows = json.load(open(path))['funding']
    pairs = sorted((int(r['fundingTime']), float(r['fundingRate'])) for r in rows)
    return [p[0] for p in pairs], [p[1] for p in pairs]


# ----------------------------------------------------------------------------- indicators

def atr(s: Series, n: int = 14) -> List[Optional[float]]:
    """Wilder ATR. Index k is defined once k >= n-1 (uses bars 0..k)."""
    out: List[Optional[float]] = [None] * len(s)
    trs = []
    for k in range(len(s)):
        if k == 0:
            tr = s.h[0] - s.l[0]
        else:
            pc = s.c[k - 1]
            tr = max(s.h[k] - s.l[k], abs(s.h[k] - pc), abs(s.l[k] - pc))
        trs.append(tr)
        if k == n - 1:
            out[k] = sum(trs) / n
        elif k >= n:
            out[k] = (out[k - 1] * (n - 1) + tr) / n
    return out


def ema(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    a = 2.0 / (n + 1)
    e = None
    for k, v in enumerate(x):
        e = v if e is None else v * a + e * (1 - a)
        if k >= n - 1:
            out[k] = e
    return out


def prior_max(x: List[float], n: int) -> List[Optional[float]]:
    """max(x[k-n .. k-1]) — excludes bar k so a breakout is measured against past bars only."""
    out: List[Optional[float]] = [None] * len(x)
    for k in range(n, len(x)):
        out[k] = max(x[k - n:k])
    return out


def prior_min(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    for k in range(n, len(x)):
        out[k] = min(x[k - n:k])
    return out


# ----------------------------------------------------------------------------- gates

def ema_gate(s: Series, n: int) -> List[int]:
    """+1 when close > EMA(n), -1 when below, 0 during warm-up."""
    e = ema(s.c, n)
    return [0 if e[k] is None else (1 if s.c[k] > e[k] else -1) for k in range(len(s))]


def htf_gate(base: Series, htf: Series, n: int) -> List[int]:
    """Higher-timeframe trend sign mapped onto base bars. Uses only HTF bars that have CLOSED
    before the base bar opens, so there is no lookahead across timeframes."""
    g_htf = ema_gate(htf, n)
    out = []
    j = -1
    for k in range(len(base)):
        # last HTF bar whose close_time <= base open time  <=>  htf.t[j] + htf_step <= base.t[k]
        while j + 1 < len(htf) and htf.t[j + 1] + _INTERVAL_MS[htf.tf] <= base.t[k]:
            j += 1
        out.append(g_htf[j] if j >= 0 else 0)
    return out


# ----------------------------------------------------------------------------- signals

def donchian_sig(s: Series, n: int, exit_n: Optional[int] = None, gate: Optional[List[int]] = None) -> List[int]:
    """Stateful channel breakout on closes.
    Entry: close beyond the prior n-bar extreme (and gate agrees, if given).
    Exit: close back through the mid-line of the entry channel, or through the prior exit_n-bar
          opposite extreme if exit_n is given. Gate turning against a position also exits.
    Direct reversal when the opposite breakout fires."""
    hi = prior_max(s.h, n)
    lo = prior_min(s.l, n)
    if exit_n:
        xhi = prior_max(s.h, exit_n)
        xlo = prior_min(s.l, exit_n)
    else:
        xhi = xlo = [None if hi[k] is None else (hi[k] + lo[k]) / 2 for k in range(len(s))]
    st_ = 0
    out = [0] * len(s)
    for k in range(len(s)):
        if hi[k] is None:
            continue
        c = s.c[k]
        gl = gate is None or gate[k] == 1
        gs = gate is None or gate[k] == -1
        if st_ == 1 and (c < xlo[k] or not gl):
            st_ = 0
        elif st_ == -1 and (c > xhi[k] or not gs):
            st_ = 0
        if st_ == 0:
            if c > hi[k] and gl:
                st_ = 1
            elif c < lo[k] and gs:
                st_ = -1
        elif st_ == 1 and c < lo[k] and gs:
            st_ = -1
        elif st_ == -1 and c > hi[k] and gl:
            st_ = 1
        out[k] = st_
    return out


def supertrend_sig(s: Series, period: int = 10, mult: float = 3.0) -> List[int]:
    """Always-in-market ATR trend flip. Returns +1/-1 after warm-up, 0 before."""
    a = atr(s, period)
    fu = fl = None
    d = 0
    out = [0] * len(s)
    for k in range(len(s)):
        if a[k] is None:
            continue
        hl2 = (s.h[k] + s.l[k]) / 2
        bu, bl = hl2 + mult * a[k], hl2 - mult * a[k]
        if fu is None:
            fu, fl, d = bu, bl, 1
        else:
            pc = s.c[k - 1]
            fu = bu if (bu < fu or pc > fu) else fu
            fl = bl if (bl > fl or pc < fl) else fl
            if d == -1 and s.c[k] > fu:
                d = 1
            elif d == 1 and s.c[k] < fl:
                d = -1
        out[k] = d
    return out


def tsmom_sig(s: Series, lookback: int) -> List[int]:
    """Sign of the lookback-bar return. Always in market after warm-up."""
    out = [0] * len(s)
    for k in range(lookback, len(s)):
        d = s.c[k] - s.c[k - lookback]
        out[k] = 1 if d > 0 else (-1 if d < 0 else 0)
    return out


# ----------------------------------------------------------------------------- simulation

@dataclass
class Risk:
    sizing: str = 'fixed'            # 'fixed': notional = lev * equity; 'risk': qty = risk_pct * equity / stop_distance
    lev: float = 1.0
    risk_pct: float = 0.01
    max_gross: float = 2.0           # hard cap on notional / equity in 'risk' sizing
    sl_mult: Optional[float] = None  # initial stop = entry -/+ sl_mult * ATR
    trail_mult: Optional[float] = None  # chandelier trail = extreme -/+ trail_mult * ATR

    def validate(self):
        if self.sizing not in ('fixed', 'risk'):
            raise ValueError(f"unknown sizing {self.sizing}")
        if self.sizing == 'risk' and not self.sl_mult:
            raise ValueError("risk sizing requires sl_mult: stop distance defines the position size")
        if self.lev <= 0 or self.risk_pct <= 0 or self.max_gross <= 0:
            raise ValueError("lev, risk_pct, max_gross must be positive")
        if self.sl_mult is not None and self.sl_mult <= 0:
            raise ValueError("sl_mult must be positive")
        if self.trail_mult is not None and self.trail_mult <= 0:
            raise ValueError("trail_mult must be positive")


@dataclass
class Result:
    eq: List[float]          # mark-to-market equity at each bar close in [start, end), starts at 1.0 before first bar
    pos: List[int]          # position side at each bar close
    trades: List[dict]


class _Book:
    def __init__(self):
        self.E = 1.0            # realised equity
        self.side = 0
        self.qty = 0.0
        self.ep = 0.0           # entry fill price (after slippage)
        self.entry_fee = 0.0
        self.stop: Optional[float] = None
        self.ext: Optional[float] = None
        self.k_in = None
        self.E_in = 1.0
        self.trades: List[dict] = []

    def open(self, side, k, o, qty, stop, slip, fee):
        px = o * (1 + slip) if side > 0 else o * (1 - slip)
        self.entry_fee = fee * qty * px
        self.E -= self.entry_fee
        self.side, self.qty, self.ep = side, qty, px
        self.stop, self.ext = stop, px
        self.k_in, self.E_in = k, self.E + self.entry_fee  # equity before this trade's fees

    def close(self, px_raw, k, reason, slip, fee):
        px = px_raw * (1 - slip) if self.side > 0 else px_raw * (1 + slip)
        gross = self.side * self.qty * (px - self.ep)
        exit_fee = fee * self.qty * px
        pnl = gross - exit_fee - self.entry_fee
        self.E += gross - exit_fee
        self.trades.append(dict(side=self.side, k_in=self.k_in, k_out=k, reason=reason, qty=self.qty,
                                ep=self.ep, px=px, pnl=pnl, ret=pnl / self.E_in, bars=k - self.k_in))
        self.side, self.qty, self.stop, self.ext = 0, 0.0, None, None
        self.entry_fee = 0.0

    def mtm(self, c):
        return self.E + (self.side * self.qty * (c - self.ep) if self.side else 0.0)


def simulate(s: Series, sig: List[int], risk: Risk, start: int, end: int,
             A: Optional[List[Optional[float]]] = None, fund_t=None, fund_r=None,
             fee: float = FEE, slip: float = SLIP) -> Result:
    """Run bars [start, end). sig[k-1] is the desired side at the open of bar k.
    Positions are flat at `start` and flattened at the close of `end-1`, so each call is a
    self-contained period (used for walk-forward folds)."""
    risk.validate()
    if start < 1 or end > len(s) or start >= end:
        raise ValueError(f"bad window [{start},{end}) for {len(s)} bars")
    if risk.sl_mult or risk.trail_mult:
        A = A or atr(s, 14)
    if fund_t is None:
        fund_t, fund_r = [], []
    fi = bisect.bisect_right(fund_t, s.t[start])
    bk = _Book()
    block = 0
    eq, pos_hist = [], []
    for k in range(start, end):
        O, H, L, C = s.o[k], s.h[k], s.l[k], s.c[k]
        # 6. funding events in (T[k-1], T[k]] are paid by the position held through them
        while fi < len(fund_t) and fund_t[fi] <= s.t[k]:
            if bk.side:
                bk.E -= bk.side * bk.qty * s.c[k - 1] * fund_r[fi]
            fi += 1
        # 4. gap-through stop at the open
        if bk.side and bk.stop is not None:
            if (bk.side > 0 and O <= bk.stop) or (bk.side < 0 and O >= bk.stop):
                block = bk.side
                bk.close(O, k, 'gap_stop', slip, fee)
        # 1/8. signal orders at the open
        desired = sig[k - 1] if k - 1 >= 0 else 0
        if block and desired != block:
            block = 0
        if desired != bk.side:
            if bk.side:
                bk.close(O, k, 'signal', slip, fee)
            if desired and desired != block:
                a = A[k - 1] if A is not None else None
                px = O * (1 + slip) if desired > 0 else O * (1 - slip)
                stop = None
                if risk.sl_mult and a:
                    d = risk.sl_mult * a
                    stop = px - desired * d
                if risk.sizing == 'risk':
                    if not (risk.sl_mult and a):
                        raise ValueError(f"no ATR available at bar {k - 1} for risk sizing")
                    qty = risk.risk_pct * bk.E / (risk.sl_mult * a)
                    qty = min(qty, risk.max_gross * bk.E / px)
                else:
                    qty = risk.lev * bk.E / px
                if qty > 0:
                    bk.open(desired, k, O, qty, stop, slip, fee)
        # 5. intrabar stop on the open position (includes a position opened on this bar)
        if bk.side and bk.stop is not None:
            if (bk.side > 0 and L <= bk.stop) or (bk.side < 0 and H >= bk.stop):
                block = bk.side
                bk.close(bk.stop, k, 'stop', slip, fee)
        # 3. trailing stop ratchet, from the close of bar k, applies to bar k+1 onward
        if bk.side and risk.trail_mult and A is not None and A[k] is not None:
            if bk.side > 0:
                bk.ext = max(bk.ext, H)
                cand = bk.ext - risk.trail_mult * A[k]
                bk.stop = cand if bk.stop is None else max(bk.stop, cand)
            else:
                bk.ext = min(bk.ext, L)
                cand = bk.ext + risk.trail_mult * A[k]
                bk.stop = cand if bk.stop is None else min(bk.stop, cand)
        # 7. mark to market at close
        if k == end - 1 and bk.side:
            bk.close(C, k, 'eod', slip, fee)
        eq.append(bk.mtm(C))
        pos_hist.append(bk.side)
    return Result(eq=eq, pos=pos_hist, trades=bk.trades)


# ----------------------------------------------------------------------------- metrics

def metrics(res: Result, tf: str) -> dict:
    eq = [1.0] + res.eq
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    bpy = BARS_PER_YEAR[tf]
    mu = st.fmean(rets)
    sd = st.pstdev(rets) or 1e-12
    peak, mdd = 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    years = len(rets) / bpy
    total = eq[-1] - 1
    cagr = (eq[-1] ** (1 / years) - 1) if years > 0 and eq[-1] > 0 else -1.0
    tr = res.trades
    wins = [t['pnl'] for t in tr if t['pnl'] > 0]
    losses = [t['pnl'] for t in tr if t['pnl'] <= 0]
    gp, gl = sum(wins), -sum(losses)
    longs = [t['ret'] for t in tr if t['side'] > 0]
    shorts = [t['ret'] for t in tr if t['side'] < 0]
    return dict(
        total=total, cagr=cagr, sharpe=mu / sd * math.sqrt(bpy), mdd=mdd,
        calmar=(cagr / abs(mdd)) if mdd < 0 else 0.0,
        n=len(tr), wr=len(wins) / len(tr) if tr else 0.0,
        pf=(gp / gl) if gl > 0 else (math.inf if gp > 0 else 0.0),
        exp=st.fmean([t['ret'] for t in tr]) if tr else 0.0,
        hold=st.fmean([t['bars'] for t in tr]) if tr else 0.0,
        exposure=sum(1 for p in res.pos if p) / len(res.pos) if res.pos else 0.0,
        nl=len(longs), el=st.fmean(longs) if longs else 0.0,
        ns=len(shorts), es=st.fmean(shorts) if shorts else 0.0,
        stops=sum(1 for t in tr if t['reason'] in ('stop', 'gap_stop')),
    )
