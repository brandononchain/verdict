/* Zearch: private research, knowledge and discovery. No client provider keys. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    node.className = cls || ''; node.textContent = text || ''; return node;
  };
  const form = $('composer'), query = $('query'), thread = $('thread'), empty = $('empty');
  const fine = document.querySelector('.fineprint'), dock = document.querySelector('.dock-inner');
  let parent = null, active = null, available = false, version = 0, history = [], workspaceReady = false;
  let workspaceData = { notes: [], documents: [], investigations: [], batches: [], history: [] };
  let accountData = { enabled: false, account: null };
  const notice = make('p', 'research-notice', 'Checking research availability…');
  notice.setAttribute('role', 'status'); empty.append(notice);
  try {
    history = JSON.parse(localStorage.getItem('zearch:research-history') || '[]')
      .filter(x => /^[a-f0-9]{32}$/.test(x.id)).slice(0, 100);
  } catch {}

  function toast(text) {
    $('toast').textContent = text; $('toast').classList.add('show');
    setTimeout(() => $('toast').classList.remove('show'), 4000);
  }
  function closeRail() { $('shell').classList.remove('rail-open'); }
  function controls() {
    const mode = $('depth').value, collecting = mode === 'scrape' || mode === 'crawl';
    $('target-url').hidden = !collecting;
    $('target-url').disabled = Boolean(active) || !collecting;
    $('target-url').placeholder = mode === 'crawl' ? 'https://example.com (up to five pages)' : 'https://example.com/page';
    query.placeholder = collecting ? 'What should Zearch extract? (optional)' : 'Ask a question or compare options…';
    if (collecting) $('use-knowledge').checked = false;
    $('use-knowledge').closest('label').hidden = collecting;
    $('decide').disabled = !active && (collecting ? !$('target-url').value.trim() : !query.value.trim());
    const action = mode === 'scrape' ? 'Scrape' : mode === 'crawl' ? 'Crawl' : 'Search';
    $('decide').querySelector('span').textContent = active ? 'Stop' : action;
    $('decide').setAttribute('aria-label', active ? 'Stop research' : action);
    $('decide').dataset.busy = String(Boolean(active));
    $('depth').disabled = Boolean(active); $('use-knowledge').disabled = Boolean(active) || !workspaceReady || collecting;
    query.style.height = 'auto'; query.style.height = Math.min(query.scrollHeight, 180) + 'px';
  }
  function persistHistory() {
    try { localStorage.setItem('zearch:research-history', JSON.stringify(history)); } catch {}
    listHistory();
  }
  function listHistory() {
    $('history').replaceChildren();
    for (const item of history) {
      const li = make('li'), button = make('button', 'h-q', item.query);
      button.onclick = () => { if (!active) { location.hash = 'r/' + item.id; closeRail(); } };
      li.append(button); $('history').append(li);
    }
    if (!history.length) $('history').append(make('li', 'h-empty', 'Your discoveries will appear here.'));
  }
  function remember(run) {
    history = [{ id: run.id, query: run.query }, ...history.filter(x => x.id !== run.id)].slice(0, 100);
    persistHistory();
  }
  function showThread() {
    empty.classList.add('hidden'); form.classList.remove('home-composer'); dock.append(form, fine);
  }
  function home() {
    if (active) return;
    version++; parent = null; thread.replaceChildren(); empty.classList.remove('hidden');
    empty.insertBefore(form, notice); empty.insertBefore(fine, notice); form.classList.add('home-composer');
    window.history.replaceState(null, '', location.pathname); query.value = ''; controls(); query.focus(); closeRail();
  }
  async function api(action, fields = {}) {
    const response = await fetch('/api/workspace', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...fields })
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Could not update your workspace');
    return data.result;
  }
  async function accountApi(action, fields = {}) {
    const response = await fetch('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...fields }) });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Account unavailable');
    return data;
  }
  async function loadAccount() {
    try {
      const response = await fetch('/api/account'), data = await response.json();
      if (!response.ok) throw Error(data.error || 'Account unavailable');
      accountData = data;
      $('account-section').hidden = !data.enabled;
      $('workspace-identity').textContent = data.account ? `Signed in as ${data.account.email}. Your research follows this account across devices.` :
        data.enabled ? 'Private to this browser until you sign in. Move its research into your account explicitly.' :
        'Private to this browser session. Account sync is not configured yet.';
      $('account-status').textContent = data.account ? 'Account active' : 'Sign in with an email code';
      $('account-email-form').hidden = Boolean(data.account);
      $('account-code-form').hidden = Boolean(data.account);
      $('claim-workspace').hidden = !data.account || !data.claim_available;
      $('account-signout').hidden = !data.account;
      $('account-delete').hidden = !data.account;
    } catch (error) { $('account-section').hidden = true; }
  }
  function button(label, callback, cls = 'ghost-btn') {
    const node = make('button', cls, label); node.type = 'button';
    node.onclick = async () => {
      node.disabled = true; node.setAttribute('aria-busy', 'true');
      try { await callback(); } catch (error) { toast(error.message); }
      finally { node.disabled = false; node.removeAttribute('aria-busy'); }
    };
    return node;
  }
  function turn(run) {
    const root = make('article', 'turn'), question = make('div', 'user-message');
    const response = make('section', 'assistant-message'), status = make('p', 'research-status');
    const body = make('div', 'research-prose'), details = make('details', 'research-evidence');
    const collecting = ['scrape', 'crawl'].includes(run.depth);
    const dashboard = make('div', 'collection-dashboard'), dashboardHead = make('header', 'collection-head');
    const dashboardTitle = make('div', 'collection-title'), dashboardTarget = make('p', 'collection-target');
    const metrics = make('div', 'collection-metrics'), tabs = make('div', 'collection-tabs');
    const panels = {}, tabButtons = {}, labels = ['Overview', 'Pages', 'Media', 'Contacts', 'Data'];
    let selectedTab = 'Overview';
    let visual = null, visualConfigured = false, visualLoaded = false;
    dashboardTitle.append(make('span', 'collection-eyebrow', run.depth === 'crawl' ? 'SITE CRAWL' : 'PAGE EXTRACTION'),
      make('h2', '', 'Collection'));
    dashboardHead.append(dashboardTitle, dashboardTarget);
    tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Collection views');
    for (const label of labels) {
      const key = label.toLowerCase(), tab = make('button', 'collection-tab', label);
      tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.id = `collection-${key}-${Math.random().toString(36).slice(2)}`;
      const panel = make('section', 'collection-panel');
      panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id);
      tab.onclick = () => selectTab(label);
      tab.onkeydown = event => {
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
        event.preventDefault(); const step = event.key === 'ArrowRight' ? 1 : -1;
        const next = labels[(labels.indexOf(selectedTab) + step + labels.length) % labels.length];
        selectTab(next); tabButtons[next].focus();
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
    body.addEventListener('click', event => {
      const citation = event.target.closest('button[data-citation-id]');
      if (!citation) return;
      const card = [...sources.children].find(item => item.dataset.sourceId === citation.dataset.citationId);
      if (!card) return;
      if (collecting) selectTab('Overview');
      details.open = true;
      const capture = card.querySelector('details');
      if (capture) capture.open = true;
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      (capture?.querySelector('summary') || card).focus();
    });
    const copy = button('Copy answer', async () => { await navigator.clipboard.writeText(run.answer || ''); toast('Answer copied'); });
    const save = button('Save', async () => {
      await api('save_investigation', { id: run.id }); toast('Investigation saved'); await loadWorkspace(false);
    });
    const monitor = button('Monitor daily', async () => {
      await api('monitor_collection', { id: run.id }); monitor.hidden = true; toast('Daily monitor saved'); await loadWorkspace(false);
    });
    const exportMenu = make('details', 'export-menu');
    const exportOptions = make('div', 'export-options');
    exportMenu.append(make('summary', '', 'Export'), exportOptions);
    for (const [format, label] of [['pdf', 'PDF'], ['txt', 'Text'], ...(collecting ? [['json', 'Data JSON'], ['csv', 'Inventory CSV']] : [])]) {
      exportOptions.append(button(label, () => {
        if (!/^[a-f0-9]{32}$/.test(run.id || '')) throw Error('Saved answer unavailable');
        const link = document.createElement('a');
        link.href = '/api/artifact?id=' + run.id + '&format=' + format;
        link.download = 'zearch-' + run.id + '.' + format;
        document.body.append(link); link.click(); link.remove(); exportMenu.open = false;
      }));
    }
    actions.setAttribute('aria-label', 'Answer actions');
    actions.append(copy, exportMenu, save, monitor); response.append(status, collecting ? dashboard : body, actions, details, trace); root.append(question, response); thread.append(root);
    function update() {
      ZearchRender.render(body, run.answer || '', run.sources || [], run.status === 'complete');
      status.textContent = run.error || (['complete', 'redacted'].includes(run.status) ? '' : ['pending', 'streaming'].includes(run.status) ? 'Research in progress' : 'Partial answer');
      if (run.usage?.citation_warnings?.length) status.textContent = run.usage.citation_warnings.join(' ');
      actions.hidden = !run.answer || !['complete', 'error', 'interrupted'].includes(run.status);
      exportMenu.hidden = run.status !== 'complete';
      save.hidden = run.status !== 'complete' || ['scrape','crawl'].includes(run.depth); sources.replaceChildren();
      monitor.hidden = !collecting || run.status !== 'complete';
      for (const source of run.sources || []) {
        const li = make('li', 'evidence-card');
        li.dataset.sourceId = String(source.n);
        li.append(source.url ? ZearchRender.sourceLink(source, source.title || source.domain) : make('span', '', source.title + (source.document_id ? ' · Private document' : ' · Private note')));
        if (source.excerpt) {
          const excerpt = make('p', 'evidence-excerpt', source.excerpt);
          excerpt.title = 'Passage considered for this answer';
          li.append(excerpt);
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
        sources.append(li);
      }
      details.hidden = !sources.children.length;
      summary.textContent = `View ${sources.children.length} ${sources.children.length === 1 ? 'source' : 'sources'}`;
      if (collecting) renderCollection();
      if (collecting && run.status === 'complete' && run.id && !visualLoaded) {
        visualLoaded = true;
        fetch('/api/collection?id=' + run.id).then(response => response.json()).then(data => {
          visual = data.visual; visualConfigured = Boolean(data.configured); renderCollection();
        }).catch(() => {});
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
        if (Number.isInteger(run.estimated_cost)) lines.push(`Estimated provider cost: $${(run.estimated_cost / 1000000).toFixed(6)}`);
        traceBody.textContent = lines.join('\n');
      }
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
        metric.type = 'button'; metric.title = `Explore ${label.toLowerCase()}`;
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
      const kinds = [...new Set(media.map(item => ['image','logo','favicon'].includes(item.kind) ? 'Images' :
        item.kind === 'video' ? 'Video' : 'Other'))];
      if (kinds.length > 1) {
        const filters = make('div', 'collection-filters');
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
        card.dataset.kind = ['image','logo','favicon'].includes(item.kind) ? 'Images' : item.kind === 'video' ? 'Video' : 'Other';
        const frame = make('div', 'collection-media-frame');
        if (['image','logo','favicon'].includes(item.kind) && /^https?:\/\//i.test(item.url)) {
          const img = document.createElement('img'); img.src = item.url; img.alt = item.label || `${item.kind} from ${domain}`;
          img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.onerror = () => { img.remove(); frame.textContent = 'Preview unavailable'; };
          frame.append(img);
        } else frame.textContent = item.kind === 'video' ? 'Video' : 'Asset';
        card.append(frame, make('small', 'collection-kind', item.kind || 'media'),
          ZearchRender.sourceLink({url:item.url,title:item.label || item.url}, item.label || item.url));
        gallery.append(card);
      }
      mediaPanel.append(gallery);
      contactPanel.append(make('h3', 'collection-section-title', 'Public contact details'));
      if (!emails.size) contactPanel.append(make('p', 'collection-empty', 'No public email addresses were found in these pages.'));
      for (const [email, page] of emails) {
        const row = make('div', 'collection-contact');
        row.append(make('strong', '', email), make('small', '', `Found on ${page.title || page.url}`),
          button('Copy email', async () => { await navigator.clipboard.writeText(email); toast('Email copied'); }));
        contactPanel.append(row);
      }
      dataPanel.append(make('h3', 'collection-section-title', 'Dataset'));
      const note = make('p', 'collection-data-note', 'Page content and assets captured from this address. Download the dataset using Export below.');
      dataPanel.append(note);
      const fields = make('dl', 'collection-fields');
      for (const [key, value] of [['Target', run.target_url || '—'], ['Scope', run.depth === 'crawl' ? 'Bounded site crawl' : 'Single page'],
        ['Pages captured', String(pages.length)], ['Media links', String(media.length)], ['Public emails', String(emails.size)]]) {
        fields.append(make('dt', '', key), make('dd', '', value));
      }
      dataPanel.append(fields);
      const decision = run.usage?.judgment;
      if (decision?.gate) {
        const jev = make('div', 'collection-decision');
        jev.append(make('strong', '', decision.gate === 'answer' ? 'Evidence reviewed' :
          decision.gate === 'review' ? 'Check conflicting sources' : 'Limited direct evidence'),
          make('small', '', `${pages.length} captured ${pages.length === 1 ? 'page' : 'pages'} available to inspect in the Pages tab.`));
        dataPanel.append(jev);
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
        visual?.status === 'queued' ? 'Queued for Zearch’s browser worker.' :
        visual?.status === 'running' ? 'Rendering the page in Zearch’s browser worker…' :
        visualConfigured ? 'Capture a rendered page and its design tokens.' : 'Visual capture is available when the Zearch browser worker is enabled.'));
      if (visualConfigured && run.status === 'complete' && (!visual || visual.retryable)) {
        visualSection.append(button(visual ? 'Retry visual capture' : 'Queue visual capture', async () => {
          const response = await fetch('/api/collection?id=' + run.id, { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
          const data = await response.json(); if (!response.ok) throw Error(data.error || 'Capture unavailable');
          visual = data; renderCollection();
        }));
      }
      if (visual?.status === 'queued' || visual?.status === 'running') {
        visualSection.append(button('Refresh capture status', async () => {
          const response = await fetch('/api/collection?id=' + run.id);
          const data = await response.json(); if (!response.ok) throw Error(data.error || 'Capture unavailable');
          visual = data.visual; renderCollection();
        }));
      }
      dataPanel.append(visualSection);
      const exportHint = make('p', 'collection-data-note', run.status === 'complete' ?
        'Use Export below to download the full JSON dataset or a flat CSV inventory.' : 'Exports become available when the collection finishes.');
      dataPanel.append(exportHint);
    }
    update(); return { run, update, status, body, root };
  }
  async function route() {
    if (active) return;
    const id = location.hash.match(/^#r\/([a-f0-9]{32})$/)?.[1];
    if (!id) return home();
    const revision = ++version;
    try {
      const records = [], seen = new Set(); let next = id;
      while (next && records.length < 20 && !seen.has(next)) {
        seen.add(next);
        const response = await fetch('/api/research?id=' + next), record = await response.json();
        if (!response.ok) throw Error(record.error || 'Could not open research');
        records.unshift(record); next = record.parent_id;
      }
      if (revision !== version) return;
      thread.replaceChildren(); showThread(); records.forEach(turn);
      parent = records.at(-1)?.status === 'complete' ? id : null;
      if (next) toast('Showing the latest 20 answers');
    } catch (error) { if (revision === version) { home(); toast(error.message); } }
  }
  async function submit(event) {
    event.preventDefault();
    if (active) { active.abort(); return; }
    const mode = $('depth').value, collecting = mode === 'scrape' || mode === 'crawl';
    const targetUrl = collecting ? $('target-url').value.trim() : null;
    const question = query.value.trim() || (mode === 'scrape' ? 'Summarize this page and extract its key facts.' : mode === 'crawl' ? 'Summarize the core product and main sections from the captured pages of this site.' : '');
    if (!question || (collecting && !targetUrl)) return;
    version++; active = new AbortController(); showThread();
    const view = turn({ query: question, target_url: targetUrl, depth: mode, answer: '', sources: [], status: 'pending' });
    query.value = ''; controls(); let complete = false, paintPending = false;
    const paint = () => {
      if (paintPending) return;
      paintPending = true;
      requestAnimationFrame(() => {
        paintPending = false;
        ZearchRender.render(view.body, view.run.answer, view.run.sources, complete);
      });
    };
    function accept(data) {
      const feed = $('feed'), follow = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
      if (data.type === 'start') { view.run.id = data.id; remember(view.run); window.history.replaceState(null, '', '#r/' + data.id); }
      if (data.type === 'status') view.status.textContent = data.text;
      if (data.type === 'research') view.run.usage = data.report;
      if (data.type === 'sources') { view.run.sources = data.sources; view.update(); }
      if (data.type === 'delta') { view.run.answer += data.text; paint(); }
      if (data.type === 'complete') { Object.assign(view.run, data.run); parent = data.run.id; complete = true; view.update(); }
      if (data.type === 'error') throw Error(data.error);
      if (follow) requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
    }
    try {
      const response = await fetch('/api/research', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: active.signal,
        body: JSON.stringify({ query: question, target_url: targetUrl, parent_id: parent, request_id: crypto.randomUUID(), depth: mode, use_knowledge: $('use-knowledge').checked })
      });
      if (!response.ok) { const data = await response.json(); throw Error(data.error || 'Research unavailable'); }
      if (response.headers.get('Content-Type')?.includes('application/json')) {
        const data = await response.json(); Object.assign(view.run, data.run); view.update();
        complete = data.run.status === 'complete'; if (complete) parent = data.run.id;
      } else {
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
        try {
          while (true) {
            const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
            let at;
            while ((at = buffer.indexOf('\n')) >= 0) {
              const line = buffer.slice(0, at); buffer = buffer.slice(at + 1);
              if (line.trim()) accept(JSON.parse(line));
            }
            if (done) break;
          }
        } finally { reader.releaseLock(); }
      }
      if (!complete) throw Error('Research ended before completion. Any partial answer is incomplete.');
    } catch (error) {
      active.abort();
      const message = error.name === 'AbortError' ? 'Stopped · any partial answer is incomplete.' : error.message;
      if (!view.run.id) {
        view.root.remove(); query.value = question;
        if (collecting) $('target-url').value = targetUrl;
        if (!thread.childElementCount) {
          empty.classList.remove('hidden'); empty.insertBefore(form, notice);
          empty.insertBefore(fine, notice); form.classList.add('home-composer');
          notice.textContent = message;
        } else toast(message);
      } else {
        view.run.status = 'interrupted'; view.run.error = message; view.update();
      }
    } finally { active = null; controls(); query.focus(); loadWorkspace(false); }
  }

  function renderWorkspace() {
    const data = workspaceData, allowance = data.allowance;
    $('workspace-status').textContent = allowance ? `${allowance.plan} · ${allowance.used}/${allowance.daily_limit} daily runs used · resets ${allowance.reset}. Provider spending caps also apply.` : '';
    $('notes-list').replaceChildren(); $('documents-list').replaceChildren(); $('research-list').replaceChildren(); $('investigations-list').replaceChildren(); $('batches-list').replaceChildren();
    for (const note of data.notes) {
      const li = make('li'); li.append(make('span', '', note.title), button('Delete note', async () => {
        if (!window.confirm('Delete this stored note and redact retained answers that used it?')) return;
        await api('delete_note', { id: note.id }); await loadWorkspace();
      })); $('notes-list').append(li);
    }
    for (const document of data.documents || []) {
      const li = make('li'); li.append(make('span', '', document.filename), button('Delete document', async () => {
        if (!window.confirm('Delete this document and redact retained answers that used it?')) return;
        await api('delete_document', { id: document.id }); await loadWorkspace(); toast('Document deleted');
      })); $('documents-list').append(li);
    }
    for (const item of data.history) {
      const li = make('li');
      li.append(button(item.query, () => { if (!active) { $('workspace').close(); location.hash = 'r/' + item.id; } }, 'workspace-title'));
      li.append(button('Delete answer', async () => {
        if (active) throw Error('Wait for the current research to finish');
        if (!window.confirm('Delete this answer and its evidence from the server? Follow-up answers derived from it will be redacted.')) return;
        await api('delete_run', { id: item.id });
        if (location.hash === '#r/' + item.id) home();
        await loadWorkspace();
      })); $('research-list').append(li);
    }
    for (const item of data.investigations) {
      const li = make('li', 'investigation-item'), actions = make('div', 'turn-actions');
      li.append(make('p', 'workspace-title', `${item.depth === 'scrape' || item.depth === 'crawl' ? 'Site monitor' : 'Investigation'} · ${item.query}`));
      if (item.target_url) li.append(make('p', 'hint', item.target_url));
      const changes = item.last_changes;
      const summary = changes.check ? `${changes.added.length} new sources · ${changes.changed.length} changed excerpts · ${changes.removed.length} removed sources.${changes.answer_changed ? ' Answer changed; review the saved runs before relying on it.' : ''} No verified fact-change alert was sent.` : 'No refresh comparison yet.';
      li.append(make('p', 'hint', summary));
      if (item.job) li.append(make('p', 'hint', item.job.error || `Refresh ${item.job.status}`));
      if (item.last_run) actions.append(button('Open latest', () => { if (!active) { $('workspace').close(); location.hash = 'r/' + item.last_run; } }));
      if (data.discovery_enabled) {
        actions.append(button('Refresh', async () => { await api('refresh', { id: item.id }); toast('Refresh queued'); await loadWorkspace(); }));
        const select = make('select', 'depth-select'); select.setAttribute('aria-label', 'Refresh schedule for ' + item.query);
        for (const [value, text] of [[0, 'Paused'], [24, 'Daily'], [168, 'Weekly']]) {
          const option = make('option', '', text); option.value = value; select.append(option);
        }
        select.value = item.interval_hours;
        select.onchange = async () => {
          select.disabled = true;
          try { await api('schedule', { id: item.id, hours: Number(select.value) }); await loadWorkspace(); }
          catch (error) { select.value = item.interval_hours; toast(error.message); }
          finally { select.disabled = false; }
        };
        actions.append(select);
      } else li.append(make('p', 'hint', 'Refresh scheduling becomes available when the discovery worker is configured.'));
      actions.append(button('Remove', async () => {
        if (!window.confirm('Remove this investigation and its schedule? Saved answers will remain.')) return;
        await api('delete_investigation', { id: item.id }); await loadWorkspace();
      })); li.append(actions); $('investigations-list').append(li);
    }
    $('batch-form').querySelector('button').disabled = !data.discovery_enabled;
    $('batch-disabled').hidden = Boolean(data.discovery_enabled);
    for (const batch of data.batches || []) {
      const li = make('li', 'investigation-item'), actions = make('div', 'turn-actions');
      li.append(make('p', 'workspace-title', `${batch.items.filter(x => x.status === 'complete').length}/${batch.items.length} pages · ${batch.status}`));
      for (const item of batch.items) {
        const row = make('div', 'batch-row'); row.append(make('span', '', item.target_url), make('small', '', item.error || item.status));
        if (item.run_id) row.append(button('Open', () => { $('workspace').close(); location.hash = 'r/' + item.run_id; }));
        li.append(row);
      }
      if (['queued','running'].includes(batch.status)) actions.append(button('Cancel queued', async () => {
        await api('cancel_batch', { id: batch.id }); await loadWorkspace();
      }));
      li.append(actions); $('batches-list').append(li);
    }
    for (const id of ['notes-list', 'documents-list', 'research-list', 'investigations-list', 'batches-list']) {
      if (!$(id).children.length) $(id).append(make('li', 'hint', 'Nothing saved here yet.'));
    }
  }
  async function loadWorkspace(showErrors = true) {
    try {
      const response = await fetch('/api/workspace'), data = await response.json();
      if (!response.ok) throw Error(data.error || 'Workspace unavailable');
      workspaceData = data; workspaceReady = true; history = data.history;
      persistHistory(); renderWorkspace(); controls();
    } catch (error) {
      workspaceReady = false; controls();
      if (showErrors) $('workspace-status').textContent = error.message;
    }
  }
  $('btn-workspace').onclick = () => { $('workspace').showModal(); closeRail(); loadWorkspace(); loadAccount(); };
  $('workspace-close').onclick = () => $('workspace').close();
  $('note-form').onsubmit = async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true;
    try {
      await api('add_note', { title: $('note-title').value, body: $('note-body').value });
      $('note-form').reset(); await loadWorkspace(); toast('Note saved');
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('batch-form').onsubmit = async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true;
    try {
      const urls = $('batch-urls').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
      await api('create_batch', { urls, query: $('batch-query').value });
      $('batch-form').reset(); await loadWorkspace(); toast('Batch queued');
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('note-file').onchange = async () => {
    const file = $('note-file').files[0]; if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 160000) { toast('Choose a .txt or .md file under 160 KB'); $('note-file').value = ''; return; }
    const text = await file.text();
    if (text.length > 40000 || text.includes('\0')) { toast('Use plain text up to 40,000 characters'); return; }
    $('note-body').value = text; if (!$('note-title').value) $('note-title').value = file.name.slice(0, 120);
  };
  $('document-form').onsubmit = async event => {
    event.preventDefault(); const file = $('document-file').files[0], submit = event.submitter;
    if (!file || !/\.(txt|md|docx)$/i.test(file.name) || file.size > 128000) { toast('Choose a .txt, .md or .docx file under 128 KB'); return; }
    submit.disabled = true;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (let at = 0; at < bytes.length; at += 8192) binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
      await api('add_document', { filename: file.name, content_base64: btoa(binary) });
      $('document-form').reset(); await loadWorkspace(); toast('Document imported');
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('account-email-form').onsubmit = async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true;
    try {
      await accountApi('request_code', { email: $('account-email').value });
      $('account-code-form').hidden = false;
      $('account-status').textContent = 'If delivery is available, check your email for the code.';
      $('account-code').focus();
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('account-code-form').onsubmit = async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true;
    try {
      await accountApi('verify_code', { email: $('account-email').value, code: $('account-code').value });
      $('account-code').value = ''; await loadAccount(); await loadWorkspace(); home(); toast('Signed in');
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('claim-workspace').onclick = async () => {
    if (active) { toast('Wait for current research to finish'); return; }
    const control = $('claim-workspace'); control.disabled = true;
    try { await accountApi('claim_workspace'); await loadWorkspace(); await loadAccount(); toast('Browser workspace moved to your account'); }
    catch (error) { toast(error.message); } finally { control.disabled = false; }
  };
  $('account-signout').onclick = async () => {
    if (active) { toast('Wait for current research to finish'); return; }
    try { await accountApi('sign_out'); history = []; persistHistory(); home(); await loadAccount(); await loadWorkspace(); toast('Signed out'); }
    catch (error) { toast(error.message); }
  };
  $('account-delete').onclick = async () => {
    if (active) { toast('Wait for current research to finish'); return; }
    if (!window.confirm('Permanently delete this account, its saved research, private knowledge and active sessions on every device?')) return;
    try { await accountApi('delete_account'); history = []; persistHistory(); home(); await loadAccount(); await loadWorkspace(); toast('Account deleted'); }
    catch (error) { toast(error.message); }
  };
  $('export-workspace').onclick = async () => {
    const control = $('export-workspace'); control.disabled = true;
    try {
      const exportData = { version: 1, exported_at: new Date().toISOString(), account: null, notes: [], documents: [], investigations: [], runs: [] };
      let cursor = null, pages = 0;
      do {
        const response = await fetch('/api/workspace?export=1' + (cursor ? '&cursor=' + cursor : ''));
        const page = await response.json(); if (!response.ok) throw Error(page.error || 'Could not export data');
        if (!cursor) exportData.account = page.account;
        exportData.notes.push(...page.notes); exportData.documents.push(...page.documents); exportData.investigations.push(...page.investigations); exportData.runs.push(...page.runs);
        cursor = page.next_cursor;
        if (++pages > 1000) throw Error('Export is too large to download in the browser');
      } while (cursor);
      const url = URL.createObjectURL(new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = 'zearch-workspace.json';
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast('Workspace download started');
    } catch (error) { toast(error.message); } finally { control.disabled = false; }
  };
  $('delete-workspace').onclick = async () => {
    if (active) { toast('Wait for current research to finish'); return; }
    if (!window.confirm('Permanently delete all saved answers, notes, investigations and evidence in this browser workspace?')) return;
    const control = $('delete-workspace'); control.disabled = true;
    try {
      await api('delete_workspace'); history = []; persistHistory(); home(); await loadWorkspace(); toast('Workspace deleted');
    } catch (error) { toast(error.message); } finally { control.disabled = false; }
  };
  form.addEventListener('submit', submit); query.addEventListener('input', controls);
  $('target-url').addEventListener('input', controls); $('depth').addEventListener('change', controls);
  query.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });
  $('new-btn').onclick = home; $('brand').onclick = event => { event.preventDefault(); home(); };
  $('clear-history').onclick = () => { history = []; persistHistory(); toast('Local shortcuts cleared; saved research remains in your workspace'); };
  $('btn-settings').onclick = () => $('settings').showModal(); $('btn-thesis').onclick = () => $('thesis').showModal();
  $('menu-btn').onclick = () => $('shell').classList.add('rail-open'); $('rail-close').onclick = closeRail; $('scrim').onclick = closeRail;
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); home(); }
    if (event.key === 'Escape') closeRail();
  });
  window.addEventListener('hashchange', route);
  listHistory(); controls(); route();
  // Initialize the session before enabling requests to avoid competing new cookies.
  loadWorkspace(false).then(() => fetch('/api/research')).then(response => {
    if (!response.ok) throw Error(); return response.json();
  }).then(data => {
    available = data.available;
    notice.textContent = available ? '' : 'Research setup is incomplete. You can send a question to check its status.'; controls();
  }).catch(() => { notice.textContent = 'Research is temporarily unavailable. Please try again later.'; });
})();
