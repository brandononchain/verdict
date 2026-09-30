const assert = require('node:assert/strict');
const core = require('../zearch-core.js');

const ID = 'a'.repeat(32);

// ---- Routing ----
assert.deepEqual(core.parseRoute(''), { type: 'home' });
assert.deepEqual(core.parseRoute('#'), { type: 'home' });
assert.deepEqual(core.parseRoute(undefined), { type: 'home' });
assert.deepEqual(core.parseRoute('#r/' + ID), { type: 'run', id: ID });
assert.deepEqual(core.parseRoute('#main'), { type: 'other' });
assert.deepEqual(core.parseRoute('#r/' + 'A'.repeat(32)), { type: 'other' });
assert.deepEqual(core.parseRoute('#r/' + ID + '/extra'), { type: 'other' });
assert.deepEqual(core.parseRoute('#r/short'), { type: 'other' });
for (const view of ['library', 'knowledge', 'monitors', 'batches', 'overview']) {
  assert.deepEqual(core.parseRoute('#' + view), { type: 'view', view });
  assert.equal(core.viewHash(view), '#' + view);
}
assert.deepEqual(core.parseRoute('#library/x'), { type: 'other' });
assert.deepEqual(core.parseRoute('#Library'), { type: 'other' });
assert.deepEqual(core.parseRoute('library'), { type: 'other' });
assert.equal(core.viewHash('main'), '');
assert.equal(core.routeHash(ID), '#r/' + ID);
assert.equal(core.routeHash('nope'), '');
assert.equal(core.isRunId(ID), true);
assert.equal(core.isRunId(ID + '0'), false);
assert.equal(core.isRunId(null), false);

// ---- NDJSON reader ----
const enc = new TextEncoder();
const streamOf = chunks => {
  let at = 0;
  return { read: async () => at < chunks.length ? { value: typeof chunks[at] === 'string' ? enc.encode(chunks[at++]) : chunks[at++], done: false } : { value: undefined, done: true } };
};
async function collect(chunks) {
  const events = [];
  const result = await core.readNdjson(streamOf(chunks), event => events.push(event));
  return { events, skipped: result.skipped };
}
(async () => {
  // Normal stream.
  let out = await collect(['{"type":"start"}\n{"type":"delta","text":"a"}\n']);
  assert.deepEqual(out.events.map(e => e.type), ['start', 'delta']);
  // Final line without a trailing newline is flushed.
  out = await collect(['{"type":"delta","text":"a"}\n{"type":"complete"}']);
  assert.deepEqual(out.events.map(e => e.type), ['delta', 'complete']);
  // Lines split across chunks, including inside a multi-byte character.
  const bytes = enc.encode('{"type":"delta","text":"café ☃"}\n');
  out = await collect([bytes.slice(0, 22), bytes.slice(22, 26), bytes.slice(26)]);
  assert.equal(out.events.length, 1); assert.equal(out.events[0].text, 'café ☃');
  // Malformed lines are skipped and counted, valid ones still arrive.
  out = await collect(['{"type":"a"}\nnot json\n{"type":"b"}\n{"broken":']);
  assert.deepEqual(out.events.map(e => e.type), ['a', 'b']);
  assert.equal(out.skipped, 2);
  // CRLF, blank lines and an empty stream.
  out = await collect(['\r\n{"type":"a"}\r\n\r\n']);
  assert.deepEqual(out.events.map(e => e.type), ['a']);
  out = await collect([]);
  assert.deepEqual(out.events, []);
  // Handler errors (for example an error event) propagate.
  await assert.rejects(core.readNdjson(streamOf(['{"type":"error"}\n']), () => { throw new Error('boom'); }), /boom/);

  // ---- fetchJson ----
  const respond = (status, body, json = true) => async () => ({
    ok: status >= 200 && status < 300, status,
    json: async () => { if (!json) throw new SyntaxError('bad'); return body; }
  });
  assert.deepEqual(await core.fetchJson('/x', {}, respond(200, { ok: 1 })), { ok: 1 });
  await assert.rejects(core.fetchJson('/x', {}, respond(400, { error: 'Nope' })), /^Error: Nope$/);
  await assert.rejects(core.fetchJson('/x', {}, respond(502, null, false)), /trouble right now/);
  await assert.rejects(core.fetchJson('/x', {}, respond(429, {})), /Too many requests/);
  await assert.rejects(core.fetchJson('/x', {}, respond(200, null, false)), /unexpected response/);
  await assert.rejects(core.fetchJson('/x', {}, async () => { throw new TypeError('Failed to fetch'); }), /Could not reach Zearch/);
  await assert.rejects(core.fetchJson('/x', {}, async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; }), error => error.name === 'AbortError');
  try { await core.fetchJson('/x', {}, respond(404, {})); } catch (error) { assert.equal(error.status, 404); }

  console.log('Core routing, NDJSON and fetch tests passed');
})().catch(error => { console.error(error); process.exit(1); });

