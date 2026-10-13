// Fetch SOLUSDT historical klines using @nemesis-oss/binance-sdk (SpotClient, public market data)
import { SpotClient, CoreContext } from '@nemesis-oss/binance-sdk';
import fs from 'node:fs';

const SYMBOL = process.argv[2] || 'SOLUSDT';
const core = new CoreContext(); // no credentials needed for public market data
const spot = new SpotClient(core);

const MS = { m: 60e3, h: 3600e3, d: 86400e3 };
const INTERVALS = [
  ['1d', MS.d],
  ['4h', 4 * MS.h],
  ['1h', MS.h],
];

async function fetchAll(interval, msPer, limitTotal) {
  const now = Date.now();
  const start = now - msPer * limitTotal;
  const out = [];
  let cursor = start;
  while (out.length < limitTotal) {
    const batch = await spot.market.klines(SYMBOL, interval, {
      startTime: cursor,
      endTime: now,
      limit: 1000,
    });
    if (!batch.length) break;
    out.push(...batch);
    const last = batch[batch.length - 1].openTime + msPer;
    if (last <= cursor) break; // guard against non-progress
    cursor = last;
    if (batch.length < 1000) break;
  }
  // dedupe by openTime, keep chronological order
  const map = new Map(out.map((k) => [k.openTime, k]));
  return [...map.values()].sort((a, b) => a.openTime - b.openTime);
}

const data = {};
for (const [interval, msPer] of INTERVALS) {
  const total = interval === '1d' ? 1500 : interval === '4h' ? 1800 : 1440; // ~4y daily, ~300d 4h, ~60d 1h
  console.log(`Fetching ${SYMBOL} ${interval} (${total} candles)...`);
  data[interval] = await fetchAll(interval, msPer, total);
  console.log(`  got ${data[interval].length} candles`);
}

fs.writeFileSync(`/workspace/data/${SYMBOL}-klines.json`, JSON.stringify({ symbol: SYMBOL, fetchedAt: new Date().toISOString(), data }, null, 0));
console.log('Saved to /workspace/data/' + SYMBOL + '-klines.json');
spot.close();
