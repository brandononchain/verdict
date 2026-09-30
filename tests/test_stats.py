import json
import time
import unittest
import test_research as baseline
import research_store as db
import usage_report
import workspace_store as workspace


class StatsTests(unittest.TestCase):
    def setUp(self):
        baseline.ResearchTests.setUp(self)
        self.limits['user_calls'] = 100

    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve

    def run_(self, owner='alice', status='complete', depth='standard', age=0, usage=None, sources=None, cost=None, updated=None):
        run, _ = self.reserve(owner)
        db.save(owner, run['id'], status=status, answer='secret answer', sources=sources or [], usage=usage or {}, estimated_cost=cost)
        now = int(time.time())
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE research_runs SET created=?,updated=? WHERE id=?', (now - age, updated or now, run['id']))
            db.execute(conn, marker, 'UPDATE research_options SET depth=? WHERE run_id=?', (depth, run['id']))
        return run['id']

    def test_empty_owner(self):
        s = workspace.stats('nobody')
        self.assertEqual(s['totals'], dict(runs=0, running=0, complete=0, interrupted=0, error=0, redacted=0))
        self.assertEqual(s['measured'], dict(latency=0, cost=0, tiers=0, gates=0))
        self.assertIsNone(s['verified_rate']); self.assertIsNone(s['fallback_rate'])
        self.assertEqual(s['latency_ms'], {'p50': None, 'p95': None})
        self.assertEqual(s['cost_usd'], {'total': 0, 'average': None})
        self.assertEqual(len(s['daily']), 14); self.assertEqual(sum(d['runs'] for d in s['daily']), 0)
        self.assertEqual(s['activity'], []); self.assertEqual(s['days'], 30)

    def test_seeded_owner_and_isolation(self):
        tier = lambda t: {'url': 'https://e.com/' + t, 'source_tier': t}
        self.run_(usage={'total_ms': 1000, 'judgment': {'gate': 'answer'}}, sources=[tier('primary'), tier('web')], cost=2000000)
        self.run_(depth='deep', usage={'total_ms': 3000, 'judgment': {'gate': 'abstain'}, 'draft_fallback_reason': 'x'}, sources=[tier('private')], cost=4000000)
        self.run_(usage={})  # old run without data
        self.run_(status='error'); self.run_(status='interrupted'); self.run_(status='redacted', usage={'redacted_knowledge': True})
        self.run_('bob', usage={'total_ms': 9, 'judgment': {'gate': 'answer'}})
        s = workspace.stats('alice')
        self.assertEqual(s['totals'], dict(runs=6, running=0, complete=3, interrupted=1, error=1, redacted=1))
        self.assertEqual(s['measured'], dict(latency=2, cost=2, tiers=2, gates=2))
        self.assertEqual(s['verified_rate'], 0.5)
        self.assertEqual(s['gates'], dict(answer=1, review=0, abstain=1))
        self.assertEqual(round(s['fallback_rate'], 4), round(1 / 3, 4))
        self.assertEqual(s['latency_ms'], {'p50': 1000, 'p95': 3000})
        self.assertEqual(s['cost_usd'], {'total': 6.0, 'average': 3.0})
        self.assertEqual(s['source_tiers'], dict(primary=1, web=1, private=1))
        self.assertEqual(s['by_mode']['deep'], 1); self.assertEqual(s['by_mode']['standard'], 4)
        self.assertEqual(sum(d['runs'] for d in s['daily']), 6)
        self.assertEqual(len(s['activity']), 6)
        self.assertNotIn('secret answer', json.dumps(s))
        self.assertEqual(workspace.stats('bob')['totals']['runs'], 1)

    def test_window_and_clamp(self):
        self.run_(age=3 * 86400); self.run_(age=20 * 86400); self.run_(age=60 * 86400)
        self.assertEqual(workspace.stats('alice', 7)['totals']['runs'], 1)
        self.assertEqual(workspace.stats('alice')['totals']['runs'], 2)
        self.assertEqual(workspace.stats('alice', 500)['days'], 90)
        self.assertEqual(workspace.stats('alice', 500)['totals']['runs'], 3)
        self.assertEqual(workspace.stats('alice', 0)['days'], 1)
        s = workspace.stats('alice', 1)
        self.assertEqual(s['totals']['runs'], 0); self.assertEqual(sum(d['runs'] for d in s['daily']), 1)

    def test_running_and_stale(self):
        live, _ = self.reserve('alice')
        stale, _ = self.reserve('alice')
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE research_runs SET updated=? WHERE id=?', (int(time.time()) - db.STALE_SECONDS - 5, stale['id']))
        self.assertEqual(workspace.running_count('alice'), 1)
        self.assertEqual(workspace.stats('alice')['totals']['running'], 1)
        self.assertEqual(workspace.running_count('bob'), 0)

    def test_activity_newest_20(self):
        for n in range(25): self.run_(age=n)
        self.assertEqual(len(workspace.stats('alice')['activity']), 20)

    def test_report_helpers(self):
        self.assertEqual(usage_report.percentile([1, 2, 3, 4], .5), 2)
        self.assertEqual(usage_report.load_json('not json', {}), {})
        self.assertEqual(dict(usage_report.gate_counts([{'judgment': {'gate': 'answer'}}, {}])), {'answer': 1})
        self.assertIn('standard', usage_report.report())


if __name__ == '__main__':
    unittest.main()
