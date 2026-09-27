# Verdict

**search → evidence pack → typed decision → confidence gate.**

Perplexity trained people to expect sources. Verdict uses the same loop for *judgments*, not paragraphs. A question goes in. Verdict searches, packs the sources into `state`, and asks TypeSafe Jev (System One) a set of finite, typed questions: Choice, Score, Noul. A policy gate then says **act**, **review**, or **abstain**. Your code owns the action.

## Run

```bash
python server.py        # stdlib only, Python 3.10+
# http://localhost:8765
```

Live model (optional):

```bash
export TYPESAFE_API_KEY=...          # server-side key (preferred)
export TYPESAFE_URL=...              # default https://api.typesafe.ai/v1/systemone
export JEV_GATEWAY_URL=...           # default https://ai-gateway.vercel.sh/v1/systemone
export JEV_MODEL=...                 # default jev-latest
export PORT=8765
```

Settings → Engine:

- **auto** (default): uses TypeSafe when the server has a key, otherwise mock.
- **mock**: offline.
- **typesafe** or **gateway**: forces a live endpoint.

A browser key can be set for local testing. The server env key always wins. Do not ship keys in the browser. If a live call fails, the run falls back to mock and shows a warning. Mock verdicts are always labeled.

## The app

- **Rail**: new verdict, playbooks, history (dot = gate outcome), thesis, settings, engine chip.
- **Stage**: a thread of verdict turns. Each turn shows:
  - the pick
  - the gate badge
  - confidence against the threshold
  - gate reasons
  - typed answer cards with probability bars
  - the numbered evidence pack
  - the raw `state`
  - copy-link, copy-JSON, and re-run actions
- **Dock**: a live neural graph sits above the composer. Nodes pulse and sparks travel the synapses. While Decide runs, the brain flips to `neural judge · firing` and the pipeline pills (search → pack → judge → gate) light up in turn. On completion the graph settles in the gate's color.

Shortcuts: `Enter` decide · `Shift+Enter` newline · `Ctrl/Cmd+K` new verdict · `/` focus composer.

## Playbooks

| id | primary | act threshold | min sources |
| --- | --- | --- | --- |
| `invest` Ship / wait | `decision`: ship · wait · kill | 72% | 3 |
| `triage` Triage / route | `route`: engineering · support · billing · security · sales | 70% | 1 |
| `risk` Risk / gate | `gate`: allow · review · block | 80% | 2 |
| `compare` Compare | `winner`: first · second · tie · insufficient | 65% | 3 |

**act** requires all of the following:

- primary confidence ≥ threshold
- source count ≥ minimum
- `evidence_sufficient` ≥ 0.5
- `needs_human` < 0.5

**review** means confidence is within 20 points of the threshold and the source minimum is met. Everything else is **abstain**. You can override the threshold per browser in Settings.

## API

| Method | Path | Body / notes |
| --- | --- | --- |
| GET | `/api/playbooks` | playbook definitions |
| POST | `/api/search` | `{ query, playbook }` → evidence pack |
| POST | `/api/decide` | `{ query, playbook, pack?, endpoint?, key?, threshold? }` |
| GET | `/api/v/:id` | shared verdict |

Share links: `/#v/<id>`. Verdicts persist to `data/verdicts.json` (gitignored, last 500).

The search packer interleaves and dedupes up to 8 sources from:

- DuckDuckGo lite
- DDG instant answers
- Wikipedia
- a small Jev seed corpus

## Files

`server.py` API + static · `index.html` shell · `styles.css` · `app.js` UI logic · `neural.js` canvas graph · `favicon.svg`

## Caveats

Hosted-only weights. Calibration is vendor-claimed, so tune gates on your own data. The Gateway endpoint path is an assumption until confirmed.

## License

MIT
