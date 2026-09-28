"""Compare two pinned, fully human-reviewed model cohorts without paid calls.

python evals/model_compare.py baseline.jsonl candidate.jsonl --policy evals/quality-policy.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from . import quality_gate, review, run
except ImportError:
    import quality_gate
    import review
    import run


def summarize(rows, expected):
    by_case = {}
    run_ids = set()
    for row in rows:
        case = expected.get(row.get('case_id'))
        if (not case or row.get('version') != 'm6.2-v1' or row.get('status') != 'complete'
                or any(row.get(key) != case[key] for key in ('category', 'mode', 'temporal'))
                or row.get('case_id') in by_case or row.get('run_id') in run_ids
                or not review.reviewed(row)
                or not row.get('citations_opened')
                or (row.get('answer_format') != 'validated_market_quote' and not row.get('jev_selection_model'))
                or type(row.get('total_ms')) is not int or row['total_ms'] < 0
                or type(row.get('estimated_cost')) is not int or row['estimated_cost'] < 0):
            raise ValueError(f"Invalid pinned cohort row: {row.get('case_id')}")
        by_case[row['case_id']] = row
        run_ids.add(row['run_id'])
    if set(by_case) != set(expected):
        raise ValueError(f'Pinned cohort has {len(by_case)} of {len(expected)} required cases')
    by_mode = {}
    for mode in quality_gate.MODES:
        group = [row for row in by_case.values() if row['mode'] == mode]
        rates = {}
        for dimension in review.DIMENSIONS:
            scores = [row['scores'][dimension] for row in group if row['scores'][dimension] != 'na']
            rates[dimension] = round(sum(score == 'pass' for score in scores) / len(scores), 4) if scores else None
        by_mode[mode] = {'cases': len(group), 'pass_rates': rates,
            'p95_total_ms': quality_gate.percentile([row['total_ms'] for row in group], .95),
            'p95_estimated_cost_usd': round(quality_gate.percentile([row['estimated_cost'] for row in group], .95) / 1_000_000, 6),
            'draft_fallbacks': sum(row.get('draft_rejected') is True for row in group),
            'answer_formats': dict(Counter(row.get('answer_format') or 'unknown' for row in group))}
    models = {key: sorted({row[key] for row in by_case.values() if row.get(key)})
              for key in ('jev_selection_model', 'jev_verification_model', 'writer_model')}
    if any(len(versions) > 1 for versions in models.values()):
        raise ValueError('Cohort contains mixed model versions; pin each model configuration')
    return by_case, {'by_mode': by_mode, 'models': models}


def compare(baseline, candidate, policy):
    expected = {case['id']: case for case in run.corpus()['cases']}
    try:
        before, before_report = summarize(baseline, expected)
        after, after_report = summarize(candidate, expected)
        if {row['run_id'] for row in before.values()} & {row['run_id'] for row in after.values()}:
            raise ValueError('Baseline and candidate cohorts reuse a run ID')
    except (ValueError, KeyError, TypeError) as exc:
        return {'status': 'HOLD', 'reasons': [str(exc)]}
    release = quality_gate.evaluate(candidate, policy)
    reasons = list(release['reasons'])
    deltas = {}
    for mode in quality_gate.MODES:
        old = before_report['by_mode'][mode]
        new = after_report['by_mode'][mode]
        rates = {}
        for dimension in review.DIMENSIONS:
            a, b = old['pass_rates'][dimension], new['pass_rates'][dimension]
            rates[dimension] = round(b - a, 4) if a is not None and b is not None else None
            if dimension in ('usefulness', 'citation_support', 'source_quality', 'abstention', 'freshness') and rates[dimension] is not None and rates[dimension] < 0:
                reasons.append(f'{mode} {dimension} regressed against baseline')
        deltas[mode] = {'pass_rate_delta': rates,
            'p95_total_ms_delta': new['p95_total_ms'] - old['p95_total_ms'],
            'p95_estimated_cost_usd_delta': round(new['p95_estimated_cost_usd'] - old['p95_estimated_cost_usd'], 6),
            'draft_fallback_delta': new['draft_fallbacks'] - old['draft_fallbacks']}
    return {'status': 'HOLD' if reasons else 'GO', 'reasons': sorted(set(reasons)),
        'baseline': before_report, 'candidate': after_report, 'by_mode_delta': deltas,
        'release_gate': release['status']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--policy', type=Path, default=Path(__file__).with_name('quality-policy.json'))
    args = parser.parse_args()
    result = compare(review.read_rows(args.baseline), review.read_rows(args.candidate), json.loads(args.policy.read_text()))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'GO' else 1)


if __name__ == '__main__':
    main()
