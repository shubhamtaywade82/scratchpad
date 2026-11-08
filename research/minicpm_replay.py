"""Does the crypto-trading-agent MiniCPM fleet have an edge? Event study on Binance 1m history.

At random 15m closes (2021-2026, ETH/SOL/XRP, BTC as anchor) the model gets the fleet's own prompt
(crypto-trading-agent src/minicpm/MiniCpmPrompt.ts, without the optional marketState block) and its answer passes
the fleet's own validation (MiniCpmService.parseAndValidate). Each approved entry is re-traded on the 1m path
from the next minute's open, for at most 48h, under three exit rules:
  FLEET  LLM stop + LLM target, stop to breakeven after +0.25% (SymbolTraderWorker.applyTrailingBreakEven)
  TIERS  LLM stop + LLM target, TrailingStopManager tiers: lock 0R@1R, 0.5R@1.5R, 1R@2R (+1.5 ATR15m trail), 2R@3R
  FLIP   same timestamps and distances, opposite side, FLEET exits (directional-skill null)
Isolated 10x, fee 5 bps + slippage 3 bps per side, funding charged. Model answers are cached per model in JSONL.

Usage: python3 -m research.minicpm_replay MODEL [MODEL ...]   -> research/results/v13-minicpm-<model>.txt
"""
import json
from bisect import bisect_left, bisect_right
import random
import statistics as st
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research import binance_1m as b1m
from research.engine import Risk, Series, atr, simulate
from research.multi_asset import ALTS, ANCHOR, to_1m

OLLAMA = 'http://127.0.0.1:11434'
SAMPLES_PER_SYMBOL = 300
MAX_HOLD_MIN = 48 * 60
LEV = 10.0
BE_MOVE = 0.0025
TIERS = ((1.0, 0.0), (1.5, 0.5), (2.0, 1.0), (3.0, 2.0))
RESULTS = Path(__file__).resolve().parent / 'results'
# Prompts are ~600 tokens; minicpm5-analyst's 32k Modelfile context alone held ~8 GB and got the run killed
NUM_CTX = 4096
TRADE_CONSTRAINTS = """### TRADE OBJECTIVES & MANDATORY CONSTRAINTS:
1. Minimum Profit Target: At 10x leverage, Take Profit (TP) requires at least 0.5% price distance.
   - For LONG: takeProfit >= currentPrice * 1.005
   - For SHORT: takeProfit <= currentPrice * 0.995
2. Stop Loss (SL):
   - For LONG: stopLoss below local support/swing low (currentPrice > stopLoss).
   - For SHORT: stopLoss above local resistance/swing high (currentPrice < stopLoss).
   - Minimum Risk/Reward Ratio: (Reward / Risk) must be >= 1.5.
3. Decision: Output "ENTER_LONG", "ENTER_SHORT", or "HOLD" if setup is unclear or suboptimal."""


def trend(closes: list) -> str:
    """SymbolTraderWorker.detectTrend: last 5 closes, +/-0.3%."""
    diff = (closes[-1] - closes[-5]) / closes[-5] * 100
    return 'BULLISH' if diff > 0.3 else ('BEARISH' if diff < -0.3 else 'SIDEWAYS')


def context(m15: Series, h1: Series, k15: int, a15: list) -> dict:
    """Fleet context as of the close of 15m bar k15 (1h bars closed by then only)."""
    j = bisect_right(h1.t, m15.t[k15] + 900_000 - 3_600_000) - 1   # last 1h bar closed by the 15m close
    price = m15.c[k15]
    open24 = h1.o[j - 23]
    return dict(price=price, trend1h=trend(h1.c[j - 4:j + 1]), trend15m=trend(m15.c[k15 - 4:k15 + 1]),
                change24hPct=(price - open24) / open24 * 100, atr14=a15[k15],
                recentHigh=max(m15.h[k15 - 19:k15 + 1]), recentLow=min(m15.l[k15 - 19:k15 + 1]))


