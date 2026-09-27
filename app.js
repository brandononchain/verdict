/* Zearch search interface. Search → evidence pack → typed judgment → confidence gate. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const LS = { settings: "zearch:settings", history: "zearch:history", cache: "zearch:cache" };

  // tiny DOM builder — all text goes through textContent (no HTML injection)
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* quota */ } };
  const pct = (p) => `${Math.round(p * 100)}%`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);

  const els = {
    shell: $("#shell"), stage: $(".stage"), feed: $("#feed"), empty: $("#empty"), thread: $("#thread"),
    starters: $("#starters"), history: $("#history"), crumbs: $("#crumbs"),
    form: $("#composer"), q: $("#query"), pb: $("#playbook"), decide: $("#decide"),
    share: $("#share-btn"), toast: $("#toast"), fineprint: $(".fineprint"), dock: $(".dock-inner"),
    settings: $("#settings"), thesis: $("#thesis"), endpoint: $("#endpoint"), key: $("#api-key"),
    threshold: $("#threshold"), thresholdVal: $("#threshold-val"), keyHint: $("#key-hint"),
  };

  const state = {
    playbooks: {},
    serverKey: false,
    settings: Object.assign({ endpoint: "auto", key: "", threshold: null, playbook: "invest" }, load(LS.settings, load("verdict:settings", {}))),
    history: load(LS.history, load("verdict:history", [])),
    cache: load(LS.cache, load("verdict:cache", {})),
    busy: false,
    current: null,
  };


  const STARTERS = [
    { pb: "invest", label: "Research a decision", q: "Should our team build this feature now or wait?" },
    { pb: "risk", label: "Assess a risk", q: "Should we approve this request or send it for review?" },
    { pb: "compare", label: "Compare options", q: "Compare two options for my use case." },
  ];

  // ───────────────────────── boot
  async function boot() {
    try {
      const r = await fetch("/api/playbooks");
      const d = await r.json();
      state.playbooks = d.playbooks;
      state.serverKey = d.server_key;
    } catch {
      toast("Server unreachable — run python3 server.py");
    }
    if (!state.playbooks[state.settings.playbook]) state.settings.playbook = Object.keys(state.playbooks)[0] || "invest";
    renderPlaybooks();
    renderStarters();
    renderHistory();
    bind();
    homeComposer();
    route();
  }

  // ───────────────────────── render: chrome
  function renderPlaybooks() {
    els.pb.replaceChildren();
    for (const [id, pb] of Object.entries(state.playbooks)) {
      els.pb.append(h("option", { value: id }, pb.name));
    }
    els.pb.value = state.settings.playbook;
  }

  function setPlaybook(id) {
    state.settings.playbook = id;
    store(LS.settings, state.settings);
    els.pb.value = id;
  }

  function thresholdFor(id) {
    return state.settings.threshold ?? state.playbooks[id]?.threshold ?? 0.7;
  }

  function renderStarters() {
    els.starters.replaceChildren(...STARTERS.map((s, i) => h("button", {
      type: "button", class: "starter", style: `animation-delay:${120 + i * 70}ms`,
      onclick: () => { setPlaybook(s.pb); els.q.value = s.q; autosize(); run(); },
    }, h("span", { class: "starter-label" }, s.label), h("span", { class: "starter-prompt" }, s.q))));
  }

  function renderHistory() {
    els.history.replaceChildren();
    if (!state.history.length) {
      els.history.append(h("li", { class: "h-empty" }, "Your recent searches will appear here."));
      return;
    }
    for (const item of state.history) {
      els.history.append(h("li", {}, h("button", {
        type: "button", title: item.query, "aria-current": String(state.current === item.id),
        onclick: () => { location.hash = `v/${item.id}`; closeRail(); },
      }, h("span", { class: `dot ${item.gate}` }), h("span", { class: "h-q" }, item.query))));
    }
  }

  function setCrumb(text) {
    els.crumbs.replaceChildren(h("span", {}, "Zearch"), h("em", {}, "/"), h("b", {}, text));
  }

  // ───────────────────────── render: conversational answer
  function renderTurn(v) {
    const p = v.policy;
    const primary = v.answers.find((a) => a.id === p.primary);
    const others = v.answers.filter((a) => a.id !== p.primary);
    const sourceLink = (s) => {
      const url = safeUrl(s.url);
      return h(url ? "a" : "span", url ? { href: url, target: "_blank", rel: "noopener noreferrer", class: "source-link" } : { class: "source-link" },
        h("span", { class: "source-number" }, s.n),
        h("span", { class: "source-title", title: s.title }, s.title || s.domain));
    };
    const sources = v.sources.length
      ? h("section", { class: "source-block", "aria-label": "Sources" },
          h("div", { class: "source-heading" }, h("span", {}, "Sources"), h("span", {}, `${v.sources.length}`)),
          h("div", { class: "source-chips" }, v.sources.slice(0, 3).map(sourceLink)),
          v.sources.length > 3 && h("details", { class: "more-sources" },
            h("summary", {}, `View all ${v.sources.length} sources`),
            h("ol", { class: "source-list" }, v.sources.map((s) => h("li", {},
              sourceLink(s), h("span", { class: "source-domain" }, `${s.domain} · ${s.source}`),
              h("p", {}, s.snippet))))))
      : h("p", { class: "no-src" }, "No web sources were returned for this search.");

    const detailSummary = h("div", { class: "detail-summary" },
      h("div", { class: "confidence-line" },
        h("span", { class: `gate gate-${p.gate}` }, h("i"), p.gate),
        h("span", {}, `${pct(p.confidence)} confidence`)),
      h("div", { class: "confidence-track" },
        h("i", { style: `width:${pct(p.confidence)}` }),
        h("b", { style: `left:${pct(p.threshold)}` })));
    const detailParts = [
      h("div", { class: "detail-checks" }, p.reasons.map((r) => h("span", {}, r))),
      others.length && h("div", { class: "typed-answers" }, h("h3", {}, "Other signals"), others.map((a, i) => answerCard(a, i))),
      h("details", { class: "raw-state" }, h("summary", {}, `Structured state sent to JEV · ${v.state.length} characters`), h("pre", {}, v.state)),
      h("div", { class: "runtime-note" }, `${v.playbook_name} · ${v.mode === "mock" ? "Mock engine" : `${v.mode} · ${v.model}`} · ${v.timing.search_ms} ms search`),
      v.warning && h("p", { class: "warn" }, v.warning),
    ];

    const turn = h("article", { class: "turn", "data-id": v.id },
      h("div", { class: "user-message" }, h("div", { class: "user-bubble" }, v.query)),
      h("section", { class: "assistant-message", "aria-label": "Zearch answer" },
        h("div", { class: "assistant-brand" },
          h("span", {}, "Zearch"),
          h("span", { class: "answer-label" }, "Answer")),
        h("div", { class: "answer-pick" }, p.pick || primary?.pick || "Search complete"),
        h("p", { class: "answer-summary" }, p.summary),
        detailSummary,
        sources,
        h("details", { class: "reasoning" },
          h("summary", {}, "How this answer was reached"),
          h("div", { class: "reasoning-body" }, detailParts)),
        h("div", { class: "turn-actions" },
          h("button", { class: "text-action", type: "button", title: "Copy share link", onclick: () => share(v) }, "Share"),
          h("button", { class: "text-action", type: "button", title: "Copy result data", onclick: () => copy(JSON.stringify(v, null, 2), "Search data copied") }, "Copy data"),
          h("button", { class: "text-action", type: "button", title: "Run this search again", onclick: () => { setPlaybook(v.playbook); els.q.value = v.query; autosize(); run(); } }, "Run again"))));

    requestAnimationFrame(() => requestAnimationFrame(() => {
      turn.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w; });
    }));
    return turn;
  }

  function answerCard(a, i) {
    const pick = a.type === "score" ? `${a.pick} · ${a.score.toFixed(2)}/${a.max}` : a.type === "noul" ? `${a.pick} · p=${a.noul.toFixed(2)}` : a.pick;
    const best = Math.max(...a.options.map((o) => o.p));
    return h("div", { class: "q", style: `animation-delay:${80 + i * 60}ms` },
      h("div", { class: "q-top" }, h("span", { class: "q-id" }, a.id), h("span", { class: "q-type" }, a.type)),
      h("div", { class: "q-pick" }, pick),
      h("p", { class: "q-ins" }, a.instructions),
      a.options.map((o) => h("div", { class: `opt${o.p === best ? " on" : ""}` },
        h("span", { class: "opt-name", title: o.desc || o.label }, o.label),
        h("span", { class: "opt-bar" }, h("i", { "data-w": pct(o.p) })),
        h("span", { class: "opt-p" }, pct(o.p)))));
  }

  // ───────────────────────── run
  async function run() {
    const query = els.q.value.trim();
    if (!query || state.busy) return;
    const playbook = els.pb.value;
    state.busy = true;
    els.decide.disabled = true;
    els.decide.classList.add("busy");
    els.decide.querySelector("span").textContent = "Searching";
    els.q.value = "";
    autosize();
    showThread();
    setCrumb(query);
    const status = h("p", { class: "pending-status" }, h("i", { "aria-hidden": "true" }), "Searching the web…");
    const pending = h("article", { class: "turn pending" },
      h("div", { class: "user-message" }, h("div", { class: "user-bubble" }, query)),
      h("section", { class: "assistant-message" },
        h("div", { class: "assistant-brand" }, h("span", {}, "Zearch")),
        status, h("div", { class: "skel" })));
    els.thread.append(pending);
    pending.scrollIntoView({ behavior: "smooth", block: "start" });

    const t0 = performance.now();
    try {
      const pack = await api("/api/search", { query, playbook });
      status.lastChild.textContent = `Reviewing ${pack.sources.length} sources…`;
      await sleep(220);
      const pb = state.playbooks[playbook];
      status.lastChild.textContent = "Weighing the evidence…";
      const tj = performance.now();
      const v = await api("/api/decide", {
        query, playbook, pack,
        endpoint: state.settings.endpoint,
        key: state.settings.key || undefined,
        threshold: state.settings.threshold,
      });
      const spent = performance.now() - tj;
      if (spent < 650) await sleep(650 - spent); // let the judge visibly fire

      remember(v);
      state.current = v.id;
      history.replaceState(null, "", `#v/${v.id}`);
      pending.replaceWith(renderTurn(v));
      els.share.classList.remove("hidden");
      renderHistory();
      const total = Math.round(performance.now() - t0);
      toast(`${v.policy.gate.toUpperCase()} · ${v.policy.pick} · ${pct(v.policy.confidence)} · ${total}ms`);
    } catch (e) {
      pending.replaceWith(h("article", { class: "turn" },
        h("div", { class: "user-message" }, h("div", { class: "user-bubble" }, query)),
        h("section", { class: "assistant-message" }, h("div", { class: "err" }, `Search failed: ${e.message}`))));
      els.q.value = query;
      autosize();
    } finally {
      state.busy = false;
      els.decide.disabled = !els.q.value.trim();
      els.decide.classList.remove("busy");
      els.decide.querySelector("span").textContent = "Search";
    }
  }

  async function api(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  }

  function remember(v) {
    state.history = [{ id: v.id, query: v.query, gate: v.policy.gate, playbook: v.playbook, created: v.created },
      ...state.history.filter((x) => x.id !== v.id)].slice(0, 60);
    state.cache[v.id] = v;
    const keep = new Set(state.history.slice(0, 30).map((x) => x.id));
    for (const k of Object.keys(state.cache)) if (!keep.has(k)) delete state.cache[k];
    store(LS.history, state.history);
    store(LS.cache, state.cache);
  }

  // ───────────────────────── routing
  function homeComposer() {
    els.form.classList.add("home-composer");
    els.fineprint.classList.add("home-fineprint");
    els.empty.append(els.form, els.fineprint, els.starters);
  }
  function showThread() {
    els.empty.classList.add("hidden");
    els.form.classList.remove("home-composer");
    els.fineprint.classList.remove("home-fineprint");
    els.dock.append(els.form, els.fineprint);
  }
  function newSearch() {
    state.current = null;
    els.thread.replaceChildren();
    els.empty.classList.remove("hidden");
    els.share.classList.add("hidden");
    homeComposer();
    setCrumb("New");
    renderHistory();
    if (location.hash) history.replaceState(null, "", location.pathname);
    els.q.focus();
  }

  async function route() {
    const shared = location.hash.match(/^#s\/([\w-]+)$/);
    if (shared) {
      try {
        const base64 = shared[1].replace(/-/g, "+").replace(/_/g, "/");
        const padded = base64 + "=".repeat((4 - base64.length % 4) % 4);
        const decoded = new TextDecoder().decode(Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)));
        const v = JSON.parse(decoded);
        if (!v?.id || !v?.policy || !Array.isArray(v.sources)) throw new Error("invalid share");
        state.current = v.id;
        state.cache[v.id] = v;
        showThread();
        els.thread.replaceChildren(renderTurn(v));
        els.share.classList.remove("hidden");
        setCrumb(v.query);
        els.feed.scrollTop = 0;
        return;
      } catch { toast("This share link is invalid"); return newSearch(); }
    }
    const m = location.hash.match(/^#v\/([\w-]+)$/);
    if (!m) return newSearch();
    const id = m[1];
    let v = state.cache[id];
    if (!v) {
      try {
        const r = await fetch(`/api/v/${encodeURIComponent(id)}`);
        if (r.ok) v = await r.json();
      } catch { /* offline */ }
    }
    if (!v) { toast("Search not found"); return newSearch(); }
    state.current = id;
    showThread();
    els.thread.replaceChildren(renderTurn(v));
    els.share.classList.remove("hidden");
    setCrumb(v.query);
    renderHistory();
    els.feed.scrollTop = 0;
  }

  // ───────────────────────── utilities
  function autosize() {
    els.q.style.height = "auto";
    els.q.style.height = Math.min(els.q.scrollHeight, 180) + "px";
    els.decide.disabled = state.busy || !els.q.value.trim();
  }
  let toastT;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(() => els.toast.classList.remove("show"), 2600);
  }
  async function copy(text, msg) {
    try { await navigator.clipboard.writeText(text); toast(msg); }
    catch { toast("Copy failed — clipboard blocked"); }
  }
  function share(v) {
    const result = v || state.cache[state.current];
    if (!result) return;
    const bytes = new TextEncoder().encode(JSON.stringify(result));
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    const payload = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    copy(`${location.origin}${location.pathname}#s/${payload}`, "Share link copied");
  }
  function openRail() { els.shell.classList.add("rail-open"); }
  function closeRail() { els.shell.classList.remove("rail-open"); }

  function openSettings() {
    els.endpoint.value = state.settings.endpoint;
    els.key.value = state.settings.key;
    const thr = thresholdFor(state.settings.playbook);
    els.threshold.value = thr;
    els.thresholdVal.textContent = state.settings.threshold == null ? `${pct(thr)} · playbook default` : pct(thr);
    els.threshold.dataset.touched = "";
    els.keyHint.textContent = state.serverKey
      ? "Server has TYPESAFE_API_KEY set — it takes precedence over any browser key."
      : "Prefer TYPESAFE_API_KEY on the server. Browser keys are demo-only.";
    els.settings.showModal();
  }

  // ───────────────────────── events
  function bind() {
    els.form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    els.q.addEventListener("input", autosize);
    els.q.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); run(); }
    });
    els.pb.addEventListener("change", () => setPlaybook(els.pb.value));
    $("#new-btn").addEventListener("click", () => { closeRail(); newSearch(); });
    $("#brand").addEventListener("click", (e) => { e.preventDefault(); newSearch(); });
    $("#menu-btn").addEventListener("click", openRail);
    $("#rail-close").addEventListener("click", closeRail);
    $("#scrim").addEventListener("click", closeRail);
    $("#clear-history").addEventListener("click", () => {
      state.history = []; state.cache = {};
      store(LS.history, []); store(LS.cache, {});
      renderHistory(); toast("Local history cleared");
    });
    els.share.addEventListener("click", () => share());
    $("#btn-settings").addEventListener("click", () => { closeRail(); openSettings(); });
    $("#btn-thesis").addEventListener("click", () => { closeRail(); els.thesis.showModal(); });

    els.threshold.addEventListener("input", () => {
      els.threshold.dataset.touched = "1";
      els.thresholdVal.textContent = pct(+els.threshold.value);
    });
    $("#threshold-reset").addEventListener("click", () => {
      els.threshold.dataset.touched = "reset";
      const d = state.playbooks[state.settings.playbook]?.threshold ?? 0.7;
      els.threshold.value = d;
      els.thresholdVal.textContent = `${pct(d)} · playbook default`;
    });
    els.settings.addEventListener("close", () => {
      if (els.settings.returnValue !== "default") return;
      state.settings.endpoint = els.endpoint.value;
      state.settings.key = els.key.value.trim();
      const t = els.threshold.dataset.touched;
      if (t === "1") state.settings.threshold = +els.threshold.value;
      if (t === "reset") state.settings.threshold = null;
      store(LS.settings, state.settings);
      toast("Settings saved");
    });
    [els.settings, els.thesis].forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close("cancel"); }));

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); newSearch(); }
      else if (e.key === "/" && document.activeElement !== els.q && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); els.q.focus(); }
      else if (e.key === "Escape") closeRail();
    });
    els.feed.addEventListener("scroll", () => els.stage.classList.toggle("scrolled", els.feed.scrollTop > 4), { passive: true });
    window.addEventListener("hashchange", () => { if (!state.busy) route(); });
    autosize();
  }

  boot();
})();
