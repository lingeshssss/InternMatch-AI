# Deployment runbook

InternMatch AI is one application behind **one URL**. The browser only talks to its own origin; a reverse proxy
(Caddy) sends `/api/*` to FastAPI unchanged and everything else to Next.js. Session cookies are first-party
(`HttpOnly`, `SameSite=Lax`, and `__Host-…; Secure` in production), so no CORS or cross-site cookies are involved.

```
browser ──► :8080 Caddy ──► /api/*  ──► FastAPI (127.0.0.1:8000) ──┐
                      └──► /*      ──► Next.js (127.0.0.1:3000)    ├──► PostgreSQL
                                       worker (tasks, scheduler) ──┘     (rate limits, leases, queue, outbox)
                                       └──► Ollama (127.0.0.1:11434, optional) / hosted AI (optional)
```

Processes: Caddy, Next.js, FastAPI, the worker. Services: PostgreSQL only (Redis was removed; leases, rate limits,
the task queue and the email outbox live in PostgreSQL). Ollama is optional and local.

## Why the Vercel deployment failed (diagnosed 2026-10-25)

| Finding | Evidence |
| --- | --- |
| Frontend compiled with no `NEXT_PUBLIC_API_URL` | Vercel project `frontend` has zero environment variables; the deployed JS bundle contains `http://localhost:8000`, and the CSP header is `connect-src 'self' http://localhost:8000`. Sign-in from `https://frontend-delta-puce-51.vercel.app` therefore calls the visitor's own machine, which the browser blocks → Firefox "NetworkError when attempting to fetch resource." |
| Backend deployed to Vercel functions without configuration | Vercel project `backend` has zero environment variables. Every request, including `/health` and the CORS preflight, returns `503 {"detail":"Rate limiter unavailable"}` because it tries Redis on localhost. No PostgreSQL, no encryption key, and no place for the persistent worker. |
| Cookies would still fail | `*.vercel.app` is on the Public Suffix List, so `frontend-….vercel.app` and `backend-….vercel.app` are different sites; the `SameSite=Lax` session cookie is not sent on cross-site `fetch`. `FRONTEND_ORIGIN` defaulted to localhost, so the Origin check would also have returned 403. |

Fixes in this branch: same-origin `/api` everywhere, CSP `connect-src 'self'`, no compile-time API URL, PostgreSQL
instead of Redis, a single container that runs all processes. Neither Vercel project was modified.

## 1. Local (recommended first): one command

Prerequisites (macOS): `brew install uv postgresql@17 caddy` and Node 24. Optional: Ollama (see LOCAL_AI.md).

```sh
cd ~/Downloads/InternMatch-AI-main      # your checkout
./scripts/install.sh                     # once: venv, npm deps, .env (never overwrites keys), local PostgreSQL, migrations
.venv/bin/python scripts/run.py          # starts PostgreSQL, migrations, API, worker, Next.js dev, Caddy
open http://localhost:8080
```

`run.py --production` serves the built frontend (`npm --prefix frontend run build` first). `Ctrl+C` stops every
process group and the PostgreSQL instance it started. The local stack binds to `127.0.0.1` only.

Checks: `curl -s localhost:8080/api/health` → `{"status":"ok","worker":true,…}`. After signing in, Settings &
sources shows AI readiness, the worker heartbeat, task-queue counts and configured feeds.

## 2. Public deployment: one container + managed PostgreSQL

**Recommendation: Render — one Docker web service + one private Render Postgres.** It is the simplest host that
matches the app: it builds the root `Dockerfile`, terminates TLS, gives one HTTPS URL, keeps the container running
(the worker lives inside it), and provides managed PostgreSQL with backups. `render.yaml` is prepared but **not applied**.

The image was built and run locally (VALIDATION.md): all four processes use ~214 MiB, health checks pass, and the
browser tests pass against it.

Costs at the time of writing (verify on render.com/pricing before creating anything): web service `0.5c-512mb`
$7/month, Postgres `0.1c-256mb` $6/month plus $0.30/GB storage; Hobby workspace $0 + compute. ≈ **$13–15/month**.
Free tiers are unsuitable: free web services sleep after 15 minutes without traffic (stopping the worker) and free
Postgres expires after 30 days. If 512 MB proves tight for four processes, use `1c-2g` ($25/month).

Tradeoffs considered:

- **Keep Vercel for the frontend**: still needs a separate always-on backend host and database (three providers), and
  Vercel must forward `/api` server-side (`API_PROXY_TARGET`, supported in `next.config.ts`). More moving parts, two
  deploys per change. Not recommended.
- **Railway**: similar container model, usage-billed ($5 Hobby includes $5 usage; ~$10/GB-RAM-month). Comparable.
- **Fly.io**: 1 GB machine ≈ $8.78/month but Managed Postgres starts at $38/month.

### Free demo option (`render-free.yaml`)

Render free web service (Docker) + a free external PostgreSQL such as Neon (free plan: no card, 1 GB storage,
100 CU-hours/month per project, compute suspends after 5 minutes idle). Tradeoffs: the Render service sleeps after
15 minutes without traffic, so the first request after a pause takes about a minute and the worker (scheduled
discovery, queued extraction) only runs while it is awake. While awake, the worker keeps the database active, which
uses Neon compute hours; continuous use for a whole month would exceed the free allowance. Fine for demos, not for
reliable alerts. Steps: create a Neon project, copy its connection string, then New → Blueprint → branch
`fix/same-origin-local-ai`, Blueprint Path `render-free.yaml`, and enter `DATABASE_URL`, `APP_ORIGINS`,
`DATA_ENCRYPTION_KEY`.

### Deploy steps (after you approve the cost)

