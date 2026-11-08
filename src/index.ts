import { getOrFetchKlines } from './data/fetcher.js';
import { generateCombinations, runGridSearch, GridSearchSpace } from './search/grid.js';
import { BacktestSummary, CandleInterval, Kline, StrategyParams } from './types.js';

interface MtfExperimentConfig {
  readonly title: string;
  readonly execKlines: Kline[];
  readonly htfKlines: Kline[];
  readonly htfInterval: CandleInterval;
  readonly minTrades?: number;
}

function formatMetrics(label: string, s: BacktestSummary): void {
  console.log(`[${label}]`);
  console.log(
    `  Trades: ${s.totalTrades} | WinRate: ${s.winRatePct.toFixed(1)}% | Net: ${s.netReturnPct.toFixed(2)}%`
  );
  console.log(
    `  ProfitFactor: ${s.profitFactor.toFixed(2)} | MaxDD: ${s.maxDrawdownPct.toFixed(2)}% | Exp: ${s.expectancyPct.toFixed(3)}%`
  );
}

function runMtfExperiment(
  config: MtfExperimentConfig,
  space: GridSearchSpace
): void {
  const { title, execKlines, htfKlines, htfInterval, minTrades = 20 } = config;
  console.log(`\n======================================================`);
  console.log(`MTF EXPERIMENT: ${title}`);
  console.log(`Execution bars: ${execKlines.length} | HTF bars: ${htfKlines.length}`);

  const combinations = generateCombinations(space, htfInterval);
  const results = runGridSearch(execKlines, combinations, htfKlines, minTrades);
  console.log(`Evaluated ${combinations.length} combinations. Qualifying results (>=${minTrades} trades): ${results.length}`);

  const top = results.slice(0, 3);
  for (let i = 0; i < top.length; i++) {
    const p = top[i].params;
    const tag = `Rank #${i + 1}: ${p.strategyType} | F(${p.fastAlma.length},${p.fastAlma.offset},${p.fastAlma.sigma}) S(${p.slowAlma.length},${p.slowAlma.offset},${p.slowAlma.sigma}) | ATRx${p.atrStopMultiplier} RR:${p.riskRewardRatio}`;
    formatMetrics(tag, top[i].summary);
  }
}

async function main(): Promise<void> {
  const symbol = 'SOLUSDT';
  console.log(`Loading market data for ${symbol} across timeframes ...`);
  const [k1h, k2h, k4h, k1d] = await Promise.all([
    getOrFetchKlines(symbol, '1h'),
    getOrFetchKlines(symbol, '2h'),
    getOrFetchKlines(symbol, '4h'),
    getOrFetchKlines(symbol, '1d'),
  ]);

  console.log(`Loaded bars -> 1h: ${k1h.length}, 2h: ${k2h.length}, 4h: ${k4h.length}, 1d: ${k1d.length}`);

  const searchSpace: GridSearchSpace = {
    fastLengths: [5, 9, 14, 21],
    slowLengths: [21, 34, 50, 89],
    offsets: [0.70, 0.85, 0.95],
    sigmas: [4, 6, 8],
    strategyTypes: ['CROSSOVER', 'PULLBACK_FAST', 'PULLBACK_SLOW'],
    atrMultipliers: [1.5, 2.0, 2.5],
    riskRewardRatios: [1.5, 2.0],
  };

  // 1. 1h Execution with 4h Trend Filter
  runMtfExperiment({
    title: '1h Execution + 4h ALMA Trend Filter',
    execKlines: k1h,
    htfKlines: k4h,
    htfInterval: '4h',
    minTrades: 25,
  }, searchSpace);

  // 2. 2h Execution with 4h Trend Filter
  runMtfExperiment({
    title: '2h Execution + 4h ALMA Trend Filter',
    execKlines: k2h,
    htfKlines: k4h,
    htfInterval: '4h',
    minTrades: 20,
  }, searchSpace);

  // 3. 2h Execution with 1D Daily Trend Filter
  runMtfExperiment({
    title: '2h Execution + 1D Daily ALMA Trend Filter',
    execKlines: k2h,
    htfKlines: k1d,
    htfInterval: '1d',
    minTrades: 15,
  }, searchSpace);

  // 4. 1h Execution with 1D Daily Trend Filter
  runMtfExperiment({
    title: '1h Execution + 1D Daily ALMA Trend Filter',
    execKlines: k1h,
    htfKlines: k1d,
    htfInterval: '1d',
    minTrades: 20,
  }, searchSpace);
}

main().catch((err) => {
  console.error('Fatal execution error:', err);
  process.exit(1);
});
