const assert = require('node:assert/strict');
const { blocks, chartData, render, sourceLink } = require('../renderer.js');

// ---- Pure parsing ----
assert.equal(blocks('# Answer\n\nText\n\n## Details')[2].text, 'Details');
assert.deepEqual(blocks('- One\n- Two')[0].items, ['One', 'Two']);
assert.equal(blocks('| A | B |\n| --- | --- |\n| 1 | 2 |')[0].type, 'table');
assert.equal(blocks('| A | B |\n| --- | --- |\n| 1 |')[0].type, 'paragraph');
assert.equal(blocks('```js\n<script>alert(1)</script>\n```')[0].type, 'code');
assert.equal(blocks('```python\nprint(1)\n```')[0].language, 'python');
const numeric = blocks('| Year | Users |\n| --- | --- |\n| 2024 | 10 [1] |\n| 2025 | 20 [1] |')[0];
assert.equal(chartData(numeric, [{ n: 1 }]).length, 2);
assert.equal(chartData(numeric, [{ n: 2 }]), null);
assert.equal(chartData(blocks('| A | B |\n| --- | --- |\n| x | 10 |\n| y | 20 |')[0], [{ n: 1 }]), null);

// Ordered lists keep one list, and their numbering, across blank lines.
const loose = blocks('1. First\n\n2. Second\n\n3. Third');
assert.equal(loose.length, 1);
assert.deepEqual(loose[0].items, ['First', 'Second', 'Third']);
assert.equal(loose[0].ordered, true);
assert.equal(blocks('3. Three\n4. Four')[0].start, 3);
assert.equal(blocks('1) One\n2) Two')[0].items.length, 2);
// A blank line followed by a different kind of block ends the list.
const ended = blocks('- One\n\nParagraph after');
assert.equal(ended.length, 2); assert.equal(ended[1].type, 'paragraph');
// A blank line then an unordered list is a new list, not a continuation of an ordered one.
assert.equal(blocks('1. One\n\n- Bullet').length, 2);
// Indented continuation lines stay with their item.
assert.deepEqual(blocks('- One\n  more of one\n- Two')[0].items, ['One\nmore of one', 'Two']);

// Tables: short separators and escaped pipes.
assert.equal(blocks('| A | B |\n| - | - |\n| 1 | 2 |')[0].type, 'table');
assert.equal(blocks('| A | B |\n|:--|--:|\n| 1 | 2 |')[0].type, 'table');
assert.deepEqual(blocks('| A | B |\n| --- | --- |\n| a \\| b | 2 |')[0].rows[0], ['a | b', '2']);
// A separator whose width differs from the header is not a table.
assert.equal(blocks('| A | B |\n| --- |\n| 1 | 2 |')[0].type, 'paragraph');
assert.equal(blocks('| A | B | C | D | E | F | G | H | I |\n|---|---|---|---|---|---|---|---|---|\n| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |')[0].type, 'paragraph');

// Blockquotes, unterminated fences and empty input.
assert.deepEqual(blocks('> Quoted\n> more')[0], { type: 'quote', text: 'Quoted\nmore' });
const open = blocks('Intro\n\n```js\nconst a = 1;\n');
assert.equal(open[1].type, 'code'); assert.equal(open[1].text, 'const a = 1;\n');
assert.deepEqual(blocks(''), []);
assert.deepEqual(blocks(undefined), []);

// ---- A tiny DOM double that tracks attributes, classes and derived text ----
class TextNode { constructor(text) { this.tag = '#text'; this.data = text; this.attrs = {}; this.children = []; } get textContent() { return this.data; } }
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.style = {}; this.className = ''; this._text = ''; this.hidden = false; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name]; }
}
global.document = { createElement: tag => new Node(tag), createElementNS: (_, tag) => new Node(tag), createTextNode: text => new TextNode(text) };
const walk = node => [node, ...(node.children || []).flatMap(walk)];
const fresh = () => new Node('div');
const find = (root, predicate) => walk(root).filter(predicate);

// ---- Unsafe input stays inert ----
let root = fresh();
render(root, '<img src=x onerror=alert(1)> [1]\n\n## Details\n\n**More**', [{ n: 1, url: 'javascript:alert(1)', title: 'Unsafe' }], true);
assert(!walk(root).some(n => n.tag === 'img' || n.tag === 'script' || n.tag === 'a'));
assert(walk(root).some(n => n.tag === 'button' && n.textContent === '[1]'));
assert(walk(root).some(n => n.tag === 'details'));
assert(walk(root).some(n => n.tag === 'strong' && n.textContent === 'More'));
assert(find(root, n => n.tag === '#text').some(n => n.data.includes('<img src=x onerror=alert(1)>')));

