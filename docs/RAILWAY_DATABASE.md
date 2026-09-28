# Railway Postgres for Zearch

Zearch's hosted Python API runs on Vercel and uses ordinary PostgreSQL through `psycopg`. Railway can host the database. There is no Supabase dependency.

## Provision

1. In Railway, create a project and add a **PostgreSQL** service.
2. In the database service's **Settings → Networking**, enable **Public Access**. Vercel runs outside the Railway project and cannot use Railway's private `DATABASE_URL`. Railway supplies a `DATABASE_PUBLIC_URL` through its TCP proxy.
3. Copy that external URL into the Vercel **verdict → Settings → Environment Variables** project setting as the server-side variable **`DATABASE_URL`**. Add it to Production. Use a different Railway database for Preview if you enable Preview research. Keep the URL secret; do not paste it into source code, `.env.example`, or a browser-side variable.
4. Add the remaining provider and budget variables below, set `ZEARCH_RESEARCH_ENABLED=1`, and deploy. The Vercel backend creates the schema automatically on its first database-backed request. It serializes concurrent initializations with a PostgreSQL advisory lock and runs the additive schema in one transaction. No local Python command or Railway SQL console is needed.
5. Check `GET /api/research` for `available: true`. This checks configuration and database connectivity, not whether provider credentials work. Run a small factual and unsupported question canary before inviting users.

Railway's public TCP proxy incurs network egress and direct connections consume Postgres connection slots. The current code opens a short-lived connection per database operation. Monitor connection count and latency as traffic rises, and add a pooler or move the backend nearer the database if needed.

## Vercel variables

| Name | Source |
|---|---|
| `DATABASE_URL` | Railway `DATABASE_PUBLIC_URL` value |
| `ZEARCH_SESSION_SECRET` | Random private string, at least 32 characters; keep stable once accounts/runs exist |
| `TYPESAFE_API_KEY` | TypeSafe account |
| `JEV_MODEL` | Optional; defaults to `jev-latest` |
| `OPENAI_API_KEY` | OpenAI API account |
| `ZEARCH_WRITER_MODEL` | An available OpenAI Responses API text model in your account |
| `TAVILY_API_KEY` | Tavily account; current web search still depends on it |
| `ZEARCH_JEV_INPUT_USD_PER_MILLION` | Current contracted Jev input-token price in USD |
| `ZEARCH_WRITER_INPUT_USD_PER_MILLION` | Defaults to `0.75` only when writer model is `gpt-5.4-mini`; required for other models |
| `ZEARCH_WRITER_OUTPUT_USD_PER_MILLION` | Current writer output-token price in USD |
| `ZEARCH_SEARCH_USD_PER_CALL` | Defaults to `0.008` for Tavily basic search; override for your effective rate |
| `ZEARCH_RESEARCH_ENABLED` | Set to `1` with the other required variables; the first request initializes the schema |

The four pricing inputs must be positive, finite values. Operational limits have defaults in `.env.example`; set them deliberately before broader access. Optional Tavily page enrichment needs `ZEARCH_ENRICHMENT_ENABLED=1` and `ZEARCH_SCRAPE_USD_PER_CALL`. Discovery jobs need a separately provisioned recurring worker; enabling the web flag alone does not run the worker.

`.env.example` is only a list of names, not a secret store. This Python app does not automatically load `.env` files for local development; export values into the process environment. Do not send credentials in chat or commit them to Git.

References: https://docs.railway.com/databases/postgresql and https://vercel.com/docs/environment-variables.
