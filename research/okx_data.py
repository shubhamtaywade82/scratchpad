"""OKX public market data fetcher. Writes JSON with provenance to data/okx/.

Why OKX: Binance (HTTP 451) and Bybit (HTTP 403, country block) are unavailable from this environment. OKX answers
normally. Using a reachable venue is not a bypass of a restriction. Data is OKX's own, not Binance's, so backtests on
it test OKX prices, OKX funding and OKX open interest.

Endpoints and limits observed:
  market/history-candles   100 rows per page, paged backwards with `after` (open time, ms)
  public/funding-rate-history  100 per page, paged backwards with `after`
  rubik/.../open-interest-volume  recent window only: 1H ~ 720 points (~30 days), 1D ~ 180 points. `begin` is rejected.
  delivery futures: current listings only; expired contracts are served by candles until settlement, then 'already settled'.

Usage:
  python3 -m research.okx_data candles SOL-USDT-SWAP 1H 2022-01-01
  python3 -m research.okx_data funding SOL-USDT-SWAP 2022-01-01
  python3 -m research.okx_data expiries SOL-USD 2024-01-01 2026-10-13
  python3 -m research.okx_data oi SOL 1H
  python3 -m research.okx_data oi SOL 1D
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = 'https://www.okx.com/api/v5'
OUT_DIR = 'data/okx'
BAR_MS = {'1H': 3_600_000, '4H': 14_400_000, '1D': 86_400_000, '15m': 900_000}


def _get(path: str, params: dict):
    q = '&'.join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"{BASE}/{path}" + (f"?{q}" if q else '')
    for attempt in range(4):
        out = subprocess.run(['curl', '-sS', '--max-time', '30', url], capture_output=True, text=True)
        try:
            body = json.loads(out.stdout)
        except json.JSONDecodeError:
            body = None
        if body is not None and body.get('code') in ('0', 0):
            return body['data']
        if body is not None and body.get('code') not in ('50011', '50013'):    # not a rate-limit: return the error
            return ('ERR', body.get('code'), body.get('msg'))
        time.sleep(1.5 * (attempt + 1))
    return ('ERR', 'retries', out.stdout[:200])


def ms(date_str: str) -> int:
    return int(datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_candles(inst: str, bar: str, since: str, until_ms=None):
    """All candles from `since` up to now (or until_ms), oldest first, deduplicated."""
    lo = ms(since)
    rows, after = {}, None
    while True:
        data = _get('market/history-candles', dict(instId=inst, bar=bar, limit=100, after=after))
        if isinstance(data, tuple):
            if data[1] == '51001' or 'settled' in str(data[2]):
                break
            raise RuntimeError(f"{inst} {bar}: {data}")
        if not data:
            break
        for r in data:
            rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in data)
        if oldest <= lo or len(data) < 100:
            break
        after = oldest
        time.sleep(0.12)
    out = [dict(t=t, o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]),
                vol=float(r[5]), volCcy=float(r[6]), volQuote=float(r[7]), confirm=r[8])
           for t, r in sorted(rows.items()) if t >= lo and (until_ms is None or t <= until_ms)]
    return out


def fetch_funding(inst: str, since: str):
    lo = ms(since)
    rows, after = {}, None
    while True:
        data = _get('public/funding-rate-history', dict(instId=inst, limit=100, after=after))
        if isinstance(data, tuple):
            raise RuntimeError(f"{inst} funding: {data}")
        if not data:
            break
        for r in data:
            rows[int(r['fundingTime'])] = r
        oldest = min(int(r['fundingTime']) for r in data)
        if oldest <= lo or len(data) < 100:
            break
        after = oldest
        time.sleep(0.12)
    return [dict(t=t, rate=float(r['realizedRate'] or r['fundingRate']), method=r['method'])
            for t, r in sorted(rows.items()) if t >= lo]


def fetch_oi(ccy: str, period: str):
    """Rubik open-interest-volume for a currency. Recent window only (1H ~720 points, 1D ~180).
    Returns rows of (ts, open_interest_usd, volume_usd), oldest first."""
    data = _get('rubik/stat/contracts/open-interest-volume', dict(ccy=ccy, period=period))
    if isinstance(data, tuple):
        raise RuntimeError(f"OI {ccy} {period}: {data}")
    rows = sorted((int(r[0]), float(r[1]), float(r[2])) for r in data)
    return [dict(t=t, oi=oi, vol=v) for t, oi, v in rows]


def save(name: str, payload: dict) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    payload['fetched_at'] = datetime.now(timezone.utc).isoformat()
    payload['source'] = 'OKX public REST (www.okx.com/api/v5)'
    with open(path, 'w') as f:
        json.dump(payload, f)
    return path


def _probe_expiry(inst: str):
    data = _get('market/history-candles', dict(instId=inst, bar='1D', limit=1))
    if isinstance(data, tuple):
        return (inst, 'settled') if 'settled' in str(data[2]) else None
    return (inst, 'live') if data else None


def _probe_date_instruments(uly: str, ymd: str):
    out = []
    for inst in (f"{uly}_UM-{ymd}", f"{uly}-{ymd}"):
        res = _probe_expiry(inst)
        if not res:
            continue
        out.append(res)
        if res[1] == 'live':
            break
    return out


def expiries(uly: str, start: str, end: str):
    """Probe every date in [start, end] as a candidate delivery ID '<UL>_UM-YYMMDD' (also the plain '<UL>-YYMMDD' form).
    Returns the IDs that exist in the candle endpoint (live or settled)."""
    found = []
    d0, d1 = datetime.strptime(start, '%Y-%m-%d'), datetime.strptime(end, '%Y-%m-%d')
    d = d0
    while d <= d1:
        if d.weekday() == 4:
            found.extend(_probe_date_instruments(uly, d.strftime('%y%m%d')))
            time.sleep(0.1)
        d += timedelta(days=1)
    return found


def _handle_expiries(argv):
    found = expiries(argv[1], argv[2], argv[3])
    path = save(f"expiries-{argv[1]}.json", dict(uly=argv[1], found=found))
    print(f"{len(found)} delivery IDs -> {path}")
    for f in found:
        print('  ', f)


def main(argv):
    cmd = argv[0] if argv else None
    if cmd == 'candles':
        inst, bar, since = argv[1], argv[2], argv[3]
        rows = fetch_candles(inst, bar, since)
        path = save(f"{inst}-{bar}.json", dict(instId=inst, bar=bar, since=since, rows=rows))
        print(f"{inst} {bar}: {len(rows)} candles -> {path}")
    elif cmd == 'funding':
        inst, since = argv[1], argv[2]
        rows = fetch_funding(inst, since)
        path = save(f"{inst}-funding.json", dict(instId=inst, since=since, rows=rows))
        print(f"{inst} funding: {len(rows)} events -> {path}")
    elif cmd == 'oi':
        ccy, period = argv[1], argv[2]
        rows = fetch_oi(ccy, period)
        path = save(f"oi-{ccy}-{period}.json", dict(ccy=ccy, period=period, rows=rows,
                                                    note='rubik window only; oi/vol as returned by OKX (USD)'))
        print(f"{ccy} OI {period}: {len(rows)} points -> {path}")
    elif cmd == 'expiries':
        _handle_expiries(argv)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