// ---- sourceLink: safe protocols only, rel, and no "undefined" title ----
const link = sourceLink({ url: 'https://example.com/a' }, 'Example');
assert.equal(link.tag, 'a'); assert.equal(link.rel, 'noopener noreferrer'); assert.equal(link.target, '_blank');
assert.equal(link.title, undefined);
assert.equal(sourceLink({ url: 'https://example.com', title: 'T' }, 'x').title, 'T');
assert.equal(sourceLink({ url: 'https://user:secret@example.com/' }, 'Creds').tag, '#text');
assert.equal(sourceLink({ url: 'ftp://example.com/file' }, 'Ftp').tag, '#text');
assert.equal(sourceLink({ url: 'not a url' }, 'Bad').tag, '#text');
assert.equal(sourceLink({}, 'None').tag, '#text');

// ---- Citations: inside bold, lists, ranges, unknown numbers ----
const sources = [{ n: 1, title: 'One' }, { n: 2, title: 'Two' }, { n: 3, title: 'Three' }];
root = fresh(); render(root, 'Claim **bold claim [1]** and *soft [2]* text.', sources, false);
const strong = find(root, n => n.tag === 'strong')[0];
assert(strong); assert(find(strong, n => n.tag === 'button' && n.attrs['data-citation-id'] === '1').length === 1);
const em = find(root, n => n.tag === 'em')[0];
assert(em); assert(find(em, n => n.tag === 'button' && n.attrs['data-citation-id'] === '2').length === 1);
root = fresh(); render(root, 'Both [1, 2] and range [1-3] plus [9].', sources, false);
const ids = find(root, n => n.tag === 'button').map(n => n.attrs['data-citation-id']);
assert.deepEqual(ids, ['1', '2', '1', '2', '3']);
assert(find(root, n => n.tag === '#text').some(n => n.data === '[9]'));
assert.equal(find(root, n => n.tag === 'button')[0].attrs['aria-label'], 'Source 1: One');
root = fresh(); render(root, 'Ignored [5] marker and snake_case_name.', sources, false);
assert.equal(find(root, n => n.tag === 'button').length, 0);
assert.equal(find(root, n => n.tag === 'em').length, 0);
assert.equal(root.textContent, 'Ignored [5] marker and snake_case_name.');
root = fresh(); render(root, '- Item [1]\n- Item [2]', sources, false);
assert.equal(find(root, n => n.tag === 'button').length, 2);

// ---- Lists render with start numbers ----
root = fresh(); render(root, '1. One\n\n2. Two\n\n3. Three', [], false);
assert.equal(find(root, n => n.tag === 'ol').length, 1);
assert.equal(find(root, n => n.tag === 'li').length, 3);
root = fresh(); render(root, '4. Four\n5. Five', [], false);
assert.equal(find(root, n => n.tag === 'ol')[0].start, 4);

// ---- Blockquote, italics ----
root = fresh(); render(root, '> A quote with *emphasis*', [], false);
assert(find(root, n => n.tag === 'blockquote').length === 1);
assert(find(root, n => n.tag === 'em' && n.textContent === 'emphasis').length === 1);

// ---- complete=false keeps Details as a plain heading; streaming never collapses ----
root = fresh(); render(root, '## Details\n\nStill writing', [], false);
assert.equal(find(root, n => n.tag === 'details').length, 0);
assert.equal(find(root, n => n.tag === 'h3').length, 1);
root = fresh(); render(root, '## Details\n\nDone', [], true);
assert.equal(find(root, n => n.tag === 'details').length, 1);
assert.equal(find(find(root, n => n.tag === 'details')[0], n => n.tag === 'p').length, 1);

// ---- Unterminated fence while streaming renders as code, not raw fence text ----
root = fresh(); render(root, 'Try:\n\n```js\nconst x = 1;', [], false);
assert.equal(find(root, n => n.className === 'answer-code').length, 1);
assert(find(root, n => n.tag === 'code').some(n => n.textContent === 'const x = 1;'));

// ---- Tables: unique labels, chart toggle semantics, chart accessibility ----
const twoTables = '| Year | Users |\n| --- | --- |\n| 2024 | 10 [1] |\n| 2025 | 20 [1] |\n\n| Name | Note |\n| --- | --- |\n| a | b |';
root = fresh(); render(root, twoTables, [{ n: 1 }], true);
const regions = find(root, n => n.attrs.role === 'region');
assert.equal(regions.length, 2);
assert.notEqual(regions[0].attrs['aria-label'], regions[1].attrs['aria-label']);
assert(regions[0].attrs['aria-label'].startsWith('Table 1'));
const toggle = find(root, n => n.tag === 'button' && n.textContent === 'View chart')[0];
assert(toggle); assert.equal(toggle.attrs['aria-pressed'], 'false');
assert(find(root, n => n.className === 'chart-fill').length === 2);
const chart = find(root, n => n.className === 'answer-chart')[0];
assert.notEqual(chart.attrs.role, 'img');
assert.equal(chart.attrs.role, 'group');
assert(find(chart, n => n.tag === 'button' && n.attrs['data-citation-id'] === '1').length === 2);
assert(find(chart, n => n.className === 'chart-track').every(n => n.attrs['aria-hidden'] === 'true'));
assert.equal(chart.hidden, true);
toggle.onclick();
assert.equal(chart.hidden, false); assert.equal(toggle.attrs['aria-pressed'], 'true');
assert.equal(toggle.textContent, 'View chart');
toggle.onclick();
assert.equal(chart.hidden, true); assert.equal(toggle.attrs['aria-pressed'], 'false');
// No chart while the answer is still streaming.
root = fresh(); render(root, twoTables, [{ n: 1 }], false);
assert.equal(find(root, n => n.className === 'answer-chart').length, 0);