// ---- Backoff, polling, ids, text helpers (synchronous) ----
assert.equal(core.backoffDelay(0), 2000);
assert.equal(core.backoffDelay(1), 3000);
assert.equal(core.backoffDelay(2), 4500);
assert.equal(core.backoffDelay(50), 15000);
assert.equal(core.backoffDelay(-3), 2000);
assert.equal(core.backoffDelay(10, { max: 5000 }), 5000);
assert.equal(core.shouldPoll('pending'), true);
assert.equal(core.shouldPoll('streaming'), true);
for (const status of ['complete', 'error', 'interrupted', 'redacted', undefined]) assert.equal(core.shouldPoll(status), false);
assert.match(core.newRequestId({ randomUUID: () => 'uuid-1' }), /^uuid-1$/);
assert.match(core.newRequestId(null), /^[0-9a-f]{32}$/);
assert.match(core.newRequestId({ getRandomValues: a => a.fill(255) }), /^f{32}$/);
assert.equal(core.hostOf('https://www.example.com/path'), 'example.com');
assert.equal(core.hostOf('nope'), '');
assert.equal(core.truncate('  a   b  ', 10), 'a b');
assert.equal(core.truncate('abcdefghij', 5), 'abcd…');

// ---- Display helpers ----
assert.equal(core.formatPercent(0.824), '82%');
assert.equal(core.formatPercent(null), '—');
assert.equal(core.formatPercent(1.4), '100%');
assert.equal(core.formatMs(420), '420 ms');
assert.equal(core.formatMs(1234), '1.2 s');
assert.equal(core.formatMs(14200), '14 s');
assert.equal(core.formatMs(125000), '2 min 5 s');
assert.equal(core.formatMs(null), '—');
assert.equal(core.formatCost(0.0012), '$0.0012');
assert.equal(core.formatCost(1.234), '$1.23');
assert.equal(core.formatCost(0), '$0.00');
assert.equal(core.formatCost(undefined), '—');
const NOW = 1_800_000_000_000;
assert.equal(core.relativeTime(NOW / 1000 - 10, NOW), 'just now');
assert.equal(core.relativeTime(NOW / 1000 - 5 * 60, NOW), '5 min ago');
assert.equal(core.relativeTime(NOW / 1000 - 3 * 3600, NOW), '3 hours ago');
assert.equal(core.relativeTime(NOW / 1000 - 86400, NOW), 'yesterday');
assert.equal(core.relativeTime(NOW / 1000 - 5 * 86400, NOW), '5 days ago');
assert.equal(core.relativeTime(NOW - 3 * 3600 * 1000, NOW), '3 hours ago');   // milliseconds are accepted
assert.equal(core.relativeTime('nonsense', NOW), '');
assert.equal(core.modeLabel('deep'), 'Deep research');
assert.equal(core.modeLabel('???'), 'Search');
assert.deepEqual(['complete', 'pending', 'streaming', 'interrupted', 'error', 'redacted', 'x'].map(core.statusTone), ['ok', 'run', 'run', 'warn', 'bad', 'idle', 'idle']);
assert.equal(core.statusLabel('streaming'), 'Running');

// ---- Chart geometry ----
assert.deepEqual(core.segments({ a: 2, b: 2, c: 0 }, ['a', 'b', 'c']).map(x => x.share), [0.5, 0.5, 0]);
assert.deepEqual(core.segments({}, ['a']), []);
assert.deepEqual(core.segments({ a: -3, b: 'x' }, ['a', 'b']), []);
assert.equal(core.sparkPoints([1], 100, 20), '');
assert.equal(core.sparkPoints([5, 5, 5], 100, 20, 0), '0.0,10.0 50.0,10.0 100.0,10.0');
assert.equal(core.sparkPoints([0, 10], 100, 20, 0), '0.0,20.0 100.0,0.0');
assert.deepEqual(core.barHeights([{ runs: 0 }, { runs: 4 }, { runs: 2 }]), [0, 1, 0.5]);
assert.deepEqual(core.barHeights([{ runs: 0 }]), [0]);
assert.deepEqual(core.barHeights(undefined), []);

