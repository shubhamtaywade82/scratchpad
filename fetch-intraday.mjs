// Fetch SOLUSDT USD-M PERP intraday candles for INTRADAY + SWING trading research.
// Uses @nemesis-oss/binance-sdk createUSDMClient -> usdm.market.klines (public, no keys).
// Pulls: 15m (~2yr), 1h (~3yr), 4h (~3yr), 1d (~3yr) with pagination + dedupe.
import { createUSDMClient } from '@nemesis-oss/binance-sdk';
import fs from 'node:fs';

const SYMBOL = process.argv[2] || 'SOLUSDT.PERP';
const usdm = createUSDMClient();
const MS = { m: 60e3, h: 3600e3, d: 86400e3 };

async function fetchAllKlines(interval, msPer, limitTotal) {
  const now = Date.now();
  const start = now - msPer * limitTotal;
  const out = [];
  let cursor = start;
  while (out.length < limitTotal) {
    const batch = await usdm.market.klines(SYMBOL, interval, { startTime: cursor, endTime: now, limit: 1000 });
    if (!batch.length) break;
    out.push(...batch);
    const last = batch[batch.length - 1].openTime + msPer;
    if (last <= cursor) break;
    cursor = last;
    if (batch.length < 1000) break;
  }
  const map = new Map(out.map((k) => [k.openTime, k]));
  return [...map.values()].sort((a, b) => a.openTime - b.openTime);
}

console.log(`Fetching intraday futures klines for ${SYMBOL} ...`);
const [k15m, k1h, k4h, k1d] = await Promise.all([
  fetchAllKlines('15m', 15 * MS.m, 70000),  // ~2 years of quarter-hours (365*2*96 = 70080)
  fetchAllKlines('1h', MS.h, 26000),        // ~3 years of hours (365*3*24 = 26280)
  fetchAllKlines('4h', 4 * MS.h, 2700),     // ~450 days
  fetchAllKlines('1d', MS.d, 1500),         // ~4.1 years
]);
let k1hFull = k1h;
if (k1h.length < 26000) console.warn(`1h shorter than requested: got ${k1h.length} of 26000 bars`);
console.log(`15m=${k15m.length} 1h=${k1hFull.length} 4h=${k4h.length} 1d=${k1d.length}`);
console.log(`coverage: 15m ${(k15m.length*15/60/24).toFixed(0)}d | 1h ${(k1hFull.length/24).toFixed(0)}d | 4h ${(k4h.length*4/24).toFixed(0)}d | 1d ${(k1d.length).toFixed(0)}d`);

const payload = {
  symbol: SYMBOL,
  fetchedAt: new Date().toISOString(),
  klines: { '15m': k15m, '1h': k1hFull, '4h': k4h, '1d': k1d },
};
fs.writeFileSync(`/workspace/data/${SYMBOL}-intraday.json`, JSON.stringify(payload));
console.log('Saved /workspace/data/' + SYMBOL + '-intraday.json');
usdm.close();
