import { AlmaConfig, Kline } from '../types.js';

export function computeAlmaWeights(
  length: number,
  offset: number,
  sigma: number
): number[] {
  const m = offset * (length - 1);
  const s = length / sigma;
  const weights = new Array<number>(length);
  let weightSum = 0;

  for (let i = 0; i < length; i++) {
    // Gaussian bell curve peak shifts toward recent bars when offset > 0.5
    const weight = Math.exp(-((i - m) ** 2) / (2 * s * s));
    weights[i] = weight;
    weightSum += weight;
  }

  return weights.map((w) => w / weightSum);
}

export function calculateAlmaSeries(
  prices: number[],
  config: AlmaConfig
): number[] {
  const { length, offset, sigma } = config;
  const result = new Array<number>(prices.length).fill(NaN);
  if (prices.length < length) return result;

  const weights = computeAlmaWeights(length, offset, sigma);
  for (let i = length - 1; i < prices.length; i++) {
    let weightedSum = 0;
    for (let j = 0; j < length; j++) {
      weightedSum += prices[i - length + 1 + j] * weights[j];
    }
    result[i] = weightedSum;
  }

  return result;
}

export function calculateAtrSeries(klines: Kline[], period = 14): number[] {
  const atr = new Array<number>(klines.length).fill(NaN);
  if (klines.length <= period) return atr;

  const trs = new Array<number>(klines.length);
  trs[0] = klines[0].high - klines[0].low;

  for (let i = 1; i < klines.length; i++) {
    const high = klines[i].high;
    const low = klines[i].low;
    const prevClose = klines[i - 1].close;
    trs[i] = Math.max(
      high - low,
      Math.abs(high - prevClose),
      Math.abs(low - prevClose)
    );
  }

  let rollingSum = 0;
  for (let i = 1; i <= period; i++) rollingSum += trs[i];
  atr[period] = rollingSum / period;

  // Wilder smoothing for true ATR
  for (let i = period + 1; i < klines.length; i++) {
    atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period;
  }

  return atr;
}
