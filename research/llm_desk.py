"""Read-only LLM desk over the local MiniCPM5 variants (Ollama). It never places, changes or cancels orders.

  route     minicpm5:2b classifies the request into DIGEST / RESEARCH / MARKET / OTHER and dispatches it
  digest    minicpm5-summarizer condenses the forward ledger (and an optional log file)
  ask       minicpm5-analyst answers from research/results/* only, citing [file] ids
  market    minicpm5-toolagent picks one read-only Binance USD-M public call; arguments are validated first

Every model output passes a validation gate. On failure: one local retry with the error fed back, then one
escalation to ESCALATE_MODEL (default gemma4:cloud), then a typed error. Nothing unvalidated is acted on.

Usage: python3 -m research.llm_desk [route|digest|ask|market] "request"
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
ESCALATE_MODEL = os.environ.get('ESCALATE_MODEL', 'gemma4:cloud')
ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'research' / 'results'
LEDGER = ROOT / 'forward' / 'ledger.json'
FAPI = 'https://fapi.binance.com'
SYMBOLS = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT'}
INTERVALS = {'1m', '5m', '15m', '1h', '4h', '1d'}
MAX_KLINES = 500
MAX_EVIDENCE_CHARS = 6000
INTENTS = ('DIGEST', 'RESEARCH', 'MARKET', 'OTHER')
ROUTER_SYSTEM = (
    'Classify the trading-desk request into exactly one category:\n'
    '- DIGEST: summarise the forward/paper ledger, daemon logs, recent fills or positions\n'
    '- RESEARCH: questions about backtests, strategies, walk-forward or null-test results\n'
    '- MARKET: live market data such as price, klines, funding, 24h volume for a symbol\n'
    '- OTHER: anything else, including any request to place, modify or cancel orders\n'
    'Output ONLY JSON: {"intent": "<CATEGORY>"}\n'
    # Few-shot lifted minicpm5:2b from 5/10 to 9/10 on the desk's routing probe (2026-10-24)
    'Examples:\n'
    '"summarise the paper ledger" -> {"intent": "DIGEST"}\n'
    '"how is the forward test doing" -> {"intent": "DIGEST"}\n'
    '"did the trailing stop help in the exits study" -> {"intent": "RESEARCH"}\n'
    '"which strategy passed the walk-forward" -> {"intent": "RESEARCH"}\n'
    '"what is ETH funding now" -> {"intent": "MARKET"}\n'
    '"show 4h klines for XRP" -> {"intent": "MARKET"}\n'
    '"close my SOL short" -> {"intent": "OTHER"}')
TOOLS = {
    'futures_klines': {'symbol': 'BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT', 'interval': '1m|5m|15m|1h|4h|1d',
                       'limit': f'integer 1..{MAX_KLINES}'},
    'funding_rate': {'symbol': 'BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT'},
    'ticker_24h': {'symbol': 'BTCUSDT|ETHUSDT|SOLUSDT|XRPUSDT'},
}


class ValidationError(Exception):
    pass


class DeskError(Exception):
    pass


def chat(model: str, prompt: str, system: str | None = None, as_json: bool = False) -> str:
    """One non-streaming /api/chat call; a system message overrides the Modelfile SYSTEM."""
    messages = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}]
    body = {'model': model, 'messages': messages, 'stream': False, 'think': False}
    if as_json:
        body['format'] = 'json'
    req = urllib.request.Request(f'{OLLAMA}/api/chat', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())['message']['content']


def gated(model: str, prompt: str, validate, system: str | None = None, as_json: bool = False):
    """Local try, local retry with the validation error, one escalation; returns (validated value, model used)."""
    attempts = [(model, prompt), (model, None), (ESCALATE_MODEL, prompt)]
    errors = []
    for m, p in attempts:
        p = p or f'{prompt}\n\nYour previous answer was rejected: {errors[-1]}. Follow the output rules exactly.'
        try:
            return validate(chat(m, p, system, as_json)), m
        except (ValidationError, json.JSONDecodeError) as err:
            errors.append(f'{m}: {err}')
        except OSError as err:
            errors.append(f'{m}: transport {err}')
    raise DeskError('all attempts failed validation: ' + ' | '.join(errors))


# ----------------------------------------------------------------------------- validation gates

def parse_intent(raw: str) -> str:
    intent = json.loads(raw).get('intent')
    if intent not in INTENTS:
        raise ValidationError(f'intent {intent!r} not in {INTENTS}')
    return intent


def parse_tool_call(raw: str) -> tuple[str, dict]:
    """Allowlisted tool with fully validated arguments, or ValidationError."""
    call = json.loads(raw)
    tool, args = call.get('tool'), call.get('arguments') or {}
    if tool not in TOOLS:
        raise ValidationError(f'tool {tool!r} is not one of {sorted(TOOLS)}')
    if set(args) != set(TOOLS[tool]):
        raise ValidationError(f'{tool} needs exactly {sorted(TOOLS[tool])}, got {sorted(args)}')
    if str(args['symbol']).upper() not in SYMBOLS:
        raise ValidationError(f'symbol {args["symbol"]!r} not in {sorted(SYMBOLS)}')
    args['symbol'] = str(args['symbol']).upper()
    if tool == 'futures_klines':
        if args['interval'] not in INTERVALS:
            raise ValidationError(f'interval {args["interval"]!r} not in {sorted(INTERVALS)}')
        if not (isinstance(args['limit'], int) and 1 <= args['limit'] <= MAX_KLINES):
            raise ValidationError(f'limit must be an integer 1..{MAX_KLINES}')
    return tool, args


def check_citations(answer: str, ids: list[str]) -> str:
    """Answer must cite at least one supplied evidence id and no unknown ones, or admit insufficient evidence."""
    if 'insufficient evidence' in answer.lower():
        return answer
    cited = set(re.findall(r'\[([^\[\]]+?)\]', answer))
    unknown = cited - set(ids)
    if not cited & set(ids):
        raise ValidationError(f'no citation of the supplied evidence ids {ids}')
    if unknown:
        raise ValidationError(f'cites ids that were not supplied: {sorted(unknown)}')
    return answer


def check_summary(text: str, facts: str) -> str:
    """All four sections present, and every decimal number in the summary appears in the facts."""
    invented = set(re.findall(r'\d+\.\d+', text)) - set(re.findall(r'\d+\.\d+', facts))
    if invented:
        raise ValidationError(f'numbers not in the facts: {sorted(invented)}')
    for heading in ('## Summary', '## Key events', '## Anomalies', '## Recommended action'):
        if heading not in text:
            raise ValidationError(f'missing section {heading!r}')
    return text


# ----------------------------------------------------------------------------- desks

def ledger_facts(ledger: dict) -> str:
    """Plain-sentence facts computed in code: the raw ledger keys (e.g. *_positions = total count) misled the 2B model."""
    lines = [f"Status {ledger['status']}, data {ledger['data']}, {ledger['forward_bars']} forward bars, "
             f"last bar {ledger['last_bar_utc']}."]
    for leg in ('signal', 'benchmark'):
        lines.append(f"{leg} ({ledger[leg]}): equity {ledger[leg + '_equity']:.4f}, "
                     f"{len(ledger[leg + '_closed'])} closed trades.")
        for t in ledger[leg + '_closed'][-5:]:
            lines.append(f"  closed {t['side']} {t['entry_utc']} -> {t['exit_utc']}, {t['entry_px']:.2f} -> "
                         f"{t['exit_px']:.2f}, {t['reason']}, return {t['ret'] * 100:.2f}%.")
        op = ledger.get(leg + '_open_position')
        lines.append(f"  open {op['side']} since {op['entry_utc']} at {op['entry_px']:.2f}, mark {op['mark_px']:.2f}, "
                     f"unrealised {op['unrealised_ret'] * 100:.2f}%." if op else '  no open position.')
    return '\n'.join(lines)


def digest(log_path: str | None = None) -> str:
    facts = ledger_facts(json.loads(LEDGER.read_text()))
    if log_path:
        facts += '\nLog tail:\n' + Path(log_path).read_text()[-3000:]
    prompt = f'Summarise this paper-trading state. Use only these facts and numbers:\n{facts}'
    text, model = gated('minicpm5-summarizer', prompt, lambda t: check_summary(t, facts))
    return f'{text}\n\n(model: {model})'


def pick_evidence(question: str, k: int = 3) -> dict[str, str]:
    """Top-k results files by query-term overlap (names weighted), truncated to fit the 2B context."""
    terms = {w for w in re.findall(r'[a-z0-9]+', question.lower()) if len(w) > 2}
    scored = []
    for path in RESULTS.glob('*.txt'):
        body = path.read_text(errors='replace')
        low = body.lower()
        score = sum(3 * (t in path.stem.lower()) + min(low.count(t), 5) for t in terms)
        scored.append((score, path.stem, body))
    scored.sort(reverse=True)
    return {stem: body[:MAX_EVIDENCE_CHARS // k] for score, stem, body in scored[:k] if score > 0}


def ask(question: str) -> str:
    evidence = pick_evidence(question)
    if not evidence:
        return 'Insufficient evidence: no results file matches the question.'
    block = '\n\n'.join(f'[{stem}]\n{body}' for stem, body in evidence.items())
    prompt = f'Evidence (cite as [id]):\n{block}\n\nQuestion: {question}'
    answer, model = gated('minicpm5-analyst', prompt, lambda a: check_citations(a, list(evidence)))
    return f'{answer}\n\n(model: {model}; evidence: {", ".join(evidence)})'


def _fapi(path: str, params: dict):
    with urllib.request.urlopen(f'{FAPI}{path}?{urllib.parse.urlencode(params)}', timeout=30) as resp:
        return json.loads(resp.read())


def run_tool(tool: str, args: dict):
    if tool == 'futures_klines':
        rows = _fapi('/fapi/v1/klines', args)
        return [dict(t=r[0], o=r[1], h=r[2], l=r[3], c=r[4], v=r[5]) for r in rows]
    if tool == 'funding_rate':
        p = _fapi('/fapi/v1/premiumIndex', args)
        return {k: p[k] for k in ('symbol', 'markPrice', 'lastFundingRate', 'nextFundingTime')}
    t = _fapi('/fapi/v1/ticker/24hr', args)
    return {k: t[k] for k in ('symbol', 'lastPrice', 'priceChangePercent', 'highPrice', 'lowPrice', 'quoteVolume')}


def market(request: str) -> str:
    prompt = f'Available tools (argument formats):\n{json.dumps(TOOLS, indent=1)}\n\nRequest: {request}'
    (tool, args), model = gated('minicpm5-toolagent', prompt, parse_tool_call, as_json=True)
    data = run_tool(tool, args)
    if tool == 'futures_klines' and len(data) > 5:
        data = {'first': data[0], 'last': data[-1], 'bars': len(data)}
    return f'{tool} {args}\n{json.dumps(data, indent=1)}\n\n(model: {model})'


def route(request: str) -> str:
    intent, _ = gated('minicpm5:2b', request, parse_intent, system=ROUTER_SYSTEM, as_json=True)
    if intent == 'DIGEST':
        return digest()
    if intent == 'RESEARCH':
        return ask(request)
    if intent == 'MARKET':
        return market(request)
    return 'OTHER: outside the read-only desk (no order actions). Use the research scripts or the daemon directly.'


if __name__ == '__main__':
    cmds = {'route': route, 'digest': lambda arg: digest(arg or None), 'ask': ask, 'market': market}
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, arg = (sys.argv[1], ' '.join(sys.argv[2:])) if sys.argv[1] in cmds else ('route', ' '.join(sys.argv[1:]))
    print(cmds[cmd](arg))
