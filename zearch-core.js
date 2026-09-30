/* Zearch core helpers: pure logic shared by app.js and the unit tests. No DOM access. */
(function (root) {
  'use strict';
  const RUN_ID = /^[a-f0-9]{32}$/;
  const ACTIVE = ['pending', 'streaming'];

  function isRunId(value) { return typeof value === 'string' && RUN_ID.test(value); }

  /* '#r/<id>' opens a saved run. Empty or '#' is home. Anything else (for example an in-page anchor) is ignored. */
  function parseRoute(hash) {
    const value = String(hash || '');
    const match = value.match(/^#r\/([a-f0-9]{32})$/);
    if (match) return { type: 'run', id: match[1] };
    return value === '' || value === '#' ? { type: 'home' } : { type: 'other' };
  }
  function routeHash(id) { return isRunId(id) ? '#r/' + id : ''; }

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

  const api = { isRunId, parseRoute, routeHash, readNdjson, backoffDelay, shouldPoll, friendlyStatus, httpError, fetchJson, newRequestId, hostOf, truncate };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ZearchCore = api;
})(typeof window === 'undefined' ? globalThis : window);