1. Push this branch and merge it (or point Render at the branch).
2. Generate a production encryption key **on your Mac**, store it in your password manager:
   `.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
3. Render Dashboard → New → Blueprint → select the repository → Render reads `render.yaml`. When prompted enter:
   `APP_ORIGINS` = `https://<service-name>.onrender.com` (exact, no trailing slash), `DATA_ENCRYPTION_KEY`
   (from step 2), `GREENHOUSE_BOARDS` / `LEVER_SITES` (optional, public identifiers).
4. Deploy. The container validates configuration, runs `alembic upgrade head`, then starts all processes.
5. Verify (section 4). Custom domain later: add it in Render, then add its origin to `APP_ORIGINS` and redeploy.

### Environment checklist (container)

| Variable | Required | Secret | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | yes | no | `production` (enables `__Host-` Secure cookies, disables API docs) |
| `APP_ORIGINS` | yes | no | Exact public `https://` origin(s). The container refuses `http://` except for local compose. |
| `DATABASE_URL` | yes | **yes** | Managed URL; `postgres://`/`postgresql://` accepted. Use a private network/`ipAllowList: []`. |
| `DATA_ENCRYPTION_KEY` | yes | **yes** | Fernet key. Same value forever unless you run a planned re-encryption. Back it up. |
| `TRUSTED_PROXIES` | yes behind a LB | no | CIDRs or `private_ranges` for the platform proxy, so rate limits see real client IPs. |
| `PORT` | platform | no | Caddy listens here (default 8080). |
| `RUN_MIGRATIONS` | no | no | `true` (default) migrates at start. Set `false` if you run migrations as a release job. |
| `AI_PROVIDER` | no | no | `disabled` on a hosted server unless you configure an authenticated private route (LOCAL_AI.md) or `openai`. |
| `AI_API_KEY` | only for `openai` | **yes** | Hosted provider key; HTTPS `AI_BASE_URL` enforced. |
| `GREENHOUSE_BOARDS`, `LEVER_SITES` | no | no | Public board identifiers. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `EMAIL_FROM` | no | no | Email digests. |
| `SMTP_PASSWORD` | with SMTP | **yes** | |

Secrets go only into the host's secret/env store. Never into Git, `NEXT_PUBLIC_*`, screenshots or logs. Changing
server env requires a restart; nothing requires a frontend rebuild (no API URL is compiled into the bundle).

### Proxy behaviour (verified locally)

- Paths are **not rewritten**: `/api/auth/login` reaches FastAPI as `/api/auth/login`.
- `X-Forwarded-For` is replaced with the single client IP Caddy resolves via `TRUSTED_PROXIES`; uvicorn trusts it only
  from `127.0.0.1`. Spoofed headers from clients are discarded.
- Request bodies: 6 MB for `/api/*` (resume limit 5 MB + multipart), 1 MB otherwise → `413`.
- Timeouts: header read 10 s, body read 60 s, upstream response headers 170 s, write 180 s. Resume extraction runs in
  the worker, so no request waits on the model.
- Access logs: JSON, request line and status only; headers (cookies, authorization) are deleted.

## 3. Database: migrations, backups, restore

- Migrations: `cd backend && ../.venv/bin/alembic upgrade head` (the launchers do this). `0002` replaces Redis with
  PostgreSQL tables (rate limits, leases, task queue, email outbox, embedding cache) and adds access/version columns;
  it was tested upgrade → downgrade → upgrade on PostgreSQL 17 with existing rows.
- Local backup: `set -a; source .env; set +a; $PG_BIN/pg_dump "${DATABASE_URL/+psycopg/}" -Fc -f internmatch-$(date +%F).dump`
- Local restore (into an empty database): `$PG_BIN/pg_restore --clean --if-exists -d "${DATABASE_URL/+psycopg/}" internmatch-YYYY-MM-DD.dump`
- A backup is useless without the **same** `DATA_ENCRYPTION_KEY`. Store key and dumps separately; test a restore.
- Render: paid Postgres has point-in-time recovery (3-day window on Hobby). Take a manual `pg_dump` before risky migrations.

## 4. Worker operation and monitoring

The worker (`python -m app.worker`) heartbeats every 30 s, elects one scheduler through a PostgreSQL lease, and
processes durable tasks: `discover`, `extract_job`, `extract_resume`, `refresh_user`, `send_email`. Tasks are
claimed with `FOR UPDATE SKIP LOCKED`, leases are renewed while running, failures retry with exponential backoff,
and exhausted tasks become `dead` with the error recorded. Email uses a transactional outbox; a crash after the SMTP
server accepted a message leaves it `uncertain` and it is **not** resent (at-most-once).

Monitor:
- `GET /api/health` (unauthenticated): database + key → 200; `"worker": true` while a heartbeat is under 2 minutes old.
- Settings & sources (signed in) or `GET /api/status`: AI readiness, worker heartbeat, task counts by status.
- Dead letters: `SELECT kind, last_error, finished_at FROM tasks WHERE status='dead' ORDER BY finished_at DESC;`
- Uncertain email: `SELECT id, created_at FROM email_outbox WHERE status='uncertain';`
- Platform health checks use `/api/health`; the container's Docker `HEALTHCHECK` uses `/api/health/live`.

## 5. Post-deploy verification

```sh
curl -fsS https://<origin>/api/health
curl -sI https://<origin>/ | grep -i content-security-policy     # connect-src 'self'
```
Then in a browser: register, reload (session persists), sign out, sign in, save a profile, upload a resume
(manual entry if AI is disabled), open a posting's evidence, save it, track an application. The automated
equivalent against any URL: `cd frontend && E2E_URL=https://<origin> npx playwright test --project same-origin`
(requires seeded controlled postings for the workflow spec; the auth spec works on an empty catalogue).
