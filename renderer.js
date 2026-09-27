/* Deliberately small Markdown subset. All untrusted text uses text nodes. */
(function (root) {
  'use strict';
  function blocks(text) {
    const lines = text.replace(/\r\n/g, '\n').split('\n');
    const result = [];
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^```/.test(line)) {
        const content = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) content.push(lines[i++]);
        if (i < lines.length) i++;
        result.push({ type: 'code', text: content.join('\n') }); continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) { result.push({ type: 'heading', level: heading[1].length, text: heading[2] }); i++; continue; }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), items = [];
        const pattern = ordered ? /^\s*\d+\.\s+(.+)$/ : /^\s*[-*]\s+(.+)$/;
        while (i < lines.length && pattern.test(lines[i])) items.push(lines[i++].replace(pattern, '$1'));
        result.push({ type: 'list', ordered, items }); continue;
      }
      const cells = row => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(s => s.trim());
      if (line.includes('|') && i + 1 < lines.length && cells(lines[i + 1]).every(c => /^:?-{3,}:?$/.test(c))) {
        const head = cells(line), rows = []; i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
        if (head.length <= 8 && rows.length <= 30 && rows.every(r => r.length === head.length)) result.push({ type: 'table', head, rows });
        else result.push({ type: 'paragraph', text: [line, ...rows.map(r => r.join(' | '))].join('\n') });
        continue;
      }
      const content = [line]; i++;
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*]|\d+\.)\s)/.test(lines[i])) {
        if (lines[i].includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{3}/.test(lines[i + 1])) break;
        content.push(lines[i++]);
      }
      result.push({ type: 'paragraph', text: content.join('\n') });
    }
    return result;
  }
  function sourceLink(source, text) {
    let url;
    try { url = new URL(source.url); } catch { return document.createTextNode(text); }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return document.createTextNode(text);
    const a = document.createElement('a'); a.className = 'citation'; a.textContent = text;
    a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = source.title;
    return a;
  }
  function inline(node, text, sources) {
    for (const part of text.split(/(\[\d+\]|\*\*[^*]+\*\*|`[^`]+`)/g)) {
      const marker = part.match(/^\[(\d+)\]$/), source = marker && sources.find(s => s.n === Number(marker[1]));
      if (source && source.url) node.append(sourceLink(source, part));
      else if (source) {
        const detail = document.createElement('span'); detail.className = 'citation'; detail.textContent = part;
        detail.title = 'Private note: ' + source.title; node.append(detail);
      } else if (/^\*\*.+\*\*$/.test(part)) {
        const strong = document.createElement('strong'); strong.textContent = part.slice(2, -2); node.append(strong);
      } else if (/^`.+`$/.test(part)) {
        const code = document.createElement('code'); code.textContent = part.slice(1, -1); node.append(code);
      } else node.append(document.createTextNode(part));
    }
  }
  function render(node, text, sources = [], complete = false) {
    node.replaceChildren(); let target = node;
    for (const block of blocks(text)) {
      let item;
      if (block.type === 'heading') {
        if (complete && /^details\s*$/i.test(block.text)) {
          const details = document.createElement('details'), summary = document.createElement('summary');
          details.className = 'answer-details'; summary.textContent = 'Explore the details'; details.append(summary); node.append(details); target = details; continue;
        }
        item = document.createElement('h' + Math.min(4, block.level + 1)); inline(item, block.text, sources);
      } else if (block.type === 'list') {
        item = document.createElement(block.ordered ? 'ol' : 'ul');
        for (const text of block.items) { const li = document.createElement('li'); inline(li, text, sources); item.append(li); }
      } else if (block.type === 'code') {
        item = document.createElement('pre'); const code = document.createElement('code'); code.textContent = block.text; item.append(code);
      } else if (block.type === 'table') {
        item = document.createElement('div'); item.className = 'answer-table'; item.tabIndex = 0; item.setAttribute('role', 'region'); item.setAttribute('aria-label', 'Comparison table');
        const table = document.createElement('table'), head = document.createElement('thead'), body = document.createElement('tbody');
        const tr = document.createElement('tr'); for (const text of block.head) { const th = document.createElement('th'); th.scope = 'col'; inline(th, text, sources); tr.append(th); } head.append(tr);
        for (const row of block.rows) { const tr = document.createElement('tr'); for (const text of row) { const td = document.createElement('td'); inline(td, text, sources); tr.append(td); } body.append(tr); }
        table.append(head, body); item.append(table);
      } else { item = document.createElement('p'); inline(item, block.text, sources); }
      target.append(item);
    }
  }
  const api = { blocks, render, sourceLink };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ZearchRender = api;
})(typeof window === 'undefined' ? {} : window);
