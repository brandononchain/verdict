"""Operator-only aggregate report. Never outputs prompts, notes, owner IDs or keys."""
import json
import math
import research_store as db


def report():
    with db.connection() as (conn, marker):
        rows=conn.execute('SELECT r.status,r.created,r.updated,r.estimated_cost,r.reserved,o.depth FROM research_runs r LEFT JOIN research_options o ON o.run_id=r.id').fetchall()
    output={}
    for mode in ('standard','deep'):
        group=[r for r in rows if (r['depth'] or 'standard')==mode]
        done=[r for r in group if r['status']=='complete']
        costs=sorted(r['estimated_cost'] for r in done if r['estimated_cost'] is not None)
        durations=sorted(r['updated']-r['created'] for r in done)
        output[mode]={'runs':len(group),'complete':len(done),'cost_records_missing':sum(r['estimated_cost'] is None for r in group),
            'estimated_provider_usd':round(sum(r['estimated_cost'] or 0 for r in group)/1000000,6),
            'p95_complete_cost_usd':costs[math.ceil(len(costs)*.95)-1]/1000000 if costs else None,
            'p95_complete_seconds':durations[math.ceil(len(durations)*.95)-1] if durations else None}
    return output


if __name__=='__main__':print(json.dumps(report(),indent=2))
