/* Zearch: private research, knowledge and discovery. No client provider keys. */
(() => {
  'use strict';
  const core = window.ZearchCore;
  const $ = id => document.getElementById(id);
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    node.className = cls || ''; node.textContent = text || ''; return node;
  };
  const form = $('composer'), query = $('query'), thread = $('thread'), empty = $('empty');
  const fine = document.querySelector('.fineprint'), dock = document.querySelector('.dock-inner');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const coarse = window.matchMedia('(pointer: coarse)');
  const mobile = window.matchMedia('(max-width: 680px)');
  const DEFAULT_TITLE = document.title;
  const MODE_HELP = {
    standard: 'Searches the web and answers with cited sources.',
    deep: 'Reads more sources for a fuller answer. Takes longer.',
    compare: 'Compares options side by side, with sources for each.',
    scrape: 'Reads one public page and extracts its facts.',
    crawl: 'Reads up to five pages of one public site.'
  };
  const STARTERS = [
    ['Compare', 'Compare PostgreSQL and MySQL for a small web app', 'compare'],
    ['Explain', 'How do heat pumps work and when do they make sense?', 'standard'],
    ['Look up', 'What changed in the latest stable Python release?', 'standard']
  ];

  let parent = null, parentLabel = '', active = null, available = false, version = 0, recent = [];
  let workspaceReady = false, workspaceLoaded = false, sessionReady = false, workspaceSeq = 0, shownId = null;
  let availabilityMessage = 'Checking research availability…';
  let workspaceData = { notes: [], documents: [], investigations: [], batches: [], history: [] };
  let accountData = { enabled: false, account: null };
  const shownIds = new Set();
  let hidden = new Set();
  const notice = make('p', 'research-notice', availabilityMessage);
  notice.setAttribute('role', 'status'); empty.append(notice);
  try {
    recent = JSON.parse(localStorage.getItem('zearch:research-history') || '[]')
      .filter(x => x && core.isRunId(x.id) && typeof x.query === 'string').slice(0, 100);
    hidden = new Set(JSON.parse(localStorage.getItem('zearch:history-hidden') || '[]').filter(core.isRunId));
  } catch {}

  /* ---------- small helpers ---------- */
  const errorText = error => (error && error.message) || 'Something went wrong. Please try again.';
  const timeoutSignal = ms => (typeof AbortSignal !== 'undefined' && AbortSignal.timeout ? AbortSignal.timeout(ms) : undefined);
  const openDialog = () => document.querySelector('dialog[open]');
  const announce = text => { const node = $('announcer'); node.textContent = ''; setTimeout(() => { node.textContent = text; }, 40); };
  const scrollBehavior = () => (reduceMotion.matches ? 'auto' : 'smooth');
  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return; } catch {}
    }
    const area = document.createElement('textarea');
    area.value = text; area.setAttribute('readonly', ''); area.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.append(area); area.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch {}
    area.remove();
    if (!ok) throw Error('Copying is not available here. Select the text and copy it manually.');
  }

  /* ---------- toasts: rendered inside the open dialog so they are visible and announced ---------- */
  let toastNode = null, toastTimer = 0, toastLeft = 0, toastStarted = 0;
  function dismissToast() { clearTimeout(toastTimer); toastTimer = 0; if (toastNode) toastNode.remove(); toastNode = null; }
  function armToast(ms) {
    clearTimeout(toastTimer); toastLeft = ms; toastStarted = Date.now();
    toastTimer = setTimeout(dismissToast, ms);
  }
  function toast(text, options = {}) {
    dismissToast();
    const dialog = openDialog(), host = dialog ? dialog.querySelector('.toast-region') : $('toast-region');
    if (!host) return;
    const node = make('div', options.error ? 'toast toast-error' : 'toast');
    if (options.error) node.setAttribute('role', 'alert');
    const close = make('button', 'toast-close'); close.type = 'button'; close.setAttribute('aria-label', 'Dismiss message');
    close.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>';
    close.onclick = dismissToast;
    node.append(make('span', 'toast-text', text), close);
    host.append(node); toastNode = node;
    if (!options.error) {
      armToast(5000);
      const pause = () => { clearTimeout(toastTimer); toastLeft = Math.max(1500, toastLeft - (Date.now() - toastStarted)); };
      node.addEventListener('mouseenter', pause); node.addEventListener('focusin', pause);
      node.addEventListener('mouseleave', () => armToast(toastLeft)); node.addEventListener('focusout', () => armToast(toastLeft));
    }
  }
  const fail = error => toast(errorText(error), { error: true });

  /* ---------- mobile rail ---------- */
  let railOpen = false, railFocus = null;
  function setRail(open) {
    const wasOpen = railOpen; railOpen = Boolean(open) && mobile.matches;
    $('shell').classList.toggle('rail-open', railOpen);
    $('menu-btn').setAttribute('aria-expanded', String(railOpen));
    $('rail').inert = mobile.matches && !railOpen;
    $('main').inert = railOpen;
    if (railOpen && !wasOpen) { railFocus = document.activeElement; $('rail-close').focus(); }
    else if (!railOpen && wasOpen) { const back = railFocus && railFocus.isConnected ? railFocus : $('menu-btn'); railFocus = null; back.focus(); }
  }
  const closeRail = () => setRail(false);
  mobile.addEventListener('change', () => setRail(false));
  $('rail').addEventListener('keydown', event => {
    if (event.key !== 'Tab' || !railOpen) return;
    const nodes = [...$('rail').querySelectorAll('a[href], button:not([disabled])')].filter(node => node.offsetParent !== null);
    if (!nodes.length) return;
    const first = nodes[0], last = nodes.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  /* ---------- composer ---------- */
  function focusQuery() {
    if (openDialog() || coarse.matches) return;
    const at = document.activeElement;
    if (!at || at === document.body || form.contains(at)) query.focus();
  }
  function syncChip() {
    $('followup').hidden = !parent;
    $('followup-text').textContent = 'Continuing from previous answer';
    $('followup').title = parentLabel ? 'Follow-up to: ' + parentLabel : '';
  }
  function setParent(id, label) { parent = id || null; parentLabel = id ? core.truncate(label, 90) : ''; syncChip(); }
  function controls() {
    const mode = $('depth').value, collecting = mode === 'scrape' || mode === 'crawl';
    $('target-url').hidden = !collecting;
    $('target-url').disabled = Boolean(active) || !collecting;
    $('target-url').placeholder = mode === 'crawl' ? 'https://example.com (up to five pages)' : 'https://example.com/page';
    query.placeholder = collecting ? 'What should Zearch extract? (optional)' : 'Ask a question or compare options…';
    if (collecting) $('use-knowledge').checked = false;
    $('use-knowledge').closest('label').hidden = collecting;
    $('decide').disabled = !active && (!sessionReady || (collecting ? !$('target-url').value.trim() : !query.value.trim()));
    const action = mode === 'scrape' ? 'Scrape' : mode === 'crawl' ? 'Crawl' : 'Search';
    $('decide').querySelector('span').textContent = active ? 'Stop' : action;
    $('decide').setAttribute('aria-label', active ? 'Stop research' : action);
    $('decide').dataset.busy = String(Boolean(active));
    $('depth').disabled = Boolean(active); $('use-knowledge').disabled = Boolean(active) || !workspaceReady || collecting;
    $('mode-help').textContent = MODE_HELP[mode] || '';
    const allowance = workspaceData.allowance;
    if (allowance && Number.isFinite(allowance.daily_limit) && Number.isFinite(allowance.used)) {
      const left = Math.max(0, allowance.daily_limit - allowance.used);
      $('allowance').textContent = `${left} of ${allowance.daily_limit} runs left today`;
    } else $('allowance').textContent = '';
    const length = query.value.length, counter = $('char-count');
    counter.hidden = length < 1600; counter.textContent = `${length} / ${query.maxLength}`;
    query.style.height = 'auto'; query.style.height = Math.min(query.scrollHeight, 180) + 'px';
  }

  /* ---------- recent searches ---------- */
  function persistHistory() {
    try {
      localStorage.setItem('zearch:research-history', JSON.stringify(recent));
      localStorage.setItem('zearch:history-hidden', JSON.stringify([...hidden].slice(-500)));
    } catch {}
    listHistory();
  }
  function listHistory() {
    const list = $('history'); list.replaceChildren();
    const items = recent.filter(x => !hidden.has(x.id));
    for (const item of items) {
      const li = make('li'), control = make('button', 'h-q', item.query);
      control.type = 'button'; control.title = item.query;
      if (item.id === shownId) control.setAttribute('aria-current', 'page');
      control.onclick = () => openRun(item.id);
      li.append(control); list.append(li);
    }
    if (!items.length) {
      const li = make('li', 'h-empty', 'Your searches will appear here.'); list.append(li);
    }
  }
  function remember(run) {
    hidden.delete(run.id);
    recent = [{ id: run.id, query: run.query }, ...recent.filter(x => x.id !== run.id)].slice(0, 100);
    persistHistory();
  }

  /* ---------- views and routing ---------- */
  function setTitle(text) {
    const short = text ? core.truncate(text, 70) : '';
    document.title = short ? `${short} — Zearch` : DEFAULT_TITLE;
    $('crumb-title').textContent = short || 'New search';
    const heading = $('thread-title'); heading.hidden = !short; heading.textContent = short;
  }
  function showThread() {
    empty.classList.add('hidden'); form.classList.remove('home-composer'); dock.append(form, fine);
  }
  function showHomeLayout() {
    empty.classList.remove('hidden'); empty.insertBefore(form, notice); empty.insertBefore(fine, notice); form.classList.add('home-composer');
  }
  function home(options = {}) {
    if (active) return;
    version++; setParent(null); shownId = null; shownIds.clear();
    thread.replaceChildren(); showHomeLayout(); notice.textContent = availabilityMessage;
    if (options.push) { if (location.hash) window.history.pushState(null, '', location.pathname + location.search); }
    else if (location.hash) window.history.replaceState(null, '', location.pathname + location.search);
    setTitle(null); query.value = ''; $('target-url').value = ''; controls(); listHistory(); setRail(false);
    if (options.focus !== false) focusQuery();
  }
  function openRun(id) {
    if (active) { toast('Stop the current research before opening another answer.'); return; }
    closeRail(); const dialog = openDialog(); if (dialog) dialog.close();
    if (location.hash !== '#r/' + id) window.history.pushState(null, '', '#r/' + id);
    route(true);
  }
  async function loadRecord(id) {
    return core.fetchJson('/api/research?id=' + id);
  }
  async function route(force) {
    await sessionPromise;
    const target = core.parseRoute(location.hash);
    if (active) {
      // Back/forward during a run: keep the URL in step with what is on screen.
      const current = active.runId ? '#r/' + active.runId : '';
      if (location.hash !== current) {
        window.history.replaceState(null, '', current || location.pathname + location.search);
        if (target.type !== 'other') toast('Stop the current research before opening another answer.');
      }
      return;
    }
    if (target.type === 'other') return;
    if (target.type === 'home') { if (shownId || thread.childElementCount || force === true) home(); return; }
    if (force !== true && target.id === shownId) return;
    const revision = ++version;
    try {
      const records = [], seen = new Set(); let next = target.id;
      while (next && records.length < 20 && !seen.has(next)) {
        seen.add(next);
        const record = await loadRecord(next);
        if (revision !== version) return;
        records.unshift(record); next = record.parent_id;
      }
      if (revision !== version) return;
      thread.replaceChildren(); showThread(); shownIds.clear(); records.forEach(record => shownIds.add(record.id));
      const views = records.map(record => turn(record)), last = records.at(-1);
      shownId = target.id; setTitle(last?.query || ''); listHistory();
      setParent(last?.status === 'complete' ? target.id : null, last?.query || '');
      if (next) toast('Showing the latest 20 answers.');
      const view = views.at(-1);
      if (view && core.shouldPoll(last.status)) poll(view, revision);
      $('feed').scrollTop = 0;
    } catch (error) { if (revision === version) { home({ focus: false }); toast(errorText(error), { error: true }); } }
  }
  /* Poll a run that was still working when it was opened, with capped backoff. */
  function poll(view, revision) {
    const started = Date.now(); let attempt = 0;
    const tick = async () => {
      if (revision !== version || !view.root.isConnected) return;
      try {
        const record = await loadRecord(view.run.id);
        if (revision !== version) return;
        Object.assign(view.run, record); view.update();
        if (!core.shouldPoll(record.status)) {
          if (record.status === 'complete') { setParent(record.id, record.query); announce('Answer ready'); }
          return;
        }
      } catch {}
      if (Date.now() - started > 10 * 60 * 1000) { view.run.error = 'This is taking longer than expected. Reload to check again.'; view.update(); return; }
      setTimeout(tick, core.backoffDelay(attempt++));
    };
    setTimeout(tick, core.backoffDelay(attempt++));
  }

  /* ---------- API helpers ---------- */
  async function api(action, fields = {}) {
    const data = await core.fetchJson('/api/workspace', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...fields })
    });
    return data.result;
  }
  const accountApi = (action, fields = {}) => core.fetchJson('/api/account', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...fields }) });
  function button(label, callback, cls = 'ghost-btn', accessibleName) {
    const node = make('button', cls, label); node.type = 'button';
    if (accessibleName) node.setAttribute('aria-label', accessibleName);
    node.onclick = async () => {
      node.disabled = true; node.setAttribute('aria-busy', 'true');
      try { await callback(); } catch (error) { fail(error); }
      finally { node.disabled = false; node.removeAttribute('aria-busy'); }
    };
    return node;
  }

  /* ---------- account ---------- */
  let sentTo = '', resendTimer = 0;
  function setCooldown(seconds) {
    const resend = $('account-resend'); clearInterval(resendTimer);
    let left = seconds;
    const paint = () => { resend.disabled = left > 0; resend.textContent = left > 0 ? `Resend code in ${left}s` : 'Resend code'; };
    paint();
    if (left > 0) resendTimer = setInterval(() => { left--; paint(); if (left <= 0) clearInterval(resendTimer); }, 1000);
  }
  function showCodeForm(email) {
    sentTo = email;
    $('account-sent').textContent = email ? `We sent an eight-digit code to ${email}. It can take a minute to arrive.` : 'Enter the email address and the code you received.';
    $('account-email-form').hidden = true; $('account-code-form').hidden = false; $('account-code').focus();
  }
  function showEmailForm() {
    sentTo = ''; clearInterval(resendTimer);
    $('account-code-form').hidden = true; $('account-email-form').hidden = false; $('account-email').focus();
  }
  async function loadAccount() {
    try {
      const data = await core.fetchJson('/api/account');
      accountData = data;
      $('account-section').hidden = !data.enabled;
      $('workspace-identity').textContent = data.account ? `Signed in as ${data.account.email}. Your research follows this account across devices.` :
        data.enabled ? 'Private to this browser until you sign in. You can move its research into your account.' :
        'Private to this browser session. Sign-in is not available on this deployment.';
      $('account-status').textContent = data.account ? 'Signed in' : sentTo ? '' : 'Sign in with an email code to keep your research across devices.';
      $('account-email-form').hidden = Boolean(data.account) || Boolean(sentTo);
      $('account-code-form').hidden = Boolean(data.account) || !sentTo;
      $('claim-workspace').hidden = !data.account || !data.claim_available;
      $('account-signout').hidden = !data.account;
      $('account-delete').hidden = !data.account;
    } catch { $('account-section').hidden = true; }
  }

  /* ---------- citation preview ---------- */
  const pop = $('cite-pop');
  function showPreview(citation, source) {
    if (!source) return;
    pop.replaceChildren(make('strong', '', source.title || core.hostOf(source.url) || 'Private note'));
    const host = core.hostOf(source.url);
    if (host) pop.append(make('small', '', host));
    if (source.excerpt) pop.append(make('p', '', core.truncate(source.excerpt, 200)));
    pop.hidden = false;
    const box = citation.getBoundingClientRect(), width = Math.min(340, window.innerWidth - 24);
    pop.style.width = width + 'px';
    const left = Math.min(Math.max(12, box.left + box.width / 2 - width / 2), window.innerWidth - width - 12);
    const height = pop.offsetHeight, above = box.top - height - 8 > 8;
    pop.style.left = left + 'px'; pop.style.top = (above ? box.top - height - 8 : box.bottom + 8) + 'px';
    citation.setAttribute('aria-describedby', 'cite-pop');
  }
  function hidePreview() {
    pop.hidden = true;
    for (const node of document.querySelectorAll('[aria-describedby="cite-pop"]')) node.removeAttribute('aria-describedby');
  }

  /* ---------- one answer ---------- */
  function turn(run) {
    const root = make('article', 'turn'), question = make('div', 'user-message');
    const response = make('section', 'assistant-message'), status = make('p', 'research-status');
    const body = make('div', 'research-prose'), details = make('details', 'research-evidence');
    const collecting = ['scrape', 'crawl'].includes(run.depth);
    const dashboard = make('div', 'collection-dashboard'), dashboardHead = make('header', 'collection-head');
    const dashboardTitle = make('div', 'collection-title'), dashboardTarget = make('p', 'collection-target');
    const metrics = make('div', 'collection-metrics'), tabs = make('div', 'collection-tabs');
    const panels = {}, tabButtons = {}, labels = ['Overview', 'Pages', 'Media', 'Contacts', 'Data'];
    const uid = Math.random().toString(36).slice(2, 8), myVersion = version;
    let selectedTab = 'Overview';
    let visual = null, visualConfigured = false, visualLoaded = false, visualAttempt = 0, visualTimer = 0;
    dashboardTitle.append(make('span', 'collection-eyebrow', run.depth === 'crawl' ? 'SITE CRAWL' : 'PAGE EXTRACTION'),
      make('h2', '', 'Collection'));
    dashboardHead.append(dashboardTitle, dashboardTarget);
    tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Collection views');
    for (const label of labels) {
      const key = label.toLowerCase(), tab = make('button', 'collection-tab', label);
      tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.id = `tab-${key}-${uid}`;
      const panel = make('section', 'collection-panel'); panel.id = `panel-${key}-${uid}`; panel.tabIndex = 0;
      panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id); tab.setAttribute('aria-controls', panel.id);
      tab.onclick = () => selectTab(label);
      tab.onkeydown = event => {
        const at = labels.indexOf(selectedTab);
        const next = event.key === 'ArrowRight' ? labels[(at + 1) % labels.length] : event.key === 'ArrowLeft' ? labels[(at - 1 + labels.length) % labels.length] :
          event.key === 'Home' ? labels[0] : event.key === 'End' ? labels.at(-1) : null;
        if (!next) return;
        event.preventDefault(); selectTab(next); tabButtons[next].focus();
      };
      tabs.append(tab); panels[label] = panel; tabButtons[label] = tab;
    }
    function selectTab(label) {
      selectedTab = label;
      for (const name of labels) {
        tabButtons[name].setAttribute('aria-selected', String(name === label));
        tabButtons[name].tabIndex = name === label ? 0 : -1;
        panels[name].hidden = name !== label;
      }
    }
    panels.Overview.append(body);
    dashboard.append(dashboardHead, metrics, tabs, ...labels.map(label => panels[label]));
    selectTab('Overview');
    const summary = make('summary'), sources = make('ol'), actions = make('div', 'turn-actions');
    const trace = make('details', 'research-trace'), traceTitle = make('summary', '', 'How this answer was checked');
    const traceBody = make('p'); trace.append(traceTitle, traceBody); trace.hidden = true;
    question.append(make('div', 'user-bubble', run.query));
    if (run.target_url) question.append(make('small', 'source-meta', run.target_url));
    response.setAttribute('aria-label', 'Zearch answer'); status.setAttribute('role', 'status');
    details.append(summary, sources);

    /* Re-render the prose without losing which <details> the reader opened. */
    function renderBody(complete) {
      const open = [...body.querySelectorAll('details')].map(node => node.open);
      ZearchRender.render(body, run.answer || '', run.sources || [], complete);
      body.querySelectorAll('details').forEach((node, index) => { if (open[index]) node.open = true; });
    }
    body.addEventListener('click', event => {
      const citation = event.target.closest('button[data-citation-id]');
      if (!citation) return;
      const card = [...sources.children].find(item => item.dataset.sourceId === citation.dataset.citationId);
      if (!card) return;
      hidePreview();
      if (collecting) selectTab('Overview');
      details.open = true;
      const capture = card.querySelector('details');
      if (capture) capture.open = true;
      card.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
      card.classList.remove('is-target'); void card.offsetWidth; card.classList.add('is-target');
      (capture?.querySelector('summary') || card).focus({ preventScroll: true });
    });
    const sourceFor = citation => (run.sources || []).find(s => String(s.n) === citation.dataset.citationId);
    body.addEventListener('mouseover', event => { const c = event.target.closest('button[data-citation-id]'); if (c) showPreview(c, sourceFor(c)); });
    body.addEventListener('focusin', event => { const c = event.target.closest('button[data-citation-id]'); if (c) showPreview(c, sourceFor(c)); });
    body.addEventListener('mouseout', event => { if (event.target.closest('button[data-citation-id]')) hidePreview(); });
    body.addEventListener('focusout', event => { if (event.target.closest('button[data-citation-id]')) hidePreview(); });

    const copy = button('Copy answer', async () => { await copyText(run.answer || ''); toast('Answer copied'); });
    const link = button('Copy link', async () => {
      await copyText(location.origin + location.pathname + core.routeHash(run.id)); toast('Link copied');
    });
    const again = button('Regenerate', () => {
      if (active) throw Error('Wait for the current research to finish.');
      startRun({ question: run.query, mode: run.depth || 'standard', targetUrl: run.target_url || null, parentId: run.parent_id || null });
    });
    const save = button('Save', async () => {
      await api('save_investigation', { id: run.id }); toast('Investigation saved'); await loadWorkspace(false);
    });
    const monitor = button('Monitor daily', async () => {
      await api('monitor_collection', { id: run.id }); monitor.hidden = true; toast('Daily monitor saved'); await loadWorkspace(false);
    });
    const exportMenu = make('details', 'export-menu');
    const exportOptions = make('div', 'export-options'), exportSummary = make('summary', '', 'Export');
    exportMenu.append(exportSummary, exportOptions);
    for (const [format, label] of [['pdf', 'PDF'], ['txt', 'Text'], ...(collecting ? [['json', 'Data JSON'], ['csv', 'Inventory CSV']] : [])]) {
      exportOptions.append(button(label, async () => {
        if (!core.isRunId(run.id)) throw Error('Save the answer before exporting it.');
        const result = await fetch(`/api/artifact?id=${run.id}&format=${format}`).catch(() => { throw Error('Could not reach Zearch. Check your connection and try again.'); });
        if (!result.ok) {
          let message = ''; try { message = (await result.json()).error; } catch {}
          throw Error(message || 'Export failed. Please try again in a moment.');
        }
        saveBlob(await result.blob(), `zearch-${run.id}.${format}`); exportMenu.open = false; exportSummary.focus();
      }));
    }
    exportMenu.addEventListener('keydown', event => {
      const items = [...exportOptions.querySelectorAll('button:not([disabled])')];
      if (event.key === 'Escape' && exportMenu.open) { event.stopPropagation(); exportMenu.open = false; exportSummary.focus(); }
      else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && items.length) {
        event.preventDefault(); if (!exportMenu.open) exportMenu.open = true;
        const at = items.indexOf(document.activeElement), step = event.key === 'ArrowDown' ? 1 : -1;
        items[at < 0 ? (step > 0 ? 0 : items.length - 1) : (at + step + items.length) % items.length].focus();
      }
    });
    actions.setAttribute('aria-label', 'Answer actions');
    actions.append(copy, link, again, exportMenu, save, monitor);
    response.append(status, collecting ? dashboard : body, actions, details, trace); root.append(question, response); thread.append(root);

    function sourceCard(source) {
      const li = make('li', 'evidence-card');
      li.dataset.sourceId = String(source.n); li.tabIndex = -1;
      const head = make('div', 'evidence-head'), host = core.hostOf(source.url);
      head.append(make('span', 'evidence-num', String(source.n)));
      head.append(source.url ? ZearchRender.sourceLink(source, source.title || host || source.url) :
        make('span', 'evidence-private', (source.title || 'Untitled') + (source.document_id ? ' · Private document' : ' · Private note')));
      li.append(head);
      if (host) li.append(make('small', 'evidence-domain', host));
      if (source.excerpt) {
        const excerpt = make('p', 'evidence-excerpt', source.excerpt);
        li.append(excerpt);
        if (source.excerpt.length > 180) {
          const more = make('button', 'link-btn', 'Show more'); more.type = 'button'; more.setAttribute('aria-expanded', 'false');
          more.onclick = () => {
            const open = excerpt.classList.toggle('expanded');
            more.textContent = open ? 'Show less' : 'Show more'; more.setAttribute('aria-expanded', String(open));
          };
          li.append(more);
        }
      }
      const provenance = [];
      if (source.source_tier === 'primary') provenance.push('Matched publisher domain');
      if (source.published_date && source.published_date_provenance === 'provider_metadata') provenance.push(`Reported publication: ${source.published_date}`);
      if (Number.isInteger(source.retrieved_at) && source.retrieved_at > 0 && source.retrieved_at < 4102444800) {
        provenance.push(`Page captured ${new Date(source.retrieved_at * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC`);
      }
      if (provenance.length) li.append(make('small', 'source-meta', provenance.join(' · ')));
      if (typeof source.text === 'string' && source.text) {
        const capture = make('details', 'source-capture');
        capture.append(make('summary', '', 'Captured evidence'));
        if (/^[a-f0-9]{64}$/.test(source.source_version_id || '')) capture.append(make('small', 'source-meta', `Capture ${source.source_version_id}`));
        const excerpt = make('pre', 'source-snapshot');
        const span = source.evidence_span;
        if (Array.isArray(span) && span.length === 2 && Number.isInteger(span[0]) && Number.isInteger(span[1]) &&
            span[0] >= 0 && span[1] > span[0] && span[1] <= source.text.length) {
          excerpt.append(document.createTextNode(source.text.slice(0, span[0])));
          excerpt.append(make('mark', '', source.text.slice(span[0], span[1])));
          excerpt.append(document.createTextNode(source.text.slice(span[1])));
        } else excerpt.textContent = source.text;
        capture.append(excerpt); li.append(capture);
      }
      return li;
    }
    const STATUS_TEXT = {
      pending: 'Research in progress', streaming: 'Research in progress',
      redacted: 'This answer was redacted because a note or document it used was deleted.',
      error: 'This answer could not be completed.', interrupted: 'This answer is incomplete.'
    };
    function update() {
      renderBody(run.status === 'complete');
      const message = run.error || run.usage?.citation_warnings?.join(' ') || STATUS_TEXT[run.status] || (run.status === 'complete' ? '' : 'Partial answer');
      status.textContent = message;
      status.dataset.tone = ['error', 'interrupted'].includes(run.status) || run.error ? 'error' : run.status === 'redacted' ? 'notice' : '';
      const finished = ['complete', 'error', 'interrupted'].includes(run.status);
      actions.hidden = !finished;
      copy.hidden = !run.answer; again.hidden = !finished || collecting && !run.target_url; again.textContent = run.status === 'complete' ? 'Regenerate' : 'Retry';
      link.hidden = !core.isRunId(run.id);
      exportMenu.hidden = run.status !== 'complete';
      save.hidden = run.status !== 'complete' || collecting; sources.replaceChildren();
      monitor.hidden = !collecting || run.status !== 'complete';
      for (const source of run.sources || []) sources.append(sourceCard(source));
      details.hidden = !sources.children.length;
      summary.textContent = `View ${sources.children.length} ${sources.children.length === 1 ? 'source' : 'sources'}`;
      if (collecting) renderCollection();
      if (collecting && run.status === 'complete' && core.isRunId(run.id) && !visualLoaded) {
        visualLoaded = true; loadVisual();
      }
      if (run.usage?.queries || run.usage?.judgment || run.usage?.market_data) {
        trace.hidden = false;
        const lines = [];
        if (run.usage.extract_calls || run.usage.crawl_calls) lines.push(`${run.usage.crawl_pages || sources.children.length} pages captured · ${run.usage.failed_pages || 0} unavailable`);
        else if (run.usage.queries) lines.push(`${run.usage.search_calls} web searches · ${run.usage.failed_searches || 0} unavailable`);
        if (run.usage.market_data) lines.push(`Market data: ${run.usage.market_data}`);
        if (run.usage.judgment) lines.push(run.usage.judgment.gate === 'answer' ? 'Relevant evidence found' :
          run.usage.judgment.gate === 'review' ? 'Sources need a closer look' : 'Direct evidence was limited');
        if (run.usage.writer_attempts > 1) lines.push('The first draft was revised and checked again');
        if (run.usage.scrape_calls || run.usage.cache_hits) lines.push(`Page extracts: ${run.usage.scrape_calls || 0} new · ${run.usage.cache_hits || 0} reused`);
        if (run.usage.draft_fallback_reason) lines.push('Some draft claims could not be supported');
        if (run.usage.total_ms != null) lines.push(`Research time: ${(run.usage.total_ms / 1000).toFixed(1)}s`);
        if (Number.isInteger(run.estimated_cost)) lines.push(`Estimated cost: $${(run.estimated_cost / 1000000).toFixed(6)}`);
        traceBody.textContent = lines.join('\n');
      }
    }
    /* Visual capture: load once, then follow a queued or running capture with capped backoff. */
    async function loadVisual() {
      try {
        const data = await core.fetchJson('/api/collection?id=' + run.id);
        visual = data.visual; visualConfigured = Boolean(data.configured); renderCollection();
      } catch {}
      scheduleVisual();
    }
    function scheduleVisual() {
      clearTimeout(visualTimer);
      if (!['queued', 'running'].includes(visual?.status) || myVersion !== version || !root.isConnected) return;
      if (visualAttempt > 40) return;
      visualTimer = setTimeout(async () => {
        try {
          const data = await core.fetchJson('/api/collection?id=' + run.id);
          visual = data.visual; renderCollection();
        } catch {}
        scheduleVisual();
      }, core.backoffDelay(visualAttempt++));
    }
    function renderCollection() {
      const pages = (run.sources || []).filter(source => source.url);
      const media = [], emails = new Map();
      for (const page of pages) {
        for (const item of page.assets || []) {
          if (media.length < 80 && item?.url && !media.some(existing => existing.url === item.url)) media.push(item);
        }
        for (const email of page.emails || []) if (emails.size < 50 && typeof email === 'string' && !emails.has(email)) emails.set(email, page);
      }
      let domain = run.target_url || pages[0]?.url || '';
      try { domain = new URL(domain).hostname; } catch { domain = 'Captured website'; }
      dashboardTarget.textContent = `${domain} · ${run.status === 'complete' ? 'Captured collection' : 'Collecting evidence'}`;
      metrics.replaceChildren();
      for (const [value, label] of [[pages.length, 'Pages'], [media.length, 'Media'], [emails.size, 'Contacts']]) {
        const metric = make('button', 'collection-metric');
        metric.type = 'button'; metric.setAttribute('aria-label', `${value} ${label.toLowerCase()}. Show ${label.toLowerCase()}`);
        metric.onclick = () => selectTab(label);
        metric.append(make('strong', '', String(value)), make('span', '', label)); metrics.append(metric);
      }
      tabButtons.Pages.textContent = `Pages ${pages.length}`;
      tabButtons.Media.textContent = `Media ${media.length}`;
      tabButtons.Contacts.textContent = `Contacts ${emails.size}`;
      const pagePanel = panels.Pages, mediaPanel = panels.Media, contactPanel = panels.Contacts, dataPanel = panels.Data;
      pagePanel.replaceChildren(); mediaPanel.replaceChildren(); contactPanel.replaceChildren(); dataPanel.replaceChildren();
      pagePanel.append(make('h3', 'collection-section-title', 'Captured pages'));
      if (!pages.length) pagePanel.append(make('p', 'collection-empty', 'Pages will appear here as they are captured.'));
      for (const page of pages) {
        const card = make('article', 'collection-page'), top = make('div', 'collection-page-top');
        top.append(make('span', 'collection-index', String(page.n || pages.indexOf(page) + 1).padStart(2, '0')),
          ZearchRender.sourceLink(page, page.title || page.url));
        card.append(top);
        if (page.description) card.append(make('p', '', page.description));
        else if (page.excerpt) card.append(make('p', '', page.excerpt.slice(0, 210)));
        card.append(make('small', 'collection-url', page.url));
        const tags = [];
        if (page.assets?.length) tags.push(`${page.assets.length} media`);
        if (page.emails?.length) tags.push(`${page.emails.length} contacts`);
        if (page.retrieved_at) tags.push(`Captured ${new Date(page.retrieved_at * 1000).toLocaleString()}`);
        if (tags.length) card.append(make('small', 'collection-page-meta', tags.join(' · ')));
        if (page.text) {
          const captured = make('details', 'collection-page-capture');
          captured.append(make('summary', '', 'Read captured page'), make('pre', '', page.text));
          card.append(captured);
        }
        pagePanel.append(card);
      }
      mediaPanel.append(make('h3', 'collection-section-title', 'Images & video'));
      if (!media.length) mediaPanel.append(make('p', 'collection-empty', 'No media links were found in these pages.'));
      const gallery = make('div', 'collection-gallery');
      const kindOf = item => (['image', 'logo', 'favicon'].includes(item.kind) ? 'Images' : item.kind === 'video' ? 'Video' : 'Other');
      const kinds = [...new Set(media.map(kindOf))];
      if (kinds.length > 1) {
        const filters = make('div', 'collection-filters');
        filters.setAttribute('role', 'group'); filters.setAttribute('aria-label', 'Filter media');
        const filterButtons = [];
        for (const kind of ['All', ...kinds]) {
          const filter = button(kind, () => {
            for (const card of gallery.children) card.hidden = kind !== 'All' && card.dataset.kind !== kind;
            for (const item of filterButtons) item.setAttribute('aria-pressed', String(item === filter));
          }, 'filter-btn');
          filter.setAttribute('aria-pressed', String(kind === 'All'));
          filterButtons.push(filter); filters.append(filter);
        }
        mediaPanel.append(filters);
      }
      for (const item of media) {
        const card = make('article', 'collection-media-card');
        card.dataset.kind = kindOf(item);
        const frame = make('div', 'collection-media-frame');
        if (kindOf(item) === 'Images' && /^https?:\/\//i.test(item.url)) {
          // Images are third-party content: load them only when asked.
          const load = make('button', 'ghost-btn', 'Load preview'); load.type = 'button';
          load.setAttribute('aria-label', `Load preview of ${item.label || item.kind || 'image'} from ${core.hostOf(item.url) || domain}`);
          load.onclick = () => {
            const img = document.createElement('img'); img.src = item.url; img.alt = item.label || `${item.kind} from ${domain}`;
            img.referrerPolicy = 'no-referrer'; img.onerror = () => { img.remove(); frame.textContent = 'Preview unavailable'; };
            frame.replaceChildren(img);
          };
          frame.append(load);
        } else frame.textContent = item.kind === 'video' ? 'Video' : 'Asset';
        card.append(frame, make('small', 'collection-kind', item.kind || 'media'),
          ZearchRender.sourceLink({ url: item.url, title: item.label || item.url }, item.label || item.url));
        gallery.append(card);
      }
      mediaPanel.append(gallery);
      contactPanel.append(make('h3', 'collection-section-title', 'Public contact details'));
      if (!emails.size) contactPanel.append(make('p', 'collection-empty', 'No public email addresses were found in these pages.'));
      for (const [email, page] of emails) {
        const row = make('div', 'collection-contact');
        row.append(make('strong', '', email), make('small', '', `Found on ${page.title || page.url}`),
          button('Copy email', async () => { await copyText(email); toast('Email copied'); }, 'ghost-btn', `Copy email ${email}`));
        contactPanel.append(row);
      }
      dataPanel.append(make('h3', 'collection-section-title', 'Dataset'));
      dataPanel.append(make('p', 'collection-data-note', 'Page content and assets captured from this address. Download the dataset with Export.'));
      const fields = make('dl', 'collection-fields');
      for (const [key, value] of [['Target', run.target_url || '—'], ['Scope', run.depth === 'crawl' ? 'Bounded site crawl' : 'Single page'],
        ['Pages captured', String(pages.length)], ['Media links', String(media.length)], ['Public emails', String(emails.size)]]) {
        fields.append(make('dt', '', key), make('dd', '', value));
      }
      dataPanel.append(fields);
      const decision = run.usage?.judgment;
      if (decision?.gate) {
        const box = make('div', 'collection-decision');
        box.append(make('strong', '', decision.gate === 'answer' ? 'Evidence reviewed' :
          decision.gate === 'review' ? 'Check conflicting sources' : 'Limited direct evidence'),
          make('small', '', `${pages.length} captured ${pages.length === 1 ? 'page' : 'pages'} available to inspect in the Pages tab.`));
        dataPanel.append(box);
      }
      const visualSection = make('section', 'collection-visual');
      visualSection.append(make('h3', 'collection-section-title', 'Visual capture'));
      if (visual?.screenshot) {
        const shot = document.createElement('img'); shot.src = '/api/collection?id=' + run.id + '&image=1';
        shot.alt = `Captured viewport of ${domain}`; shot.loading = 'lazy'; visualSection.append(shot);
        const shotLink = make('a', 'collection-download', 'Download screenshot');
        shotLink.href = shot.src; shotLink.download = 'zearch-' + run.id + (visual.image_type === 'image/jpeg' ? '.jpg' : visual.image_type === 'image/webp' ? '.webp' : '.png'); visualSection.append(shotLink);
      }
      const guide = visual?.styleguide;
      if (guide && typeof guide === 'object') {
        const colors = guide.colors && typeof guide.colors === 'object' ? Object.entries(guide.colors).slice(0, 12) : [];
        const palette = make('div', 'collection-palette');
        for (const [name, value] of colors) {
          if (typeof value !== 'string') continue;
          const chip = make('div', 'collection-color');
          const swatch = make('span', 'collection-swatch');
          if (/^#[0-9a-f]{3,8}$/i.test(value) || /^rgba?\([\d\s.,%]+\)$/i.test(value)) swatch.style.backgroundColor = value;
          chip.append(swatch, make('small', '', `${name} · ${value}`)); palette.append(chip);
        }
        visualSection.append(palette);
        const typography = guide.typography;
        if (typography?.p?.fontFamily) visualSection.append(make('p', 'collection-data-note', `Body type: ${typography.p.fontFamily}`));
        const headingFont = typography?.headings?.h1?.fontFamily;
        if (headingFont) visualSection.append(make('p', 'collection-data-note', `Heading type: ${headingFont}`));
      }
      if (visual?.error) visualSection.append(make('p', 'collection-data-note', visual.error));
      if (!visual?.screenshot && !guide) visualSection.append(make('p', 'collection-data-note',
        visual?.status === 'queued' ? 'Queued for capture. This page updates when it is ready.' :
        visual?.status === 'running' ? 'Capturing the page…' :
        visualConfigured ? 'Capture a rendered page and its design tokens.' : 'Visual capture is not enabled on this deployment.'));
      if (visualConfigured && run.status === 'complete' && (!visual || visual.retryable)) {
        visualSection.append(button(visual ? 'Retry visual capture' : 'Queue visual capture', async () => {
          visual = await core.fetchJson('/api/collection?id=' + run.id, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
          visualAttempt = 0; renderCollection(); scheduleVisual();
        }));
      }
      if (visual?.status === 'queued' || visual?.status === 'running') {
        visualSection.append(button('Check capture status', async () => {
          const data = await core.fetchJson('/api/collection?id=' + run.id);
          visual = data.visual; renderCollection(); scheduleVisual();
        }));
      }
      dataPanel.append(visualSection);
      dataPanel.append(make('p', 'collection-data-note', run.status === 'complete' ?
        'Use Export to download the full JSON dataset or a flat CSV inventory.' : 'Exports become available when the collection finishes.'));
    }
    update(); return { run, update, status, body, root, renderBody };
  }

  /* ---------- running a question ---------- */
  function submit(event) {
    event.preventDefault();
    if (active) { if (event.submitter === $('decide')) active.abort(); return; }   // Enter never stops a run
    if (!sessionReady) return;
    const mode = $('depth').value, collecting = mode === 'scrape' || mode === 'crawl';
    const targetUrl = collecting ? $('target-url').value.trim() : null;
    const question = query.value.trim() || (mode === 'scrape' ? 'Summarize this page and extract its key facts.' : mode === 'crawl' ? 'Summarize the core product and main sections from the captured pages of this site.' : '');
    if (!question || (collecting && !targetUrl)) return;
    startRun({ question, mode, targetUrl, parentId: parent, fromComposer: true });
  }
  async function startRun({ question, mode, targetUrl, parentId, fromComposer = false }) {
    if (active || !sessionReady) return;
    const collecting = mode === 'scrape' || mode === 'crawl';
    version++; active = new AbortController(); showThread(); closeRail();
    const view = turn({ query: question, target_url: targetUrl, depth: mode, answer: '', sources: [], status: 'pending' });
    if (fromComposer) { query.value = ''; $('target-url').value = ''; }
    controls();
    view.root.scrollIntoView({ behavior: 'auto', block: 'start' });
    let complete = false, timer = 0, lastPaint = 0;
    const paint = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = 0;
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed && view.body.contains(selection.anchorNode)) { paint(); return; }   // do not fight a selection
        lastPaint = performance.now();
        requestAnimationFrame(() => { if (!complete) view.renderBody(false); });
      }, Math.max(0, 120 - (performance.now() - lastPaint)));
    };
    const feed = $('feed');
    function accept(data) {
      const follow = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
      if (data.type === 'start') {
        active.runId = data.id; view.run.id = data.id; shownId = data.id; shownIds.add(data.id); remember(view.run);
        window.history.replaceState(null, '', core.routeHash(data.id)); setTitle(question); view.update();
      }
      if (data.type === 'status') view.status.textContent = data.text;
      if (data.type === 'research') view.run.usage = data.report;
      if (data.type === 'sources') { view.run.sources = data.sources; view.update(); }
      if (data.type === 'delta') { view.run.answer += data.text; paint(); }
      if (data.type === 'complete') {
        clearTimeout(timer); timer = 0; complete = true; Object.assign(view.run, data.run); view.update();
        setParent(data.run.id, question); announce('Answer ready');
      }
      if (data.type === 'error') throw Error(data.error);
      if (follow) requestAnimationFrame(() => { feed.scrollTo({ top: feed.scrollHeight, behavior: 'instant' }); });
    }
    try {
      const response = await fetch('/api/research', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: active.signal,
        body: JSON.stringify({ query: question, target_url: targetUrl, parent_id: parentId, request_id: core.newRequestId(), depth: mode, use_knowledge: $('use-knowledge').checked && !collecting })
      });
      if (!response.ok) {
        let data = null; try { data = await response.json(); } catch {}
        throw core.httpError(response.status, data);
      }
      if (response.headers.get('Content-Type')?.includes('application/json')) {
        const data = await response.json(); Object.assign(view.run, data.run); view.update();
        complete = data.run.status === 'complete'; if (complete) { setParent(data.run.id, question); announce('Answer ready'); }
      } else {
        const reader = response.body.getReader();
        try { await core.readNdjson(reader, accept); } finally { reader.releaseLock(); }
      }
      if (!complete) throw Error('Research ended before completion. Any partial answer is incomplete.');
    } catch (error) {
      clearTimeout(timer); timer = 0;
      const failure = error.name === 'AbortError' ? 'Stopped · any partial answer is incomplete.' : errorText(error);
      active.abort();
      if (!view.run.id) {
        view.root.remove();
        if (fromComposer) { query.value = question; if (collecting) $('target-url').value = targetUrl; }
        if (!thread.childElementCount) { showHomeLayout(); setTitle(null); notice.textContent = failure; }
        else toast(failure, { error: true });
      } else {
        view.run.status = 'interrupted'; view.run.error = failure; view.update();
      }
    } finally { active = null; controls(); focusQuery(); loadWorkspace(false); }
  }

  /* ---------- workspace ---------- */
  const LISTS = ['notes-list', 'documents-list', 'research-list', 'investigations-list', 'batches-list'];
  const EMPTY = {
    'notes-list': 'No notes yet. Add one above and switch on “Use my notes” when you search.',
    'documents-list': 'No documents yet. Import a .txt, .md or .docx file to search alongside the web.',
    'research-list': 'No saved research yet. Your answers appear here after you search.',
    'investigations-list': 'No investigations yet. Choose Save under an answer to refresh it later.',
    'batches-list': 'No batches yet. Add page URLs above to collect several pages at once.'
  };
  function showWorkspaceSkeleton() {
    for (const id of LISTS) {
      const list = $(id); list.replaceChildren();
      for (let i = 0; i < 2; i++) { const li = make('li', 'skeleton'); li.setAttribute('aria-hidden', 'true'); list.append(li); }
    }
  }
  function renderWorkspace() {
    const data = workspaceData, allowance = data.allowance;
    $('workspace-status').textContent = allowance ? `${allowance.plan} plan · ${allowance.used} of ${allowance.daily_limit} runs used today · resets ${allowance.reset}. Daily usage limits also apply.` : '';
    for (const id of LISTS) $(id).replaceChildren();
    for (const note of data.notes || []) {
      const li = make('li'); li.append(make('span', '', note.title), button('Delete', async () => {
        if (!window.confirm('Delete this stored note and redact saved answers that used it?')) return;
        await api('delete_note', { id: note.id }); await loadWorkspace(); toast('Note deleted');
      }, 'ghost-btn', `Delete note: ${note.title}`)); $('notes-list').append(li);
    }
    for (const item of data.documents || []) {
      const li = make('li'); li.append(make('span', '', item.filename), button('Delete', async () => {
        if (!window.confirm('Delete this document and redact saved answers that used it?')) return;
        await api('delete_document', { id: item.id }); await loadWorkspace(); toast('Document deleted');
      }, 'ghost-btn', `Delete document: ${item.filename}`)); $('documents-list').append(li);
    }
    for (const item of data.history || []) {
      const li = make('li');
      li.append(button(item.query, () => openRun(item.id), 'workspace-title', `Open answer: ${item.query}`));
      li.append(button('Delete', async () => {
        if (active) throw Error('Wait for the current research to finish.');
        if (!window.confirm('Delete this answer and its evidence from the server? Follow-up answers derived from it will be redacted.')) return;
        await api('delete_run', { id: item.id });
        if (parent === item.id) setParent(null);
        if (shownIds.has(item.id)) home({ focus: false });
        recent = recent.filter(x => x.id !== item.id); persistHistory();
        await loadWorkspace(); toast('Answer deleted');
      }, 'ghost-btn', `Delete answer: ${item.query}`)); $('research-list').append(li);
    }
    for (const item of data.investigations || []) {
      const li = make('li', 'investigation-item'), actions = make('div', 'turn-actions');
      li.append(make('p', 'workspace-title', `${item.depth === 'scrape' || item.depth === 'crawl' ? 'Site monitor' : 'Investigation'} · ${item.query}`));
      if (item.target_url) li.append(make('p', 'hint', item.target_url));
      const changes = item.last_changes || {}, count = key => (Array.isArray(changes[key]) ? changes[key].length : 0);
      const summary = changes.check ? `${count('added')} new sources · ${count('changed')} changed excerpts · ${count('removed')} removed sources.${changes.answer_changed ? ' The answer changed; review the saved runs before relying on it.' : ''} No verified fact-change alert was sent.` : 'No refresh comparison yet.';
      li.append(make('p', 'hint', summary));
      if (item.job) li.append(make('p', 'hint', item.job.error || `Refresh ${item.job.status}`));
      if (item.last_run) actions.append(button('Open latest', () => openRun(item.last_run), 'ghost-btn', `Open latest answer: ${item.query}`));
      if (data.discovery_enabled) {
        actions.append(button('Refresh', async () => { await api('refresh', { id: item.id }); await loadWorkspace(); toast('Refresh queued'); }, 'ghost-btn', `Refresh: ${item.query}`));
        const wrap = make('span', 'mode-select-wrap'), select = make('select', 'depth-select'); select.setAttribute('aria-label', 'Refresh schedule for ' + item.query);
        for (const [value, text] of [[0, 'Paused'], [24, 'Daily'], [168, 'Weekly']]) {
          const option = make('option', '', text); option.value = value; select.append(option);
        }
        select.value = item.interval_hours;
        select.onchange = async () => {
          select.disabled = true;
          try { await api('schedule', { id: item.id, hours: Number(select.value) }); await loadWorkspace(); }
          catch (error) { select.value = item.interval_hours; fail(error); }
          finally { select.disabled = false; }
        };
        wrap.append(select); wrap.insertAdjacentHTML('beforeend', '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>');
        actions.append(wrap);
      } else li.append(make('p', 'hint', 'Scheduled refresh is not enabled on this deployment.'));
      actions.append(button('Remove', async () => {
        if (!window.confirm('Remove this investigation and its schedule? Saved answers will remain.')) return;
        await api('delete_investigation', { id: item.id }); await loadWorkspace(); toast('Investigation removed');
      }, 'ghost-btn', `Remove investigation: ${item.query}`)); li.append(actions); $('investigations-list').append(li);
    }
    $('batch-form').querySelector('button').disabled = !data.discovery_enabled;
    $('batch-disabled').hidden = Boolean(data.discovery_enabled);
    for (const batch of data.batches || []) {
      const items = batch.items || [];
      const li = make('li', 'investigation-item'), actions = make('div', 'turn-actions');
      li.append(make('p', 'workspace-title', `${items.filter(x => x.status === 'complete').length}/${items.length} pages · ${batch.status}`));
      for (const item of items) {
        const row = make('div', 'batch-row'); row.append(make('span', '', item.target_url), make('small', '', item.error || item.status));
        if (item.run_id) row.append(button('Open', () => openRun(item.run_id), 'ghost-btn', `Open answer for ${item.target_url}`));
        li.append(row);
      }
      if (['queued', 'running'].includes(batch.status)) actions.append(button('Cancel queued', async () => {
        await api('cancel_batch', { id: batch.id }); await loadWorkspace(); toast('Batch canceled');
      }));
      li.append(actions); $('batches-list').append(li);
    }
    for (const id of LISTS) if (!$(id).children.length) $(id).append(make('li', 'empty-note', EMPTY[id]));
  }
  async function loadWorkspace(showErrors = true) {
    const seq = ++workspaceSeq;
    try {
      const data = await core.fetchJson('/api/workspace');
      if (seq !== workspaceSeq) return;   // a newer load is in flight or finished
      workspaceData = { notes: [], documents: [], investigations: [], batches: [], history: [], ...data };
      workspaceReady = true; workspaceLoaded = true;
      recent = (workspaceData.history || []).filter(x => core.isRunId(x.id)).map(x => ({ id: x.id, query: x.query })).slice(0, 100);
      persistHistory(); renderWorkspace(); controls();
    } catch (error) {
      if (seq !== workspaceSeq) return;
      if (!workspaceLoaded) for (const id of LISTS) { $(id).replaceChildren(make('li', 'empty-note', 'Could not load this yet.')); }
      if (showErrors) $('workspace-status').textContent = errorText(error);
      controls();
    }
  }
  function openWorkspace() {
    $('workspace').showModal(); closeRail();
    if (!workspaceLoaded) showWorkspaceSkeleton();
    loadWorkspace(); loadAccount();
  }
  $('btn-workspace').onclick = openWorkspace;
  $('workspace-close').onclick = () => $('workspace').close();
  $('note-form').onsubmit = async event => {
    event.preventDefault(); const submitter = event.submitter; submitter.disabled = true;
    try {
      await api('add_note', { title: $('note-title').value, body: $('note-body').value });
      $('note-form').reset(); await loadWorkspace(); toast('Note saved');
    } catch (error) { fail(error); } finally { submitter.disabled = false; }
  };
  $('batch-form').onsubmit = async event => {
    event.preventDefault(); const submitter = event.submitter; submitter.disabled = true;
    try {
      const urls = $('batch-urls').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
      await api('create_batch', { urls, query: $('batch-query').value });
      $('batch-form').reset(); await loadWorkspace(); toast('Batch queued');
    } catch (error) { fail(error); } finally { submitter.disabled = false; }
  };
  $('note-file').onchange = async () => {
    const file = $('note-file').files[0]; if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 160000) { toast('Choose a .txt or .md file under 160 KB', { error: true }); $('note-file').value = ''; return; }
    try {
      const text = await file.text();
      if (text.length > 40000 || text.includes('\0')) { toast('Use plain text up to 40,000 characters', { error: true }); $('note-file').value = ''; return; }
      $('note-body').value = text; if (!$('note-title').value) $('note-title').value = file.name.slice(0, 120);
    } catch { toast('Could not read that file. Try another one.', { error: true }); $('note-file').value = ''; }
  };
  $('document-form').onsubmit = async event => {
    event.preventDefault(); const file = $('document-file').files[0], submitter = event.submitter;
    if (!file || !/\.(txt|md|docx)$/i.test(file.name) || file.size > 128000) { toast('Choose a .txt, .md or .docx file under 128 KB', { error: true }); return; }
    submitter.disabled = true;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (let at = 0; at < bytes.length; at += 8192) binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
      await api('add_document', { filename: file.name, content_base64: btoa(binary) });
      $('document-form').reset(); await loadWorkspace(); toast('Document imported');
    } catch (error) { fail(error); } finally { submitter.disabled = false; }
  };
  $('account-email-form').onsubmit = async event => {
    event.preventDefault(); const submitter = event.submitter; submitter.disabled = true;
    try {
      const email = $('account-email').value.trim();
      await accountApi('request_code', { email });
      showCodeForm(email); setCooldown(30); $('account-status').textContent = 'Check your email for the code.';
    } catch (error) { fail(error); } finally { submitter.disabled = false; }
  };
  $('account-have-code').onclick = () => {
    if (!$('account-email').value.trim()) { toast('Enter your email address first.', { error: true }); $('account-email').focus(); return; }
    showCodeForm($('account-email').value.trim()); $('account-sent').textContent = `Enter the eight-digit code sent to ${sentTo}.`; setCooldown(0);
  };
  $('account-resend').onclick = async () => {
    const control = $('account-resend'); control.disabled = true;
    try { await accountApi('request_code', { email: sentTo }); setCooldown(30); toast('A new code is on its way.'); }
    catch (error) { fail(error); control.disabled = false; }
  };
  $('account-change').onclick = () => { $('account-code').value = ''; showEmailForm(); $('account-status').textContent = 'Enter the email address you want to use.'; };
  $('account-code-form').onsubmit = async event => {
    event.preventDefault(); const submitter = event.submitter; submitter.disabled = true;
    try {
      await accountApi('verify_code', { email: sentTo || $('account-email').value.trim(), code: $('account-code').value.trim() });
      $('account-code').value = ''; sentTo = ''; clearInterval(resendTimer);
      await loadAccount(); await loadWorkspace(); home({ focus: false }); toast('Signed in');
    } catch (error) { fail(error); } finally { submitter.disabled = false; }
  };
  $('claim-workspace').onclick = async () => {
    if (active) { toast('Wait for the current research to finish.'); return; }
    const control = $('claim-workspace'); control.disabled = true;
    try { await accountApi('claim_workspace'); await loadWorkspace(); await loadAccount(); toast('Browser research moved to your account'); }
    catch (error) { fail(error); } finally { control.disabled = false; }
  };
  const afterIdentityChange = () => { recent = []; hidden = new Set(); persistHistory(); home({ focus: false }); };
  $('account-signout').onclick = async () => {
    if (active) { toast('Wait for the current research to finish.'); return; }
    try { await accountApi('sign_out'); afterIdentityChange(); await loadAccount(); await loadWorkspace(); toast('Signed out'); }
    catch (error) { fail(error); }
  };
  $('account-delete').onclick = async () => {
    if (active) { toast('Wait for the current research to finish.'); return; }
    if (!window.confirm('Permanently delete this account, its saved research, private knowledge and active sessions on every device?')) return;
    try { await accountApi('delete_account'); afterIdentityChange(); await loadAccount(); await loadWorkspace(); toast('Account deleted'); }
    catch (error) { fail(error); }
  };
  $('export-workspace').onclick = async () => {
    const control = $('export-workspace'); control.disabled = true;
    try {
      const exportData = { version: 1, exported_at: new Date().toISOString(), account: null, notes: [], documents: [], investigations: [], runs: [] };
      let cursor = null, pages = 0;
      do {
        const page = await core.fetchJson('/api/workspace?export=1' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''));
        if (!cursor) exportData.account = page.account;
        exportData.notes.push(...(page.notes || [])); exportData.documents.push(...(page.documents || []));
        exportData.investigations.push(...(page.investigations || [])); exportData.runs.push(...(page.runs || []));
        cursor = page.next_cursor;
        if (++pages > 1000) throw Error('Export is too large to download in the browser.');
      } while (cursor);
      saveBlob(new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' }), 'zearch-workspace.json');
      toast('Download started');
    } catch (error) { fail(error); } finally { control.disabled = false; }
  };
  $('delete-workspace').onclick = async () => {
    if (active) { toast('Wait for the current research to finish.'); return; }
    if (!window.confirm('Permanently delete all saved answers, notes, investigations and evidence in this browser workspace?')) return;
    const control = $('delete-workspace'); control.disabled = true;
    try {
      await api('delete_workspace'); afterIdentityChange(); await loadWorkspace(); toast('Workspace deleted');
    } catch (error) { fail(error); } finally { control.disabled = false; }
  };

  /* ---------- wiring ---------- */
  form.addEventListener('submit', submit); query.addEventListener('input', controls);
  $('target-url').addEventListener('input', controls); $('depth').addEventListener('change', controls);
  query.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (!active) form.requestSubmit();
  });
  $('followup-clear').onclick = () => { setParent(null); query.focus(); };
  $('new-btn').onclick = () => home({ push: true }); $('brand').onclick = event => { event.preventDefault(); home({ push: true }); };
  $('clear-history').onclick = () => {
    for (const item of recent) hidden.add(item.id);
    persistHistory(); toast('Recent searches hidden. Saved research is still in Your workspace.');
  };
  $('btn-settings').onclick = () => $('settings').showModal(); $('btn-thesis').onclick = () => $('thesis').showModal();
  $('menu-btn').onclick = () => setRail(true); $('rail-close').onclick = closeRail; $('scrim').onclick = closeRail;
  $('skip-link').onclick = event => { event.preventDefault(); (query.hidden ? $('main') : query).focus(); };
  for (const dialog of document.querySelectorAll('dialog')) {
    let downOnBackdrop = false;
    dialog.addEventListener('mousedown', event => { downOnBackdrop = event.target === dialog; });
    dialog.addEventListener('click', event => { if (event.target === dialog && downOnBackdrop) dialog.close(); });
    dialog.addEventListener('close', () => { if (toastNode && dialog.contains(toastNode)) dismissToast(); });
  }
  document.addEventListener('click', event => {
    for (const menu of document.querySelectorAll('details.export-menu[open]')) if (!menu.contains(event.target)) menu.open = false;
  });
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
  $('shortcut').textContent = mac ? '⌘K' : 'Ctrl K';
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (!openDialog()) home({ push: true });
    }
    if (event.key === 'Escape') { hidePreview(); if (railOpen) closeRail(); }
  });
  // Back/forward and manual hash edits fire both events; coalesce them into one route().
  let routeQueued = false;
  const scheduleRoute = () => { if (routeQueued) return; routeQueued = true; setTimeout(() => { routeQueued = false; route(); }, 0); };
  window.addEventListener('hashchange', scheduleRoute);
  window.addEventListener('popstate', scheduleRoute);
  STARTERS.forEach(([label, prompt, mode], index) => {
    const starter = make('button', 'starter'); starter.type = 'button'; starter.style.animationDelay = `${index * 40}ms`;
    starter.append(make('span', 'starter-label', label), make('span', 'starter-prompt', prompt));
    starter.onclick = () => { $('depth').value = mode; query.value = prompt; controls(); query.focus(); };
    $('starters').append(starter);
  });
  setRail(false); listHistory(); controls(); syncChip();

  /* Initialize the session before enabling requests, so parallel first requests do not each mint a cookie. */
  const sessionPromise = (async () => {
    try {
      await loadWorkspace(false);
      const data = await core.fetchJson('/api/research', { signal: timeoutSignal(10000) });
      available = Boolean(data.available);
      availabilityMessage = available ? '' : 'Research setup is incomplete. You can send a question to check its status.';
    } catch { availabilityMessage = 'Research is temporarily unavailable. Please try again later.'; }
    finally { sessionReady = true; if (!thread.childElementCount) notice.textContent = availabilityMessage; controls(); }
  })();
  route().then(() => { if (!shownId) focusQuery(); });
})();
