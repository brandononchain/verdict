#!/usr/bin/env python3
"""Zearch: source-backed search -> evidence pack -> typed judgment -> confidence gate.

Stdlib only. Serves the static app and a small JSON API.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STORE = DATA / "verdicts.json"
PORT = int(os.environ.get("PORT", "8765"))
UA = "Mozilla/5.0 (Zearch evidence packer)"
SEARCH_TIMEOUT = 4.5
MAX_SOURCES = 8
MAX_STATE_CHARS = 6000

ENDPOINTS = {
    "typesafe": os.environ.get("TYPESAFE_URL", "https://api.typesafe.ai/v1/systemone"),
    "gateway": os.environ.get("JEV_GATEWAY_URL", "https://ai-gateway.vercel.sh/v1/systemone"),
}
MODEL = os.environ.get("JEV_MODEL", "jev-latest")

# ---------------------------------------------------------------- playbooks

PLAYBOOKS: dict[str, dict] = {
    "invest": {
        "name": "Ship / wait",
        "blurb": "Listings, launches, yields. Go, hold, or walk.",
        "primary": "decision",
        "threshold": 0.72,
        "min_sources": 3,
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": "Given the evidence, what should the team do now?",
                "criteria": {
                    "ship": "Proceed now; evidence supports acting this cycle",
                    "wait": "Hold; evidence is incomplete or timing is wrong",
                    "kill": "Walk away; evidence shows material downside",
                },
            },
            "conviction": {
                "type": "score",
                "instructions": "How strong is the case for the recommended action?",
                "criteria": ["Weak", "Mixed", "Solid", "Strong", "Overwhelming"],
            },
            "evidence_sufficient": {
                "type": "noul",
                "instructions": "Is the evidence sufficient to act without further diligence?",
            },
            "downside_material": {
                "type": "noul",
                "instructions": "Does the evidence show a material, hard-to-reverse downside?",
            },
        },
    },
    "triage": {
        "name": "Triage / route",
        "blurb": "Tickets, alerts, inbound. Send it to the right queue.",
        "primary": "route",
        "threshold": 0.7,
        "min_sources": 1,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which team should own this?",
                "criteria": {
                    "engineering": "Bugs, outages, integrations",
                    "support": "How-to, account, general help",
                    "billing": "Payments, refunds, invoices",
                    "security": "Abuse, fraud, vulnerabilities, exposure",
                    "sales": "Pricing, expansion, new business",
                },
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgent is this?",
                "criteria": ["Low", "Normal", "High", "Critical"],
            },
            "needs_human": {
                "type": "noul",
                "instructions": "Does this require a human before any automated action?",
            },
        },
    },
    "risk": {
        "name": "Risk / gate",
        "blurb": "Allow, review, or block. Calibrated, not vibes.",
        "primary": "gate",
        "threshold": 0.8,
        "min_sources": 2,
        "questions": {
            "gate": {
                "type": "choice",
                "instructions": "Should this action be allowed?",
                "criteria": {
                    "allow": "Low risk; proceed automatically",
                    "review": "Uncertain or moderate risk; route to a reviewer",
                    "block": "High risk; stop the action",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "If this goes wrong, how bad is it?",
                "criteria": ["None", "Low", "Medium", "High", "Severe"],
            },
            "reversible": {
                "type": "noul",
                "instructions": "Is the worst outcome easily reversible?",
            },
            "evidence_sufficient": {
                "type": "noul",
                "instructions": "Is there enough evidence to make this call?",
            },
        },
    },
    "compare": {
        "name": "Compare",
        "blurb": "A vs B. Pick one, or say it is a coin flip.",
        "primary": "winner",
        "threshold": 0.65,
        "min_sources": 3,
        "questions": {
            "winner": {
                "type": "choice",
                "instructions": "Which option named first in the question is better for the stated goal?",
                "criteria": {
                    "first": "The first option named is better",
                    "second": "The second option named is better",
                    "tie": "Materially equivalent",
                    "insufficient": "Evidence cannot separate them",
                },
            },
            "margin": {
                "type": "score",
                "instructions": "How large is the gap between the options?",
                "criteria": ["Negligible", "Small", "Clear", "Decisive"],
            },
            "evidence_sufficient": {
                "type": "noul",
                "instructions": "Does the evidence cover both options fairly?",
            },
        },
    },
}

SEED = [
    {
        "title": "Jev System One — typed decisions",
        "url": "https://docs.typesafe.ai/systemone/reference",
        "snippet": "System One takes state and questions and returns Choice, Score, or Noul answers with "
        "probabilities. Roughly 70–500ms latency. $0.042 per million input tokens; output is free.",
        "source": "seed",
        "keys": ["jev", "typesafe", "system one", "systemone", "noul"],
    },
    {
        "title": "Vercel AI Gateway — Jev availability",
        "url": "https://vercel.com/ai-gateway",
        "snippet": "Jev is available through the Vercel AI Gateway. Vercel described it as the fastest Gateway "
        "launch they have seen.",
        "source": "seed",
        "keys": ["vercel", "ai gateway", "jev"],
    },
    {
        "title": "Calibration caveat",
        "url": "https://docs.typesafe.ai/systemone/reference",
        "snippet": "Confidence scores are vendor-claimed as calibrated. Weights are hosted-only. Validate "
        "thresholds on your own labeled data before automating irreversible actions.",
        "source": "seed",
        "keys": ["calibrat", "confidence score", "jev", "typesafe"],
    },
]

# ---------------------------------------------------------------- search


def _get(url: str, timeout: float = SEARCH_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(600_000)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def search_ddg_instant(q: str) -> list[dict]:
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1}
    )
    d = json.loads(_get(url))
    out = []
    if d.get("AbstractText"):
        out.append({
            "title": d.get("Heading") or q,
            "url": d.get("AbstractURL") or "",
            "snippet": d["AbstractText"],
            "source": "ddg",
        })
    for t in d.get("RelatedTopics", [])[:4]:
        if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
            out.append({"title": t["Text"][:80], "url": t["FirstURL"], "snippet": t["Text"], "source": "ddg"})
    return out


def search_wikipedia(q: str) -> list[dict]:
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 3}
    )
    d = json.loads(_get(url))
    hits = d.get("query", {}).get("search", [])
    words = q.split()
    if not hits and len(words) > 2:  # CirrusSearch ANDs terms; loosen
        return search_wikipedia(" ".join(words[: max(2, len(words) // 2)]))
    out = []
    for r in hits:
        title = r.get("title", "")
        out.append({
            "title": title,
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "snippet": _clean(r.get("snippet", "")),
            "source": "wikipedia",
        })
    return out


_DDG_A = re.compile(r"""<a[^>]+href=["']([^"']+)["'][^>]*class=["']result-link["'][^>]*>(.*?)</a>""", re.S)
_DDG_S = re.compile(r"""class=["']result-snippet["'][^>]*>(.*?)</td>""", re.S)


def search_ddg_html(q: str) -> list[dict]:
    body = _get("https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q})).decode("utf-8", "ignore")
    links, snippets = _DDG_A.findall(body), _DDG_S.findall(body)
    out = []
    for i, (href, title) in enumerate(links[:8]):
        href = html.unescape(href)
        if "y.js" in href:  # sponsored
            continue
        if "uddg=" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        if href.startswith("//"):
            href = "https:" + href
        out.append({
            "title": _clean(title),
            "url": href,
            "snippet": _clean(snippets[i]) if i < len(snippets) else "",
            "source": "web",
        })
    return out


def search_seed(q: str) -> list[dict]:
    ql = q.lower()
    hits = [s for s in SEED if any(k in ql for k in s["keys"])]
    return [{k: v for k, v in s.items() if k != "keys"} for s in hits]


PROVIDERS = {"web": search_ddg_html, "ddg": search_ddg_instant, "wikipedia": search_wikipedia, "seed": search_seed}
KEYWORD_PROVIDERS = {"ddg", "wikipedia"}  # these need terse keyword queries, not sentences

_STOP = set("""a an the and or but if of to in on at for from by with about into over under this that these those
is are was were be been being do does did should would could can will shall may might must we our us you your they
their it its i me my let lets let's what which who whom whose when where why how vs versus than then there here
now this year quarter today any some all more most less very just also not no yes""".split())


def keywords(q: str) -> str:
    words = re.findall(r"[A-Za-z0-9$][\w$.\-]*", q)
    kept = [w for w in words if w.lower() not in _STOP and len(w) > 1]
    return " ".join(kept[:7]) or q


def pack_evidence(query: str, playbook: str) -> dict:
    t0 = time.perf_counter()
    results: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    kw = keywords(query)
    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as ex:
        futs = {name: ex.submit(fn, kw if name in KEYWORD_PROVIDERS else query) for name, fn in PROVIDERS.items()}
        for name, f in futs.items():
            try:
                results[name] = f.result(timeout=SEARCH_TIMEOUT + 1)
            except Exception as e:  # network is best-effort
                results[name] = []
                errors[name] = type(e).__name__

    # interleave providers so one source cannot flood the pack
    seen, sources = set(), []
    order = ["web", "wikipedia", "ddg", "seed"]
    for i in range(MAX_SOURCES):
        for name in order:
            lst = results.get(name, [])
            if i < len(lst):
                s = lst[i]
                key = (s.get("url") or s.get("title", "")).rstrip("/").lower()
                if not s.get("snippet") or key in seen:
                    continue
                seen.add(key)
                sources.append(s)
    sources = sources[:MAX_SOURCES]
    for n, s in enumerate(sources, 1):
        s["n"] = n
        s["domain"] = urllib.parse.urlparse(s.get("url", "")).netloc.replace("www.", "") or s["source"]

    return {
        "query": query,
        "playbook": playbook,
        "sources": sources,
        "state": build_state(query, playbook, sources),
        "providers": {k: len(v) for k, v in results.items()},
        "errors": errors,
        "ms": round((time.perf_counter() - t0) * 1000),
    }


def build_state(query: str, playbook: str, sources: list[dict]) -> str:
    pb = PLAYBOOKS[playbook]
    lines = [f"QUESTION: {query}", f"PLAYBOOK: {pb['name']}", f"DATE: {time.strftime('%Y-%m-%d')}", "EVIDENCE:"]
    if not sources:
        lines.append("(no external evidence retrieved)")
    for s in sources:
        lines.append(f"[{s['n']}] {s['title']} — {s['snippet']} ({s['domain']})")
    state = "\n".join(lines)
    return state[:MAX_STATE_CHARS]


# ---------------------------------------------------------------- decide


def call_jev(endpoint: str, key: str, state: str, questions: dict) -> dict:
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(
        ENDPOINTS[endpoint],
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _softmax(xs: list[float]) -> list[float]:
    import math
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [v / s for v in e]


NEG = ("hack", "exploit", "fraud", "scam", "lawsuit", "enforcement", "delist", "rug pull", "breach", "outage", "refund",
       "chargeback", "leak", "vulnerab", "sanction", "depeg", "insolv", "collapse", "bankrupt")
POS = ("audit", "growth", "adoption", "launch", "partnership", "revenue", "liquidity", "record", "approved", "fastest",
       "stable", "profitable")


def mock_jev(query: str, state: str, questions: dict) -> dict:
    """Deterministic stand-in so the UI works offline. Clearly labeled as mock."""
    text = (query + " " + state).lower()
    neg = sum(text.count(w) for w in NEG)
    pos = sum(text.count(w) for w in POS)
    n_src = state.count("\n[")
    tilt = max(-2.5, min(2.5, (pos - neg) * 0.35))
    seed = int(hashlib.sha256((query + state[:400]).encode()).hexdigest(), 16)

    def jitter(i: int) -> float:
        return ((seed >> (i * 7)) % 1000) / 1000 - 0.5

    answers = {}
    for qi, (qid, q) in enumerate(questions.items()):
        if q["type"] == "choice":
            keys = list(q["criteria"].keys())
            logits = []
            for i, k in enumerate(keys):
                x = jitter(qi * 11 + i) * 1.6
                if k in ("ship", "allow", "first"):
                    x += tilt
                if k in ("kill", "block"):
                    x -= tilt
                if k in ("wait", "review", "insufficient") and n_src < 3:
                    x += 1.4
                if k == "security" and any(w in text for w in ("breach", "fraud", "leak", "vulnerab", "hack")):
                    x += 2.5
                if k == "billing" and any(w in text for w in ("refund", "invoice", "charge", "payment")):
                    x += 2.2
                if k == "engineering" and any(w in text for w in ("outage", "down", "bug", "error", "api")):
                    x += 1.8
                logits.append(x * 1.2)
            # shrink toward uniform so the mock never claims certainty
            p = [0.9 * v + 0.1 / len(keys) for v in _softmax(logits)]
            best = max(range(len(keys)), key=lambda i: p[i])
            answers[qid] = {"type": "choice", "choice": keys[best], "confidence": round(p[best], 4),
                            "probabilities": {k: round(v, 4) for k, v in zip(keys, p)}}
        elif q["type"] == "score":
            levels = q["criteria"]
            centre = (len(levels) - 1) * (0.5 + jitter(qi * 13) * 0.6 + (neg - pos) * 0.04)
            centre = max(0, min(len(levels) - 1, centre))
            p = _softmax([-((i - centre) ** 2) * 1.3 for i in range(len(levels))])
            best = max(range(len(levels)), key=lambda i: p[i])
            answers[qid] = {"type": "score", "score": round(sum(i * v for i, v in enumerate(p)), 3),
                            "legend": {str(i): l for i, l in enumerate(levels)},
                            "probabilities": {str(i): round(v, 4) for i, v in enumerate(p)},
                            "confidence": round(p[best], 4)}
        else:
            base = 0.5 + jitter(qi * 17) * 0.5
            if qid == "evidence_sufficient":
                base = min(0.95, 0.2 + n_src * 0.1)
            if qid in ("downside_material",):
                base = min(0.95, 0.2 + neg * 0.12)
            if qid == "reversible":
                base = max(0.05, 0.75 - neg * 0.1)
            answers[qid] = {"type": "noul", "noul": round(max(0.01, min(0.99, base)), 4)}
    return {"model": "mock-jev", "answers": answers,
            "usage": {"input_tokens": max(1, len(state) // 4), "output_tokens": 0}}


def normalize(questions: dict, raw: dict) -> list[dict]:
    """Flatten Choice / Score / Noul into one shape the UI can render."""
    out = []
    for qid, q in questions.items():
        a = (raw.get("answers") or {}).get(qid) or {}
        item = {"id": qid, "type": q["type"], "instructions": q["instructions"], "options": []}
        if q["type"] == "choice":
            probs = a.get("probabilities") or {}
            for k, desc in q["criteria"].items():
                item["options"].append({"key": k, "label": k, "desc": desc, "p": float(probs.get(k, 0))})
            item["pick"] = a.get("choice")
            item["confidence"] = float(a.get("confidence", probs.get(a.get("choice"), 0) if probs else 0))
        elif q["type"] == "score":
            probs = a.get("probabilities") or {}
            legend = a.get("legend") or {str(i): l for i, l in enumerate(q["criteria"])}
            for i, label in enumerate(q["criteria"]):
                item["options"].append({"key": str(i), "label": legend.get(str(i), label), "p": float(probs.get(str(i), 0))})
            score = float(a.get("score", 0))
            item["score"] = score
            item["pick"] = legend.get(str(round(score)), "")
            item["max"] = len(q["criteria"]) - 1
            item["confidence"] = float(a.get("confidence", max((o["p"] for o in item["options"]), default=0)))
        else:
            p = float(a.get("noul", 0))
            item["options"] = [{"key": "true", "label": "yes", "p": p}, {"key": "false", "label": "no", "p": 1 - p}]
            item["pick"] = "yes" if p >= 0.5 else "no"
            item["noul"] = p
            item["confidence"] = max(p, 1 - p)
        out.append(item)
    return out


def apply_policy(playbook: str, answers: list[dict], n_sources: int, threshold: float | None) -> dict:
    pb = PLAYBOOKS[playbook]
    thr = float(threshold) if threshold is not None else pb["threshold"]
    primary = next(a for a in answers if a["id"] == pb["primary"])
    conf = primary["confidence"]
    reasons = []
    by_id = {a["id"]: a for a in answers}

    ok_conf = conf >= thr
    reasons.append(f"{pb['primary']} confidence {conf:.0%} {'≥' if ok_conf else '<'} threshold {thr:.0%}")
    ok_src = n_sources >= pb["min_sources"]
    reasons.append(f"{n_sources} source{'s' if n_sources != 1 else ''} packed "
                   f"({'meets' if ok_src else 'below'} minimum {pb['min_sources']})")
    ok_ev = True
    if "evidence_sufficient" in by_id:
        p = by_id["evidence_sufficient"]["noul"]
        ok_ev = p >= 0.5
        reasons.append(f"evidence sufficient p={p:.2f}")
    ok_human = True
    if "needs_human" in by_id:
        p = by_id["needs_human"]["noul"]
        ok_human = p < 0.5
        reasons.append(f"needs human p={p:.2f}")

    if ok_conf and ok_src and ok_ev and ok_human:
        gate = "act"
        summary = f"Act on “{primary['pick']}”. Your code owns the action."
    elif conf >= thr - 0.2 and ok_src:
        gate = "review"
        summary = f"Lean “{primary['pick']}”, but route to a human before acting."
    else:
        gate = "abstain"
        summary = "Not enough signal. Gather more evidence or reframe the question."
    return {"gate": gate, "summary": summary, "threshold": thr, "confidence": conf,
            "pick": primary["pick"], "primary": pb["primary"], "reasons": reasons}


def decide(body: dict) -> dict:
    query = (body.get("query") or "").strip()[:1000]
    playbook = body.get("playbook") if body.get("playbook") in PLAYBOOKS else "invest"
    if not query:
        raise ValueError("query is required")
    pack = body.get("pack")
    if not (isinstance(pack, dict) and pack.get("query") == query and pack.get("playbook") == playbook):
        pack = pack_evidence(query, playbook)
    questions = PLAYBOOKS[playbook]["questions"]
    endpoint = body.get("endpoint") or "auto"
    if endpoint == "auto":
        endpoint = "typesafe" if os.environ.get("TYPESAFE_API_KEY") else "mock"
    key = os.environ.get("TYPESAFE_API_KEY") or (body.get("key") or "").strip()

    mode, warning = "mock", None
    t0 = time.perf_counter()
    raw = None
    if endpoint in ENDPOINTS and key:
        try:
            raw = call_jev(endpoint, key, pack["state"], questions)
            mode = endpoint
        except urllib.error.HTTPError as e:
            warning = f"{endpoint} returned HTTP {e.code}; fell back to mock"
        except Exception as e:
            warning = f"{endpoint} unreachable ({type(e).__name__}); fell back to mock"
    elif endpoint in ENDPOINTS:
        warning = f"no API key for {endpoint}; using mock"
    if raw is None:
        raw = mock_jev(query, pack["state"], questions)
    judge_ms = round((time.perf_counter() - t0) * 1000)

    answers = normalize(questions, raw)
    policy = apply_policy(playbook, answers, len(pack["sources"]), body.get("threshold"))
    usage = raw.get("usage") or {}
    verdict = {
        "id": secrets.token_urlsafe(6),
        "created": int(time.time()),
        "query": query,
        "playbook": playbook,
        "playbook_name": PLAYBOOKS[playbook]["name"],
        "mode": mode,
        "model": raw.get("model", MODEL),
        "warning": warning,
        "answers": answers,
        "policy": policy,
        "sources": pack["sources"],
        "state": pack["state"],
        "timing": {"search_ms": pack.get("ms", 0), "judge_ms": judge_ms},
        "usage": usage,
        "cost_usd": round(usage.get("input_tokens", 0) * 0.042 / 1_000_000, 8),
    }
    save(verdict)
    return verdict


# ---------------------------------------------------------------- storage

_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(STORE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(v: dict) -> None:
    # Vercel Functions have an ephemeral, read-only deployment filesystem.
    # Shared links on hosted deployments carry a compact result snapshot in the URL.
    if os.environ.get("VERCEL"):
        return
    with _lock:
        DATA.mkdir(exist_ok=True)
        d = _load()
        d[v["id"]] = v
        if len(d) > 500:
            for k in sorted(d, key=lambda k: d[k]["created"])[: len(d) - 500]:
                d.pop(k)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), "utf-8")
        tmp.replace(STORE)


def get_verdict(vid: str) -> dict | None:
    with _lock:
        return _load().get(vid)


# ---------------------------------------------------------------- http


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/research":
            import research_http
            return research_http.get(self)
        if path == "/api/playbooks":
            return self._json(200, {
                "playbooks": {k: {"name": v["name"], "blurb": v["blurb"], "primary": v["primary"],
                                  "threshold": v["threshold"], "min_sources": v["min_sources"],
                                  "questions": v["questions"]} for k, v in PLAYBOOKS.items()},
                "server_key": bool(os.environ.get("TYPESAFE_API_KEY")),
                "model": MODEL,
            })
        if path.startswith("/api/v/"):
            v = get_verdict(path.rsplit("/", 1)[-1])
            return self._json(200, v) if v else self._json(404, {"error": "not found"})
        if path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        # only serve the app's own static files
        allowed = {"/", "/index.html", "/styles.css", "/app.js", "/favicon.svg", "/zearch-mark.svg", "/assets/zearch-horizon.jpg"}
        if path not in allowed:
            self.path = "/"
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/research":
            import research_http
            return research_http.post(self)
        try:
            body = self._body()
            if path == "/api/search":
                q = (body.get("query") or "").strip()[:1000]
                pb = body.get("playbook") if body.get("playbook") in PLAYBOOKS else "invest"
                if not q:
                    return self._json(400, {"error": "query is required"})
                return self._json(200, pack_evidence(q, pb))
            if path == "/api/decide":
                return self._json(200, decide(body))
            return self._json(404, {"error": "not found"})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(500, {"error": type(e).__name__})


if __name__ == "__main__":
    import research_store
    research_store.migrate()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Zearch → http://localhost:{PORT}  (jev: {'server key' if os.environ.get('TYPESAFE_API_KEY') else 'mock unless key set'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
