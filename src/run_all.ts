import { getOrFetchKlines } from './data/fetcher.js';
import { runCrossAssetValidation } from './validation/out_of_sample.js';
import { evaluateParameterBasin } from './validation/sensitivity.js';
import { runAdvancedSimulation } from './backtest/advanced_engine.js';
import { checkLiveMarketSignal } from './live/daemon.js';
import { BacktestSummary, StrategyParams } from './types.js';

const BEST_PARAMS: StrategyParams = {
  fastAlma: { length: 21, offset: 0.95, sigma: 4 },
  slowAlma: { length: 34, offset: 0.95, sigma: 4 },
  strategyType: 'CROSSOVER',
  atrStopMultiplier: 1.5,
  riskRewardRatio: 1.5,
  htfFilterInterval: '4h',
};

function printSummaryRow(label: string, s: BacktestSummary): void {
  console.log(
    `  ${label.padEnd(20)} | Trades: ${String(s.totalTrades).padStart(3)} | Win: ${s.winRatePct.toFixed(1).padStart(5)}% | Net: ${(s.netReturnPct >= 0 ? '+' : '') + s.netReturnPct.toFixed(1).padStart(6)}% | PF: ${s.profitFactor.toFixed(2).padStart(4)} | MaxDD: ${s.maxDrawdownPct.toFixed(1).padStart(4)}%`
  );
}

async function executeTrack1(): Promise<void> {
  console.log('\n===============================================================');
  console.log('TRACK 1: CHRONOLOGICAL 70/30 TRAIN-TEST SPLIT & CROSS-ASSET TEST');
  console.log('===============================================================');
  const symbols = ['SOLUSDT', 'BTCUSDT', 'ETHUSDT'];
  const results = await runCrossAssetValidation(symbols, BEST_PARAMS);

  for (const sym of symbols) {
    const res = results[sym];
    console.log(`\n[Asset: ${sym}]`);
    printSummaryRow('70% In-Sample (Train)', res.inSample);
    printSummaryRow('30% Out-of-Sample (Test)', res.outOfSample);
    printSummaryRow('Full Period Combined', res.fullPeriod);
  }
}

async function executeTrack2(): Promise<void> {
  console.log('\n===============================================================');
  console.log('TRACK 2: PARAMETER BASIN & SENSITIVITY ANALYSIS (SOLUSDT)');
  console.log('===============================================================');
  const [k2h, k4h] = await Promise.all([
    getOrFetchKlines('SOLUSDT', '2h'),
    getOrFetchKlines('SOLUSDT', '4h'),
  ]);

  const basinMetrics = evaluateParameterBasin(k2h, k4h, BEST_PARAMS, {
    fastRange: [18, 19, 20, 21, 22, 23],
    slowRange: [30, 32, 34, 36, 38],
    offsetRange: [0.85, 0.90, 0.95],
    sigmaRange: [3.5, 4.0, 5.0],
  });

  console.log(`Neighborhood Parameter Combinations Evaluated: ${basinMetrics.totalEvaluated}`);
  console.log(`Profitable Neighbors Ratio (PF > 1.0): ${basinMetrics.profitableRatio.toFixed(1)}%`);
  console.log(`Strong Edge Neighbors Ratio (PF >= 2.0): ${basinMetrics.strongEdgeRatio.toFixed(1)}%`);
  console.log(`Average Neighborhood Profit Factor: ${basinMetrics.averageProfitFactor}`);
  console.log(`Average Neighborhood Win Rate: ${basinMetrics.averageWinRate}%`);
}

async function executeTrack3(): Promise<void> {
  console.log('\n===============================================================');
  console.log('TRACK 3: ADVANCED TRADE MANAGEMENT (50% TP1 + TRAILING ALMA)');
  console.log('===============================================================');
  const [k2h, k4h] = await Promise.all([
    getOrFetchKlines('SOLUSDT', '2h'),
    getOrFetchKlines('SOLUSDT', '4h'),
  ]);

  const simResult = runAdvancedSimulation(k2h, BEST_PARAMS, k4h, {
    initialCapital: 10000,
    riskPerTradePct: 0.01,
    enableScaleOut: true,
    enableFundingFilter: true,
  });

  printSummaryRow('Scale-Out (50% TP1 + Runner)', simResult.summary);
}

async function executeTrack4(): Promise<void> {
  console.log('\n===============================================================');
  console.log('TRACK 4: LIVE MARKET SCANNER SNAPSHOT (SOLUSDT)');
  console.log('===============================================================');
  const alert = await checkLiveMarketSignal('SOLUSDT', BEST_PARAMS);
  console.log(`Snapshot Timestamp: ${new Date(alert.timestamp).toISOString()}`);
  console.log(`Symbol: ${alert.symbol} | Current Price: $${alert.currentPrice.toFixed(2)}`);
  console.log(`ALMA Fast(21): $${alert.fastAlma.toFixed(2)} | ALMA Slow(34): $${alert.slowAlma.toFixed(2)}`);
  console.log(`HTF 4H Trend Regime: ${alert.htfTrend}`);
  console.log(`Execution Signal: [${alert.direction}]`);
  if (alert.suggestedStopPrice) {
    console.log(`Suggested Invalidation (Stop Loss): $${alert.suggestedStopPrice.toFixed(2)}`);
    console.log(`Suggested Take Profit Target: $${alert.suggestedTargetPrice?.toFixed(2)}`);
  }
}

async function main(): Promise<void> {
  await executeTrack1();
  await executeTrack2();
  await executeTrack3();
  await executeTrack4();
}

main().catch((err) => {
  console.error('Execution failure:', err);
  process.exit(1);
});
