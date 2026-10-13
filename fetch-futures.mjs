// Fetch SOLUSDT PERPETUAL FUTURES data using @nemesis-oss/binance-sdk (USDMClient, public endpoints)
// Pulls: futures klines (1d/4h), funding rate history (full 8h series), open interest history (5m -> daily),
// top-trader long/short ratios, taker buy/sell ratio. All public — no API keys required.
import { createUSDMClient } from '@nemesis-oss/binance-sdk';
import fs from 'node:fs';

const SYMBOL = process.argv[2] || 'SOLUSDT.PERP'; // e.g. SOLUSDT.PERP or SOLUSDC.PERP
const usdm = createUSDMClient(); // no credentials needed for public market data

const MS = { h: 3600e3, d: 86400e3 };

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

// Funding rate history: /fapi/v1/fundingRate caps at 1000 rows per call -> paginate by startTime
async function fetchFunding() {
  const now = Date.now();
  const out = [];
  let cursor = now - 1500 * MS.d; // ~4 years back
  while (true) {
    const batch = await usdm.data.fundingRateHistory(SYMBOL, { startTime: cursor, endTime: now, limit: 1000 });
    if (!batch || !batch.length) break;
    out.push(...batch);
    const lastTime = batch[batch.length - 1].fundingTime;
    if (lastTime <= cursor || batch.length < 1000) break;
    cursor = lastTime + 1;
  }
  const map = new Map(out.map((f) => [f.fundingTime, f]));
  return [...map.values()].sort((a, b) => a.fundingTime - b.fundingTime);
}

// Open interest history: only last 30 days available from Binance; period max 1d*limit... use 1h, 720 rows
async function fetchOI(period, limit) {
  try {
    return await usdm.data.openInterestHist(SYMBOL, period, limit);
  } catch (e) {
    console.warn('OI fetch failed:', e.message?.slice(0, 120));
    return [];
  }
}

async function fetchRatio(fn, period, limit) {
  try {
    return await fn.call(usdm.data, SYMBOL, period, limit);
  } catch (e) {
    console.warn('ratio fetch failed:', e.message?.slice(0, 120));
    return [];
  }
}

console.log(`Fetching USDM-M futures data for ${SYMBOL} ...`);
const [k1d, k4h, funding, oi1h, topAcct, topPos, globalAcct, taker] = await Promise.all([
  fetchAllKlines('1d', MS.d, 1500),
  fetchAllKlines('4h', 4 * MS.h, 1800),
  fetchFunding(),
  fetchOI('1h', 500),
  fetchRatio(usdm.data.topLongShortAccountRatio, '1d', 500),
  fetchRatio(usdm.data.topLongShortPositionRatio, '1d', 500),
  fetchRatio(usdm.data.globalLongShortAccountRatio, '1d', 500),
  fetchRatio(usdm.data.takerLongShortRatio, '1d', 500),
]);
console.log(`klines 1d=${k1d.length} 4h=${k4h.length} funding=${funding.length} oi=${oi1h.length} topAcct=${topAcct.length} topPos=${topPos.length} global=${globalAcct.length} taker=${taker.length}`);

let live = null;
try {
  live = {
    premiumIndex: await usdm.data.premiumIndex(SYMBOL),
    openInterest: await usdm.data.openInterest(SYMBOL),
    ticker24hr: await usdm.market.ticker24hr(SYMBOL),
  };
} catch (e) { console.warn('live snapshot failed:', e.message?.slice(0, 120)); }

const payload = { symbol: SYMBOL, fetchedAt: new Date().toISOString(), klines: { '1d': k1d, '4h': k4h }, funding, oi1h, topAcct, topPos, globalAcct, taker, live };
fs.writeFileSync(`/workspace/data/${SYMBOL}-futures.json`, JSON.stringify(payload));
console.log('Saved /workspace/data/' + SYMBOL + '-futures.json');
usdm.close();
