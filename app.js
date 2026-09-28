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
  let workspaceData = { notes: [], investigations: [], history: [] };
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
    $('decide').disabled = !active && !query.value.trim();
    $('decide').querySelector('span').textContent = active ? 'Stop' : 'Search';
    $('decide').setAttribute('aria-label', active ? 'Stop research' : 'Search');
    $('decide').dataset.busy = String(Boolean(active));
    $('depth').disabled = Boolean(active); $('use-knowledge').disabled = Boolean(active) || !workspaceReady;
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
  function button(label, callback, cls = 'ghost-btn') {
    const node = make('button', cls, label); node.type = 'button';
    node.onclick = async () => {
      node.disabled = true;
      try { await callback(); } catch (error) { toast(error.message); }
      finally { node.disabled = false; }
    };
    return node;
  }
  function turn(run) {
    const root = make('article', 'turn'), question = make('div', 'user-message');
    const response = make('section', 'assistant-message'), status = make('p', 'research-status');
    const body = make('div', 'research-prose'), details = make('details', 'research-evidence');
    const summary = make('summary'), sources = make('ol'), actions = make('div', 'turn-actions');
    const trace = make('details', 'research-trace'), traceTitle = make('summary', '', 'Research approach');
    const traceBody = make('p'); trace.append(traceTitle, traceBody); trace.hidden = true;
    question.append(make('div', 'user-bubble', run.query));
    response.setAttribute('aria-label', 'Zearch answer'); status.setAttribute('role', 'status');
    details.append(summary, sources);
    body.addEventListener('click', event => {
      const citation = event.target.closest('button[data-citation-id]');
      if (!citation) return;
      const card = [...sources.children].find(item => item.dataset.sourceId === citation.dataset.citationId);
      if (!card) return;
      details.open = true;
      const capture = card.querySelector('details');
      if (capture) capture.open = true;
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      (capture?.querySelector('summary') || card).focus();
    });
    const copy = button('Copy', async () => { await navigator.clipboard.writeText(run.answer || ''); toast('Answer copied'); });
    const save = button('Save investigation', async () => {
      await api('save_investigation', { id: run.id }); toast('Investigation saved'); await loadWorkspace(false);
    });
    actions.append(copy, save); response.append(status, body, details, trace, actions); root.append(question, response); thread.append(root);
    function update() {
      ZearchRender.render(body, run.answer || '', run.sources || [], run.status === 'complete');
      status.textContent = run.error || (['complete', 'redacted'].includes(run.status) ? '' : ['pending', 'streaming'].includes(run.status) ? 'Research in progress' : 'Partial answer');
      if (run.usage?.citation_warnings?.length) status.textContent = run.usage.citation_warnings.join(' ');
      actions.hidden = !run.answer || !['complete', 'error', 'interrupted'].includes(run.status);
      save.hidden = run.status !== 'complete'; sources.replaceChildren();
      for (const source of run.sources || []) {
        const li = make('li');
        li.dataset.sourceId = String(source.n);
        li.append(source.url ? ZearchRender.sourceLink(source, source.title || source.domain) : make('span', '', source.title + ' · Private note'));
        li.append(make('p', '', source.evidence_span ? `Jev inspected: ${source.excerpt}` : source.excerpt));
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
      details.hidden = !sources.children.length; summary.textContent = sources.children.length + (sources.children.length === 1 ? ' source' : ' sources');
      if (run.usage?.queries || run.usage?.judgment || run.usage?.market_data) {
        trace.hidden = false;
        const lines = [];
        if (run.usage.queries) lines.push(`${run.usage.search_calls} search attempts · ${run.usage.failed_searches || 0} failed. ${run.usage.ranking}.`, ...run.usage.queries);
        if (run.usage.market_data) lines.push(`Market data: ${run.usage.market_data}`);
        if (run.usage.judgment) lines.push(`Jev evidence decision: ${run.usage.judgment.gate}`);
        if (run.usage.answer_format) lines.push(`Answer path: ${run.usage.answer_format}`);
        if (run.usage.scrape_calls || run.usage.cache_hits) lines.push(`Page extracts: ${run.usage.scrape_calls || 0} new · ${run.usage.cache_hits || 0} reused`);
        if (run.usage.draft_fallback_reason) lines.push(`Draft fallback: ${run.usage.draft_fallback_reason.replaceAll('_', ' ')}`);
        if (run.usage.total_ms != null) lines.push(`Research time: ${(run.usage.total_ms / 1000).toFixed(1)}s`);
        if (Number.isInteger(run.estimated_cost)) lines.push(`Estimated provider cost: $${(run.estimated_cost / 1000000).toFixed(6)}`);
        traceBody.textContent = lines.join('\n');
      }
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
    const question = query.value.trim(); if (!question) return;
    version++; active = new AbortController(); showThread();
    const view = turn({ query: question, answer: '', sources: [], status: 'pending' });
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
        body: JSON.stringify({ query: question, parent_id: parent, request_id: crypto.randomUUID(), depth: $('depth').value, use_knowledge: $('use-knowledge').checked })
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
    $('notes-list').replaceChildren(); $('research-list').replaceChildren(); $('investigations-list').replaceChildren();
    for (const note of data.notes) {
      const li = make('li'); li.append(make('span', '', note.title), button('Delete note', async () => {
        if (!window.confirm('Delete this stored note? Existing answers containing it will remain until separately deleted.')) return;
        await api('delete_note', { id: note.id }); await loadWorkspace();
      })); $('notes-list').append(li);
    }
    for (const item of data.history) {
      const li = make('li');
      li.append(button(item.query, () => { if (!active) { $('workspace').close(); location.hash = 'r/' + item.id; } }, 'workspace-title'));
      li.append(button('Delete answer', async () => {
        if (active) throw Error('Wait for the current research to finish');
        if (!window.confirm('Delete this answer and its evidence from the server? Follow-up answers remain.')) return;
        await api('delete_run', { id: item.id });
        if (location.hash === '#r/' + item.id) home();
        await loadWorkspace();
      })); $('research-list').append(li);
    }
    for (const item of data.investigations) {
      const li = make('li', 'investigation-item'), actions = make('div', 'turn-actions');
      li.append(make('p', 'workspace-title', item.query));
      const changes = item.last_changes;
      const summary = changes.check ? `${changes.added.length} new sources · ${changes.changed.length} changed excerpts · ${changes.removed.length} removed sources. Text changes do not necessarily mean facts changed.` : 'No refresh comparison yet.';
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
    for (const id of ['notes-list', 'research-list', 'investigations-list']) {
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
  $('btn-workspace').onclick = () => { $('workspace').showModal(); closeRail(); loadWorkspace(); };
  $('workspace-close').onclick = () => $('workspace').close();
  $('note-form').onsubmit = async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true;
    try {
      await api('add_note', { title: $('note-title').value, body: $('note-body').value });
      $('note-form').reset(); await loadWorkspace(); toast('Note saved');
    } catch (error) { toast(error.message); } finally { submit.disabled = false; }
  };
  $('note-file').onchange = async () => {
    const file = $('note-file').files[0]; if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 160000) { toast('Choose a .txt or .md file under 160 KB'); $('note-file').value = ''; return; }
    const text = await file.text();
    if (text.length > 40000 || text.includes('\0')) { toast('Use plain text up to 40,000 characters'); return; }
    $('note-body').value = text; if (!$('note-title').value) $('note-title').value = file.name.slice(0, 120);
  };
  $('export-workspace').onclick = async () => {
    const control = $('export-workspace'); control.disabled = true;
    try {
      const exportData = { version: 1, exported_at: new Date().toISOString(), notes: [], investigations: [], runs: [] };
      let cursor = null, pages = 0;
      do {
        const response = await fetch('/api/workspace?export=1' + (cursor ? '&cursor=' + cursor : ''));
        const page = await response.json(); if (!response.ok) throw Error(page.error || 'Could not export data');
        exportData.notes.push(...page.notes); exportData.investigations.push(...page.investigations); exportData.runs.push(...page.runs);
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
