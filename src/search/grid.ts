import {
  BacktestSummary,
  CandleInterval,
  Kline,
  StrategyParams,
  StrategyType,
} from '../types.js';
import { runBacktest } from '../backtest/engine.js';
import { calculateAlmaSeries } from '../indicators/alma.js';

export interface GridSearchSpace {
  readonly fastLengths: number[];
  readonly slowLengths: number[];
  readonly offsets: number[];
  readonly sigmas: number[];
  readonly strategyTypes: StrategyType[];
  readonly atrMultipliers: number[];
  readonly riskRewardRatios: number[];
}

export interface GridSearchResult {
  readonly params: StrategyParams;
  readonly summary: BacktestSummary;
}

interface AlmaPair {
  readonly fastLength: number;
  readonly slowLength: number;
}

interface AlmaSetting {
  readonly fastLength: number;
  readonly slowLength: number;
  readonly offset: number;
  readonly sigma: number;
}

function getValidLengthPairs(fastList: number[], slowList: number[]): AlmaPair[] {
  const pairs: AlmaPair[] = [];
  for (const f of fastList) {
    for (const s of slowList) {
      if (f < s) pairs.push({ fastLength: f, slowLength: s });
    }
  }
  return pairs;
}

function buildAlmaSettings(
  pairs: AlmaPair[],
  offsets: number[],
  sigmas: number[]
): AlmaSetting[] {
  const settings: AlmaSetting[] = [];
  for (const p of pairs) {
    for (const offset of offsets) {
      for (const sigma of sigmas) {
        settings.push({ ...p, offset, sigma });
      }
    }
  }
  return settings;
}

function buildStrategyList(
  settings: AlmaSetting[],
  types: StrategyType[],
  htfInterval?: CandleInterval
): Omit<StrategyParams, 'atrStopMultiplier' | 'riskRewardRatio'>[] {
  const list: Omit<StrategyParams, 'atrStopMultiplier' | 'riskRewardRatio'>[] = [];
  for (const s of settings) {
    for (const strategyType of types) {
      list.push({
        fastAlma: { length: s.fastLength, offset: s.offset, sigma: s.sigma },
        slowAlma: { length: s.slowLength, offset: s.offset, sigma: s.sigma },
        strategyType,
        htfFilterInterval: htfInterval,
      });
    }
  }
  return list;
}

export function generateCombinations(
  space: GridSearchSpace,
  htfInterval?: CandleInterval
): StrategyParams[] {
  const pairs = getValidLengthPairs(space.fastLengths, space.slowLengths);
  const settings = buildAlmaSettings(pairs, space.offsets, space.sigmas);
  const baseStrategies = buildStrategyList(settings, space.strategyTypes, htfInterval);
  const combinations: StrategyParams[] = [];

  for (const base of baseStrategies) {
    for (const atr of space.atrMultipliers) {
      for (const rr of space.riskRewardRatios) {
        combinations.push({
          ...base,
          atrStopMultiplier: atr,
          riskRewardRatio: rr,
        });
      }
    }
  }

  return combinations;
}

export function runGridSearch(
  execKlines: Kline[],
  combinations: StrategyParams[],
  htfKlines?: Kline[],
  minTrades = 20
): GridSearchResult[] {
  let htfCtx: { klines: Kline[]; fastAlma: number[]; slowAlma: number[] } | undefined;
  if (htfKlines && htfKlines.length > 0) {
    const closes = htfKlines.map((k) => k.close);
    const fastAlma = calculateAlmaSeries(closes, { length: 21, offset: 0.85, sigma: 6 });
    const slowAlma = calculateAlmaSeries(closes, { length: 50, offset: 0.85, sigma: 6 });
    htfCtx = { klines: htfKlines, fastAlma, slowAlma };
  }

  const results: GridSearchResult[] = [];
  for (const params of combinations) {
    const { summary } = runBacktest(execKlines, params, htfCtx);
    // Discard under-sampled parameter sets to prevent fitting on statistical noise
    if (summary.totalTrades >= minTrades) {
      results.push({ params, summary });
    }
  }

  return results.sort((a, b) => b.summary.profitFactor - a.summary.profitFactor);
}