def prompt(symbol: str, s: dict, b: dict) -> str:
    """Port of buildTradingPrompt (no marketState section)."""
    return f"""You are an elite quantitative crypto trader operating with 10x leverage on Binance USDT-Margined Futures.
Analyze market data for {symbol} using BTCUSDT as macro context anchor.

### MACRO CONTEXT (BTCUSDT Anchor):
- BTC Price: ${b['price']:.2f} | 1h: {b['trend1h']} | 15m: {b['trend15m']} | 24h: {b['change24hPct']:.2f}%

### ASSET DATA ({symbol}):
- Current Price: ${s['price']} | 1h: {s['trend1h']} | 15m: {s['trend15m']} | 24h: {s['change24hPct']:.2f}%
- ATR(14): {s['atr14']:.4f} | Support: {s['recentLow']} | Resistance: {s['recentHigh']}
- Swing High: {s['recentHigh']} | Swing Low: {s['recentLow']}

{TRADE_CONSTRAINTS}

Return ONLY a valid JSON object with EXACTLY this structure (no markdown fences, no explanatory text):
{{
  "action": "ENTER_LONG" | "ENTER_SHORT" | "HOLD",
  "confidence": 0.85,
  "entry": {s['price']},
  "stopLoss": 0.0,
  "takeProfit": 0.0,
  "reason": "Brief technical rationale"
}}"""


def parse_and_validate(raw: str, price: float):
    """Port of MiniCpmService.parseAndValidate: (side, entry, sl, tp), 'HOLD', or None (rejected)."""
    try:
        p = json.loads(raw.split('</think>')[-1].strip())
        action = str(p.get('action', '')).upper()
        if action == 'HOLD':
            return 'HOLD'
        entry, sl, tp = float(p.get('entry') or price), float(p['stopLoss']), float(p['takeProfit'])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if action == 'ENTER_LONG' and sl < entry < tp and (tp - entry) / entry * 100 >= 0.49:
        return 1, entry, sl, tp
    if action == 'ENTER_SHORT' and tp < entry < sl and (entry - tp) / entry * 100 >= 0.49:
        return -1, entry, sl, tp
    return None


def generate(model: str, text: str) -> str:
    body = dict(model=model, prompt=text, format='json', stream=False, options=dict(temperature=0.2, top_p=0.9, num_ctx=NUM_CTX))
    req = urllib.request.Request(f'{OLLAMA}/api/generate', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())['response']
        except OSError as err:  # Ollama returns sporadic HTTP 500 under parallel load
            last = err
            time.sleep(2 * (attempt + 1))
    print(f'[{model}] giving up on one prompt: {last}', file=sys.stderr)
    return None


def ask_all(model: str, jobs: list) -> dict:
    """Cached model answers keyed by 'SYMBOL:t'."""
    cache_path = RESULTS / f"v13-minicpm-{model.replace('/', '_').replace(':', '_')}.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            row = json.loads(line)
            cache[row['key']] = row['raw']
    todo = [j for j in jobs if j['key'] not in cache]
    with ThreadPoolExecutor(2) as pool, cache_path.open('a') as out:
        for job, raw in zip(todo, pool.map(lambda j: generate(model, j['prompt']), todo)):
            if raw is None:
                continue  # not cached, so a rerun retries it; excluded from this report
            cache[job['key']] = raw
            out.write(json.dumps(dict(key=job['key'], raw=raw)) + '\n')
    return cache


def trade(m1: Series, i0: int, side: int, sl: float, tp: float, a1m: list, risk: Risk, fund) -> dict | None:
    """One position from the open of minute i0, held at most MAX_HOLD_MIN minutes."""
    lo, hi = i0 - 1, min(i0 + MAX_HOLD_MIN, len(m1.t))
    s = Series('1m', m1.t[lo:hi], m1.o[lo:hi], m1.h[lo:hi], m1.l[lo:hi], m1.c[lo:hi])
    n = len(s.t)
    r = simulate(s, [side] * n, risk, 1, n, A=a1m[lo:hi], fund_t=fund[0], fund_r=fund[1], stop_px=[sl] * n)
    if not r.trades:
        return None  # skipped: stop beyond the 10x liquidation buffer
    t = r.trades
    move = sum(x['side'] * (x['px'] - x['ep']) * x['qty'] for x in t) / (t[0]['ep'] * sum(x['qty'] for x in t))
    return dict(move=move, ret=sum(x['ret'] for x in t), reason=t[-1]['kind'], minutes=t[-1]['bars'])


