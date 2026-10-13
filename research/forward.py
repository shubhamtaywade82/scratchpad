"""Forward paper-trading of the 1h volatility-adaptive Supertrend on live SOL-USD hourly bars.

Data: Kraken public OHLC (SOLUSD, 60-minute). Binance USD-M is geo-restricted from the research environment (HTTP 451),
so this is SPOT, not perpetual: no funding is charged, and fees/slippage use the perpetual cost model (5 + 3 bps/side).
The engine is causal, so replaying stored bars reproduces exactly what a live run would have decided bar by bar.

Store:   forward/bars-kraken-1h.json  append-only completed bars (dedupe by open time; gaps are reported, never filled)
         forward/ledger.json          deployment params, status, closed trades, open position, equity
Commands:
  python3 -m research.forward deploy   pin the forward start to the first bar not yet complete, start flat
  python3 -m research.forward update   fetch, append completed bars, replay, write the ledger
  python3 -m research.forward status   print the ledger summary
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from research.adaptive_st import vol_adaptive_st_sig
from research.engine import Risk, atr, simulate, supertrend_sig, to_series

STORE = 'forward/bars-kraken-1h.json'
LEDGER = 'forward/ledger.json'
KRAKEN_URL = 'https://api.kraken.com/0/public/OHLC?pair=SOLUSD&interval=60'
HOUR_MS = 3_600_000
WARMUP_BARS = 300          # indicator warm-up before the forward start (ATR14 + 100-bar percentile window)
RISK = dict(sizing='risk', risk_pct=0.01, lev=5.0, sl_mult=3.0)   # 1% risk, 3-ATR stop, 5x margin ceiling
SIGNAL = 'vol-adaptive Supertrend p20 L100 1.5-4 (candidate)'
BENCH = 'fixed Supertrend p10 x2 (benchmark)'


def _now_ms() -> int:
    return int(time.time() * 1000)


def fetch_kraken() -> list:
    """Return completed hourly bars from Kraken. The forming candle is dropped."""
    out = subprocess.run(['curl', '-sS', '--max-time', '30', KRAKEN_URL], capture_output=True, text=True, check=True).stdout
    body = json.loads(out)
    if body.get('error'):
        raise RuntimeError(f"kraken error: {body['error']}")
    rows = body['result']['SOLUSD']
    now = _now_ms()
    bars = []
    for r in rows:
        t = int(r[0]) * 1000
        if t + HOUR_MS > now:      # bar still forming
            continue
        bars.append(dict(openTime=t, open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]),
                         volume=float(r[6])))
    return bars


def load_store() -> dict:
    if not os.path.exists(STORE):
        return {'source': 'kraken SOLUSD 60m', 'bars': []}
    return json.load(open(STORE))


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def merge(store: dict, fetched: list) -> int:
    have = {b['openTime']: b for b in store['bars']}
    added = 0
    for b in fetched:
        if b['openTime'] not in have:
            have[b['openTime']] = b
            added += 1
    store['bars'] = [have[t] for t in sorted(have)]
    store['fetched_at'] = datetime.now(timezone.utc).isoformat()
    return added


def contiguous_prefix(bars: list):
    """Longest run of hourly-contiguous bars from the start. Returns (run, first_gap_time or None)."""
    run = [bars[0]] if bars else []
    for a, b in zip(bars, bars[1:]):
        if b['openTime'] - a['openTime'] != HOUR_MS:
            return run, a['openTime'] + HOUR_MS
        run.append(b)
    return run, None


def _waiting(n_bars: int) -> dict:
    out = dict(status='WAITING', forward_bars=n_bars, bars_total=0)
    for name in ('signal', 'benchmark'):
        out.update({f'{name}_equity': 1.0, f'{name}_closed': [], f'{name}_open_position': None,
                    f'{name}_flat_bars': 0, f'{name}_positions': 0})
    return out


def _format_open_pos(open_t, bars, mark_px):
    if not open_t:
        return None
    t = open_t[-1]
    return dict(side='long' if t['side'] > 0 else 'short',
                entry_utc=datetime.fromtimestamp(bars[t['k_in']]['openTime'] / 1000, timezone.utc).isoformat(),
                entry_px=t['ep'], mark_px=mark_px, unrealised_ret=t['ret'])


def _format_closed_trades(closed, bars):
    return [
        dict(side='long' if t['side'] > 0 else 'short',
             entry_utc=datetime.fromtimestamp(bars[t['k_in']]['openTime'] / 1000, timezone.utc).isoformat(),
             exit_utc=datetime.fromtimestamp(bars[t['k_out']]['openTime'] / 1000, timezone.utc).isoformat(),
             entry_px=round(t['ep'], 4), exit_px=round(t['px'], 4), reason=t['reason'], ret=t['ret'], r=t['r'])
        for t in closed
    ]


def replay(bars: list, start_t: int):
    """Causal replay over stored bars from the forward start. Returns the ledger body."""
    if not bars:
        return _waiting(0)
    s = to_series('1h', bars)
    start = next((i for i, b in enumerate(bars) if b['openTime'] >= start_t), len(bars))
    n = len(s)
    out = {'bars_total': n, 'last_bar_utc': datetime.fromtimestamp(bars[-1]['openTime'] / 1000, timezone.utc).isoformat()}
    if n - start < 2:
        out.update(_waiting(n - start))
        out['bars_total'] = n
        return out
    risk, A = Risk(**RISK), atr(s, 14)
    sigs = {'signal': vol_adaptive_st_sig(s, 20, 100, 1.5, 4.0),
            'benchmark': supertrend_sig(s, 10, 2.0)}
    res = {}
    for key, sig in sigs.items():
        r = simulate(s, sig, risk, start, n, A=A, fee=0.0005, slip=0.0003)
        closed = [t for t in r.trades if t['reason'] != 'eod']
        open_t = [t for t in r.trades if t['reason'] == 'eod']
        res[key] = dict(equity=r.eq[-1], closed=_format_closed_trades(closed, bars),
                        open_position=_format_open_pos(open_t, bars, s.c[-1]),
                        flat_bars=sum(1 for p in r.pos if p == 0),
                        positions=len(closed) + len(open_t))
    out.update(status='LIVE', forward_bars=n - start, **{f"{k}_{f}": v for k in res for f, v in res[k].items()})
    return out


def cmd_deploy():
    store = load_store()
    fetched = fetch_kraken()
    merge(store, fetched)
    save_json(STORE, store)
    # first bar that opens after deployment: its decision uses only bars that are already complete, so no entry is backdated
    start_t = (_now_ms() // HOUR_MS + 1) * HOUR_MS
    ledger = dict(deployed_utc=datetime.now(timezone.utc).isoformat(), start_open_time_ms=start_t,
                  start_utc=datetime.fromtimestamp(start_t / 1000, timezone.utc).isoformat(),
                  signal=SIGNAL, benchmark=BENCH, risk=RISK, costs='taker 5 bps + slippage 3 bps per side; no funding (spot)',
                  data=store.get('source'), status='DEPLOYED', forward_bars=0, equity=1.0)
    save_json(LEDGER, ledger)
    print(f"deployed: forward start {ledger['start_utc']}; stored bars {len(store['bars'])}")


def cmd_update():
    if not os.path.exists(LEDGER):
        raise SystemExit("not deployed: run `python3 -m research.forward deploy` first")
    ledger = json.load(open(LEDGER))
    store = load_store()
    try:
        added = merge(store, fetch_kraken())
    except Exception as e:                      # network or venue failure: record it, do not touch the ledger's history
        ledger['last_error'] = f"{datetime.now(timezone.utc).isoformat()}: {e}"
        save_json(LEDGER, ledger)
        raise SystemExit(f"fetch failed, ledger unchanged: {e}")
    save_json(STORE, store)
    floor = ledger['start_open_time_ms'] - WARMUP_BARS * HOUR_MS
    run, gap = contiguous_prefix([b for b in store['bars'] if b['openTime'] >= floor])
    if gap is not None:
        ledger['status'] = 'GAP'
        ledger['gap_at_utc'] = datetime.fromtimestamp(gap / 1000, timezone.utc).isoformat()
        ledger['note'] = 'Missing hourly bar. Replay halted at the gap; resolve manually before trusting results.'
        save_json(LEDGER, ledger)
        raise SystemExit(f"gap at {ledger['gap_at_utc']}: replay halted")
    body = replay(run, ledger['start_open_time_ms'])
    ledger.update(body)
    ledger.pop('note', None)
    ledger['last_update_utc'] = datetime.now(timezone.utc).isoformat()
    ledger['new_bars_this_run'] = added
    save_json(LEDGER, ledger)
    print(json.dumps({k: ledger.get(k) for k in ('status', 'forward_bars', 'signal_equity', 'benchmark_equity',
                                                 'last_bar_utc', 'new_bars_this_run')}, indent=1))


def cmd_status():
    ledger = json.load(open(LEDGER))
    keys = ('status', 'start_utc', 'last_bar_utc', 'forward_bars', 'signal_equity', 'benchmark_equity')
    for k in keys:
        print(f"{k:<18} {ledger.get(k)}")
    for name in ('signal', 'benchmark'):
        closed = ledger.get(f'{name}_closed', [])
        wins = [c for c in closed if c['ret'] > 0]
        print(f"{name}: closed {len(closed)}  win {len(wins)}/{len(closed)}  open {ledger.get(f'{name}_open_position')}")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    {'deploy': cmd_deploy, 'update': cmd_update, 'status': cmd_status}[cmd]()
