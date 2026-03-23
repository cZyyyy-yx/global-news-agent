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
- calls OpenAI to generate Chinese report text if `OPENAI_API_KEY` is configured
- falls back to an edge-only RSS summary when OpenAI is missing
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

## Deploy To Cloudflare

1. Create a new GitHub repository under your account.
2. Push this project to that repository.
3. Install Wrangler locally.
4. Login to Cloudflare:

```bash
wrangler login
```

5. Create a local secret file from the example:

```bash
cp .dev.vars.example .dev.vars
```

6. Put your OpenAI key into `.dev.vars` for local development, and add the same secret to Cloudflare:

```bash
wrangler secret put OPENAI_API_KEY
wrangler secret put OPENAI_MODEL
```

`OPENAI_MODEL` is optional. The default is `gpt-5-mini`.

7. Test locally:

```bash
wrangler dev
```

8. Deploy:

```bash
wrangler deploy
```

After deploy, Cloudflare will return a stable Worker URL such as:

```text
https://global-news-agent.<your-subdomain>.workers.dev
```

If you later want your own domain, attach a custom domain in Cloudflare.

## GitHub Auto Deploy

Recommended workflow:

1. Push this repo to GitHub.
2. In Cloudflare Workers, connect the Worker to the GitHub repository.
3. Add `OPENAI_API_KEY` as a production secret in Cloudflare.
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
- The current fallback mode works without OpenAI, but the Chinese report quality is much better when `OPENAI_API_KEY` is configured.
- If you want long-term history, the next step is adding KV, D1, or R2 storage.
