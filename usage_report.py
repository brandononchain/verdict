"""Operator-only aggregate report. Never outputs prompts, notes, owner IDs or keys."""
import json
import math
from collections import Counter
import research_store as db


def percentile(values, portion):
    rows=sorted(values)
    return rows[math.ceil(len(rows)*portion)-1] if rows else None


def report():
    with db.connection() as (conn, marker):
        rows=conn.execute('SELECT r.status,r.created,r.updated,r.estimated_cost,r.reserved,r.usage,r.sources,o.depth FROM research_runs r LEFT JOIN research_options o ON o.run_id=r.id').fetchall()
    output={}
    for mode in ('standard','deep','compare','scrape','crawl'):
        group=[r for r in rows if (r['depth'] or 'standard')==mode]
        done=[r for r in group if r['status']=='complete']
        costs=sorted(r['estimated_cost'] for r in done if r['estimated_cost'] is not None)
        durations=sorted(r['updated']-r['created'] for r in done)
        traces=[json.loads(r['usage'] or '{}') for r in group]
        stages={name: [trace['stage_ms'][name] for trace in traces
                       if isinstance(trace.get('stage_ms'),dict) and type(trace['stage_ms'].get(name)) is int]
                for name in ('market_quote','retrieval','private_knowledge','enrichment','jev_selection','writer','jev_verification')}
        totals=[trace['total_ms'] for trace in traces if type(trace.get('total_ms')) is int]
        tiers=Counter(source.get('source_tier','web') for r in done for source in json.loads(r['sources'] or '[]'))
        output[mode]={'runs':len(group),'complete':len(done),'cost_records_missing':sum(r['estimated_cost'] is None for r in group),
            'estimated_provider_usd':round(sum(r['estimated_cost'] or 0 for r in group)/1000000,6),
            'p95_complete_cost_usd':percentile(costs,.95)/1000000 if costs else None,
            'p95_complete_seconds':percentile(durations,.95),
            'p50_total_ms':percentile(totals,.5), 'p95_total_ms':percentile(totals,.95),
            'stage_ms':{name:{'count':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95)}
                        for name,values in stages.items() if values},
            'status_counts':dict(Counter(r['status'] for r in group)),
            'failure_stages':dict(Counter(t['failure_stage'] for t in traces if t.get('failure_stage'))),
            'failure_kinds':dict(Counter(t['failure_kind'] for t in traces if t.get('failure_kind'))),
            'search_failure_kinds':dict(sum((Counter(t.get('search_failure_kinds') or {}) for t in traces),Counter())),
            'draft_fallback_reasons':dict(Counter(t['draft_fallback_reason'] for t in traces if t.get('draft_fallback_reason'))),
            'jev_gates':dict(Counter(t['judgment']['gate'] for t in traces if isinstance(t.get('judgment'),dict) and t['judgment'].get('gate'))),
            'source_tiers':dict(tiers)}
    return output


if __name__=='__main__':print(json.dumps(report(),indent=2))
