# Collection operations

Zearch's Scrape and Crawl answers are Jev-checked research runs. The collection dashboard shows captured pages and assets in chat. Visual capture, batches, and monitors are separate actions with explicit limits.

## Visual capture

Set `CONTEXT_DEV_API_KEY` on Vercel. A completed Scrape or Crawl run exposes **Data → Capture screenshot & styleguide**. This makes two provider requests against its public target URL: a fresh viewport screenshot and an extracted design system. The owner-scoped screenshot is stored in Railway Postgres, limited to 1.5 MB; the styleguide is limited to 100 KB. The JSON export includes styleguide metadata and screenshot availability. The image downloads through `/api/collection?id=<run>&image=1` with the same owner cookie. No visual capture runs during ordinary research.

Set `ZEARCH_DAILY_VISUAL_USER` (default 3) and `ZEARCH_DAILY_VISUAL_GLOBAL` (default 40) for maximum capture attempts per UTC day. One attempt may make two provider calls and may consume credits even if an output fails. Repeated capture of a completed result uses the saved output. An explicit failed retry consumes another attempt. Review provider pricing and credits before enabling the key.

## URL batches

Set `ZEARCH_DISCOVERY_ENABLED=1` in both Vercel and the Railway discovery worker. `railway.discovery.json` runs `python discovery.py` every five minutes. In **Your workspace → Collection batches**, queue 2–10 unique public HTTPS URLs and an optional question. The worker claims one URL per invocation, runs the usual Scrape/Jev/writer workflow, and saves each answer under the submitting owner. It never automatically repeats an uncertain paid call. A batch can be partial; its failed item remains visible, with the saved run when available. Cancel stops queued pages, while an already running page finishes. The normal daily research and provider spending limits apply to each page.

## Site monitors

After a completed Scrape or Crawl, choose **Monitor daily**. The saved investigation retains its target URL and research mode. The same Railway worker refreshes it once per day; the workspace can pause or switch to weekly and request a manual refresh. Monitors expire after 29 days. A refresh compares normalized captured page text and answer text with the prior run. Added, removed, changed pages or answer changes become **review candidates**. This is a content comparison, not a verified fact-change alert, and no outbound notification is sent. Every refresh consumes the normal research allowance. Source captures and Jev evidence decisions remain attached to their runs.

## Operations

Railway must have the existing `DATABASE_URL`, `TAVILY_API_KEY`, `TYPESAFE_API_KEY`, writer settings and spend caps. Vercel must have the same research configuration plus `CONTEXT_DEV_API_KEY` for visual capture. First request to a hosted instance runs the idempotent Postgres migration; the Railway worker also checks the schema. A batch can be started while visual capture is unconfigured, and a normal search does not depend on the visual provider.
