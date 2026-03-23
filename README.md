# Global News Agent

Cloudflare-oriented long-term version of the project.

This repo now contains two tracks:

- `src/worker.js`: the long-term deployment path for Cloudflare Workers
- legacy local Python scripts: the old local-only workflow, kept temporarily for migration

## Recommended Path

Use the Worker version if your goal is:

- GitHub-based auto deploy
- stable long-term hosting
- no local `cloudflared` dependency
- public access through a Cloudflare-managed endpoint

The Worker does this:

- fetches global RSS feeds at the edge
- deduplicates and ranks events
- generates a usable Chinese report even without OpenAI
- optionally calls OpenAI to improve Chinese report quality if `OPENAI_API_KEY` is configured
- serves both dashboard HTML and `/api/report`
- caches the generated report for 15 minutes

## Files

- `wrangler.toml`: Cloudflare Worker config
- `src/worker.js`: deployable Worker entry
- `.dev.vars.example`: local Worker secret example

Legacy local files still exist for transition, but they are no longer the preferred hosting route:

- `agent.py`
- `server.py`
- `share_public.py`
- related `.bat` launchers

## No-API First Deploy

You can deploy this version without any OpenAI key.

1. Install Wrangler locally.
2. Login to Cloudflare:

```bash
wrangler login
```

3. Test locally:

```bash
wrangler dev
```

4. Deploy:

```bash
wrangler deploy
```

After deploy, Cloudflare will return a stable Worker URL such as:

```text
https://global-news-agent.<your-subdomain>.workers.dev
```

This no-API version already includes:

- RSS aggregation
- event ranking
- Chinese title/summary fallback
- dashboard page
- JSON report API

## Optional OpenAI Upgrade

If you later get an OpenAI key, add it as a secret to improve Chinese quality:

```bash
wrangler secret put OPENAI_API_KEY
wrangler secret put OPENAI_MODEL
```

`OPENAI_MODEL` is optional. The default is `gpt-5-mini`.

## GitHub Auto Deploy

Recommended workflow:

1. Push this repo to GitHub.
2. In Cloudflare Workers, connect the Worker to the GitHub repository.
3. If you have one, add `OPENAI_API_KEY` as a production secret in Cloudflare.
4. Use the default deploy command from `wrangler.toml`.

This gives you automatic redeploys on every push to the main branch.

## API

- `GET /`: dashboard
- `GET /api/report`: latest report JSON
- `GET /api/report?refresh=1`: bypass cache and regenerate
- `GET /api/health`: health check

## Notes

- The Worker version is the long-term path.
- The current edge version does not yet persist historical archives.
- The no-API version is now treated as a valid first deployment target.
- If you later add `OPENAI_API_KEY`, the Worker will use it as an enhancement, not as a hard dependency.
- If you want long-term history, the next step is adding KV, D1, or R2 storage.
