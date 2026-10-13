"""Hyperliquid public info API: SOL perp funding history (hourly settlements) and 1h candles. Writes data/hl/.

Depth observed: funding history and candles start 2023-05 for SOL (the listing). fundingHistory returns at most 500 rows per
call, paged forward with startTime. candleSnapshot returns at most 5000 rows per call.

Usage:  python3 -m research.hl_data
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone

URL = 'https://api.hyperliquid.xyz/info'
OUT = 'data/hl'
HOUR = 3_600_000


def _post(body: dict):
    for attempt in range(4):
        out = subprocess.run(['curl', '-sS', '--max-time', '30', '-X', 'POST', '-H', 'Content-Type: application/json',
                              '-d', json.dumps(body), URL], capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"hyperliquid request failed: {out[:200]}")


def funding(coin: str, start_ms: int, end_ms: int):
    rows, cur = {}, start_ms
    while cur < end_ms:
        page = _post({"type": "fundingHistory", "coin": coin, "startTime": cur})
        if not isinstance(page, list) or not page:
            break
        for r in page:
            if r['time'] <= end_ms:
                rows[int(r['time'])] = float(r['fundingRate'])
        last = max(int(r['time']) for r in page)
        if last <= cur:
            break
        cur = last + 1
        time.sleep(0.15)
    return [dict(t=t, rate=rows[t]) for t in sorted(rows)]


def candles(coin: str, interval: str, start_ms: int, end_ms: int):
    """Paged candles. The API returns at most 5000 rows per call and keeps only recent history for 1h (~208 days)."""
    step_ms = {'1h': HOUR, '4h': 4 * HOUR, '1d': 24 * HOUR}[interval]
    rows, cur = {}, start_ms
    while cur < end_ms:
        page = _post({"type": "candleSnapshot",
                      "req": {"coin": coin, "interval": interval, "startTime": cur, "endTime": end_ms}})
        if not isinstance(page, list) or not page:
            break
        for c in page:
            rows[int(c['t'])] = dict(t=int(c['t']), o=float(c['o']), h=float(c['h']), l=float(c['l']),
                                     c=float(c['c']), v=float(c['v']))
        last = max(int(c['t']) for c in page)
        if last + step_ms <= cur:
            break
        cur = last + step_ms
        time.sleep(0.15)
    return [rows[t] for t in sorted(rows)]


def save(name, payload):
    os.makedirs(OUT, exist_ok=True)
    payload['fetched_at'] = datetime.now(timezone.utc).isoformat()
    payload['source'] = 'Hyperliquid public info API (api.hyperliquid.xyz/info)'
    path = os.path.join(OUT, name)
    with open(path, 'w') as f:
        json.dump(payload, f)
    return path


if __name__ == '__main__':
    start = int(datetime(2023, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() * 1000)
    fr = funding('SOL', start, end)
    print(f"HL SOL funding: {len(fr)} settlements -> {save('SOL-funding.json', dict(coin='SOL', rows=fr))}")
    for itv in ('1d', '4h', '1h'):
        cs = candles('SOL', itv, start, end)
        print(f"HL SOL {itv} candles: {len(cs)} -> {save(f'SOL-{itv}.json', dict(coin='SOL', interval=itv, rows=cs))}")