def risks(entry: float, sl: float, tp: float) -> dict:
    d = abs(entry - sl)
    base = dict(sizing='fixed', lev=LEV, tp_r=abs(tp - entry) / d)
    return {'FLEET': Risk(**base, be_r=BE_MOVE * entry / d),
            'TIERS': Risk(**base, lock_steps=TIERS, trail_mult=1.5, trail_act_r=2.0)}


def summary(name: str, rows: list) -> str:
    if not rows:
        return f'  {name:6s} no trades'
    rets = [r['ret'] for r in rows]
    wins = [r['move'] for r in rows if r['move'] > 0]
    sd = st.pstdev(rets) or 1e-12
    reasons = {}
    for r in rows:
        reasons[r['reason']] = reasons.get(r['reason'], 0) + 1
    return (f"  {name:6s} n {len(rows):4d}  win {len(wins) / len(rows) * 100:4.1f}%  "
            f"mean margin ret {st.fmean(rets) * 100:+6.2f}%  (t {st.fmean(rets) / sd * len(rets) ** 0.5:+5.2f})  "
            f"median {st.median(rets) * 100:+6.2f}%  winners in 1-10% move: {sum(1 for w in wins if .01 <= w <= .10)}/{len(wins)}"
            f"  mean move {st.fmean(r['move'] for r in rows) * 100:+.3f}%  exits {reasons}")


def load(sym: str):
    cols = b1m.load_1m(sym)
    m1 = Series('1m', cols['t'], cols['o'], cols['h'], cols['l'], cols['c'])
    m15, h1 = b1m.resample(cols, '15m'), b1m.resample(cols, '1h')
    return m1, m15, h1, atr(m15, 14)


def run(models: list):
    rnd = random.Random(13)
    _, b15, bh1, ba15 = load(ANCHOR)
    b_index = {t: k for k, t in enumerate(b15.t)}
    data, jobs = {}, []
    for sym in ALTS:
        m1, m15, h1, a15 = load(sym)
        data[sym] = (m1, m15, a15, b1m.load_funding(sym))
        for k in sorted(rnd.sample(range(200, len(m15.t) - 200), SAMPLES_PER_SYMBOL)):
            if m15.t[k] not in b_index:
                continue
            s, b = context(m15, h1, k, a15), context(b15, bh1, b_index[m15.t[k]], ba15)
            jobs.append(dict(key=f'{sym}:{m15.t[k]}', sym=sym, k=k, price=s['price'], prompt=prompt(sym, s, b)))
    for model in models:
        answers = ask_all(model, jobs)
        report(model, jobs, answers, data)


def report(model: str, jobs: list, answers: dict, data: dict):
    lines = [f'v13 MiniCPM fleet replay: model {model}, {len(jobs)} decision points, 1m path, 10x isolated, 48h max hold']
    for sym in ALTS:
        m1, m15, a15, fund = data[sym]
        a1m = to_1m(a15, m15, m1.t)
        rows, holds, invalid, skipped = {'FLEET': [], 'TIERS': [], 'FLIP': []}, 0, 0, 0
        for j in (j for j in jobs if j['sym'] == sym and j['key'] in answers):
            dec = parse_and_validate(answers[j['key']], j['price'])
            if dec is None:
                invalid += 1
                continue
            if dec == 'HOLD':
                holds += 1
                continue
            side, entry, sl, tp = dec
            i0 = bisect_left(m1.t, m15.t[j['k']] + 900_000)
            for name, risk in risks(entry, sl, tp).items():
                out = trade(m1, i0, side, sl, tp, a1m, risk, fund)
                if out:
                    rows[name].append(out)
                elif name == 'FLEET':
                    skipped += 1
            flip = trade(m1, i0, -side, 2 * entry - sl, 2 * entry - tp, a1m, risks(entry, sl, tp)['FLEET'], fund)
            if flip:
                rows['FLIP'].append(flip)
        n = sum(1 for j in jobs if j['sym'] == sym and j['key'] in answers)
        lines.append(f"\n--- {sym}: {n} prompts, HOLD {holds}, rejected by fleet validation {invalid}, "
                     f"entries {n - holds - invalid} (stop beyond 10x liquidation buffer, not traded: {skipped})")
        lines += [summary(name, r) for name, r in rows.items()]
    text = '\n'.join(lines) + '\n'
    (RESULTS / f"v13-minicpm-{model.replace('/', '_').replace(':', '_')}.txt").write_text(text)
    print(text)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run(sys.argv[1:])
