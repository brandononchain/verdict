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
