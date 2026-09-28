"""Create human scorecards from eval results and summarize completed reviews.

python evals/review.py init eval-results.jsonl review.jsonl
python evals/review.py report review.jsonl
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

DIMENSIONS = ('usefulness', 'citation_support', 'source_quality', 'abstention', 'freshness')
FAILURES = ('retrieval', 'extraction', 'jev_selection', 'writer', 'jev_verification', 'rendering', 'other', 'none')


def read_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({row['run_id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate run IDs')
    return rows


def init(source, destination):
    if destination.exists():
        raise ValueError('Scorecard already exists')
    rows = read_rows(source)
    with destination.open('x') as output:
        for row in rows:
            card = {key: row[key] for key in ('version', 'case_id', 'category', 'mode', 'temporal', 'run_id', 'status')}
            usage = row.get('usage') or {}
            card.update(estimated_cost=row.get('estimated_cost'), total_ms=usage.get('total_ms'),
                        jev_gate=(usage.get('judgment') or {}).get('gate'),
                        answer_format=usage.get('answer_format'))
            card.update(candidate_urls=usage.get('candidate_urls'), selected_urls=usage.get('selected_urls'),
                        primary_selected_urls=[source.get('canonical_url') for source in row.get('sources', [])
                                               if source.get('source_tier') == 'primary' and source.get('canonical_url')],
                        relevant_candidate_urls=None, source_relevance_reviewed=False)
            card.update(reviewer=None, reviewed_at=None, citations_opened=False,
                        scores={key: None for key in DIMENSIONS}, failure_stage=None, notes='')
            output.write(json.dumps(card) + '\n')
    return len(rows)


def reviewed(row):
    scores = row.get('scores', {})
    values = tuple(scores.get(key) for key in DIMENSIONS)
    if all(value is None for value in values) and not row.get('reviewer'):
        return False
    if row['status'] != 'complete' or not row.get('reviewer') or not row.get('reviewed_at') or type(row.get('citations_opened')) is not bool:
        raise ValueError(f"Incomplete review metadata: {row['case_id']}")
    if any(value not in ('pass', 'fail', 'na') for value in values):
        raise ValueError(f"Invalid score: {row['case_id']}")
    if row.get('failure_stage') not in FAILURES:
        raise ValueError(f"Invalid failure stage: {row['case_id']}")
    if scores['citation_support'] != 'na' and not row['citations_opened']:
        raise ValueError(f"Citations must be opened: {row['case_id']}")
    if row['temporal'] == 'current' and scores['freshness'] == 'na':
        raise ValueError(f"Freshness must be scored for current case: {row['case_id']}")
    return True


def report(rows):
    if any(row.get('version') != 'm6.2-v1' for row in rows):
        raise ValueError('Unknown review corpus version')
    complete = [row for row in rows if row['status'] == 'complete']
    scored = [row for row in complete if reviewed(row)]
    scored_ids = {row['run_id'] for row in scored}
    def p95(values):
        values = sorted(value for value in values if type(value) is int and value >= 0)
        return values[math.ceil(len(values) * .95) - 1] if values else None
    def group(group_rows):
        reviewed_rows = [row for row in group_rows if row['run_id'] in scored_ids]
        return {'runs': len(group_rows), 'reviewed': len(reviewed_rows),
                'p95_total_ms': p95(row.get('total_ms') for row in group_rows),
                'estimated_cost_usd': round(sum(row.get('estimated_cost') or 0 for row in group_rows) / 1_000_000, 6),
                'missing_cost_records': sum(row.get('estimated_cost') is None for row in group_rows),
                'scores': {key: dict(Counter(row['scores'][key] for row in reviewed_rows))
                           for key in DIMENSIONS},
                'failure_stages': dict(Counter(row['failure_stage'] for row in reviewed_rows))}
    return {'version': 'm6.2-v1', 'corpus_size': 100, 'runs': len(rows),
            'complete': len(complete), 'reviewed': len(scored),
            'unique_cases_reviewed': len({row['case_id'] for row in scored}),
            'by_mode': {mode: group([row for row in rows if row['mode'] == mode])
                        for mode in ('standard', 'deep', 'compare')},
            'by_category': {category: group([row for row in rows if row['category'] == category])
                            for category in sorted({row['category'] for row in rows})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'report'))
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    if args.command == 'init':
        if not args.output:
            parser.error('init requires output scorecard path')
        print(f'Created {init(args.input, args.output)} blank scorecards')
    else:
        print(json.dumps(report(read_rows(args.input)), indent=2))


if __name__ == '__main__':
    main()
