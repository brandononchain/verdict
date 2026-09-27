"""Opt-in paid canary/evaluation. Uses normal budgets and durable run records.

Run from repository root: python evals/run.py --execute --limit 3
Without --execute only lists questions. Scores require human review.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research
import research_store as db
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--execute', action='store_true')
parser.add_argument('--limit', type=int, default=3)
parser.add_argument('--depth', choices=['standard','deep'], default='standard')
args = parser.parse_args()
cases = json.loads(Path(__file__).with_name('questions.json').read_text())[:max(0,min(20,args.limit))]
for case in cases:
    if not args.execute:
        print(json.dumps(case)); continue
    record,fresh,history = research.prepare('operator-evaluation', {
        'query':case['query'], 'request_id':'eval-'+uuid.uuid4().hex, 'depth':args.depth})
    for event in research.run('operator-evaluation',record,history):
        pass
    saved=db.get_run('operator-evaluation',record['id'])
    print(json.dumps({'case':case['id'], 'run':saved, 'rubric':case['rubric'],
        'human_review_required':True, 'quality_score':None}))
