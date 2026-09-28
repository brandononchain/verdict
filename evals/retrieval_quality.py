"""Measure ranker recall within the provider candidate pool after human URL review.

python evals/retrieval_quality.py reviewed-scorecards.jsonl
"""
import argparse
import json
from pathlib import Path

try:
    from . import review
except ImportError:
    import review


def report(rows):
    measurements = []
    for row in rows:
        if not row.get('source_relevance_reviewed'):
            continue
        if not review.reviewed(row) or not row.get('citations_opened'):
            raise ValueError(f"Incomplete source review: {row.get('case_id')}")
        candidates, selected, relevant, primary = (row.get(key) for key in
            ('candidate_urls', 'selected_urls', 'relevant_candidate_urls', 'primary_selected_urls'))
        if any(not isinstance(group, list) or any(not isinstance(url, str) for url in group)
               or len(set(group)) != len(group) for group in (candidates, selected, relevant, primary)):
            raise ValueError(f"Invalid URL inventory: {row.get('case_id')}")
        candidate_set, selected_set, relevant_set = set(candidates), set(selected), set(relevant)
        if not selected_set <= candidate_set or not relevant_set <= candidate_set or not set(primary) <= selected_set:
            raise ValueError(f"URLs outside candidate pool: {row.get('case_id')}")
        measurements.append((row['mode'], len(relevant_set & selected_set),
                             len(relevant_set), len(selected_set), len(primary)))
    result = {}
    for mode in ('standard', 'deep', 'compare'):
        group = [values for values in measurements if values[0] == mode]
        found, relevant, selected, primary = (sum(values[index] for values in group) for index in (1, 2, 3, 4))
        result[mode] = {'reviewed_cases': len(group), 'relevant_selected': found,
                        'relevant_candidates': relevant, 'selected_sources': selected,
                        'matched_publisher_sources': primary,
                        'candidate_recall': round(found / relevant, 4) if relevant else None,
                        'selected_precision': round(found / selected, 4) if selected else None,
                        'matched_publisher_share': round(primary / selected, 4) if selected else None}
    return {'status': 'MEASURED' if measurements else 'NO_HUMAN_SOURCE_REVIEWS',
            'scope': 'Recall among provider-returned URLs, not total web recall',
            'by_mode': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards', type=Path)
    args = parser.parse_args()
    print(json.dumps(report(review.read_rows(args.scorecards)), indent=2))


if __name__ == '__main__':
    main()
