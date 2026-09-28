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
        result.push({ type: 'code', language: line.slice(3).trim().replace(/[^a-zA-Z0-9+#.-]/g, '').slice(0, 24), text: content.join('\n') }); continue;
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
      if (source) {
        const citation = document.createElement('button'); citation.type = 'button'; citation.className = 'citation citation-button';
        citation.textContent = part; citation.title = 'Open captured evidence';
        citation.setAttribute('data-citation-id', String(source.n)); node.append(citation);
      } else if (/^\*\*.+\*\*$/.test(part)) {
        const strong = document.createElement('strong'); strong.textContent = part.slice(2, -2); node.append(strong);
      } else if (/^`.+`$/.test(part)) {
        const code = document.createElement('code'); code.textContent = part.slice(1, -1); node.append(code);
      } else node.append(document.createTextNode(part));
    }
  }
  function chartData(block, sources) {
    if (block.head.length !== 2 || block.rows.length < 2 || block.rows.length > 20) return null;
    const allowed = new Set(sources.map(s => s.n));
    const rows = block.rows.map(row => {
      const match = row[1].match(/^([+-]?(?:\d+(?:,\d{3})*|\d+)(?:\.\d+)?)\s*(%|[a-zA-Z]{0,6})?\s*\[(\d+)\]$/);
      if (!match || !allowed.has(Number(match[3])) || row[0].length > 80) return null;
      const value = Number(match[1].replaceAll(',', ''));
      if (!Number.isFinite(value) || value < 0 || value > 1e12) return null;
      return { label: row[0], value, unit: match[2] || '', source: Number(match[3]), display: row[1] };
    });
    if (rows.some(row => !row) || new Set(rows.map(row => row.unit)).size !== 1) return null;
    return rows;
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
        item = document.createElement('div'); item.className = 'answer-code';
        const label = document.createElement('span'); label.className = 'answer-code-language'; label.textContent = block.language || 'Code';
        const pre = document.createElement('pre'), code = document.createElement('code');
        code.textContent = block.text; pre.append(code); item.append(label, pre);
      } else if (block.type === 'table') {
        item = document.createElement('div'); item.className = 'answer-table'; item.tabIndex = 0; item.setAttribute('role', 'region'); item.setAttribute('aria-label', 'Comparison table');
        const table = document.createElement('table'), head = document.createElement('thead'), body = document.createElement('tbody');
        const tr = document.createElement('tr'); for (const text of block.head) { const th = document.createElement('th'); th.scope = 'col'; inline(th, text, sources); tr.append(th); } head.append(tr);
        for (const row of block.rows) { const tr = document.createElement('tr'); for (const text of row) { const td = document.createElement('td'); inline(td, text, sources); tr.append(td); } body.append(tr); }
        table.append(head, body); item.append(table);
        if (complete) {
          const data = chartData(block, sources);
          if (data) {
            const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'chart-toggle'; toggle.textContent = 'View chart';
            const chart = document.createElement('div'); chart.className = 'answer-chart'; chart.hidden = true;
            chart.setAttribute('role', 'img'); chart.setAttribute('aria-label', `${block.head[1]} by ${block.head[0]}`);
            const maximum = Math.max(...data.map(row => row.value), 1);
            for (const row of data) {
              const bar = document.createElement('div'); bar.className = 'chart-row';
              const name = document.createElement('span'); name.textContent = row.label;
              const track = document.createElement('div'); track.className = 'chart-track';
              const fill = document.createElement('div'); fill.className = 'chart-fill'; fill.style.width = `${row.value / maximum * 100}%`;
              track.append(fill);
              const value = document.createElement('span'); inline(value, row.display, sources);
              bar.append(name, track, value); chart.append(bar);
            }
            toggle.onclick = () => { chart.hidden = !chart.hidden; table.hidden = !table.hidden; toggle.textContent = chart.hidden ? 'View chart' : 'View table'; };
            item.prepend(toggle); item.append(chart);
          }
        }
      } else { item = document.createElement('p'); inline(item, block.text, sources); }
      target.append(item);
    }
  }
  const api = { blocks, chartData, render, sourceLink };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ZearchRender = api;
})(typeof window === 'undefined' ? {} : window);
