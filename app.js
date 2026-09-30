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
  const svgNS = 'http://www.w3.org/2000/svg';
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
  const DEPTH_HINT = {
    standard: '1 query', deep: 'Up to 3 queries and a gap search', compare: 'Up to 3 queries, side by side',
    scrape: '1 page', crawl: 'Up to 5 pages'
  };
  const SHORTCUTS = [
    { mode: 'deep', icon: 'deep', title: 'Deep research', text: 'Reads more sources and searches for gaps before it answers.', example: 'How do heat pumps work and when do they make sense?' },
    { mode: 'compare', icon: 'compare', title: 'Compare options', text: 'Puts choices side by side, with sources for each.', example: 'Compare PostgreSQL and MySQL for a small web app' },
    { mode: 'crawl', icon: 'crawl', title: 'Crawl a site', text: 'Reads up to five pages of one public site.', example: 'A documentation site or a product page', url: true }
  ];
  const VIEW_TITLES = { overview: 'Overview', library: 'Library', knowledge: 'Knowledge', monitors: 'Monitors', batches: 'Batches' };
  const SURFACE_NODE = { research: 'feed', overview: 'view-overview', library: 'view-library', knowledge: 'view-knowledge', monitors: 'view-monitors', batches: 'view-batches' };
  const icon = (name, cls) => {
    const svg = document.createElementNS(svgNS, 'svg'), use = document.createElementNS(svgNS, 'use');
    svg.setAttribute('class', 'ico' + (cls ? ' ' + cls : '')); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
    use.setAttribute('href', '#i-' + name); svg.append(use); return svg;
  };

  let parent = null, parentLabel = '', active = null, available = false, version = 0, recent = [];
  let workspaceReady = false, workspaceLoaded = false, sessionReady = false, workspaceSeq = 0, shownId = null, lastWorkspaceLoad = 0;
  let surface = 'research', currentTitle = '';
  let availabilityMessage = 'Checking research availability…';
  let workspaceData = { notes: [], documents: [], investigations: [], batches: [], history: [] };
  let accountData = { enabled: false, account: null };
  const shownIds = new Set();
  const notice = $('research-notice'); notice.textContent = availabilityMessage;
  try {
    recent = JSON.parse(localStorage.getItem('zearch:research-history') || '[]')
      .filter(x => x && core.isRunId(x.id) && typeof x.query === 'string').slice(0, 100);
  } catch {}

  /* ---------- small helpers ---------- */
  const errorText = error => (error && error.message) || 'Something went wrong. Please try again.';
  const timeoutSignal = ms => (typeof AbortSignal !== 'undefined' && AbortSignal.timeout ? AbortSignal.timeout(ms) : undefined);
  const openDialog = () => document.querySelector('dialog[open]');
  const announce = text => { const node = $('announcer'); node.textContent = ''; setTimeout(() => { node.textContent = text; }, 40); };
  const scrollBehavior = () => (reduceMotion.matches || document.documentElement.dataset.motion === 'reduce' ? 'auto' : 'smooth');
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

  /* ---------- rail: mobile drawer and desktop collapse ---------- */
  let railOpen = false, railFocus = null, collapsed = false;
  try { collapsed = localStorage.getItem('zearch:rail') === 'collapsed'; } catch {}
  function setCollapsed(value, persist = true) {
    collapsed = Boolean(value);
    $('shell').classList.toggle('rail-collapsed', collapsed);
    const toggle = $('rail-toggle');
    toggle.setAttribute('aria-expanded', String(!collapsed)); toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    if (persist) { try { localStorage.setItem('zearch:rail', collapsed ? 'collapsed' : 'expanded'); } catch {} }
  }
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

  /* ---------- popover menus (topbar options, composer "More") ---------- */
  function popMenu(trigger, menu) {
    const items = () => [...menu.querySelectorAll('[role=menuitem]')];
    const close = restore => {
      if (menu.hidden) return;
      menu.hidden = true; trigger.setAttribute('aria-expanded', 'false'); if (restore) trigger.focus();
    };
    const open = last => {
      menu.hidden = false; trigger.setAttribute('aria-expanded', 'true');
      const list = items(); (last ? list.at(-1) : list[0])?.focus();
    };
    trigger.addEventListener('click', () => (menu.hidden ? open(false) : close(true)));
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); if (menu.hidden) open(event.key === 'ArrowUp'); }
    });
    menu.addEventListener('keydown', event => {
      const list = items(), at = list.indexOf(document.activeElement);
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
      else if (event.key === 'Tab') close(false);
      else if (event.key === 'ArrowDown') { event.preventDefault(); list[(at + 1) % list.length].focus(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); list[(at - 1 + list.length) % list.length].focus(); }
      else if (event.key === 'Home') { event.preventDefault(); list[0].focus(); }
      else if (event.key === 'End') { event.preventDefault(); list.at(-1).focus(); }
    });
    menu.addEventListener('click', event => { if (event.target.closest('[role=menuitem]')) close(false); });
    document.addEventListener('click', event => { if (!menu.hidden && !menu.contains(event.target) && !trigger.contains(event.target)) close(false); });
    return { close };
  }

  /* ---------- composer ---------- */
  function focusQuery() {
    if (openDialog() || coarse.matches || surface !== 'research') return;
    const at = document.activeElement;
    if (!at || at === document.body || form.contains(at)) query.focus();
  }
  function syncChip() {
    $('followup').hidden = !parent;
    $('followup-text').textContent = 'Continuing from previous answer';
    $('followup').title = parentLabel ? 'Follow-up to: ' + parentLabel : '';
  }
  function setParent(id, label) { parent = id || null; parentLabel = id ? core.truncate(label, 90) : ''; syncChip(); }
  const chips = [...document.querySelectorAll('#mode-chips .mode-chip')];
  /* The hidden #depth select stays the source of truth for the mode; the chips mirror it. */
  function setMode(mode) {
    if ($('depth').value === mode) return;
    $('depth').value = mode; $('depth').dispatchEvent(new Event('change'));
  }
  for (const chip of chips) {
    chip.addEventListener('click', () => { setMode(chip.dataset.mode); });
    chip.addEventListener('keydown', event => {
      const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
      if (!step && event.key !== 'Home' && event.key !== 'End') return;
      event.preventDefault();
      const at = chips.indexOf(chip), next = event.key === 'Home' ? chips[0] : event.key === 'End' ? chips.at(-1) : chips[(at + step + chips.length) % chips.length];
      setMode(next.dataset.mode); next.focus();
    });
  }
  let pillText = '';
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
    for (const chip of chips) {
      const on = chip.dataset.mode === mode;
      chip.setAttribute('aria-checked', String(on)); chip.tabIndex = on ? 0 : -1; chip.disabled = Boolean(active);
    }
    $('depth-hint-text').textContent = DEPTH_HINT[mode] || '';
    $('mode-help').textContent = MODE_HELP[mode] || '';
    const allowance = workspaceData.allowance;
    if (allowance && Number.isFinite(allowance.daily_limit) && Number.isFinite(allowance.used)) {
      const left = Math.max(0, allowance.daily_limit - allowance.used);
      $('allowance-chip').hidden = false;
      $('allowance').textContent = `${allowance.used}/${allowance.daily_limit} runs today`;
      $('allowance-chip').title = `${left} of ${allowance.daily_limit} runs left today. Resets ${allowance.reset}.`;
      $('menu-allowance').textContent = `${left} of ${allowance.daily_limit} runs left today`;
    } else { $('allowance-chip').hidden = true; $('allowance').textContent = ''; $('menu-allowance').textContent = ''; }
    const running = Math.max(Number(workspaceData.running) || 0, active ? 1 : 0), text = running === 1 ? '1 run in progress' : `${running} runs in progress`;
    $('runs-pill').hidden = running < 1;
    if (running >= 1 && text !== pillText) $('runs-pill-text').textContent = text;
    pillText = running >= 1 ? text : '';
    const length = query.value.length, counter = $('char-count');
    counter.hidden = length < 1600; counter.textContent = `${length} / ${query.maxLength}`;
    query.style.height = 'auto'; query.style.height = Math.min(query.scrollHeight, 180) + 'px';
  }

  /* ---------- recent research: compact rail list and the Home timeline ---------- */
  function persistHistory() {
    try { localStorage.setItem('zearch:research-history', JSON.stringify(recent)); } catch {}
    listHistory();
  }
  function listHistory() {
    const list = $('history'); list.replaceChildren();
    for (const item of recent.slice(0, 5)) {
      const li = make('li'), control = make('button', 'h-q', item.query);
      control.type = 'button'; control.title = item.query;
      if (item.id === shownId && surface === 'research') control.setAttribute('aria-current', 'page');
      control.onclick = () => openRun(item.id);
      li.append(control); list.append(li);
    }
    list.hidden = !list.children.length;
    renderRecent();
  }
  function renderRecent() {
    const section = $('recent'), list = $('recent-list'); list.replaceChildren();
    section.hidden = !workspaceLoaded;
    const items = (workspaceData.history || []).filter(x => core.isRunId(x.id)).slice(0, 5);
    $('recent-more').hidden = !items.length;
    for (const item of items) {
      const li = make('li', 'tl-item'), dot = make('span', 'dot'), meta = make('span', 'tl-meta');
      dot.dataset.tone = core.statusTone(item.status); dot.setAttribute('aria-hidden', 'true');
      const title = make('button', 'tl-title', item.query); title.type = 'button'; title.title = item.query;
      title.onclick = () => openRun(item.id);
      meta.textContent = [core.statusLabel(item.status), core.relativeTime(item.created)].filter(Boolean).join(' · ');
      li.append(dot, title, meta); list.append(li);
    }
    if (!items.length) {
      const li = make('li', 'tl-empty'), ask = make('button', 'link-btn', 'Ask your first question'); ask.type = 'button';
      ask.onclick = () => { query.focus(); };
      li.append(make('span', '', 'Nothing here yet. '), ask); list.append(li);
    }
  }
  function remember(run) {
    recent = [{ id: run.id, query: run.query }, ...recent.filter(x => x.id !== run.id)].slice(0, 100);
    persistHistory();
  }

  /* ---------- views and routing ---------- */
  function syncTitle() {
    const name = surface === 'research' ? currentTitle : VIEW_TITLES[surface];
    document.title = name ? `${core.truncate(name, 70)} — Zearch` : DEFAULT_TITLE;
  }
  function setTitle(text) {
    currentTitle = text ? core.truncate(text, 70) : '';
    const heading = $('thread-title'); heading.hidden = !currentTitle; heading.textContent = currentTitle;
    syncTitle();
  }
  /* One place decides what is on screen: the Research feed (home or an answer) or one view panel. */
  function showSurface(name, options = {}) {
    if (!SURFACE_NODE[name]) name = 'research';
    const changed = surface !== name; surface = name;
    for (const [key, id] of Object.entries(SURFACE_NODE)) $(id).hidden = key !== name;
    document.querySelector('.dock').hidden = name !== 'research';
    $('main').dataset.surface = name;
    for (const link of document.querySelectorAll('#rail .nav-item[data-view]')) {
      const on = link.dataset.view === (name === 'research' ? 'home' : name);
      if (on) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    const tabbed = name === 'research' || name === 'overview';
    $('subbar').hidden = !tabbed;
    for (const [key, tab] of [['research', $('tab-research')], ['overview', $('tab-overview')]]) {
      tab.setAttribute('aria-selected', String(key === name)); tab.tabIndex = key === name ? 0 : -1;
    }
    syncTitle(); listHistory();
    if (name !== 'research') {
      if (name === 'overview') loadStats(); else if (!workspaceLoaded || Date.now() - lastWorkspaceLoad > 2000) { if (!workspaceLoaded) showWorkspaceSkeleton(); loadWorkspace(false); }
      if (options.focus !== false && changed) $(SURFACE_NODE[name]).focus({ preventScroll: true });
      $(SURFACE_NODE[name]).scrollTop = 0;
    }
  }
  function goView(name) {
    if (location.hash === core.viewHash(name)) route(true); else window.history.pushState(null, '', core.viewHash(name)), route(true);
  }
  function showThread() {
    empty.classList.add('hidden'); form.classList.remove('home-composer'); dock.append(form, fine);
  }
  function showHomeLayout() {
    empty.classList.remove('hidden'); $('composer-slot').append(form, fine); form.classList.add('home-composer');
  }
  function home(options = {}) {
    if (active) {
      const current = active.runId ? '#r/' + active.runId : '';
      if (location.hash !== current) window.history.replaceState(null, '', current || location.pathname + location.search);
      showSurface('research', { focus: false }); return;
    }
    version++; setParent(null); shownId = null; shownIds.clear();
    thread.replaceChildren(); showHomeLayout(); notice.textContent = availabilityMessage;
    if (!options.keepSurface) {
      if (options.push) { if (location.hash) window.history.pushState(null, '', location.pathname + location.search); }
      else if (location.hash) window.history.replaceState(null, '', location.pathname + location.search);
      showSurface('research', { focus: false });
    }
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
    if (target.type === 'view') { showSurface(target.view); return; }
    if (active) {
      // Back/forward during a run: keep the URL in step with what is on screen.
      const current = active.runId ? '#r/' + active.runId : '';
      if (location.hash !== current) {
        window.history.replaceState(null, '', current || location.pathname + location.search);
        if (target.type !== 'other') toast('Stop the current research before opening another answer.');
      }
      if (target.type !== 'other') showSurface('research', { focus: false });
      return;
    }
    if (target.type === 'other') return;
    if (target.type === 'home') { if (shownId || thread.childElementCount || force === true) home(); else showSurface('research', { focus: false }); return; }
    if (force !== true && target.id === shownId) { showSurface('research', { focus: false }); return; }
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
      shownId = target.id; showSurface('research', { focus: false }); setTitle(last?.query || ''); listHistory();
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
  function renderAccountCard() {
    const email = accountData.account && accountData.account.email;
    $('account-avatar').textContent = email ? email.trim().charAt(0).toUpperCase() : 'G';
    $('account-name').textContent = email || 'Guest';
    $('account-sub').textContent = email ? 'Signed in' : accountData.enabled ? 'Sign in to keep your research' : 'Private to this browser';
    $('account-card').setAttribute('aria-label', `Account and data: ${email || 'Guest'}`);
  }
  async function loadAccount() {
    try {
      const data = await core.fetchJson('/api/account');
      accountData = data; renderAccountCard();
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
    } catch { $('account-section').hidden = true; accountData = { enabled: false, account: null }; renderAccountCard(); }
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
    } finally {
      active = null; controls(); focusQuery(); loadWorkspace(false);
      statsState.stale = true; if (surface === 'overview') loadStats();
    }
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
  function renderLibrary() {
    const list = $('research-list'), all = workspaceData.history || [], needle = $('library-search').value.trim().toLowerCase();
    const items = all.filter(item => core.isRunId(item.id) && (!needle || String(item.query).toLowerCase().includes(needle)));
    list.replaceChildren();
    $('library-count').textContent = !all.length ? '' : needle ? `${items.length} of ${all.length} shown` : `${all.length} saved`;
    for (const item of items) {
      const li = make('li', 'library-item'), dot = make('span', 'dot'), meta = make('span', 'lib-meta');
      dot.dataset.tone = core.statusTone(item.status); dot.setAttribute('aria-hidden', 'true');
      const seconds = core.toSeconds(item.created);
      meta.textContent = [core.statusLabel(item.status), seconds ? new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : ''].filter(Boolean).join(' · ');
      if (seconds) meta.title = new Date(seconds * 1000).toLocaleString();
      const open = button(item.query, () => openRun(item.id), 'workspace-title', `Open answer: ${item.query}`);
      const del = button('Delete', async () => {
        if (active) throw Error('Wait for the current research to finish.');
        if (!window.confirm('Delete this answer and its evidence from the server? Follow-up answers derived from it will be redacted.')) return;
        await api('delete_run', { id: item.id });
        if (parent === item.id) setParent(null);
        if (shownIds.has(item.id)) home({ focus: false, keepSurface: surface !== 'research' });
        recent = recent.filter(x => x.id !== item.id); persistHistory();
        await loadWorkspace(); toast('Answer deleted');
      }, 'ghost-btn', `Delete answer: ${item.query}`);
      li.append(dot, open, meta, del); list.append(li);
    }
    if (!items.length) {
      const li = make('li', 'empty-note');
      li.append(make('span', '', all.length ? `No saved answers match “${core.truncate(needle, 40)}”.` : EMPTY['research-list'] + ' '));
      if (!all.length) { const ask = make('button', 'solid-btn', 'Ask a question'); ask.type = 'button'; ask.onclick = () => home({ push: true }); li.append(ask); }
      list.append(li);
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
    renderLibrary();
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
      workspaceReady = true; workspaceLoaded = true; lastWorkspaceLoad = Date.now();
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
    const dialog = $('workspace'); if (openDialog() && openDialog() !== dialog) openDialog().close();
    dialog.showModal(); closeRail();
    if (!workspaceLoaded) showWorkspaceSkeleton();
    loadWorkspace(); loadAccount();
  }
  $('account-card').onclick = openWorkspace; $('menu-account').onclick = openWorkspace;
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
  const afterIdentityChange = () => { recent = []; statsState.data = null; persistHistory(); home({ focus: false, keepSurface: surface !== 'research' }); };
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
  async function exportWorkspace(control) {
    control.disabled = true;
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
  }
  $('export-workspace').onclick = () => exportWorkspace($('export-workspace'));
  $('menu-export').onclick = () => exportWorkspace($('menu-export'));
  $('delete-workspace').onclick = async () => {
    if (active) { toast('Wait for the current research to finish.'); return; }
    if (!window.confirm('Permanently delete all saved answers, notes, investigations and evidence in this browser workspace?')) return;
    const control = $('delete-workspace'); control.disabled = true;
    try {
      await api('delete_workspace'); afterIdentityChange(); await loadWorkspace(); toast('Workspace deleted');
    } catch (error) { fail(error); } finally { control.disabled = false; }
  };

  /* ---------- overview: analytics computed from the owner's own runs ---------- */
  const statsState = { days: 30, status: 'idle', data: null, error: '', stale: false, sort: { key: 'created', dir: 'desc' } };
  let statsSeq = 0, overviewBuilt = false, overviewFocus = null;
  const overviewContent = () => $('overview-content');
  function buildOverview() {
    if (overviewBuilt) return; overviewBuilt = true;
    const body = $('overview-body'), head = make('header', 'view-head');
    const title = make('div'); title.append(make('h1', '', 'Overview'), make('p', 'hint', 'Computed from your own runs. Nothing here is estimated beyond what each figure says.'));
    const range = make('div', 'segmented', ''); range.id = 'stats-range'; range.setAttribute('role', 'group'); range.setAttribute('aria-label', 'Time range');
    for (const days of [7, 30]) {
      const choice = make('button', '', `Last ${days} days`); choice.type = 'button'; choice.dataset.days = String(days);
      choice.onclick = () => { if (statsState.days === days) return; statsState.data = null; statsState.days = days; loadStats(days); };
      range.append(choice);
    }
    head.append(title, range);
    const content = make('div', 'overview-content'); content.id = 'overview-content';
    body.append(head, content);
  }
  async function loadStats(days = statsState.days) {
    buildOverview();
    const seq = ++statsSeq; statsState.days = days; statsState.stale = false;
    if (!statsState.data) statsState.status = 'loading';
    renderOverview();
    try {
      const data = await core.fetchJson('/api/workspace?stats=1&days=' + days);
      if (seq !== statsSeq) return;
      statsState.data = data; statsState.status = 'ready'; statsState.error = '';
    } catch (error) {
      if (seq !== statsSeq) return;
      statsState.status = statsState.data ? 'ready' : 'error'; statsState.error = errorText(error);
      if (statsState.data) toast('Could not refresh the overview. Showing the last figures loaded.', { error: true });
    }
    renderOverview();
  }
  function skeleton(cls) { const node = make('div', 'skeleton ' + (cls || '')); node.setAttribute('aria-hidden', 'true'); return node; }
  function legend(parts) {
    const list = make('ul', 'legend');
    for (const [label, count, tone] of parts) {
      const li = make('li'), swatch = make('span', 'swatch'); swatch.dataset.tone = tone; swatch.setAttribute('aria-hidden', 'true');
      li.append(swatch, make('span', '', label), make('b', '', String(count))); list.append(li);
    }
    return list;
  }
  function stack(counts, keys, labels, tones, describe) {
    const parts = core.segments(counts, keys), bar = make('div', 'stack');
    bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', describe);
    for (const part of parts) {
      if (!part.count) continue;
      const seg = make('span', 'seg'); seg.dataset.tone = tones[part.key]; seg.style.flexGrow = String(part.count); bar.append(seg);
    }
    if (!parts.length) bar.classList.add('stack-empty');
    return { bar, legend: legend(keys.map(key => [labels[key], Number(counts[key]) || 0, tones[key]])) };
  }
  function statCard(name, value, sub, foot) {
    const card = make('article', 'card stat'), title = make('h3', 'stat-title', name);
    card.append(title, make('p', 'stat-value', value), make('p', 'stat-sub', sub || ''));
    const slot = make('div', 'stat-visual'); card.append(slot);
    if (foot) card.append(make('p', 'stat-foot', foot));
    card.visual = slot; return card;
  }
  function spark(values, label) {
    const points = core.sparkPoints(values, 120, 32, 3);
    if (!points) return null;
    const svg = document.createElementNS(svgNS, 'svg'), line = document.createElementNS(svgNS, 'polyline');
    svg.setAttribute('viewBox', '0 0 120 32'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('class', 'spark'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label);
    line.setAttribute('points', points); svg.append(line);
    return svg;
  }
  const runsWord = count => `${count} ${count === 1 ? 'run' : 'runs'}`;
  function statusPill(status) {
    const pill = make('span', 'pill'); pill.dataset.tone = core.statusTone(status);
    const dot = make('span', 'dot'); dot.setAttribute('aria-hidden', 'true'); pill.append(dot, make('span', '', core.statusLabel(status))); return pill;
  }
  function renderActivity(data) {
    const card = make('section', 'card activity'), head = make('header', 'section-head'), rows = core.sortActivity(data.activity || [], statsState.sort.key, statsState.sort.dir);
    card.setAttribute('aria-labelledby', 'activity-title');
    const shown = rows.length, total = data.totals.runs;
    head.append(make('h2', '', 'Activity log'), make('span', 'hint', shown < total ? `Latest ${shown} of ${total} runs` : runsWord(total)));
    head.firstChild.id = 'activity-title'; card.append(head);
    const wrap = make('div', 'table-wrap'), table = make('table', 'log');
    table.append(Object.assign(make('caption', 'sr-only', 'Recent runs. Use the column buttons to sort.')));
    const thead = make('thead'), tr = make('tr');
    const columns = [['created', 'Time'], ['query', 'Question'], ['depth', 'Mode'], ['status', 'Status'], ['total_ms', 'Duration'], ['sources', 'Sources']];
    for (const [key, label] of columns) {
      const th = make('th'); th.scope = 'col'; th.dataset.col = key;
      const active = statsState.sort.key === key;
      th.setAttribute('aria-sort', active ? (statsState.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none');
      const sort = make('button', 'th-sort'); sort.type = 'button'; sort.dataset.sort = key; sort.append(make('span', '', label), icon('sort'));
      sort.onclick = () => {
        const same = statsState.sort.key === key;
        statsState.sort = { key, dir: same ? (statsState.sort.dir === 'desc' ? 'asc' : 'desc') : (['query', 'depth', 'status'].includes(key) ? 'asc' : 'desc') };
        overviewFocus = `[data-sort="${key}"]`; renderOverview();
      };
      th.append(sort); tr.append(th);
    }
    thead.append(tr); table.append(thead);
    const tbody = make('tbody');
    for (const row of rows) {
      const line = make('tr'), seconds = core.toSeconds(row.created);
      const cell = (label, node) => { const td = make('td'); td.dataset.label = label; td.append(node); line.append(td); return td; };
      const time = make('time', '', core.relativeTime(row.created));
      if (seconds) { time.dateTime = new Date(seconds * 1000).toISOString(); time.title = new Date(seconds * 1000).toLocaleString(); }
      cell('Time', time);
      const open = make('button', 'row-link', row.query); open.type = 'button'; open.title = row.query;
      open.setAttribute('aria-label', `Open answer: ${row.query}`); open.onclick = () => openRun(row.id);
      cell('Question', open).classList.add('q');
      cell('Mode', make('span', '', core.modeLabel(row.depth)));
      cell('Status', statusPill(row.status));
      cell('Duration', make('span', 'num', core.formatMs(row.total_ms)));
      cell('Sources', make('span', 'num', row.status === 'redacted' ? '—' : String(row.sources ?? '—')));
      tbody.append(line);
    }
    table.append(tbody); wrap.append(table); card.append(wrap);
    return card;
  }
  function renderOverview() {
    buildOverview();
    for (const choice of $('stats-range').children) choice.setAttribute('aria-pressed', String(Number(choice.dataset.days) === statsState.days));
    const host = overviewContent(); host.replaceChildren(); host.setAttribute('aria-busy', String(statsState.status === 'loading'));
    if (statsState.status === 'loading' || statsState.status === 'idle') {
      const grid = make('div', 'stat-grid');
      for (let i = 0; i < 4; i++) grid.append(skeleton('sk-card'));
      host.append(grid, skeleton('sk-wide')); return;
    }
    if (statsState.status === 'error') {
      const card = make('div', 'card empty-card'); card.setAttribute('role', 'alert');
      card.append(make('h2', '', 'Overview is not available right now'), make('p', 'hint', statsState.error || 'Please try again in a moment.'));
      const retry = make('button', 'ghost-btn', 'Try again'); retry.type = 'button'; retry.onclick = () => loadStats(); card.append(retry); host.append(card); return;
    }
    const data = statsState.data, totals = data.totals || {}, measured = data.measured || {};
    if (!totals.runs) {
      const card = make('div', 'card empty-card');
      card.append(make('h2', '', `No research in the last ${statsState.days} days`),
        make('p', 'hint', statsState.days === 7 ? 'Try the last 30 days, or ask a question. Overview is computed from your own runs.' : 'Ask a question and this page fills in with the checks, timings and sources of your own runs. Nothing is shown until then.'));
      const start = make('button', 'solid-btn', 'Start researching'); start.type = 'button'; start.onclick = () => home({ push: true }); card.append(start); host.append(card); return;
    }
    const parts = [runsWord(totals.runs)];
    for (const [key, label] of [['complete', 'complete'], ['interrupted', 'interrupted'], ['error', 'with errors'], ['redacted', 'redacted']]) if (totals[key]) parts.push(`${totals[key]} ${label}`);
    host.append(make('p', 'overview-summary', `${parts.join(' · ')} in the last ${data.days || statsState.days} days`));
    const grid = make('div', 'stat-grid');
    // Verified answers
    const verified = statCard('Verified answers', core.formatPercent(data.verified_rate), data.verified_rate === null || data.verified_rate === undefined ? 'No checked answers yet' : 'had direct evidence',
      measured.gates ? `Across ${measured.gates} checked ${measured.gates === 1 ? 'answer' : 'answers'}` : 'Older runs carry no evidence check');
    const gates = data.gates || {}, gateStack = stack(gates, ['answer', 'review', 'abstain'], { answer: 'Answered', review: 'Needs review', abstain: 'Withheld' },
      { answer: 'ok', review: 'warn', abstain: 'idle' }, `Checked answers: ${gates.answer || 0} answered, ${gates.review || 0} need review, ${gates.abstain || 0} withheld`);
    verified.visual.append(gateStack.bar, gateStack.legend);
    // Latency
    const latency = data.latency_ms || {}, times = (data.activity || []).map(row => row.total_ms).filter(v => typeof v === 'number').reverse();
    const speed = statCard('Research time', core.formatMs(latency.p50), latency.p95 != null ? `median · 95% under ${core.formatMs(latency.p95)}` : 'median',
      measured.latency ? `Across ${measured.latency} timed ${measured.latency === 1 ? 'run' : 'runs'}` : 'Older runs carry no timing');
    const line = spark(times, `Research time of the latest ${times.length} timed runs, oldest to newest, from ${core.formatMs(times[0])} to ${core.formatMs(times.at(-1))}`);
    if (line) { speed.visual.append(line, make('p', 'spark-cap', `Latest ${times.length} runs, oldest to newest`)); }
    // Cost
    const cost = data.cost_usd || {};
    const spend = statCard('Estimated cost', measured.cost ? core.formatCost(cost.total) : '—', cost.average != null ? `${core.formatCost(cost.average)} average per run` : 'No cost data yet',
      measured.cost ? `Across ${measured.cost} ${measured.cost === 1 ? 'run' : 'runs'} with cost data. An estimate, not a bill.` : 'Older runs carry no cost data');
    // Source mix
    const tiers = data.source_tiers || {}, tierTotal = (tiers.primary || 0) + (tiers.web || 0) + (tiers.private || 0);
    const mix = statCard('Source mix', tierTotal ? String(tierTotal) : '—', tierTotal ? `cited ${tierTotal === 1 ? 'source' : 'sources'}` : 'No cited sources yet',
      measured.tiers ? `Across ${measured.tiers} ${measured.tiers === 1 ? 'run' : 'runs'} with sources` : 'Older runs carry no source data');
    const tierStack = stack(tiers, ['primary', 'web', 'private'], { primary: 'Primary publisher', web: 'Web', private: 'Your notes' },
      { primary: 'c1', web: 'c2', private: 'c3' }, `Cited sources: ${tiers.primary || 0} primary, ${tiers.web || 0} web, ${tiers.private || 0} from your notes`);
    mix.visual.append(tierStack.bar, tierStack.legend);
    grid.append(verified, speed, spend, mix); host.append(grid);
    // Runs per day + insights
    const split = make('div', 'overview-split');
    const daily = data.daily || [], heights = core.barHeights(daily), peak = Math.max(0, ...daily.map(d => d.runs || 0));
    const chart = make('section', 'card'), chartHead = make('header', 'section-head');
    chart.setAttribute('aria-labelledby', 'daily-title');
    chartHead.append(make('h2', '', 'Runs per day'), make('span', 'hint', `Last ${daily.length} days`)); chartHead.firstChild.id = 'daily-title';
    const bars = make('div', 'bars'); bars.setAttribute('role', 'img');
    const sum = daily.reduce((n, d) => n + (d.runs || 0), 0), busiest = daily.reduce((best, d) => ((d.runs || 0) > (best.runs || 0) ? d : best), {});
    bars.setAttribute('aria-label', `Runs per day over the last ${daily.length} days: ${sum} in total${peak ? `, busiest day ${busiest.day} with ${peak}` : ''}`);
    daily.forEach((day, index) => {
      const col = make('div', 'bar'); col.setAttribute('aria-hidden', 'true'); col.title = `${day.day}: ${runsWord(day.runs || 0)}`;
      const fill = make('span', 'bar-fill'); fill.style.height = Math.max(day.runs ? 4 : 0, Math.round(heights[index] * 100)) + '%'; col.append(fill); bars.append(col);
    });
    const axis = make('div', 'bar-axis'); axis.setAttribute('aria-hidden', 'true');
    const label = day => { const d = new Date(day + 'T00:00:00Z'); return Number.isNaN(d.getTime()) ? day : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }); };
    axis.append(make('span', '', daily.length ? label(daily[0].day) : ''), make('span', '', peak ? `Busiest: ${peak}` : 'No runs'), make('span', '', daily.length ? label(daily.at(-1).day) : ''));
    chart.append(chartHead, bars, axis);
    const modes = Object.entries(data.by_mode || {}).filter(([, count]) => count > 0);
    if (modes.length) {
      const list = make('ul', 'chip-list'); list.setAttribute('aria-label', 'Runs by mode');
      for (const [mode, count] of modes) list.append(make('li', 'stat-chip', `${core.modeLabel(mode)} ${count}`));
      chart.append(list);
    }
    const noticed = make('section', 'card insights'), noticedHead = make('header', 'section-head');
    noticed.setAttribute('aria-labelledby', 'noticed-title');
    noticedHead.append(make('h2', '', 'What Zearch noticed')); noticedHead.firstChild.id = 'noticed-title'; noticed.append(noticedHead);
    const sentences = core.insights(data), list = make('ul', 'insight-list');
    for (const sentence of sentences) list.append(make('li', '', sentence));
    if (!sentences.length) list.append(make('li', 'hint', 'Not enough measured runs yet to say anything reliable.'));
    noticed.append(list, make('p', 'hint', 'Written from your stored run data by fixed rules, not by a model.'));
    split.append(chart, noticed); host.append(split);
    host.append(renderActivity(data));
    if (overviewFocus) { const target = host.querySelector(overviewFocus); overviewFocus = null; if (target) target.focus(); }
  }

  /* ---------- command palette ---------- */
  const palette = $('palette'), paletteInput = $('palette-input'), paletteList = $('palette-list');
  let paletteItems = [], paletteIndex = 0;
  function startMode(mode, text) {
    home({ push: true, focus: false }); setMode(mode);
    if (text && mode !== 'scrape' && mode !== 'crawl') query.value = text;
    controls(); (mode === 'scrape' || mode === 'crawl' ? $('target-url') : query).focus();
  }
  function paletteSource(needle) {
    const go = hash => () => { if (hash === '') home({ push: true }); else goView(hash); };
    const items = [
      { label: 'New research', keywords: 'home ask question start', group: 'Go to', icon: 'plus', run: () => home({ push: true }) },
      { label: 'Library', keywords: 'saved answers history delete', group: 'Go to', icon: 'library', run: go('library') },
      { label: 'Knowledge', keywords: 'notes documents private', group: 'Go to', icon: 'knowledge', run: go('knowledge') },
      { label: 'Monitors', keywords: 'investigations refresh schedule', group: 'Go to', icon: 'monitors', run: go('monitors') },
      { label: 'Batches', keywords: 'collection pages urls', group: 'Go to', icon: 'batches', run: go('batches') },
      { label: 'Overview', keywords: 'analytics stats insights activity', group: 'Go to', icon: 'overview', run: go('overview') },
      { label: 'Settings', keywords: 'theme dark light motion', group: 'Open', icon: 'settings', run: () => $('settings').showModal() },
      { label: 'Account and data', keywords: 'sign in export delete', group: 'Open', icon: 'user', run: openWorkspace },
      { label: 'Help and About', keywords: 'about jev how it works', group: 'Open', icon: 'help', run: () => $('thesis').showModal() }
    ];
    for (const mode of ['standard', 'deep', 'compare', 'scrape', 'crawl']) {
      items.push({ label: `${core.modeLabel(mode)} mode`, keywords: `start ${mode} research`, group: 'Start', icon: mode === 'standard' ? 'search' : mode === 'deep' ? 'deep' : mode, run: () => startMode(mode, '') });
    }
    const runs = (workspaceData.history || []).filter(x => core.isRunId(x.id)).slice(0, 100);
    runs.forEach((item, index) => items.push({ label: item.query, group: 'Library', icon: 'library', meta: core.relativeTime(item.created), rank: -index * 0.01, run: () => openRun(item.id) }));
    const shown = core.paletteFilter(items, needle, needle ? 12 : 10);
    if (needle) {
      const text = core.truncate(needle, 80);
      shown.push({ label: `Search: ${text}`, group: 'Ask', icon: 'search', run: () => { startMode('standard', needle); form.requestSubmit(); } },
        { label: `Deep research: ${text}`, group: 'Ask', icon: 'deep', run: () => { startMode('deep', needle); form.requestSubmit(); } });
    }
    return shown;
  }
  function renderPalette() {
    paletteItems = paletteSource(paletteInput.value.trim());
    paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
    paletteList.replaceChildren();
    paletteItems.forEach((item, index) => {
      const li = make('li', 'palette-item'); li.id = 'palette-opt-' + index; li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(index === paletteIndex));
      li.append(icon(item.icon), make('span', 'p-label', item.label), make('span', 'p-group', item.meta ? `${item.group} · ${item.meta}` : item.group));
      li.onmousemove = () => { if (paletteIndex !== index) { paletteIndex = index; markPalette(); } };
      li.onclick = () => runPalette(index);
      paletteList.append(li);
    });
    if (!paletteItems.length) paletteList.append(Object.assign(make('li', 'palette-none', 'No matches. Try a shorter word.')));
    markPalette();
    $('palette-status').textContent = paletteItems.length ? `${paletteItems.length} results` : 'No results';
  }
  function markPalette() {
    [...paletteList.querySelectorAll('[role=option]')].forEach((node, index) => {
      node.setAttribute('aria-selected', String(index === paletteIndex));
      if (index === paletteIndex) { node.scrollIntoView({ block: 'nearest' }); paletteInput.setAttribute('aria-activedescendant', node.id); }
    });
    if (!paletteItems.length) paletteInput.removeAttribute('aria-activedescendant');
  }
  function runPalette(index) {
    const item = paletteItems[index]; if (!item) return;
    palette.close(); closeRail(); item.run();
  }
  function openPalette() {
    if (palette.open) return;
    const other = openDialog(); if (other) return;
    paletteInput.value = ''; paletteIndex = 0; renderPalette(); palette.showModal(); paletteInput.focus();
    if (!workspaceLoaded) loadWorkspace(false).then(() => { if (palette.open) renderPalette(); });
  }
  paletteInput.addEventListener('input', () => { paletteIndex = 0; renderPalette(); });
  paletteInput.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); if (!paletteItems.length) return;
      paletteIndex = (paletteIndex + (event.key === 'ArrowDown' ? 1 : -1) + paletteItems.length) % paletteItems.length; markPalette();
    } else if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); runPalette(paletteIndex); }
  });

  /* ---------- settings: theme and motion ---------- */
  function syncSettings() {
    let theme = 'system', motion = false;
    try { theme = core.normalizeTheme(localStorage.getItem('zearch:theme')); motion = localStorage.getItem('zearch:motion') === 'reduce'; } catch {}
    for (const radio of document.querySelectorAll('input[name=theme]')) radio.checked = radio.value === theme;
    $('reduce-motion').checked = motion;
  }
  function savePreference(key, value) {
    try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch {}
    try { core.applyPreferences(document, localStorage); } catch {}
    const chosen = document.documentElement.getAttribute('data-theme');
    for (const meta of document.querySelectorAll('meta[name=theme-color]')) {
      if (!meta.dataset.base) meta.dataset.base = meta.getAttribute('content');
      meta.setAttribute('content', chosen === 'dark' ? '#212121' : chosen === 'light' ? '#f6f7f9' : meta.dataset.base);
    }
  }
  for (const radio of document.querySelectorAll('input[name=theme]')) radio.addEventListener('change', () => { if (radio.checked) savePreference('zearch:theme', radio.value === 'system' ? null : radio.value); });
  $('reduce-motion').addEventListener('change', () => savePreference('zearch:motion', $('reduce-motion').checked ? 'reduce' : null));

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
  $('nav-home').onclick = event => { event.preventDefault(); home({ push: true }); };
  $('recent-more').onclick = () => closeRail();
  for (const link of document.querySelectorAll('#rail .nav-item[href^="#"]')) link.addEventListener('click', () => closeRail());
  const openSettings = () => { const other = openDialog(); if (other) other.close(); syncSettings(); $('settings').showModal(); closeRail(); };
  const openThesis = () => { closeRail(); $('thesis').showModal(); };
  $('btn-settings').onclick = openSettings; $('menu-settings').onclick = openSettings; $('btn-thesis').onclick = openThesis;
  $('settings-account').onclick = () => { $('settings').close(); openWorkspace(); };
  $('rail-search').onclick = () => { closeRail(); openPalette(); };
  $('rail-toggle').onclick = () => setCollapsed(!collapsed);
  $('menu-btn').onclick = () => setRail(true); $('rail-close').onclick = closeRail; $('scrim').onclick = closeRail;
  popMenu($('more-btn'), $('more-menu')); popMenu($('more-modes'), $('more-modes-menu'));
  $('library-search').addEventListener('input', renderLibrary);
  $('tab-research').onclick = () => { if (surface === 'research') return; if (active) home(); else if (shownId) openRun(shownId); else home({ push: true }); };
  $('tab-overview').onclick = () => goView('overview');
  $('subbar').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [$('tab-research'), $('tab-overview')], at = tabs.indexOf(document.activeElement); if (at < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs[(at + 1) % 2];
    next.focus(); next.click();
  });
  $('skip-link').onclick = event => { event.preventDefault(); (surface === 'research' && !empty.classList.contains('hidden') || surface === 'research' && !query.hidden ? query : $(SURFACE_NODE[surface])).focus(); };
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
      if (palette.open) palette.close(); else openPalette();
    }
    if (event.key === 'Escape') { hidePreview(); if (railOpen) closeRail(); }
  });
  // Back/forward and manual hash edits fire both events; coalesce them into one route().
  let routeQueued = false;
  const scheduleRoute = () => { if (routeQueued) return; routeQueued = true; setTimeout(() => { routeQueued = false; route(); }, 0); };
  window.addEventListener('hashchange', scheduleRoute);
  window.addEventListener('popstate', scheduleRoute);
  SHORTCUTS.forEach((card, index) => {
    const starter = make('button', 'starter'); starter.type = 'button'; starter.style.animationDelay = `${index * 40}ms`;
    const head = make('span', 'starter-head'); head.append(icon(card.icon), make('span', 'starter-label', card.title));
    starter.append(head, make('span', 'starter-text', card.text), make('span', 'starter-example', card.url ? card.example : `Try: ${card.example}`));
    starter.onclick = () => {
      setMode(card.mode); controls();
      if (card.url) $('target-url').focus(); else { query.value = card.example; controls(); query.focus(); }
    };
    $('starters').append(starter);
  });
  setCollapsed(collapsed, false); syncSettings();
  setRail(false); listHistory(); controls(); syncChip();

  /* Initialize the session before enabling requests, so parallel first requests do not each mint a cookie. */
  const sessionPromise = (async () => {
    try {
      await loadWorkspace(false);
      const data = await core.fetchJson('/api/research', { signal: timeoutSignal(10000) });
      available = Boolean(data.available);
      availabilityMessage = available ? '' : 'Research setup is incomplete. You can send a question to check its status.';
    } catch { availabilityMessage = 'Research is temporarily unavailable. Please try again later.'; }
    finally { sessionReady = true; if (!thread.childElementCount) notice.textContent = availabilityMessage; controls(); loadAccount(); }
  })();
  route().then(() => { if (!shownId) focusQuery(); });
})();
