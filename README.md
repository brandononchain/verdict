# Zearch

**Source-backed AI search with typed judgments.**

Zearch is an open-source search interface for JEV (TypeSafe AI). It searches the web, packs evidence into structured state, asks a finite set of typed questions, and presents the answers with confidence and a transparent policy gate.

The interface follows familiar AI search conventions: one focused composer, a readable conversation thread, visible citations, and controls that stay secondary. Its distinct focus is making structured judgments and their confidence inspectable.

## Run locally

```bash
python3 server.py
# http://localhost:8765
```

Python 3.10+ is required. The server uses the standard library.

Optional live engine configuration:

```bash
export TYPESAFE_API_KEY=...          # server-side key (preferred)
export TYPESAFE_URL=...              # default https://api.typesafe.ai/v1/systemone
export JEV_GATEWAY_URL=...           # default https://ai-gateway.vercel.sh/v1/systemone
export JEV_MODEL=...                 # default jev-latest
export PORT=8765
```

Settings → Engine:

- **Auto** uses TypeSafe when the server has a key, otherwise the offline mock.
- **Mock** runs locally without a key.
- **TypeSafe** or **Gateway** selects a live endpoint.

The server key takes precedence over a browser key. Browser keys are intended only for local testing. If a live call fails, Zearch falls back to a clearly labeled mock response.

## Search flow

1. Search providers return candidate pages and snippets.
2. Zearch interleaves and deduplicates up to eight sources.
3. The source packer builds the structured state sent to JEV.
4. The selected playbook supplies finite Choice, Score, or Noul questions.
5. A policy gate returns **act**, **review**, or **abstain** based on confidence, source count, evidence sufficiency, and the human-review signal.

The result includes the primary choice, confidence vs. threshold, gate reasons, typed answer cards, source links, and the state sent to the model. Local shared searches use `/#v/<id>`; hosted links carry the result snapshot in the URL, so they work without a database.

## Playbooks

| id | purpose | act threshold | min sources |
| --- | --- | ---: | ---: |
| `invest` | Ship / wait / kill | 72% | 3 |
| `triage` | Route an issue | 70% | 1 |
| `risk` | Allow / review / block | 80% | 2 |
| `compare` | Compare two options | 65% | 3 |

An **act** result requires the primary confidence to meet its threshold, the minimum source count, sufficient evidence, and no human-review requirement. **Review** is returned near the confidence threshold when the source minimum is met. Other cases **abstain**. Thresholds can be adjusted in Settings.

## Search sources

The packer combines:

- DuckDuckGo Lite
- DuckDuckGo instant answers
- Wikipedia
- A small JEV seed corpus

Network search is best-effort. Provider errors or missing results can affect the quality of a search and are reflected in the returned provider data.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/playbooks` | Playbook definitions and engine status |
| POST | `/api/search` | `{ query, playbook }` → evidence pack |
| POST | `/api/decide` | `{ query, playbook, pack?, endpoint?, key?, threshold? }` → structured result |
| GET | `/api/v/:id` | Shared result |

Local searches are stored in `data/verdicts.json` (gitignored), up to the latest 500. Vercel Functions use stateless share links because their filesystem is ephemeral.

## Files

- `server.py` — search providers, JEV API, policy, and static HTTP server
- `index.html` — app structure and metadata
- `styles.css` — responsive interface
- `app.js` — search flow, rendering, history, settings, and sharing
- `favicon.svg` — Zearch mark
- `api/` — Vercel Python Functions for the search API
- `vercel.json` — function runtime configuration

## Limitations

JEV weights are hosted. Calibration claims come from the vendor and should be validated on your own data. Search snippets and confidence scores are not guarantees; verify sources before acting.

## License

MIT
