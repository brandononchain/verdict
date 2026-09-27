# Verdict

Perplexity-style UI for TypeSafe Jev.

Search packs evidence into `state`. Jev returns Choice / Score / Noul. Your code owns the action.

## Run

```bash
python3 server.py
# http://localhost:8765
```

Live model (optional):

```bash
export TYPESAFE_API_KEY=...
```

Then Settings → `typesafe` or `gateway`. Prefer the env var. Do not ship keys in the browser for production.

## API

| Method | Path | Body / notes |
| --- | --- | --- |
| POST | `/api/search` | `{ query }` |
| POST | `/api/decide` | `{ query, playbook, endpoint?, key? }` |
| GET | `/api/v/:id` | shared verdict |

Playbooks: `invest` · `triage` · `risk` · `compare`

Share links: `/#v/<id>`

Search packer: DuckDuckGo instant answers + Wikipedia + DDG HTML + Jev seed corpus. Mock decisions if Jev is unset.

## License

MIT
