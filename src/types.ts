export type CandleInterval = '5m' | '15m' | '1h' | '2h' | '4h' | '1d';

export interface Kline {
  readonly openTime: number;
  readonly open: number;
  readonly high: number;
  readonly low: number;
  readonly close: number;
  readonly volume: number;
  readonly closeTime: number;
}

export interface AlmaConfig {
  readonly length: number;
  readonly offset: number;
  readonly sigma: number;
}

export type StrategyType = 'CROSSOVER' | 'PULLBACK_FAST' | 'PULLBACK_SLOW';

export interface StrategyParams {
  readonly fastAlma: AlmaConfig;
  readonly slowAlma: AlmaConfig;
  readonly strategyType: StrategyType;
  readonly atrStopMultiplier: number;
  readonly riskRewardRatio: number;
  readonly htfFilterInterval?: CandleInterval;
}

export interface TradeRecord {
  readonly entryTime: number;
  readonly exitTime: number;
  readonly side: 'LONG' | 'SHORT';
  readonly entryPrice: number;
  readonly exitPrice: number;
  readonly netReturnPct: number;
  readonly isWin: boolean;
}

export interface BacktestSummary {
  readonly totalTrades: number;
  readonly winRatePct: number;
  readonly netReturnPct: number;
  readonly profitFactor: number;
  readonly maxDrawdownPct: number;
  readonly expectancyPct: number;
}
