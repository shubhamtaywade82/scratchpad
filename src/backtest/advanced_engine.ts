import { BacktestSummary, Kline, StrategyParams, TradeRecord } from '../types.js';
import { calculateAlmaSeries, calculateAtrSeries } from '../indicators/alma.js';

interface AdvancedTradeState {
  readonly side: 'LONG' | 'SHORT';
  readonly entryTime: number;
  readonly entryPrice: number;
  stopPrice: number;
  readonly tp1Price: number;
  isTp1Reached: boolean;
  realizedPnl: number;
  remainingUnits: number;
}

export interface AdvancedSimConfig {
  readonly initialCapital: number;
  readonly riskPerTradePct: number; // e.g. 0.01 for 1% risk per trade
  readonly enableScaleOut: boolean;
  readonly enableFundingFilter: boolean;
}

const TAKER_FEE_PCT = 0.0005;
const SLIPPAGE_PCT = 0.0002;

function computePositionSize(
  capital: number,
  riskPct: number,
  entryPrice: number,
  stopPrice: number
): number {
  const riskAmount = capital * riskPct;
  const stopDistPct = Math.abs(entryPrice - stopPrice) / entryPrice;
  if (stopDistPct <= 0) return 0;
  // Position sizing bounded by risk budget
  return riskAmount / stopDistPct;
}

function processScaleOutExit(
  trade: AdvancedTradeState,
  bar: Kline,
  slowAlma: number
): { isClosed: boolean; exitPrice: number; pnl: number } {
  // Check TP1 scale-out first
  if (!trade.isTp1Reached) {
    const hitTp1 = trade.side === 'LONG' ? bar.high >= trade.tp1Price : bar.low <= trade.tp1Price;
    if (hitTp1) {
      trade.isTp1Reached = true;
      trade.stopPrice = trade.entryPrice; // Move to breakeven
      const pnl50 = (trade.side === 'LONG'
        ? (trade.tp1Price - trade.entryPrice) / trade.entryPrice
        : (trade.entryPrice - trade.tp1Price) / trade.entryPrice) * 0.5;
      trade.realizedPnl += pnl50 - (TAKER_FEE_PCT + SLIPPAGE_PCT);
      trade.remainingUnits = 0.5;
    }
  }

  // Check Stop Loss
  const hitStop = trade.side === 'LONG' ? bar.low <= trade.stopPrice : bar.high >= trade.stopPrice;
  if (hitStop) {
    const lossPct = (trade.side === 'LONG'
      ? (trade.stopPrice - trade.entryPrice) / trade.entryPrice
      : (trade.entryPrice - trade.stopPrice) / trade.entryPrice) * trade.remainingUnits;
    return { isClosed: true, exitPrice: trade.stopPrice, pnl: trade.realizedPnl + lossPct };
  }

  // Check Trailing ALMA exit for runner
  if (trade.isTp1Reached && !isNaN(slowAlma)) {
    const hitAlma = trade.side === 'LONG' ? bar.close < slowAlma : bar.close > slowAlma;
    if (hitAlma) {
      const pnlRunner = (trade.side === 'LONG'
        ? (bar.close - trade.entryPrice) / trade.entryPrice
        : (trade.entryPrice - bar.close) / trade.entryPrice) * trade.remainingUnits;
      return { isClosed: true, exitPrice: bar.close, pnl: trade.realizedPnl + pnlRunner };
    }
  }

  return { isClosed: false, exitPrice: 0, pnl: 0 };
}

export function runAdvancedSimulation(
  klines: Kline[],
  params: StrategyParams,
  htfBars: Kline[],
  config: AdvancedSimConfig
): { trades: TradeRecord[]; summary: BacktestSummary } {
  const closes = klines.map((k) => k.close);
  const fast = calculateAlmaSeries(closes, params.fastAlma);
  const slow = calculateAlmaSeries(closes, params.slowAlma);
  const atr = calculateAtrSeries(klines, 14);

  const trades: TradeRecord[] = [];
  let current: AdvancedTradeState | null = null;
  let capital = config.initialCapital;

  for (let i = 1; i < klines.length - 1; i++) {
    const nextBar = klines[i + 1];

    if (current) {
      const exit = processScaleOutExit(current, nextBar, slow[i]);
      if (exit.isClosed) {
        const netPct = exit.pnl - (TAKER_FEE_PCT + SLIPPAGE_PCT) * 2;
        capital *= 1 + netPct;
        trades.push({
          entryTime: current.entryTime,
          exitTime: nextBar.closeTime,
          side: current.side,
          entryPrice: current.entryPrice,
          exitPrice: exit.exitPrice,
          netReturnPct: netPct,
          isWin: netPct > 0,
        });
        current = null;
      }
      continue;
    }

    if (isNaN(atr[i]) || isNaN(fast[i]) || isNaN(slow[i])) continue;
    const isBull = fast[i - 1] <= slow[i - 1] && fast[i] > slow[i];
    const isBear = fast[i - 1] >= slow[i - 1] && fast[i] < slow[i];
    if (!isBull && !isBear) continue;

    const entryPrice = nextBar.open;
    const stopDist = atr[i] * params.atrStopMultiplier;
    current = {
      side: isBull ? 'LONG' : 'SHORT',
      entryTime: nextBar.openTime,
      entryPrice,
      stopPrice: isBull ? entryPrice - stopDist : entryPrice + stopDist,
      tp1Price: isBull ? entryPrice + stopDist * params.riskRewardRatio : entryPrice - stopDist * params.riskRewardRatio,
      isTp1Reached: false,
      realizedPnl: 0,
      remainingUnits: 1.0,
    };
  }

  return { trades, summary: computeEquitySummary(trades) };
}

function computeEquitySummary(trades: TradeRecord[]): BacktestSummary {
  if (trades.length === 0) {
    return { totalTrades: 0, winRatePct: 0, netReturnPct: 0, profitFactor: 0, maxDrawdownPct: 0, expectancyPct: 0 };
  }
  let equity = 1.0;
  let peak = 1.0;
  let maxDd = 0;
  let winSum = 0;
  let lossSum = 0;
  let wins = 0;

  for (const t of trades) {
    equity *= 1 + t.netReturnPct;
    if (equity > peak) peak = equity;
    const dd = (peak - equity) / peak;
    if (dd > maxDd) maxDd = dd;

    if (t.netReturnPct > 0) {
      wins++;
      winSum += t.netReturnPct;
    } else {
      lossSum += Math.abs(t.netReturnPct);
    }
  }

  const pf = lossSum > 0 ? winSum / lossSum : winSum > 0 ? 99 : 0;
  return {
    totalTrades: trades.length,
    winRatePct: (wins / trades.length) * 100,
    netReturnPct: (equity - 1) * 100,
    profitFactor: Number(pf.toFixed(3)),
    maxDrawdownPct: maxDd * 100,
    expectancyPct: ((equity - 1) / trades.length) * 100,
  };
}
