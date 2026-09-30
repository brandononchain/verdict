/* Deliberately small Markdown subset. All untrusted text uses text nodes. */
(function (root) {
  'use strict';
  const LIST_ITEM = /^\s*([-*]|\d+[.)])\s+(.*)$/;
  const SEPARATOR = /^:?-+:?$/;
  const cells = row => row.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '').split(/(?<!\\)\|/).map(s => s.trim().replace(/\\\|/g, '|'));
  const isSeparator = (line, width) => {
    if (!line || !line.includes('|')) return false;
    const parts = cells(line);
    return parts.length === width && parts.every(c => SEPARATOR.test(c));
  };
  function blocks(text) {
    const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
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
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
        result.push({ type: 'quote', text: quote.join('\n') }); continue;
      }
      const first = line.match(LIST_ITEM);
      if (first) {
        const ordered = /^\s*\d/.test(line), items = [], start = ordered ? Number(line.match(/^\s*(\d+)/)[1]) : 1;
        const kind = l => { const m = l.match(LIST_ITEM); return m ? (/^\s*\d/.test(l) ? 'ol' : 'ul') : null; };
        while (i < lines.length) {
          const current = lines[i], m = current.match(LIST_ITEM);
          if (m && kind(current) === (ordered ? 'ol' : 'ul')) { items.push(m[2]); i++; continue; }
          if (!current.trim()) {
            // A blank line does not end a list when the next non-blank line is another item of the same kind.
            let j = i; while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && kind(lines[j]) === (ordered ? 'ol' : 'ul')) { i = j; continue; }
            break;
          }
          if (/^\s{2,}\S/.test(current) && items.length) { items[items.length - 1] += '\n' + current.trim(); i++; continue; }
          break;
        }
        result.push({ type: 'list', ordered, start, items }); continue;
      }
      if (line.includes('|') && i + 1 < lines.length && isSeparator(lines[i + 1], cells(line).length)) {
        const head = cells(line), rows = []; i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
        if (head.length <= 8 && rows.length <= 30 && rows.every(r => r.length === head.length)) result.push({ type: 'table', head, rows });
        else result.push({ type: 'paragraph', text: [line, ...rows.map(r => r.join(' | '))].join('\n') });
        continue;
      }
      const content = [line]; i++;
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*>|\s*([-*]|\d+[.)])\s)/.test(lines[i])) {
        if (lines[i].includes('|') && i + 1 < lines.length && isSeparator(lines[i + 1], cells(lines[i]).length)) break;
        content.push(lines[i++]);
      }
      result.push({ type: 'paragraph', text: content.join('\n') });
    }
    return result;
  }
  function sourceLink(source, text) {
    let url;
    try { url = new URL(source && source.url); } catch { return document.createTextNode(text); }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return document.createTextNode(text);
    const a = document.createElement('a'); a.className = 'citation'; a.textContent = text;
    a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.referrerPolicy = 'no-referrer';
    if (source.title) a.title = source.title;
    return a;
  }
  /* "[1]", "[1, 2]" and "[1-3]" all become one button per source number. */
  function citationNumbers(marker) {
    const numbers = [];
    for (const part of marker.slice(1, -1).split(',')) {
      const range = part.trim().match(/^(\d+)\s*[–-]\s*(\d+)$/);
      if (range) {
        const from = Number(range[1]), to = Number(range[2]);
        if (to >= from && to - from < 20) for (let n = from; n <= to; n++) numbers.push(n);
        else return [];
      } else if (/^\d+$/.test(part.trim())) numbers.push(Number(part.trim()));
      else return [];
    }
    return numbers;
  }
  const INLINE = /(\[\d+(?:\s*[,–-]\s*\d+)*\]|\*\*[^*]+\*\*|`[^`]+`|(?<![*\w])\*[^*\s](?:[^*]*[^*\s])?\*(?!\*)|(?<![\w])_[^_\s](?:[^_]*[^_\s])?_(?![\w]))/g;
  function inline(node, text, sources) {
    for (const part of text.split(INLINE)) {
      if (!part) continue;
      if (part.startsWith('[') && part.endsWith(']')) {
        const numbers = citationNumbers(part), found = numbers.map(n => sources.find(s => s.n === n));
        if (numbers.length && found.some(Boolean)) {
          numbers.forEach((n, index) => {
            const source = found[index];
            if (!source) { node.append(document.createTextNode(`[${n}]`)); return; }
            const citation = document.createElement('button'); citation.type = 'button'; citation.className = 'citation citation-button';
            citation.textContent = `[${n}]`; citation.title = 'Show source ' + n;
            citation.setAttribute('aria-label', `Source ${n}${source.title ? ': ' + source.title : ''}`);
            citation.setAttribute('data-citation-id', String(n)); node.append(citation);
          });
          continue;
        }
      }
      if (/^\*\*.+\*\*$/.test(part)) {
        const strong = document.createElement('strong'); inline(strong, part.slice(2, -2), sources); node.append(strong);
      } else if (/^`.+`$/.test(part)) {
        const code = document.createElement('code'); code.textContent = part.slice(1, -1); node.append(code);
      } else if (/^\*[^*].*\*$/.test(part) || /^_[^_].*_$/.test(part)) {
        const em = document.createElement('em'); inline(em, part.slice(1, -1), sources); node.append(em);
      } else node.append(document.createTextNode(part));
    }
  }
  function chartData(block, sources) {
    if (block.head.length !== 2 || block.rows.length < 2 || block.rows.length > 20) return null;
    const allowed = new Set(sources.map(s => s.n));
    const rows = block.rows.map(row => {
      const match = typeof row[1] === 'string' && row[1].match(/^([+-]?(?:\d+(?:,\d{3})*|\d+)(?:\.\d+)?)\s*(%|[a-zA-Z]{0,6})?\s*\[(\d+)\]$/);
      if (!match || !allowed.has(Number(match[3])) || row[0].length > 80) return null;
      const value = Number(match[1].replaceAll(',', ''));
      if (!Number.isFinite(value) || value < 0 || value > 1e12) return null;
      return { label: row[0], value, unit: match[2] || '', source: Number(match[3]), display: row[1] };
    });
    if (rows.some(row => !row) || new Set(rows.map(row => row.unit)).size !== 1) return null;
    return rows;
  }
  function marketChart(source) {
    const chart = source?.chart, points = chart?.points;
    if (chart?.kind !== 'price_series' || chart.unit !== 'USD' ||
        !Number.isInteger(chart.captured_at) || chart.captured_at < 1 || chart.captured_at > 4102444800 ||
        !Array.isArray(points) || points.length < 2 || points.length > 30 ||
        !points.every((p, i) => Array.isArray(p) && p.length === 2 &&
          Number.isInteger(p[0]) && Number.isFinite(p[1]) && p[1] > 0 &&
          (i === 0 || p[0] > points[i - 1][0]))) return null;
    const prices = points.map(p => p[1]), low = Math.min(...prices), high = Math.max(...prices);
    const spread = Math.max(high - low, high * .001);
    const coords = points.map((p, i) => `${20 + i * 560 / (points.length - 1)},${160 - (p[1] - low + spread * .08) * 135 / (spread * 1.16)}`).join(' ');
    const figure = document.createElement('figure'); figure.className = 'market-figure';
    const symbol = source.market?.symbol || 'Market';
    const heading = document.createElement('figcaption'); heading.textContent = `${symbol}-USD · 24-hour price context`;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 600 180'); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${symbol}-USD hourly Coinbase Exchange closes from $${low.toLocaleString()} to $${high.toLocaleString()} USD. Snapshot, not a streaming chart.`);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', coords); line.setAttribute('fill', 'none');
    line.setAttribute('stroke', '#dedede'); line.setAttribute('stroke-width', '2.5');
    line.setAttribute('stroke-linejoin', 'round'); line.setAttribute('stroke-linecap', 'round');
    svg.append(line);
    const foot = document.createElement('small');
    foot.textContent = `Coinbase Exchange hourly closes · snapshot ${new Date(chart.captured_at * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC · last trade above may differ from the last hourly close.`;
    figure.append(heading, svg, foot); return figure;
  }
  function marketCard(source) {
    const market = source?.market;
    if (!market || !['BTC','ETH','SOL','XRP'].includes(market.symbol) ||
        typeof market.price !== 'string' || !/^\$\d{1,3}(?:,\d{3})*(?:\.\d{2})$/.test(market.price) ||
        !Number.isInteger(market.observed_at) || market.observed_at < 1 || market.observed_at > 4102444800) return null;
    const card = document.createElement('section'); card.className = 'market-card';
    card.setAttribute('aria-label', `${market.name || market.symbol} price snapshot`);
    const head = document.createElement('div'); head.className = 'market-card-head';
    const title = document.createElement('span'); title.textContent = `${market.name || market.symbol} · ${market.symbol}/USD`;
    const venue = document.createElement('span'); venue.textContent = 'Coinbase Exchange';
    head.append(title, venue);
    const price = document.createElement('div'); price.className = 'market-price'; price.textContent = market.price;
    const time = document.createElement('p'); time.className = 'market-time';
    time.textContent = `Last trade · ${new Date(market.observed_at * 1000).toISOString().replace('T', ' ').slice(0, 19)} UTC`;
    card.append(head, price, time);
    const visual = marketChart(source);
    if (visual) card.append(visual);
    else { const unavailable = document.createElement('p'); unavailable.className = 'market-no-chart';
      unavailable.textContent = '24-hour chart unavailable for this snapshot.'; card.append(unavailable); }
    const foot = document.createElement('p'); foot.className = 'market-disclaimer';
    foot.textContent = 'Venue snapshot, not a consolidated or streaming price. ';
    foot.append(sourceLink(source, 'Open price source')); card.append(foot);
    return card;
  }
  /* The server-rendered quote card replaces the model's own restatement of the same quote. */
  function isQuoteParagraph(block, market) {
    return Boolean(block && block.type === 'paragraph' && market && typeof market.price === 'string' &&
      /last traded price/i.test(block.text) && block.text.includes(market.price));
  }
  function render(node, text, sources = [], complete = false) {
    node.replaceChildren(); let target = node, tableCount = 0, quote = null;
    if (complete) {
      const market = sources.find(s => s.content_type === 'market_ticker');
      if (market) { const card = marketCard(market); if (card) { node.append(card); quote = market.market; }
        else { const visual = marketChart(market); if (visual) node.append(visual); } }
    }
    for (const [index, block] of blocks(text).entries()) {
      if (index === 0 && quote && isQuoteParagraph(block, quote)) continue;
      let item;
      if (block.type === 'heading') {
        if (complete && /^details\s*$/i.test(block.text)) {
          const details = document.createElement('details'), summary = document.createElement('summary');
          details.className = 'answer-details'; summary.textContent = 'Explore the details'; details.append(summary); node.append(details); target = details; continue;
        }
        item = document.createElement('h' + Math.min(4, block.level + 1)); inline(item, block.text, sources);
      } else if (block.type === 'list') {
        item = document.createElement(block.ordered ? 'ol' : 'ul');
        if (block.ordered && block.start !== 1) item.start = block.start;
        for (const text of block.items) { const li = document.createElement('li'); inline(li, text, sources); item.append(li); }
      } else if (block.type === 'quote') {
        item = document.createElement('blockquote'); inline(item, block.text, sources);
      } else if (block.type === 'code') {
        item = document.createElement('div'); item.className = 'answer-code';
        const label = document.createElement('span'); label.className = 'answer-code-language'; label.textContent = block.language || 'Code';
        const pre = document.createElement('pre'), code = document.createElement('code');
        code.textContent = block.text; pre.append(code); item.append(label, pre);
      } else if (block.type === 'table') {
        tableCount++;
        item = document.createElement('div'); item.className = 'answer-table'; item.tabIndex = 0; item.setAttribute('role', 'region');
        item.setAttribute('aria-label', `Table ${tableCount}: ${block.head.join(', ').slice(0, 80)}`);
        const table = document.createElement('table'), head = document.createElement('thead'), body = document.createElement('tbody');
        const tr = document.createElement('tr'); for (const text of block.head) { const th = document.createElement('th'); th.scope = 'col'; inline(th, text, sources); tr.append(th); } head.append(tr);
        for (const row of block.rows) { const tr = document.createElement('tr'); for (const text of row) { const td = document.createElement('td'); inline(td, text, sources); tr.append(td); } body.append(tr); }
        table.append(head, body); item.append(table);
        if (complete) {
          const data = chartData(block, sources);
          if (data) {
            const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'chart-toggle'; toggle.textContent = 'View chart';
            toggle.setAttribute('aria-pressed', 'false');
            const chart = document.createElement('div'); chart.className = 'answer-chart'; chart.hidden = true;
            chart.setAttribute('role', 'group'); chart.setAttribute('aria-label', `${block.head[1]} by ${block.head[0]}`);
            const maximum = Math.max(...data.map(row => row.value), 1);
            for (const row of data) {
              const bar = document.createElement('div'); bar.className = 'chart-row';
              const name = document.createElement('span'); name.textContent = row.label;
              const track = document.createElement('div'); track.className = 'chart-track'; track.setAttribute('aria-hidden', 'true');
              const fill = document.createElement('div'); fill.className = 'chart-fill'; fill.style.width = `${row.value / maximum * 100}%`;
              track.append(fill);
              const value = document.createElement('span'); inline(value, row.display, sources);
              bar.append(name, track, value); chart.append(bar);
            }
            toggle.onclick = () => {
              chart.hidden = !chart.hidden; table.hidden = !table.hidden;
              toggle.setAttribute('aria-pressed', String(!chart.hidden));
            };
            item.prepend(toggle); item.append(chart);
          }
        }
      } else { item = document.createElement('p'); inline(item, block.text, sources); }
      target.append(item);
    }
  }
  const api = { blocks, chartData, marketChart, render, sourceLink };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ZearchRender = api;
})(typeof window === 'undefined' ? {} : window);