// ---- Insight sentences: deterministic and only from the stats given ----
const stats = {
  days: 30, totals: { runs: 12, complete: 9, interrupted: 1, error: 1, redacted: 1, running: 0 },
  measured: { latency: 9, cost: 9, tiers: 9, gates: 8 }, verified_rate: 0.75, gates: { answer: 6, review: 1, abstain: 1 },
  fallback_rate: 0.1111, latency_ms: { p50: 14200, p95: 31000 }, cost_usd: { total: 0.05, average: 0.0055 },
  source_tiers: { primary: 10, web: 30, private: 0 }, by_mode: { standard: 4, deep: 6, compare: 0, scrape: 0, crawl: 0 }, daily: [], activity: []
};
const lines = core.insights(stats);
assert.equal(lines.length, 3);
assert.equal(lines[0], '75% of 8 checked answers had direct evidence that passed Jev\u2019s check.');
assert.equal(lines[1], 'Median research time was 14 s, and 95% of runs finished within 31 s, across 9 timed runs.');
assert.match(lines[2], /1 answer was withheld/);
assert.deepEqual(core.insights(stats), lines);                       // deterministic
assert.equal(core.insights(stats, 10).length, 7);
assert.match(core.insights(stats, 10).join(' '), /Deep research was your most used mode: 6 of 10 runs/);
assert.match(core.insights(stats, 10).join(' '), /25% of 40 cited sources/);
assert.deepEqual(core.insights(null), []);
assert.deepEqual(core.insights({ totals: { runs: 0 } }), []);
// Nothing measured: no invented percentages or timings.
const bare = { totals: { runs: 2, error: 0, interrupted: 0 }, measured: { latency: 0, cost: 0, tiers: 0, gates: 0 }, verified_rate: null, gates: {}, fallback_rate: null,
  latency_ms: { p50: null, p95: null }, source_tiers: { primary: 0, web: 0, private: 0 }, by_mode: { standard: 2 } };
assert.deepEqual(core.insights(bare), ['Search was your most used mode: 2 of 2 runs.']);
assert.match(core.insights({ ...bare, totals: { runs: 3, error: 1, interrupted: 2 } }, 5).join(' '), /3 runs ended in an error or was interrupted/);

// ---- Activity sorting ----
const rows = [{ id: 1, query: 'b', total_ms: 30, sources: 2, created: 3 }, { id: 2, query: 'A', total_ms: null, sources: 5, created: 1 }, { id: 3, query: 'c', total_ms: 10, sources: 0, created: 2 }];
assert.deepEqual(core.sortActivity(rows, 'total_ms', 'asc').map(r => r.id), [3, 1, 2]);
assert.deepEqual(core.sortActivity(rows, 'total_ms', 'desc').map(r => r.id), [1, 3, 2]);   // missing values stay last
assert.deepEqual(core.sortActivity(rows, 'query', 'asc').map(r => r.id), [2, 1, 3]);
assert.deepEqual(core.sortActivity(rows, 'created', 'desc').map(r => r.id), [1, 3, 2]);
assert.deepEqual(core.sortActivity(rows, 'nope', 'asc').map(r => r.id), [1, 2, 3]);
assert.deepEqual(rows.map(r => r.id), [1, 2, 3]);                                          // input is not mutated

// ---- Command palette matcher ----
const items = [{ label: 'Library', keywords: 'saved answers history' }, { label: 'Deep research', keywords: 'mode' }, { label: 'Overview', keywords: 'analytics stats' },
  { label: 'How do heat pumps work?', group: 'Library' }, { label: 'Compare' }];
