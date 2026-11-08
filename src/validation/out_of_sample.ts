import { BacktestSummary, Kline, StrategyParams } from '../types.js';
import { runBacktest } from '../backtest/engine.js';
import { calculateAlmaSeries } from '../indicators/alma.js';
import { getOrFetchKlines } from '../data/fetcher.js';

export interface SplitResult {
  readonly inSample: BacktestSummary;
  readonly outOfSample: BacktestSummary;
  readonly fullPeriod: BacktestSummary;
}

export function splitKlinesChronological(
  klines: Kline[],
  trainRatio = 0.7
): { train: Kline[]; test: Kline[] } {
  const cutoff = Math.floor(klines.length * trainRatio);
  return {
    train: klines.slice(0, cutoff),
    test: klines.slice(cutoff),
  };
}

function buildHtfContext(htfKlines: Kline[]) {
  const closes = htfKlines.map((k) => k.close);
  // HTF 21/50 ALMA for directional bias
  return {
    klines: htfKlines,
    fastAlma: calculateAlmaSeries(closes, { length: 21, offset: 0.85, sigma: 6 }),
    slowAlma: calculateAlmaSeries(closes, { length: 50, offset: 0.85, sigma: 6 }),
  };
}

export function evaluateTrainTestSplit(
  execBars: Kline[],
  htfBars: Kline[],
  params: StrategyParams,
  trainRatio = 0.7
): SplitResult {
  const { train, test } = splitKlinesChronological(execBars, trainRatio);
  const htfCtx = buildHtfContext(htfBars);

  const resTrain = runBacktest(train, params, htfCtx);
  const resTest = runBacktest(test, params, htfCtx);
  const resFull = runBacktest(execBars, params, htfCtx);

  return {
    inSample: resTrain.summary,
    outOfSample: resTest.summary,
    fullPeriod: resFull.summary,
  };
}

export async function runCrossAssetValidation(
  symbols: string[],
  params: StrategyParams
): Promise<Record<string, SplitResult>> {
  const results: Record<string, SplitResult> = {};
  for (const sym of symbols) {
    const [execKlines, htfKlines] = await Promise.all([
      getOrFetchKlines(sym, '2h'),
      getOrFetchKlines(sym, '4h'),
    ]);
    results[sym] = evaluateTrainTestSplit(execKlines, htfKlines, params, 0.7);
  }
  return results;
}
