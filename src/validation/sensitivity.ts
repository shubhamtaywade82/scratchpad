import { BacktestSummary, Kline, StrategyParams } from '../types.js';
import { runBacktest } from '../backtest/engine.js';
import { calculateAlmaSeries } from '../indicators/alma.js';

export interface BasinMetrics {
  readonly totalEvaluated: number;
  readonly profitableRatio: number;
  readonly strongEdgeRatio: number; // Ratio of neighbors with PF >= 2.0
  readonly averageProfitFactor: number;
  readonly averageWinRate: number;
}

export interface BasinGridConfig {
  readonly fastRange: number[];
  readonly slowRange: number[];
  readonly offsetRange: number[];
  readonly sigmaRange: number[];
}

function buildNeighborParams(
  config: BasinGridConfig,
  base: StrategyParams
): StrategyParams[] {
  const list: StrategyParams[] = [];
  for (const f of config.fastRange) {
    for (const s of config.slowRange) {
      if (f >= s) continue;
      for (const offset of config.offsetRange) {
        for (const sigma of config.sigmaRange) {
          list.push({
            ...base,
            fastAlma: { length: f, offset, sigma },
            slowAlma: { length: s, offset, sigma },
          });
        }
      }
    }
  }
  return list;
}

export function evaluateParameterBasin(
  execBars: Kline[],
  htfBars: Kline[],
  baseParams: StrategyParams,
  basinGrid: BasinGridConfig
): BasinMetrics {
  const htfCtx = {
    klines: htfBars,
    fastAlma: calculateAlmaSeries(htfBars.map((k) => k.close), { length: 21, offset: 0.85, sigma: 6 }),
    slowAlma: calculateAlmaSeries(htfBars.map((k) => k.close), { length: 50, offset: 0.85, sigma: 6 }),
  };

  const neighbors = buildNeighborParams(basinGrid, baseParams);
  let profitableCount = 0;
  let strongCount = 0;
  let pfSum = 0;
  let wrSum = 0;

  for (const p of neighbors) {
    const { summary } = runBacktest(execBars, p, htfCtx);
    if (summary.profitFactor > 1.0) profitableCount++;
    if (summary.profitFactor >= 2.0) strongCount++;
    pfSum += summary.profitFactor;
    wrSum += summary.winRatePct;
  }

  const total = neighbors.length;
  return {
    totalEvaluated: total,
    profitableRatio: total > 0 ? (profitableCount / total) * 100 : 0,
    strongEdgeRatio: total > 0 ? (strongCount / total) * 100 : 0,
    averageProfitFactor: total > 0 ? Number((pfSum / total).toFixed(2)) : 0,
    averageWinRate: total > 0 ? Number((wrSum / total).toFixed(1)) : 0,
  };
}