// ---- Market card ----
const market = (overrides = {}, chart = true) => ({
  n: 1, content_type: 'market_ticker', url: 'https://api.exchange.coinbase.com/products/SOL-USD/ticker',
  market: { symbol: 'SOL', name: 'Solana', price: '$116.83', observed_at: 1790650800, venue: 'Coinbase Exchange', ...overrides },
  ...(chart ? { chart: { kind: 'price_series', unit: 'USD', captured_at: 1790650800, points: [[1790643600, 115], [1790647200, 116.83]] } } : {})
});
const quote = 'Solana’s last traded price on Coinbase Exchange was **$116.83 USD** at 2026-09-29 03:00:00 UTC. [1]\n\nPrices change continuously.';
root = fresh(); render(root, quote, [market()], true);
assert(find(root, n => n.className === 'market-card').length === 1);
assert(find(root, n => n.className === 'market-price' && n.textContent === '$116.83').length === 1);
assert(find(root, n => n.tag === 'polyline').length === 1);
assert(!find(root, n => n.tag === 'p').some(n => n.textContent.includes('last traded price on Coinbase')));
assert(find(root, n => n.tag === 'p').some(n => n.textContent === 'Prices change continuously.'));
// The dedupe is not anchored to a fixed phrase, but a different first paragraph is kept.
root = fresh(); render(root, 'The last traded price for SOL was $116.83 right now. [1]\n\nMore.', [market()], true);
assert(find(root, n => n.className === 'market-card').length === 1);
assert(!find(root, n => n.tag === 'p').some(n => n.textContent.includes('last traded price')));
root = fresh(); render(root, 'Solana is a blockchain. [1]\n\nMore.', [market()], true);
assert(find(root, n => n.tag === 'p').some(n => n.textContent.startsWith('Solana is a blockchain')));
// Card is only shown once complete.
root = fresh(); render(root, quote, [market()], false);
assert.equal(find(root, n => n.className === 'market-card').length, 0);
// Rejection paths: no card, so the quote paragraph stays.
for (const bad of [{ symbol: 'DOGE' }, { price: '116.83' }, { price: '$116.8' }, { price: 116.83 }, { observed_at: 0 }, { observed_at: 4102444801 }, { observed_at: 1.5 }]) {
  root = fresh(); render(root, quote, [market(bad)], true);
  assert.equal(find(root, n => n.className === 'market-card').length, 0, JSON.stringify(bad));
  assert(find(root, n => n.tag === 'p').some(n => n.textContent.includes('last traded price')), JSON.stringify(bad));
}
// A card with an invalid chart says so instead of drawing one.
root = fresh(); render(root, quote, [market({}, false)], true);
assert.equal(find(root, n => n.tag === 'svg').length, 0);
assert(find(root, n => n.className === 'market-no-chart').length === 1);
// Chart validation: non-increasing timestamps, too few points, wrong unit.
const badChart = points => ({ ...market(), chart: { kind: 'price_series', unit: 'USD', captured_at: 1790650800, points } });
for (const points of [[[2, 1], [1, 2]], [[1, 1]], [[1, 0], [2, 1]], [[1, 1], [2, NaN]]]) {
  root = fresh(); render(root, 'x', [badChart(points)], true);
  assert.equal(find(root, n => n.tag === 'svg').length, 0, JSON.stringify(points));
}
root = fresh(); render(root, 'x', [{ ...market(), chart: { ...market().chart, unit: 'EUR' } }], true);
assert.equal(find(root, n => n.tag === 'svg').length, 0);
// Card source link must be a safe link.
root = fresh(); render(root, quote, [{ ...market(), url: 'https://user:pw@evil.example/' }], true);
assert.equal(find(root, n => n.tag === 'a').length, 0);
root = fresh(); render(root, quote, [market()], true);
const sourceAnchor = find(root, n => n.tag === 'a')[0];
assert.equal(sourceAnchor.rel, 'noopener noreferrer');
// Market chart alone (no card) when only the chart data is valid.
root = fresh(); render(root, 'A fresh quote. [1]', [{ n: 1, content_type: 'market_ticker', url: 'https://api.exchange.coinbase.com/products/BTC-USD/ticker',
  chart: { kind: 'price_series', unit: 'USD', captured_at: 1790000000, points: [[1789992800, 100], [1789996400, 105]] } }], true);
assert(find(root, n => n.tag === 'svg').length === 1);
assert(find(root, n => n.tag === 'polyline').length === 1);

console.log('Renderer parsing, disclosure and unsafe-link tests passed');
