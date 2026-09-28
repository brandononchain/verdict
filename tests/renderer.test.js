const assert = require('node:assert/strict');
const { blocks, chartData, render } = require('../renderer.js');
assert.equal(blocks('# Answer\n\nText\n\n## Details')[2].text, 'Details');
assert.deepEqual(blocks('- One\n- Two')[0].items, ['One','Two']);
assert.equal(blocks('| A | B |\n| --- | --- |\n| 1 | 2 |')[0].type, 'table');
assert.equal(blocks('| A | B |\n| --- | --- |\n| 1 |')[0].type, 'paragraph');
assert.equal(blocks('```js\n<script>alert(1)</script>\n```')[0].type, 'code');
assert.equal(blocks('```python\nprint(1)\n```')[0].language, 'python');
const numeric = blocks('| Year | Users |\n| --- | --- |\n| 2024 | 10 [1] |\n| 2025 | 20 [1] |')[0];
assert.equal(chartData(numeric, [{n:1}]).length, 2);
assert.equal(chartData(numeric, [{n:2}]), null);
assert.equal(chartData(blocks('| A | B |\n| --- | --- |\n| x | 10 |\n| y | 20 |')[0], [{n:1}]), null);
// Tiny DOM double checks safe node creation and progressive disclosure.
class Node {
  constructor(tag) { this.tag=tag; this.children=[]; this.textContent=''; this.style={}; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute() {}
}
global.document={createElement:tag=>new Node(tag),createTextNode:text=>({tag:'#text',textContent:text})};
const root=new Node('div');
render(root,'<img src=x onerror=alert(1)> [1]\n\n## Details\n\n**More**',[{n:1,url:'javascript:alert(1)',title:'Unsafe'}],true);
const walk=node=>[node,...(node.children||[]).flatMap(walk)];
assert(!walk(root).some(n=>n.tag==='img'||n.tag==='script'||n.tag==='a'));
assert(walk(root).some(n=>n.tag==='button'&&n.textContent==='[1]'));
assert(walk(root).some(n=>n.tag==='details'));
assert(walk(root).some(n=>n.tag==='strong'&&n.textContent==='More'));
render(root, '| Year | Users |\n| --- | --- |\n| 2024 | 10 [1] |\n| 2025 | 20 [1] |', [{n:1}], true);
assert(walk(root).some(n=>n.tag==='button'&&n.textContent==='View chart'));
assert(walk(root).some(n=>n.tag==='div'&&n.className==='chart-fill'));
console.log('Renderer parsing, disclosure and unsafe-link tests passed');
