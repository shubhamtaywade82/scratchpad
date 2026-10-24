import {
  BacktestSummary,
  Kline,
  StrategyParams,
  TradeRecord,
} from '../types.js';
import { calculateAlmaSeries, calculateAtrSeries } from '../indicators/alma.js';

interface HtfContext {
  readonly klines: Kline[];
  readonly fastAlma: number[];
  readonly slowAlma: number[];
}

interface ActiveTrade {
  readonly side: 'LONG' | 'SHORT';
  readonly entryTime: number;
  readonly entryPrice: number;
  readonly stopPrice: number;
  readonly targetPrice: number;
}

const TAKER_FEE_PCT = 0.0005; // Binance VIP0 futures taker fee
const SLIPPAGE_PCT = 0.0002; // Average market slippage on liquid futures

function findLastClosedHtfIndex(htfKlines: Kline[], targetTime: number): number {
  let low = 0;
  let high = htfKlines.length - 1;
  let result = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (htfKlines[mid].closeTime <= targetTime) {
      result = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return result;
}

function checkHtfFilter(
  htf: HtfContext,
  execCloseTime: number,
  side: 'LONG' | 'SHORT'
): boolean {
  const idx = findLastClosedHtfIndex(htf.klines, execCloseTime);
  if (idx < 1 || isNaN(htf.fastAlma[idx]) || isNaN(htf.slowAlma[idx])) return true;

  // Confirmed HTF trend: fast above slow and slow sloping in trend direction
  const isUp = htf.fastAlma[idx] > htf.slowAlma[idx] && htf.slowAlma[idx] >= htf.slowAlma[idx - 1];
  const isDown = htf.fastAlma[idx] < htf.slowAlma[idx] && htf.slowAlma[idx] <= htf.slowAlma[idx - 1];
  return side === 'LONG' ? isUp : isDown;
}

function evaluateSignal(
  i: number,
  bars: Kline[],
  fast: number[],
  slow: number[],
  params: StrategyParams
): 'LONG' | 'SHORT' | null {
  const { strategyType } = params;
  if (isNaN(fast[i]) || isNaN(slow[i]) || isNaN(fast[i - 1]) || isNaN(slow[i - 1])) {
    return null;
  }

  if (strategyType === 'CROSSOVER') {
    if (fast[i - 1] <= slow[i - 1] && fast[i] > slow[i]) return 'LONG';
    if (fast[i - 1] >= slow[i - 1] && fast[i] < slow[i]) return 'SHORT';
    return null;
  }

  const isFastRef = strategyType === 'PULLBACK_FAST';
  const refLine = isFastRef ? fast : slow;

  if (fast[i] > slow[i] && slow[i] >= slow[i - 1]) {
    if (bars[i].low <= refLine[i] && bars[i].close > refLine[i]) return 'LONG';
  }
  if (fast[i] < slow[i] && slow[i] <= slow[i - 1]) {
    if (bars[i].high >= refLine[i] && bars[i].close < refLine[i]) return 'SHORT';
  }
  return null;
}

function resolveExit(
  trade: ActiveTrade,
  bar: Kline
): { isExited: boolean; exitPrice: number; reason?: 'STOP_LOSS' | 'TAKE_PROFIT' } {
  if (trade.side === 'LONG') {
    if (bar.low <= trade.stopPrice) return { isExited: true, exitPrice: trade.stopPrice, reason: 'STOP_LOSS' };
    if (bar.high >= trade.targetPrice) return { isExited: true, exitPrice: trade.targetPrice, reason: 'TAKE_PROFIT' };
  } else {
    if (bar.high >= trade.stopPrice) return { isExited: true, exitPrice: trade.stopPrice, reason: 'STOP_LOSS' };
    if (bar.low <= trade.targetPrice) return { isExited: true, exitPrice: trade.targetPrice, reason: 'TAKE_PROFIT' };
  }
  return { isExited: false, exitPrice: 0 };
}

function calculateSummary(trades: TradeRecord[]): BacktestSummary {
  if (trades.length === 0) {
    return { totalTrades: 0, winRatePct: 0, netReturnPct: 0, profitFactor: 0, maxDrawdownPct: 0, expectancyPct: 0 };
  }

  let totalWinPct = 0;
  let totalLossPct = 0;
  let wins = 0;
  let equity = 1.0;
  let peak = 1.0;
  let maxDd = 0;

  for (const t of trades) {
    equity *= 1 + t.netReturnPct;
    if (equity > peak) peak = equity;
    const dd = (peak - equity) / peak;
    if (dd > maxDd) maxDd = dd;

    if (t.netReturnPct > 0) {
      wins++;
      totalWinPct += t.netReturnPct;
    } else {
      totalLossPct += Math.abs(t.netReturnPct);
    }
  }

  const pf = totalLossPct > 0 ? totalWinPct / totalLossPct : totalWinPct > 0 ? 99 : 0;
  return {
    totalTrades: trades.length,
    winRatePct: (wins / trades.length) * 100,
    netReturnPct: (equity - 1) * 100,
    profitFactor: Number(pf.toFixed(3)),
    maxDrawdownPct: maxDd * 100,
    expectancyPct: ((equity - 1) / trades.length) * 100,
  };
}

function executeTradeExit(trade: ActiveTrade, bar: Kline): TradeRecord | null {
  const exitResult = resolveExit(trade, bar);
  if (!exitResult.isExited) return null;

  const rawReturn = trade.side === 'LONG'
    ? (exitResult.exitPrice - trade.entryPrice) / trade.entryPrice
    : (trade.entryPrice - exitResult.exitPrice) / trade.entryPrice;
  const netReturn = rawReturn - (TAKER_FEE_PCT + SLIPPAGE_PCT) * 2;

  return {
    entryTime: trade.entryTime,
    exitTime: bar.closeTime,
    side: trade.side,
    entryPrice: trade.entryPrice,
    exitPrice: exitResult.exitPrice,
    stopPrice: trade.stopPrice,
    targetPrice: trade.targetPrice,
    exitReason: exitResult.reason,
    netReturnPct: netReturn,
    isWin: netReturn > 0,
  };
}

function buildTradeEntry(
  signal: 'LONG' | 'SHORT',
  bar: Kline,
  atrValue: number,
  params: StrategyParams
): ActiveTrade {
  const entryPrice = bar.open;
  const stopDistance = atrValue * params.atrStopMultiplier;
  const targetDistance = stopDistance * params.riskRewardRatio;
  return {
    side: signal,
    entryTime: bar.openTime,
    entryPrice,
    stopPrice: signal === 'LONG' ? entryPrice - stopDistance : entryPrice + stopDistance,
    targetPrice: signal === 'LONG' ? entryPrice + targetDistance : entryPrice - targetDistance,
  };
}

export function runBacktest(
  klines: Kline[],
  params: StrategyParams,
  htfContext?: HtfContext
): { trades: TradeRecord[]; summary: BacktestSummary } {
  const closes = klines.map((k) => k.close);
  const fast = calculateAlmaSeries(closes, params.fastAlma);
  const slow = calculateAlmaSeries(closes, params.slowAlma);
  const atr = calculateAtrSeries(klines, 14);

  const trades: TradeRecord[] = [];
  let current: ActiveTrade | null = null;

  for (let i = 1; i < klines.length - 1; i++) {
    const nextBar = klines[i + 1];
    if (current) {
      const finished = executeTradeExit(current, nextBar);
      if (finished) {
        trades.push(finished);
        current = null;
      }
      continue;
    }

    if (isNaN(atr[i])) continue;
    const signal = evaluateSignal(i, klines, fast, slow, params);
    if (!signal) continue;
    if (htfContext && !checkHtfFilter(htfContext, klines[i].closeTime, signal)) continue;
    current = buildTradeEntry(signal, nextBar, atr[i], params);
  }

  return { trades, summary: calculateSummary(trades) };
}
