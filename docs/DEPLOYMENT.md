# Deployment runbook

This repository has a working development foundation, not a completed production launch. Read LIMITATIONS.md before enabling public traffic. Live external integrations require actual credentials and validation; none are simulated.

## Local development

Prerequisites: Python 3.12, uv, Node 24, Docker Compose. From the checkout root:

```sh
./scripts/install.sh
.venv/bin/python scripts/run.py
```

Install creates an ignored local encryption key only when `.env` does not exist. Keep this file private and backed up; losing the key makes encrypted data unrecoverable. Existing values are never overwritten. The local Compose credentials are development defaults and must not be used in production. For managed services, install dependencies separately and use `alembic upgrade head` rather than starting Compose.

Copy missing nonsecret settings from `.env.example` into `.env`. `GREENHOUSE_BOARDS` and `LEVER_SITES` are comma-separated official board identifiers, validated against `[A-Za-z0-9_-]`. Obtain identifiers from employers' official careers links. Empty lists perform no discovery. Employers are targets, never assumed openings. Greenhouse: boards-api.greenhouse.io; Lever: api.lever.co. Require egress to these hosts and api.openai.com for the default AI provider. Use provider keys only on server processes. `AI_API_KEY` may be provisioned through the environment's HTTPS secret proxy; use its configured destination. `DATA_ENCRYPTION_KEY`, database passwords, and SMTP credentials require direct runtime secret injection, not an HTTP proxy placeholder.

`AI_BASE_URL`, `AI_MODEL`, and `EMBEDDING_MODEL` select an OpenAI-compatible provider. The default is OpenAI gpt-4.1-mini and text-embedding-3-small. Provider access, availability, and output accuracy must be validated with real data before relying on results. AI calls incur provider charges. Resume contents are sent to this provider only during upload extraction; profile sections are sent during semantic matching.

`FRONTEND_ORIGIN` must exactly match the frontend URL including scheme and port. Unsafe requests require this Origin. `NEXT_PUBLIC_API_URL` is compiled into the frontend and requires a rebuild if changed. Local health: `curl -f http://localhost:8000/health`; it checks database, Redis, and encryption configuration and reports configured integration flags (not successful provider authentication).

## Validation

```sh
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/alembic upgrade head
cd ../frontend
npm run build
```

The unit/integration suite uses controlled fixtures and SQLite for isolated tests. PostgreSQL HTTP smoke validation is separate. No fixture postings are inserted into the running catalogue. Trigger discovery from the dashboard after configuring sources and starting `python -m app.worker` from `backend`. Inspect `/discovery` for source-specific outcomes and `/jobs?mode=explore` for actual retrieved descriptions. AI outages leave postings Unverified. A successful empty feed closes absent postings; failed feeds do not. Retrieval older than 48 hours cannot produce Verified Eligible.

## Managed deployment

1. Provision private managed PostgreSQL 16 and Redis 7 with TLS, backups, restricted network access, and resource limits. Inject `DATABASE_URL` using `postgresql+psycopg://...` and `REDIS_URL` using `rediss://...` into the API and worker. Use direct secret injection for credentials. Keep database owner/migration credentials separate from application credentials; application tables must not be publicly exposed.
2. Generate a Fernet `DATA_ENCRYPTION_KEY` securely and inject the same value into API and worker. Store it in the hosting secret manager. Never place it in NEXT_PUBLIC variables. Plan key rotation and backup restoration before launch.
3. Build the backend image from `backend/`. Run `alembic upgrade head` once as a release job with migration permissions. Run the API with the Dockerfile command, and a separate always-on process with `python -m app.worker` using the same image. There are no required local files in these containers; resumes are encrypted in PostgreSQL.
4. Deploy `frontend/` to Vercel with Next.js, setting `NEXT_PUBLIC_API_URL` to the HTTPS API origin before build. Set backend `APP_ENV=production` and `FRONTEND_ORIGIN` to the exact HTTPS frontend origin. Cookies are Secure in production. Prefer `app.yourdomain.com` and `api.yourdomain.com` to keep requests same-site; cross-site Vercel/hosting defaults will not work with SameSite=Lax cookies. Do not weaken cookie protections to mask domain configuration errors.
5. Set AI credentials, reviewed source identifiers, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `EMAIL_FROM` on the backend/worker only. SMTP uses STARTTLS with certificate validation. Verify sender/domain and recipient ownership before enabling email publicly.
6. Put the API behind a trusted TLS proxy. Default startup ignores forwarded IP headers. Configure trusted proxy IPs explicitly if enabling them; otherwise all clients behind a proxy may share the IP rate bucket. Add upstream request-body limits (5 MB + multipart overhead), timeouts, concurrency limits, WAF controls, and sandboxed document parsing before accepting untrusted public uploads.
7. Check `/health`, register/sign in, confirm a profile, upload and review a real resume, retrieve configured public feeds, inspect source quotes, exercise unknown authorization, and verify tenant isolation in the deployed instance. Validate email delivery and worker leadership/failure recovery. Run a real-provider extraction evaluation dataset and red-team prompt injection tests before relying on Verified Eligible publicly.
8. Configure structured logging/error monitoring without document contents, passwords, or tokens. Alert on failed discovery runs, worker outages, stale feeds, database failures, and provider spend. Logs currently emit error types; there is no hosted monitoring integration.

The worker uses Redis leader locking and database uniqueness to avoid duplicate rows. External email is at-least-once on a crash between SMTP acceptance and committing delivery status; exactly-once email delivery is not guaranteed. The lock has a one-hour lease: shard long discovery runs and implement lease renewal before scaling beyond small catalogues.

## Privacy & recovery

Profile, resumes, qualifications, application notes, evaluation results, and semantic matching evidence use authenticated encryption at rest. Passwords use Argon2id and opaque seven-day session tokens are hashed in the database. Ownership is enforced server-side on every private API route; this is not PostgreSQL RLS. Use a private database and never expose its tables directly to browsers. Account deletion removes associated private data from the active database. Backups require a documented expiry/deletion policy. Notification and audit history is pruned after 90 days by the worker; resumes persist until user deletion. Export contains sensitive data. Test a backup restoration with the encryption key before release.
