"""Opt-in paid evaluation through normal budget and durable run paths.

List: python evals/run.py --limit 3
Execute: python evals/run.py --execute --limit 3 --output eval-results.jsonl
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research
import research_store as db


def corpus():
    data = json.loads(Path(__file__).with_name('cases-v1.json').read_text())
    cases = data['cases']
    ids = {case['id'] for case in cases}
    if data['version'] != 'm6.2-v1' or len(cases) != 100 or len(ids) != 100:
        raise ValueError('Invalid review corpus')
    for case in cases:
        if case.get('parent_case_id') and case['parent_case_id'] not in ids:
            raise ValueError('Unknown parent case')
    return data


def selection(cases, ids, category, limit):
    by_id = {case['id']: case for case in cases}
    if any(case_id not in by_id for case_id in ids):
        raise ValueError('Unknown case ID')
    chosen = [case for case in cases if (not ids or case['id'] in ids) and
              (not category or case['category'] == category)][:limit]
    ordered, seen = [], set()
    def include(case):
        if case['id'] in seen:
            return
        if case.get('parent_case_id'):
            include(by_id[case['parent_case_id']])
        seen.add(case['id'])
        ordered.append(case)
    for case in chosen:
        include(case)
    return ordered


def execute(case, version, parents):
    parent = parents.get(case.get('parent_case_id'))
    record, _, history = research.prepare('operator-evaluation', {
        'query': case['query'], 'request_id': 'eval-' + uuid.uuid4().hex,
        'depth': case['mode'], 'parent_id': parent})
    for _ in research.run('operator-evaluation', record, history):
        pass
    saved = db.get_run('operator-evaluation', record['id'])
    if saved['status'] == 'complete':
        parents[case['id']] = saved['id']
    return {'version': version, 'case_id': case['id'], 'category': case['category'],
            'mode': case['mode'], 'temporal': case['temporal'], 'query': case['query'],
            'evidence_expectation': case['evidence_expectation'],
            'review_focus': case['review_focus'], 'parent_case_id': case.get('parent_case_id'),
            'run_id': saved['id'], 'status': saved['status'], 'answer': saved['answer'],
            'sources': saved['sources'], 'usage': saved['usage'],
            'estimated_cost': saved['estimated_cost'], 'error': saved['error']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Use paid providers and normal budgets')
    parser.add_argument('--output', type=Path, help='JSONL result file, required for execution')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--category')
    parser.add_argument('--ids', nargs='+', default=[])
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 100 or (args.execute and not args.output):
        parser.error('limit must be 1–100; --execute requires --output')
    data = corpus()
    if args.category and args.category not in {case['category'] for case in data['cases']}:
        parser.error('Unknown category')
    try:
        cases = selection(data['cases'], args.ids, args.category, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.execute:
        for case in cases:
            print(json.dumps(case))
        return
    if args.output.exists():
        parser.error('Output already exists; choose a new file for each batch')
    parents = {}
    with args.output.open('x') as output:
        for case in cases:
            if case.get('parent_case_id') and case['parent_case_id'] not in parents:
                print(f"Skipping {case['id']}: parent did not complete", file=sys.stderr)
                continue
            try:
                row = execute(case, data['version'], parents)
            except (db.LimitReached, research.Unavailable) as exc:
                print(f'Stopped before {case["id"]}: {exc}', file=sys.stderr)
                break
            output.write(json.dumps(row) + '\n')
            output.flush()
            print(f"{case['id']} {row['status']} {row['run_id']}")


if __name__ == '__main__':
    main()
