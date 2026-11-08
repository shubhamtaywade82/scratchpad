import fs from 'node:fs';
import path from 'node:path';
import { createUSDMClient } from '@nemesis-oss/binance-sdk';
import { CandleInterval, Kline } from '../types.js';

interface RawKlineRecord {
  openTime: number;
  open: number | string;
  high: number | string;
  low: number | string;
  close: number | string;
  volume: number | string;
  closeTime: number;
}

function normalizeKline(raw: RawKlineRecord): Kline {
  return {
    openTime: Number(raw.openTime),
    open: Number(raw.open),
    high: Number(raw.high),
    low: Number(raw.low),
    close: Number(raw.close),
    volume: Number(raw.volume),
    closeTime: Number(raw.closeTime),
  };
}

export function loadCachedKlines(
  filePath: string,
  interval: CandleInterval
): Kline[] | null {
  if (!fs.existsSync(filePath)) return null;
  const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  const rawList = content.klines?.[interval] as RawKlineRecord[] | undefined;
  if (!rawList || rawList.length === 0) return null;
  return rawList.map(normalizeKline);
}

const INTERVAL_MS: Record<CandleInterval, number> = {
  '5m': 300_000,
  '15m': 900_000,
  '1h': 3_600_000,
  '2h': 7_200_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
};

export async function fetchBinanceKlines(
  symbol: string,
  interval: CandleInterval,
  totalLimit = 2000
): Promise<Kline[]> {
  const client = createUSDMClient();
  const allKlines: Kline[] = [];
  const durationMs = totalLimit * (INTERVAL_MS[interval] || 3_600_000);
  let nextStartTime = Date.now() - durationMs;

  try {
    while (allKlines.length < totalLimit) {
      const remaining = totalLimit - allKlines.length;
      const batchLimit = Math.min(1000, remaining);
      const batch = await client.market.klines(symbol, interval, {
        startTime: nextStartTime,
        limit: batchLimit,
      });

      if (!batch || batch.length === 0) break;
      allKlines.push(...batch.map((b) => normalizeKline(b as RawKlineRecord)));
      const lastBar = batch[batch.length - 1];
      nextStartTime = Number(lastBar.closeTime) + 1;
      if (batch.length < batchLimit) break;
    }
  } finally {
    client.close();
  }

  // Deduplicate timestamps in case of overlapping boundaries
  const map = new Map<number, Kline>();
  for (const bar of allKlines) map.set(bar.openTime, bar);
  return Array.from(map.values()).sort((a, b) => a.openTime - b.openTime);
}

export async function getOrFetchKlines(
  symbol: string,
  interval: CandleInterval,
  cacheDir = 'data'
): Promise<Kline[]> {
  const candidateFiles = [
    path.join(cacheDir, `${symbol}-intraday.json`),
    path.join(cacheDir, `${symbol}-${interval}.json`),
  ];
  for (const f of candidateFiles) {
    const cached = loadCachedKlines(f, interval);
    if (cached && cached.length > 500) return cached;
  }
  return fetchBinanceKlines(symbol, interval, 3000);
}
