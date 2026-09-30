/* Zearch core helpers: pure logic shared by app.js and the unit tests. No DOM access. */
(function (root) {
  'use strict';
  const RUN_ID = /^[a-f0-9]{32}$/;
  const ACTIVE = ['pending', 'streaming'];

  function isRunId(value) { return typeof value === 'string' && RUN_ID.test(value); }

  const VIEWS = ['library', 'knowledge', 'monitors', 'batches', 'overview'];
  /* '#r/<id>' opens a saved run; '#library', '#knowledge', '#monitors', '#batches' and '#overview' open a view.
     Empty or '#' is home. Anything else (for example an in-page anchor such as '#main') is ignored. */
  function parseRoute(hash) {
    const value = String(hash || '');
    const match = value.match(/^#r\/([a-f0-9]{32})$/);
    if (match) return { type: 'run', id: match[1] };
    const view = value.startsWith('#') ? value.slice(1) : '';
    if (VIEWS.includes(view)) return { type: 'view', view };
    return value === '' || value === '#' ? { type: 'home' } : { type: 'other' };
  }
  function routeHash(id) { return isRunId(id) ? '#r/' + id : ''; }
  function viewHash(view) { return VIEWS.includes(view) ? '#' + view : ''; }

  /* Reads a newline-delimited JSON stream. Flushes the decoder and the final unterminated line,
     and skips lines that are not valid JSON instead of aborting the whole stream. */
  async function readNdjson(reader, onEvent) {
    const decoder = new TextDecoder();
    let buffer = '', skipped = 0;
    const emit = raw => {
      const line = raw.trim();
      if (!line) return;
      let data;
      try { data = JSON.parse(line); } catch { skipped++; return; }
      onEvent(data);
    };
    const drain = () => {
      let at;
      while ((at = buffer.indexOf('\n')) >= 0) { const line = buffer.slice(0, at); buffer = buffer.slice(at + 1); emit(line); }
    };
    while (true) {
      const { value, done } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: !done });
      if (done) { buffer += decoder.decode(); break; }
      drain();
    }
    drain();
    emit(buffer);
    return { skipped };
  }

  function backoffDelay(attempt, options = {}) {
    const { base = 2000, factor = 1.5, max = 15000 } = options;
    return Math.min(max, Math.round(base * Math.pow(factor, Math.max(0, attempt))));
  }
  function shouldPoll(status) { return ACTIVE.includes(status); }

  function friendlyStatus(status) {
    if (status === 401 || status === 403) return 'Your session has expired. Reload the page and try again.';
    if (status === 404) return 'That item could not be found. It may have been deleted.';
    if (status === 413) return 'That is too large to send. Try something smaller.';
    if (status === 429) return 'Too many requests right now. Please wait a moment and try again.';
    if (status >= 500) return 'Zearch is having trouble right now. Please try again in a moment.';
    return 'Something went wrong. Please try again.';
  }
  function httpError(status, data) {
    const message = data && typeof data.error === 'string' && data.error ? data.error : friendlyStatus(status);
    const error = new Error(message); error.status = status; return error;
  }

  /* fetch + JSON with friendly errors for network failures, non-2xx responses and non-JSON bodies. */
  async function fetchJson(url, options, fetchImpl) {
    const run = fetchImpl || (root.fetch && root.fetch.bind(root));
    let response;
    try { response = await run(url, options); } catch (error) {
      if (error && error.name === 'AbortError') throw error;
      throw new Error('Could not reach Zearch. Check your connection and try again.');
    }
    let data = null;
    try { data = await response.json(); } catch {}
    if (!response.ok) throw httpError(response.status, data);
    if (data === null || typeof data !== 'object') throw new Error('Zearch returned an unexpected response. Please try again.');
    return data;
  }

  function newRequestId(cryptoImpl) {
    const source = cryptoImpl === undefined ? root.crypto : cryptoImpl;
    if (source && typeof source.randomUUID === 'function') return source.randomUUID();
    const bytes = new Uint8Array(16);
    if (source && typeof source.getRandomValues === 'function') source.getRandomValues(bytes);
    else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  }

  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
  }
  function truncate(text, length) {
    const value = String(text || '').replace(/\s+/g, ' ').trim();
    return value.length > length ? value.slice(0, length - 1).trimEnd() + '…' : value;
  }


  /* ---------- display helpers ---------- */
  const MODE_LABELS = { standard: 'Search', deep: 'Deep research', compare: 'Compare', scrape: 'Scrape', crawl: 'Crawl' };
  function modeLabel(mode) { return MODE_LABELS[mode] || MODE_LABELS.standard; }
  const isNum = value => typeof value === 'number' && Number.isFinite(value);
  function formatPercent(rate) { return isNum(rate) ? Math.round(Math.min(1, Math.max(0, rate)) * 100) + '%' : '—'; }
  function formatMs(ms) {
    if (!isNum(ms) || ms < 0) return '—';
    if (ms < 1000) return Math.round(ms) + ' ms';
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + ' s';
    const minutes = Math.floor(ms / 60000), seconds = Math.round((ms % 60000) / 1000);
    return seconds === 60 ? (minutes + 1) + ' min' : minutes + ' min ' + seconds + ' s';
  }
  function formatCost(usd) {
    if (!isNum(usd) || usd < 0) return '—';
    if (usd === 0) return '$0.00';
    return usd < 0.01 ? '$' + usd.toFixed(4) : '$' + usd.toFixed(2);
  }
  /* seconds since epoch (a millisecond value is also accepted). */
  function toSeconds(value) {
    if (isNum(value)) return value > 1e11 ? value / 1000 : value;
    const parsed = Date.parse(value); return Number.isFinite(parsed) ? parsed / 1000 : null;
  }
  function relativeTime(value, nowMs) {
    const then = toSeconds(value); if (then === null) return '';
    const seconds = Math.max(0, Math.round(((nowMs === undefined ? Date.now() : nowMs) / 1000) - then));
    if (seconds < 45) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return minutes + ' min ago';
    const hours = Math.round(minutes / 60);
    if (hours < 24) return hours + (hours === 1 ? ' hour ago' : ' hours ago');
    const days = Math.round(hours / 24);
    if (days < 30) return days === 1 ? 'yesterday' : days + ' days ago';
    const months = Math.round(days / 30);
    return months < 12 ? months + (months === 1 ? ' month ago' : ' months ago') : Math.round(months / 12) + ' yr ago';
  }
  const STATUS_LABELS = { complete: 'Complete', pending: 'Running', streaming: 'Running', interrupted: 'Interrupted', error: 'Error', redacted: 'Redacted' };
  function statusLabel(status) { return STATUS_LABELS[status] || 'Unknown'; }
  /* Tone drives the pill and dot colour; the label always carries the meaning as well. */
  function statusTone(status) {
    return status === 'complete' ? 'ok' : ACTIVE.includes(status) ? 'run' : status === 'interrupted' ? 'warn' : status === 'error' ? 'bad' : 'idle';
  }

  /* ---------- chart geometry (pure) ---------- */
  /* Share of each key in a {key: count} object, in the given key order. Empty when nothing was counted. */
  function segments(counts, keys) {
    const values = keys.map(key => Math.max(0, Number(counts && counts[key]) || 0));
    const total = values.reduce((a, b) => a + b, 0);
    if (!total) return [];
    return keys.map((key, index) => ({ key, count: values[index], share: values[index] / total }));
  }
  /* SVG polyline points for a small trend line. Needs at least two numeric values. */
  function sparkPoints(values, width, height, pad) {
    const list = (values || []).filter(isNum);
    if (list.length < 2) return '';
    const inset = pad === undefined ? 2 : pad, low = Math.min(...list), high = Math.max(...list), span = high - low || 1;
    return list.map((value, index) => {
      const x = inset + index * (width - inset * 2) / (list.length - 1);
      const y = high === low ? height / 2 : height - inset - (value - low) * (height - inset * 2) / span;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
  }
  /* Bar heights (0..1) against the busiest day. */
  function barHeights(daily) {
    const runs = (daily || []).map(item => Math.max(0, Number(item && item.runs) || 0)), top = Math.max(0, ...runs);
    return runs.map(value => (top ? value / top : 0));
  }

  /* ---------- insights: deterministic sentences from real stats, no model call ---------- */
  function plural(count, one, many) { return count + ' ' + (count === 1 ? one : many || one + 's'); }
  function insights(stats, limit) {
    const max = limit === undefined ? 3 : limit;
    if (!stats || !stats.totals || !stats.totals.runs) return [];
    const totals = stats.totals, measured = stats.measured || {}, out = [];
    if (isNum(stats.verified_rate) && measured.gates > 0) {
      out.push(formatPercent(stats.verified_rate) + ' of ' + plural(measured.gates, 'checked answer') + ' had direct evidence that passed Jev\u2019s check.');
    }
    const latency = stats.latency_ms || {};
    if (isNum(latency.p50) && measured.latency > 0) {
      out.push('Median research time was ' + formatMs(latency.p50) + (isNum(latency.p95) && measured.latency > 1 ? ', and 95% of runs finished within ' + formatMs(latency.p95) : '') +
        ', across ' + plural(measured.latency, 'timed run') + '.');
    }
    const gates = stats.gates || {};
    if (gates.abstain > 0) out.push(plural(gates.abstain, 'answer') + (gates.abstain === 1 ? ' was' : ' were') + ' withheld because the sources did not directly answer the question.');
    if (isNum(stats.fallback_rate) && stats.fallback_rate > 0) {
      out.push('In ' + formatPercent(stats.fallback_rate) + ' of completed answers the draft could not be fully supported, so Zearch showed the selected passage instead.');
    }
    const trouble = (totals.error || 0) + (totals.interrupted || 0);
    if (trouble > 0) out.push(plural(trouble, 'run') + ' ended in an error or was interrupted.');
    const modes = Object.entries(stats.by_mode || {}).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);
    if (modes.length) out.push(modeLabel(modes[0][0]) + ' was your most used mode: ' + modes[0][1] + ' of ' + plural(modes.reduce((n, [, c]) => n + c, 0), 'run') + '.');
    const tiers = stats.source_tiers || {}, tierTotal = (tiers.primary || 0) + (tiers.web || 0) + (tiers.private || 0);
    if (tierTotal > 0 && tiers.primary > 0) out.push(formatPercent(tiers.primary / tierTotal) + ' of ' + plural(tierTotal, 'cited source') + ' came from publisher domains that matched the topic.');
    return out.slice(0, Math.max(0, max));
  }

  /* ---------- activity table sorting ---------- */
  const SORT_KEYS = ['created', 'query', 'depth', 'status', 'total_ms', 'sources'];
  function sortActivity(rows, key, direction) {
    const list = Array.isArray(rows) ? rows.slice() : [];
    if (!SORT_KEYS.includes(key)) return list;
    const sign = direction === 'asc' ? 1 : -1;
    const value = row => { const v = row && row[key]; return v === undefined || v === null ? null : v; };
    return list.sort((a, b) => {
      const x = value(a), y = value(b);
      if (x === null && y === null) return 0;
      if (x === null) return 1;      // missing values always last
      if (y === null) return -1;
      const cmp = typeof x === 'string' || typeof y === 'string' ? String(x).localeCompare(String(y), undefined, { sensitivity: 'base' }) : x - y;
      return cmp * sign;
    });
  }

  /* ---------- command palette matching ---------- */
  /* Higher is better; -1 means no match. Every word must appear (substring), otherwise an in-order letter match is a weak fallback. */
  function paletteScore(text, needle) {
    const hay = String(text || '').toLowerCase(), query = String(needle || '').toLowerCase().trim();
    if (!query) return 1;
    const words = query.split(/\s+/);
    if (words.every(word => hay.includes(word))) {
      const first = hay.indexOf(words[0]);
      return 100 - Math.min(50, first) + (hay.startsWith(words[0]) ? 30 : 0) - Math.min(20, Math.floor(hay.length / 20));
    }
    const letters = query.replace(/\s+/g, ''); let at = 0;
    for (const ch of hay) if (ch === letters[at]) at++;
    return at === letters.length && letters.length >= 3 ? 10 : -1;
  }
  /* items: [{ label, keywords?, group?, rank? }]. Stable for equal scores, so the caller's order is the tiebreak. */
  function paletteFilter(items, needle, limit) {
    const scored = [];
    (items || []).forEach((item, index) => {
      const score = Math.max(paletteScore(item.label, needle), paletteScore((item.keywords || '') + ' ' + item.label, needle) - 5);
      if (score >= 0) scored.push({ item, score: score + (item.rank || 0), index });
    });
    scored.sort((a, b) => b.score - a.score || a.index - b.index);
    return scored.slice(0, limit || 30).map(entry => entry.item);
  }

  /* ---------- rail width, target URL, follow-ups, library filter ---------- */
  const RAIL_MIN = 224, RAIL_DEFAULT = 258;
  function railMaxWidth(viewport) { return Math.max(RAIL_MIN, Math.floor((Number(viewport) || 0) * 0.2)); }
  /* Rail width in px: at least 224, at most 20% of the viewport (never below the minimum). Non-numbers give the default. */
  function clampRailWidth(value, viewport) {
    const n = Number(value), max = railMaxWidth(viewport);
    return Math.min(max, Math.max(RAIL_MIN, Number.isFinite(n) ? Math.round(n) : RAIL_DEFAULT));
  }
  /* Public HTTPS page only. The server stays authoritative; this only explains the problem early. */
  function validateTargetUrl(value) {
    const text = String(value || '').trim();
    if (!text) return { ok: false, empty: true, reason: '' };
    if (text.length > 2048) return { ok: false, reason: 'That address is too long.' };
    let url; try { url = new URL(text); } catch { return { ok: false, reason: 'Enter a full address that starts with https://' }; }
    if (url.protocol !== 'https:') return { ok: false, reason: 'Only https:// pages can be read.' };
    if (url.username || url.password) return { ok: false, reason: 'Remove the username and password from the address.' };
    const host = url.hostname.toLowerCase();
    if (!host.includes('.') || host === 'localhost' || host.endsWith('.local') || host.endsWith('.internal') || /^\d+\.\d+\.\d+\.\d+$/.test(host) || host.startsWith('['))
      return { ok: false, reason: 'Use a public website address, not a local or IP address.' };
    return { ok: true, reason: '' };
  }
  /* Optional backend suggestions (usage.followups): up to 3 short unique strings, otherwise nothing. */
  function followupSuggestions(usage) {
    const list = usage && Array.isArray(usage.followups) ? usage.followups : [], out = [];
    for (const item of list) {
      if (typeof item !== 'string') continue;
      const text = item.replace(/\s+/g, ' ').trim();
      if (!text || text.length > 160 || out.some(x => x.toLowerCase() === text.toLowerCase())) continue;
      out.push(text); if (out.length === 3) break;
    }
    return out;
  }
  /* Library filter. Rows without a depth only match the "all" mode filter. */
  function filterLibrary(items, options = {}) {
    const needle = String(options.needle || '').trim().toLowerCase(), mode = options.mode || 'all', status = options.status || 'all';
    return (items || []).filter(item => {
      if (needle && !String(item.query || '').toLowerCase().includes(needle)) return false;
      if (mode !== 'all' && item.depth !== mode) return false;
      if (status === 'running') return ACTIVE.includes(item.status);
      return status === 'all' || item.status === status;
    });
  }
  /* Whether any row carries a depth, so the UI knows if the mode filter can work. */
  const hasDepth = items => (items || []).some(item => item && typeof item.depth === 'string' && item.depth);

  /* ---------- theme ---------- */
  const THEMES = ['system', 'light', 'dark'];
  function normalizeTheme(value) { return THEMES.includes(value) ? value : 'system'; }
  /* Sets data-theme (absent means follow the system) and data-motion. Safe with blocked storage. */
  function applyPreferences(doc, storage) {
    let theme = 'system', motion = 'system';
    try { theme = normalizeTheme(storage.getItem('zearch:theme')); motion = storage.getItem('zearch:motion') === 'reduce' ? 'reduce' : 'system'; } catch {}
    if (theme === 'system') doc.documentElement.removeAttribute('data-theme'); else doc.documentElement.setAttribute('data-theme', theme);
    if (motion === 'reduce') doc.documentElement.setAttribute('data-motion', 'reduce'); else doc.documentElement.removeAttribute('data-motion');
    return { theme, motion };
  }

  const api = { VIEWS, isRunId, parseRoute, routeHash, viewHash, modeLabel, formatPercent, formatMs, formatCost, toSeconds, relativeTime, statusLabel, statusTone, segments, sparkPoints, barHeights, insights, sortActivity, paletteScore, paletteFilter, normalizeTheme, applyPreferences, RAIL_MIN, RAIL_DEFAULT, railMaxWidth, clampRailWidth, validateTargetUrl, followupSuggestions, filterLibrary, hasDepth, readNdjson, backoffDelay, shouldPoll, friendlyStatus, httpError, fetchJson, newRequestId, hostOf, truncate };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {
    root.ZearchCore = api;
    // Loaded in <head> before first paint so the saved theme never flashes. Storage may be blocked.
    if (root.document) { try { applyPreferences(root.document, root.localStorage); } catch {} }
  }
})(typeof window === 'undefined' ? globalThis : window);
