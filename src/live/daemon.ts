import { createUSDMClient } from '@nemesis-oss/binance-sdk';
import { calculateAlmaSeries, calculateAtrSeries } from '../indicators/alma.js';
import { Kline, StrategyParams } from '../types.js';
import { getOrFetchKlines } from '../data/fetcher.js';

export interface LiveSignalAlert {
  readonly timestamp: number;
  readonly symbol: string;
  readonly direction: 'LONG' | 'SHORT' | 'NEUTRAL';
  readonly currentPrice: number;
  readonly fastAlma: number;
  readonly slowAlma: number;
  readonly htfTrend: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  readonly suggestedStopPrice?: number;
  readonly suggestedTargetPrice?: number;
}

function checkHtfRegime(htfBars: Kline[]): 'BULLISH' | 'BEARISH' | 'NEUTRAL' {
  const closes = htfBars.map((k) => k.close);
  const fast = calculateAlmaSeries(closes, { length: 21, offset: 0.85, sigma: 6 });
  const slow = calculateAlmaSeries(closes, { length: 50, offset: 0.85, sigma: 6 });
  const n = htfBars.length - 1;
  if (isNaN(fast[n]) || isNaN(slow[n]) || isNaN(slow[n - 1])) return 'NEUTRAL';
  if (fast[n] > slow[n] && slow[n] >= slow[n - 1]) return 'BULLISH';
  if (fast[n] < slow[n] && slow[n] <= slow[n - 1]) return 'BEARISH';
  return 'NEUTRAL';
}

function evaluateCurrentSignal(
  execBars: Kline[],
  htfBars: Kline[],
  params: StrategyParams
): LiveSignalAlert {
  const n = execBars.length - 1;
  const closes = execBars.map((k) => k.close);
  const fast = calculateAlmaSeries(closes, params.fastAlma);
  const slow = calculateAlmaSeries(closes, params.slowAlma);
  const atr = calculateAtrSeries(execBars, 14);

  const htfTrend = checkHtfRegime(htfBars);
  const isBullCross = fast[n - 1] <= slow[n - 1] && fast[n] > slow[n];
  const isBearCross = fast[n - 1] >= slow[n - 1] && fast[n] < slow[n];

  const price = execBars[n].close;
  const atrVal = atr[n];
  const stopDist = atrVal * params.atrStopMultiplier;

  if (isBullCross && htfTrend === 'BULLISH') {
    return {
      timestamp: execBars[n].closeTime,
      symbol: 'SOLUSDT',
      direction: 'LONG',
      currentPrice: price,
      fastAlma: fast[n],
      slowAlma: slow[n],
      htfTrend,
      suggestedStopPrice: price - stopDist,
      suggestedTargetPrice: price + stopDist * params.riskRewardRatio,
    };
  }

  if (isBearCross && htfTrend === 'BEARISH') {
    return {
      timestamp: execBars[n].closeTime,
      symbol: 'SOLUSDT',
      direction: 'SHORT',
      currentPrice: price,
      fastAlma: fast[n],
      slowAlma: slow[n],
      htfTrend,
      suggestedStopPrice: price + stopDist,
      suggestedTargetPrice: price - stopDist * params.riskRewardRatio,
    };
  }

  return {
    timestamp: execBars[n].closeTime,
    symbol: 'SOLUSDT',
    direction: 'NEUTRAL',
    currentPrice: price,
    fastAlma: fast[n],
    slowAlma: slow[n],
    htfTrend,
  };
}

export async function checkLiveMarketSignal(
  symbol: string,
  params: StrategyParams
): Promise<LiveSignalAlert> {
  const [execBars, htfBars] = await Promise.all([
    getOrFetchKlines(symbol, '2h'),
    getOrFetchKlines(symbol, '4h'),
  ]);
  return evaluateCurrentSignal(execBars, htfBars, params);
}