assert.deepEqual(core.paletteFilter(items, '').map(i => i.label), items.map(i => i.label));       // empty query keeps order
assert.equal(core.paletteFilter(items, 'lib')[0].label, 'Library');
assert.equal(core.paletteFilter(items, 'analytics')[0].label, 'Overview');                       // keyword match
assert.deepEqual(core.paletteFilter(items, 'heat pump').map(i => i.label), ['How do heat pumps work?']);
assert.equal(core.paletteFilter(items, 'dpr')[0].label, 'Deep research');                        // in-order letters
assert.deepEqual(core.paletteFilter(items, 'zzz'), []);
assert.equal(core.paletteFilter(items, '', 2).length, 2);
assert.ok(core.paletteScore('Library', 'lib') > core.paletteScore('Public library', 'lib'));

// ---- Theme preferences ----
const fakeDoc = () => { const attrs = {}; return { attrs, documentElement: { setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: k => { delete attrs[k]; } } }; };
const store = values => ({ getItem: key => (key in values ? values[key] : null) });
let doc = fakeDoc();
assert.deepEqual(core.applyPreferences(doc, store({})), { theme: 'system', motion: 'system' });
assert.deepEqual(doc.attrs, {});
doc = fakeDoc(); core.applyPreferences(doc, store({ 'zearch:theme': 'dark', 'zearch:motion': 'reduce' }));
assert.deepEqual(doc.attrs, { 'data-theme': 'dark', 'data-motion': 'reduce' });
doc = fakeDoc(); assert.equal(core.applyPreferences(doc, store({ 'zearch:theme': '<script>' })).theme, 'system');
doc = fakeDoc(); assert.equal(core.applyPreferences(doc, { getItem: () => { throw new Error('blocked'); } }).theme, 'system');   // blocked storage
assert.equal(core.normalizeTheme('light'), 'light');

// ---- Rail width ----
assert.equal(core.clampRailWidth(100, 1280), 224);
assert.equal(core.clampRailWidth(999, 1280), 256);
assert.equal(core.clampRailWidth(240, 1280), 240);
assert.equal(core.clampRailWidth(400, 800), 224);            // 20% of 800 is below the minimum, so the minimum wins
assert.equal(core.clampRailWidth('abc', 1920), 258);
assert.equal(core.clampRailWidth(600, 1920), 384);
assert.equal(core.railMaxWidth(0), 224);

// ---- Target URL validation ----
assert.equal(core.validateTargetUrl('').empty, true);
assert.equal(core.validateTargetUrl('https://example.com/page').ok, true);
for (const bad of ['http://example.com', 'example.com', 'https://user:pw@example.com', 'https://localhost/x', 'https://127.0.0.1/', 'https://intranet/', 'ftp://example.com', 'javascript:alert(1)'])
  assert.equal(core.validateTargetUrl(bad).ok, false, bad);
assert.match(core.validateTargetUrl('http://example.com').reason, /https/);
assert.equal(core.validateTargetUrl('https://example.com/' + 'a'.repeat(2100)).ok, false);

// ---- Follow-up suggestions ----
assert.deepEqual(core.followupSuggestions(undefined), []);
assert.deepEqual(core.followupSuggestions({}), []);
assert.deepEqual(core.followupSuggestions({ followups: 'nope' }), []);
assert.deepEqual(core.followupSuggestions({ followups: ['  One  ', 2, null, 'one', 'Two', '', 'Three', 'Four'] }), ['One', 'Two', 'Three']);
assert.deepEqual(core.followupSuggestions({ followups: ['x'.repeat(200), 'ok'] }), ['ok']);

// ---- Library filter ----
const lib = [{ id: 1, query: 'Heat pumps', status: 'complete', depth: 'deep' }, { id: 2, query: 'Postgres', status: 'error', depth: 'compare' }, { id: 3, query: 'Old row', status: 'streaming' }];
assert.deepEqual(core.filterLibrary(lib, {}).map(r => r.id), [1, 2, 3]);
assert.deepEqual(core.filterLibrary(lib, { needle: 'heat' }).map(r => r.id), [1]);
assert.deepEqual(core.filterLibrary(lib, { mode: 'deep' }).map(r => r.id), [1]);
assert.deepEqual(core.filterLibrary(lib, { status: 'running' }).map(r => r.id), [3]);
assert.deepEqual(core.filterLibrary(lib, { status: 'error', mode: 'compare' }).map(r => r.id), [2]);
assert.equal(core.hasDepth(lib), true); assert.equal(core.hasDepth([{ query: 'a' }]), false);
console.log('Core display, insight, sort and palette tests passed');
