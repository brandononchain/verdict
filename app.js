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
    starters: $("#starters"), pbList: $("#pb-list"), history: $("#history"), crumbs: $("#crumbs"),
    form: $("#composer"), q: $("#query"), pb: $("#playbook"), decide: $("#decide"), gateHint: $("#gate-hint"),
    progress: $("#progress"), judgeState: $("#judge-state"), pipeline: $("#pipeline"), modeChip: $("#mode-chip"),
    share: $("#share-btn"), toast: $("#toast"),
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
    { pb: "invest", q: "Should we list this RWA token on a CEX this quarter?" },
    { pb: "risk", q: "Let an agent auto-approve refunds under $200 for accounts with prior chargebacks?" },
    { pb: "triage", q: "Customer says the API has returned 502 errors for three days and wants a refund." },
    { pb: "compare", q: "Arbitrum vs Base for launching a consumer app this year?" },
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
    renderMode();
    bind();
    route();
  }

  // ───────────────────────── render: chrome
  function renderPlaybooks() {
    els.pbList.replaceChildren();
    els.pb.replaceChildren();
    for (const [id, pb] of Object.entries(state.playbooks)) {
      els.pbList.append(h("li", {}, h("button", {
        type: "button", "aria-pressed": String(id === state.settings.playbook), "data-pb": id,
        onclick: () => { setPlaybook(id); closeRail(); els.q.focus(); },
      }, h("i"), h("span", {}, pb.name), h("small", {}, pb.blurb))));
      els.pb.append(h("option", { value: id }, pb.name));
    }
    els.pb.value = state.settings.playbook;
    renderGateHint();
  }

  function setPlaybook(id) {
    state.settings.playbook = id;
    store(LS.settings, state.settings);
    els.pb.value = id;
    els.pbList.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pb === id)));
    renderGateHint();
  }

  function thresholdFor(id) {
    return state.settings.threshold ?? state.playbooks[id]?.threshold ?? 0.7;
  }

  function renderGateHint() {
    const pb = state.playbooks[state.settings.playbook];
    if (!pb) return;
    els.gateHint.textContent = `act ≥ ${pct(thresholdFor(state.settings.playbook))} · min ${pb.min_sources} src · ${Object.keys(pb.questions).length} questions`;
  }

  function renderStarters() {
    els.starters.replaceChildren(...STARTERS.map((s, i) => h("button", {
      type: "button", class: "starter", style: `animation-delay:${120 + i * 70}ms`,
      onclick: () => { setPlaybook(s.pb); els.q.value = s.q; autosize(); run(); },
    }, h("small", {}, state.playbooks[s.pb]?.name || s.pb), h("span", {}, s.q))));
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

  function renderMode() {
    const ep = state.settings.endpoint;
    let label, live = false;
    if (ep === "auto") { live = state.serverKey; label = live ? "typesafe · server key" : "mock engine"; }
    else if (ep === "mock") label = "mock engine";
    else { live = !!(state.serverKey || state.settings.key); label = `${ep} · ${live ? "live" : "no key"}`; }
    els.modeChip.classList.toggle("live", live);
    els.modeChip.querySelector("span").textContent = label;
  }

  function setCrumb(text) {
    els.crumbs.replaceChildren(h("span", {}, "Zearch"), h("em", {}, "/"), h("b", {}, text));
  }

  // ───────────────────────── render: verdict
  function renderTurn(v) {
    const p = v.policy;
    const primary = v.answers.find((a) => a.id === p.primary);
    const others = v.answers.filter((a) => a.id !== p.primary);

    const meter = h("div", { class: "meter" },
      h("div", { class: "meter-track" },
        h("div", { class: "meter-fill", "data-w": pct(p.confidence) }),
        h("div", { class: "meter-thr", style: `left:${p.threshold * 100}%`, "data-l": `gate ${pct(p.threshold)}` })),
      h("div", { class: "meter-legend" },
        h("span", {}, "confidence ", h("b", {}, pct(p.confidence))),
        h("span", {}, primary.options.map((o) => `${o.label} ${pct(o.p)}`).join(" · "))));

    const card = h("div", { class: `result-card ${p.gate}` },
      h("div", {}, h("div", { class: "v-label" }, `${p.primary} · ${primary.type}`), h("div", { class: "v-pick" }, p.pick || "—")),
      h("div", { class: "v-right" }, h("span", { class: `gate ${p.gate}` }, h("i"), p.gate)),
      h("p", { class: "v-summary" }, p.summary),
      meter,
      h("ul", { class: "reasons", style: "grid-column:1/-1" }, p.reasons.map((r) => h("li", {}, r))));

    const answers = h("div", { class: "answers" }, others.map((a, i) => answerCard(a, i)));

    const sources = v.sources.length
      ? h("ol", { class: "sources" }, v.sources.map((s) => {
          const url = safeUrl(s.url);
          return h("li", { class: "src" }, h(url ? "a" : "div", url ? { href: url, target: "_blank", rel: "noopener noreferrer" } : { class: "a" },
            h("span", { class: "src-n" }, s.n),
            h("span", { class: "src-d" }, s.domain, h("em", {}, s.source)),
            h("span", { class: "src-t" }, s.title),
            h("span", { class: "src-s" }, s.snippet)));
        }))
      : h("p", { class: "no-src" }, "No external evidence retrieved. The gate treats this as low signal.");

    const meta = h("div", { class: "turn-meta" },
      h("span", {}, h("b", {}, v.playbook_name)),
      h("span", {}, `engine `, h("b", {}, v.mode === "mock" ? "mock" : `${v.mode} · ${v.model}`)),
      h("span", {}, `search `, h("b", {}, `${v.timing.search_ms}ms`)),
      h("span", {}, `judge `, h("b", {}, v.timing.judge_ms < 1 ? "<1ms" : `${v.timing.judge_ms}ms`)),
      h("span", {}, `${v.usage.input_tokens || 0} tok in · `, h("b", {}, `$${(v.cost_usd || 0).toFixed(6)}`)),
      v.warning && h("span", { class: "warn" }, `⚠ ${v.warning}`));

    const turn = h("article", { class: "turn", "data-id": v.id },
      h("h2", { class: "turn-q" }, v.query),
      meta,
      card,
      others.length && h("div", { class: "section-h" }, h("span", {}, "Typed answers"), h("span", {}, "Choice · Score · Noul")),
      others.length && answers,
      h("div", { class: "section-h" }, h("span", {}, "Evidence pack"), h("span", {}, `${v.sources.length} sources → state`)),
      sources,
      h("details", { class: "state" }, h("summary", {}, `state sent to Jev · ${v.state.length} chars`), h("pre", {}, v.state)),
      h("div", { class: "turn-actions" },
        h("button", { class: "ghost-btn", type: "button", onclick: () => share(v) }, "Copy share link"),
        h("button", { class: "ghost-btn", type: "button", onclick: () => copy(JSON.stringify(v, null, 2), "Search data copied") }, "Copy JSON"),
        h("button", { class: "ghost-btn", type: "button", onclick: () => { setPlaybook(v.playbook); els.q.value = v.query; autosize(); run(); } }, "Re-run")));

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

  // ───────────────────────── search progress
  function setFiring(on) {
    els.progress.classList.toggle("working", on);
    els.judgeState.textContent = on ? "working" : "ready";
  }
  function step(name, status) {
    const li = els.pipeline.querySelector(`[data-step="${name}"]`);
    if (!li) return;
    li.classList.remove("run", "done");
    if (status) li.classList.add(status);
  }
  function resetPipeline() { els.pipeline.querySelectorAll("li").forEach((li) => li.classList.remove("run", "done")); }

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
    resetPipeline();
    setFiring(true);

    const log = h("ol", { class: "pending-log" });
    const pending = h("article", { class: "turn pending" }, h("h2", { class: "turn-q" }, query), h("div", { class: "skel" }), log);
    els.thread.append(pending);
    pending.scrollIntoView({ behavior: "smooth", block: "start" });
    const say = (label, text) => log.append(h("li", {}, h("b", {}, label), " ", text));

    const t0 = performance.now();
    try {
      step("search", "run");
      say("search", "querying web · wikipedia · instant answers · seed corpus");
      const pack = await api("/api/search", { query, playbook });
      step("search", "done");
      const live = Object.entries(pack.providers).filter(([, n]) => n).map(([k, n]) => `${k}:${n}`).join(" ");
      say("search", `${pack.ms}ms · ${live || "no provider results"}`);

      step("pack", "run");
      say("pack", `${pack.sources.length} sources deduped → ${pack.state.length} chars of state`);
      await sleep(220);
      step("pack", "done");

      step("judge", "run");
      const pb = state.playbooks[playbook];
      say("judge", `${Object.keys(pb.questions).length} typed questions in parallel`);
      const tj = performance.now();
      const v = await api("/api/decide", {
        query, playbook, pack,
        endpoint: state.settings.endpoint,
        key: state.settings.key || undefined,
        threshold: state.settings.threshold,
      });
      const spent = performance.now() - tj;
      if (spent < 650) await sleep(650 - spent); // let the judge visibly fire
      step("judge", "done");

      step("gate", "run");
      await sleep(160);
      step("gate", "done");

      remember(v);
      state.current = v.id;
      history.replaceState(null, "", `#v/${v.id}`);
      pending.replaceWith(renderTurn(v));
      els.share.classList.remove("hidden");
      renderHistory();
      const total = Math.round(performance.now() - t0);
      toast(`${v.policy.gate.toUpperCase()} · ${v.policy.pick} · ${pct(v.policy.confidence)} · ${total}ms`);
    } catch (e) {
      resetPipeline();
      pending.replaceWith(h("article", { class: "turn" }, h("h2", { class: "turn-q" }, query), h("div", { class: "err" }, `Search failed: ${e.message}`)));
      els.q.value = query;
      autosize();
    } finally {
      setFiring(false);
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
  function showThread() { els.empty.classList.add("hidden"); }
  function newSearch() {
    state.current = null;
    els.thread.replaceChildren();
    els.empty.classList.remove("hidden");
    els.share.classList.add("hidden");
    setCrumb("New");
    resetPipeline();
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
      renderMode(); renderGateHint();
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
