"""M6.4 release gate for a pinned human-reviewed 100-case cohort.

python evals/quality_gate.py review-cohort.jsonl --policy evals/quality-policy.json
Returns HOLD until a complete cohort and evidence-based thresholds are present.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

try:
    from . import review, run
except ImportError:
    import review
    import run

MODES = ('standard', 'deep', 'compare')
DIMENSIONS = review.DIMENSIONS


def percentile(values, portion):
    values = sorted(values)
    return values[math.ceil(len(values) * portion) - 1] if values else None


def evaluate(rows, policy):
    expected = {case['id']: case for case in run.corpus()['cases']}
    reasons = []
    complete = [row for row in rows if row.get('status') == 'complete']
    valid = []
    for row in complete:
        try:
            if review.reviewed(row):
                valid.append(row)
        except ValueError as exc:
            reasons.append(str(exc))
    counts = Counter(row.get('case_id') for row in valid)
    missing = sorted(set(expected) - counts.keys())
    repeated = sorted(case_id for case_id, count in counts.items() if count > 1)
    unexpected = sorted(set(counts) - set(expected))
    if missing:
        reasons.append(f'{len(missing)} corpus cases lack a completed human review')
    if repeated:
        reasons.append(f'{len(repeated)} cases have multiple reviews; pin one run per case')
    if unexpected:
        reasons.append(f'{len(unexpected)} reviewed cases are outside the versioned corpus')
    for row in valid:
        case = expected.get(row.get('case_id'))
        if row.get('version') != 'm6.2-v1':
            reasons.append(f"Corpus version mismatch: {row.get('case_id')}")
        if case and any(row.get(k) != case[k] for k in ('category', 'mode', 'temporal')):
            reasons.append(f"Case metadata mismatch: {row.get('case_id')}")
        if not row.get('citations_opened'):
            reasons.append(f"Sources not inspected: {row.get('case_id')}")
        if type(row.get('total_ms')) is not int or row['total_ms'] < 0:
            reasons.append(f"Timing missing: {row.get('case_id')}")
        if type(row.get('estimated_cost')) is not int or row['estimated_cost'] < 0:
            reasons.append(f"Provider cost estimate missing: {row.get('case_id')}")
    if (not isinstance(policy, dict) or policy.get('version') != 'm6.4-v1'
            or not isinstance(policy.get('baseline_id'), str) or not policy['baseline_id'].strip()):
        reasons.append('Measured baseline ID and thresholds have not been approved')
        policy = {}
    thresholds = policy.get('thresholds') or {}
    rates = {}
    for mode in MODES:
        group = [row for row in valid if row.get('mode') == mode]
        if any(row.get('scores', {}).get('abstention') == 'na' for row in group):
            reasons.append(f'{mode} abstention decisions were not scored')
        mode_policy = thresholds.get(mode) or {}
        mode_rates = {}
        for dimension in DIMENSIONS:
            values = [row['scores'][dimension] for row in group if row['scores'][dimension] != 'na']
            rate = sum(v == 'pass' for v in values) / len(values) if values else None
            mode_rates[dimension] = round(rate, 4) if rate is not None else None
            minimum = (mode_policy.get('min_pass_rate') or {}).get(dimension)
            if values and (type(minimum) not in (float, int) or not 0 <= minimum <= 1):
                reasons.append(f'{mode} {dimension} threshold missing or invalid')
            elif values and rate < minimum:
                reasons.append(f'{mode} {dimension} pass rate below threshold')
        latency = percentile([row['total_ms'] for row in group if type(row.get('total_ms')) is int], .95)
        cost = percentile([row['estimated_cost'] for row in group if type(row.get('estimated_cost')) is int], .95)
        max_latency = mode_policy.get('max_p95_total_ms')
        max_cost = mode_policy.get('max_p95_estimated_cost_usd')
        if type(max_latency) not in (float, int) or max_latency <= 0:
            reasons.append(f'{mode} latency threshold missing or invalid')
        elif latency is not None and latency > max_latency:
            reasons.append(f'{mode} p95 latency above threshold')
        if type(max_cost) not in (float, int) or max_cost <= 0:
            reasons.append(f'{mode} cost threshold missing or invalid')
        elif cost is not None and cost / 1_000_000 > max_cost:
            reasons.append(f'{mode} p95 estimated cost above threshold')
        rates[mode] = {'reviews': len(group), 'pass_rates': mode_rates,
                       'p95_total_ms': latency,
                       'p95_estimated_cost_usd': round(cost / 1_000_000, 6) if cost is not None else None}
    return {'status': 'HOLD' if reasons else 'GO', 'reviewed_cases': len(counts),
            'required_cases': len(expected), 'by_mode': rates, 'reasons': sorted(set(reasons))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards', type=Path)
    parser.add_argument('--policy', type=Path, default=Path(__file__).with_name('quality-policy.json'))
    args = parser.parse_args()
    rows = review.read_rows(args.scorecards)
    policy = json.loads(args.policy.read_text())
    result = evaluate(rows, policy)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'GO' else 1)


if __name__ == '__main__':
    main()
