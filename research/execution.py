"""Live and dry-run execution adapter for perpetual futures trading.

Translates high-level trading signals into risk-budgeted bracket orders
with hard ATR stop-losses, enforced liquidation buffers, and idempotent execution.
Supports OKX v5 isolated perpetual swaps.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from research.engine import Risk

OKX_REST_URL = 'https://www.okx.com'


@dataclass
class MarketContext:
    equity: float
    entry_px: float
    atr: float
    side: int                # +1 long, -1 short


@dataclass
class OrderPlan:
    inst_id: str
    side_str: str            # 'buy' or 'sell'
    qty: float               # base asset quantity
    notional: float          # USD/USDT notional
    entry_px: float
    stop_px: float
    stop_dist_pct: float
    eff_lev: float
    cl_ord_id: str


def _calc_stop_bounds(ctx: MarketContext, risk: Risk) -> Tuple[float, float]:
    mult = risk.sl_mult or 3.0
    stop_px = ctx.entry_px - ctx.side * mult * ctx.atr
    if stop_px <= 0:
        raise ValueError(f"stop price {stop_px:.4f} must be positive")
    dist_pct = abs(ctx.entry_px - stop_px) / ctx.entry_px
    max_safe_dist = risk.liq_buffer * risk.liq_frac
    if dist_pct > max_safe_dist:
        raise ValueError(
            f"stop distance {dist_pct:.2%} exceeds liquidation safety limit "
            f"{max_safe_dist:.2%} for leverage {risk.lev:g}x"
        )
    return stop_px, dist_pct


def _generate_cl_ord_id(prefix: str = "agt") -> str:
    # 32-char alphanumeric ID required by OKX v5
    rand_hex = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
    return f"{prefix}{int(time.time())}{rand_hex}"[:32]


def plan_order(ctx: MarketContext, risk: Risk, inst_id: str = "SOL-USDT-SWAP") -> OrderPlan:
    """Calculate risk-budgeted position size, hard stop price, and bracket order."""
    if ctx.equity <= 0 or ctx.entry_px <= 0 or ctx.atr <= 0:
        raise ValueError("equity, entry price, and ATR must be positive")
    if ctx.side not in (1, -1):
        raise ValueError("side must be +1 (long) or -1 (short)")

    stop_px, dist_pct = _calc_stop_bounds(ctx, risk)
    budget_notional = ctx.equity * risk.risk_pct / dist_pct
    max_notional = ctx.equity * risk.lev
    notional = min(budget_notional, max_notional)
    qty = notional / ctx.entry_px

    return OrderPlan(
        inst_id=inst_id,
        side_str='buy' if ctx.side > 0 else 'sell',
        qty=qty,
        notional=notional,
        entry_px=ctx.entry_px,
        stop_px=stop_px,
        stop_dist_pct=dist_pct,
        eff_lev=notional / ctx.equity,
        cl_ord_id=_generate_cl_ord_id(),
    )


class OKXPerpAdapter:
    """Execution adapter for OKX v5 isolated margin perpetual swaps."""

    def __init__(self, key: str = "", secret: str = "", passphrase: str = "", is_sim: bool = True):
        self.key = key or os.getenv('OKX_API_KEY', '')
        self.secret = secret or os.getenv('OKX_API_SECRET', '')
        self.passphrase = passphrase or os.getenv('OKX_API_PASSPHRASE', '')
        self.is_sim = is_sim

    def sign_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        # OKX v5 signature requires ISO timestamp with 'Z' and trailing milliseconds
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        msg = f"{ts}{method.upper()}{path}{body}"
        h = hmac.new(self.secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
        sig = base64.b64encode(h.digest()).decode('utf-8')
        return {
            'OKX-ACCESS-KEY': self.key,
            'OKX-ACCESS-SIGN': sig,
            'OKX-ACCESS-TIMESTAMP': ts,
            'OKX-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json',
        }

    def build_bracket_payload(self, plan: OrderPlan) -> dict:
        """Create OKX v5 trade order payload with an attached conditional stop-loss order."""
        return {
            'instId': plan.inst_id,
            'tdMode': 'isolated',
            'side': plan.side_str,
            'ordType': 'market',
            'sz': f"{plan.qty:.2f}",
            'clOrdId': plan.cl_ord_id,
            'attachAlgoOrds': [{
                'attachAlgoClOrdId': f"{plan.cl_ord_id}sl"[:32],
                'slTriggerPx': f"{plan.stop_px:.2f}",
                'slOrdPx': '-1',    # -1 specifies market execution once stop triggers
            }]
        }

    def execute(self, plan: OrderPlan) -> dict:
        """Submit bracket order to exchange, or return simulated receipt if dry-run."""
        payload = self.build_bracket_payload(plan)
        if self.is_sim or not self.key:
            return {
                'status': 'SIMULATED',
                'plan': plan.__dict__,
                'payload': payload,
                'executed_at': datetime.now(timezone.utc).isoformat(),
            }
        return self._send_request('/api/v5/trade/order', payload)

    def _send_request(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload)
        headers = self.sign_headers('POST', path, body)
        req = urllib.request.Request(f"{OKX_REST_URL}{path}", data=body.encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('code') != '0':
                    raise RuntimeError(f"OKX error {data.get('code')}: {data.get('msg')}")
                return data
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode('utf-8')
            raise RuntimeError(f"HTTP error {err.code}: {err_msg}") from err
