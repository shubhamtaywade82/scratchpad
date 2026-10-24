"""Binance USD-M 1m klines and funding from data.binance.vision, plus 1m -> HTF resampling.

Usage: python3 -m research.binance_1m fetch [SYM ...]
"""
import csv
import hashlib
import io
import sys
import urllib.error
import urllib.request
import zipfile
from array import array
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from research.engine import Series

ROOT = Path(__file__).resolve().parent.parent / 'data' / 'binance-1m'
BASE = 'https://data.binance.vision/data/futures/um'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT')
START = date(2021, 1, 1)
MINUTE_MS = 60_000
TF_MS = {'15m': 900_000, '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000}


class ChecksumError(Exception):
    pass


def _get(url: str) -> bytes | None:
    """Return the body of `url`, or None on 404 (month/day not published yet)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def _download(url: str, dest: Path) -> bool:
    """Download a zip and verify it against Binance's published sha256. True if present."""
    if dest.exists():
        return True
    body = _get(url)
    if body is None:
        return False
    expected = (_get(url + '.CHECKSUM') or b'').split()[:1]
    actual = hashlib.sha256(body).hexdigest()
    if not expected or expected[0].decode() != actual:
        raise ChecksumError(f'{url}: sha256 {actual} != published {expected}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True


def _months(until: date) -> list[str]:
    months, d = [], START
    while d < until.replace(day=1):
        months.append(f'{d.year}-{d.month:02d}')
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def fetch(sym: str, today: date) -> None:
    """Fetch monthly klines and funding up to last month, then daily klines for this month."""
    for month in _months(today):
        _download(f'{BASE}/monthly/klines/{sym}/1m/{sym}-1m-{month}.zip',
                  ROOT / sym / f'{sym}-1m-{month}.zip')
        _download(f'{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{month}.zip',
                  ROOT / sym / 'funding' / f'{sym}-fundingRate-{month}.zip')
    d = today.replace(day=1)
    while d < today:
        _download(f'{BASE}/daily/klines/{sym}/1m/{sym}-1m-{d.isoformat()}.zip',
                  ROOT / sym / 'daily' / f'{sym}-1m-{d.isoformat()}.zip')
        d += timedelta(days=1)


def _csv_rows(path: Path):
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            for row in csv.reader(io.TextIOWrapper(fh)):
                if row and row[0][0].isdigit():
                    yield row


def _open_ms(row) -> float:
    t = float(row[0])
    return t // 1000 if t > 1e14 else t  # some 2025+ archives are in microseconds


def _first_ms(path: Path) -> float:
    return _open_ms(next(_csv_rows(path)))


def load_1m(sym: str) -> dict[str, array]:
    """All local 1m bars for `sym` as columns t,o,h,l,c,v,tb (sorted, deduplicated)."""
    cols = {k: array('d') for k in ('t', 'o', 'h', 'l', 'c', 'v', 'tb')}
    # Some monthly archives are truncated (SOL/XRP 2022-02, 2022-04); daily files patch them, so order by content
    files = sorted(list((ROOT / sym).glob('*.zip')) + list((ROOT / sym / 'daily').glob('*.zip')), key=_first_ms)
    last_t = -1.0
    for path in files:
        for row in _csv_rows(path):
            t = _open_ms(row)
            if t <= last_t:
                continue
            last_t = t
            for key, idx in (('t', None), ('o', 1), ('h', 2), ('l', 3), ('c', 4), ('v', 5), ('tb', 9)):
                cols[key].append(t if idx is None else float(row[idx]))
    return cols


def load_funding(sym: str) -> tuple[list[int], list[float]]:
    """Funding settlement times (ms) and rates, ascending."""
    rows = []
    for path in sorted((ROOT / sym / 'funding').glob('*.zip')):
        rows += [(int(r[0]), float(r[2])) for r in _csv_rows(path)]
    rows.sort()
    return [t for t, _ in rows], [r for _, r in rows]


def fill_gaps(sym: str) -> list[str]:
    """Download daily archives for every UTC day that has missing minutes; returns the days fetched."""
    t = load_1m(sym)['t']
    days = set()
    for a, b in zip(t, t[1:]):
        for m in range(int(a) + MINUTE_MS, int(b), MINUTE_MS):
            days.add(datetime.fromtimestamp(m / 1000, timezone.utc).date().isoformat())
    fetched = [d for d in sorted(days) if _download(f'{BASE}/daily/klines/{sym}/1m/{sym}-1m-{d}.zip',
                                                       ROOT / sym / 'daily' / f'{sym}-1m-{d}.zip')]
    return fetched


def missing_minutes(cols: dict[str, array]) -> int:
    """Count of 1m bars absent between the first and last timestamp."""
    t = cols['t']
    return int((t[-1] - t[0]) / MINUTE_MS) + 1 - len(t) if len(t) else 0


def resample(cols: dict[str, array], tf: str) -> Series:
    """UTC-epoch-aligned HTF bars; buckets missing any minute are dropped (engine sees a gap)."""
    tf_ms, need = TF_MS[tf], TF_MS[tf] // MINUTE_MS
    out = Series(tf=tf, t=[], o=[], h=[], l=[], c=[], v=[], tb=[])
    t, o, h, l, c, v, tb = (cols[k] for k in ('t', 'o', 'h', 'l', 'c', 'v', 'tb'))
    i, n = 0, len(t)
    while i < n:
        bucket = int(t[i]) // tf_ms
        j = i
        while j < n and int(t[j]) // tf_ms == bucket:
            j += 1
        if j - i == need:
            out.t.append(bucket * tf_ms)
            out.o.append(o[i])
            out.h.append(max(h[i:j]))
            out.l.append(min(l[i:j]))
            out.c.append(c[j - 1])
            out.v.append(sum(v[i:j]))
            out.tb.append(sum(tb[i:j]))
        i = j
    return out


if __name__ == '__main__':
    if sys.argv[1:2] != ['fetch']:
        sys.exit(__doc__)
    today = datetime.now(timezone.utc).date()
    for sym in sys.argv[2:] or SYMBOLS:
        fetch(sym, today)
        print(sym, 'patched days:', fill_gaps(sym), 'missing minutes:', missing_minutes(load_1m(sym)), flush=True)
