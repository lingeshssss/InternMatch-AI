# Validation evidence

Recorded 2026-10-25 on the owner's MacBook Air (Apple M5, 16 GB, macOS 27.2) for branch `fix/same-origin-local-ai`.
These results do not establish a public deployment, real-world extraction accuracy, or SMTP delivery.

## Deployment diagnosis (the reported "NetworkError")

- `https://frontend-delta-puce-51.vercel.app`: deployed bundle contains `http://localhost:8000`; response CSP
  `connect-src 'self' http://localhost:8000`; Vercel project `frontend` has no environment variables.
- `https://backend-mu-beryl-48.vercel.app`: `GET /health` and the CORS preflight for `POST /auth/login` both return
  `503 {"detail":"Rate limiter unavailable"}`; project `backend` has no environment variables; no runtime log entries.
- Neither Vercel project was changed.

## Automated tests

| Suite | Result |
| --- | --- |
| Backend `pytest` (SQLite, no services) | **142 passed**. Includes acceptance cases A–F, quality gate (grounding, exceptions incl. outside the quoted fragment, coverage scanner, prompt injection, contradictions, term detection, EEO boilerplate, PhD standing), provider abstraction (URL policy, no key for Ollama, mandatory key/HTTPS for hosted, malformed-output retry, missing model, unreachable runtime, opt-in fallback, digest-versioned embedding cache), queue (lease, renewal, retry, dead letter, crash reclaim), outbox (sent once, interrupted → uncertain, connection failure retryable), Origin/CSRF, cookies (`__Host-`/Secure in production), session revocation, saved-version alerts, unbounded saved view, resume upload with AI unavailable, timezone conversion regression, managed DB URL normalization. |
| Baseline before changes | 46 passed, 6 failed on this Mac (the suite required a live Redis server). |
| Browser (Playwright/Chromium, `scripts/e2e.sh`, production builds behind Caddy, disposable databases) | **4 passed** in one run on the final code (25 s): same-origin auth (register, cookie attributes, reload persistence, `/api/auth/me`, logout revocation, wrong password, login, forged-Origin 403, no foreign-origin requests); workflow (profile, Potentially→Verified transition, evidence quotes/PASS/FAIL/source links, Ineligible and Unverified in Explore, search, saved view, application tracking, 390 px layout, theme); local-AI resume extraction with review-before-confirm; AI-unavailable status, clear error, no fabricated draft, manual entry. |
| Frontend `tsc --noEmit`, `next build` (Next.js 16.4.3, standalone) | pass |
| `npm audit` | 0 vulnerabilities |
| `pip-audit -r backend/requirements.lock` | No known vulnerabilities found (Redis client removed from the lock) |
| PostgreSQL 17 migration `0002` | upgrade → downgrade → upgrade with pre-existing rows; defaults applied |

Bugs found and fixed during validation (each has a regression test): non-UTC timestamp relabelling (4 h error),
Caddy listening on all interfaces, toasts hidden from assistive technology while a dialog was open, auth form stuck in
registration mode after sign-out, resume drafts overwriting confirmed profile fields, exception clauses outside the
quoted fragment, standing comparisons across conventions, EEO statements flagged as citizenship conditions, internship
term in ATS titles missed, "senior PhD student" read as undergraduate standing, successful empty extractions labelled Unverified.

## Same-origin stack (manual HTTP checks through Caddy on :8080)

`/api/health` 200 with worker heartbeat; page CSP `connect-src 'self'`; register sets
`internmatch_session; HttpOnly; Path=/; SameSite=lax` (no Domain); `/api/auth/me` with the cookie 200; cross-origin
`POST` 403; 7 MB upload 413; listeners: Caddy `127.0.0.1/[::1]:8080`, API `127.0.0.1:8000`, Next `127.0.0.1:3000`,
PostgreSQL `127.0.0.1:55432`, Ollama `127.0.0.1:11434`. Launcher stop: all ports freed, no orphan processes, restart OK.

## Production container (local Docker via Colima 0.10.3 / Docker 29.5)

`docker build .` succeeds (image 699 MB: Next.js standalone, FastAPI, worker, Caddy; non-root user `internmatch`).
`docker compose up` with a separate PostgreSQL 17 container and `APP_ENV=production`: migrations applied at start,
`/api/health` 200 with worker heartbeat, Docker `HEALTHCHECK` healthy, production CSP, cookie
`__Host-internmatch_session; HttpOnly; Secure; SameSite=lax; Path=/`, API docs disabled (404). Memory for all four
processes: 214 MiB. Playwright auth spec and local-AI resume spec **passed against the container**; the container's
worker reached Ollama on the Mac through `host.docker.internal` while Ollama stayed bound to `127.0.0.1`.
`docker compose restart`: graceful SIGTERM shutdown (worker stopped cleanly), idempotent migrations, healthy again in
~2 s. Entrypoint refuses `http://` public origins, invalid Fernet keys and non-production `APP_ENV`. Test containers
and volume were removed afterwards.

## Local AI

Installed Ollama 0.40.11 (official notarized DMG). Benchmarks in `backend/evaluation/results/` (summary in LOCAL_AI.md):
`qwen3.5:9b`, 96 extractions over 32 controlled cases: 0 false Verified, 0 false Ineligible, 0 schema rejections,
accuracy 0.95 / 0.89 (tuning / held-out), median 8.9–9.9 s. `qwen3-embedding:0.6b`: top-1 6/6 on the matching check.

## Live integrations (real network, this Mac)

- Public feeds: Greenhouse `stripe, airbnb, figma, discord, databricks, robinhood` and Lever `palantir, spotify` returned
  HTTP 200 (Lever `plaid` 404). The earlier cloud CONNECT 403 was an egress restriction, not a credential issue.
- End-to-end discovery in a disposable database (`GREENHOUSE_BOARDS=robinhood,figma`): 10 internship postings fetched and
  persisted in 3.1 s; 10 durable `extract_job` tasks completed with `qwen3.5:9b` in 165 s; all `done`, none dead.
  Decisions for a sample B.S. student (May 2028, rising junior for Summer 2027, authorized, Python/SQL): two PhD
  internships Ineligible (degree FAIL), eight Potentially Eligible (no stated hard requirements, or unresolved
  conditions such as "full-time MBA program"), none Verified. The database was dropped afterwards; the development
  catalogue contains no postings until you configure boards.

## Not run / blocked

- Public deployment and deployed end-to-end tests: awaiting your approval of hosting costs.
- SMTP delivery: no credentials. Hosted AI fallback: not enabled, no key.
- Load testing, security review, real-posting labelled accuracy evaluation.
