# Validation evidence

These results apply to this cloud instance and the checked-out files. They do not establish production deployment, a newly published environment, real-provider accuracy, or live opportunity availability.

## Passed

- `./scripts/install.sh`: repeated successfully using pinned Python requirements and `npm ci`, existing ignored encryption configuration, healthy PostgreSQL 16 and Redis 7 containers, and Alembic migrations. Home-directory cache writes were replaced with `/workspace/.cache` locations.
- Backend: **52 passed**, zero skipped, with one upstream Starlette TestClient deprecation warning. Tests exercise graduation boundaries, first-year/rising-sophomore rules, junior-only failure, GPA including zero/unknown, unknown authorization, degree aliases, mandatory vs preferred qualifications, missing academic scope, inaccessible/incomplete/closed sources, contradictory requirements, authentication/Origin checks, encrypted profiles, tenant isolation, confirmation before using resume facts, unsafe uploads, source quote/metadata validation, duplicate ingestion, successful-feed closure vs failed-feed preservation, notification deduplication, stale-source suppression and refreshed decision caching.
- PostgreSQL migration `0001`: upgraded on the development database. A separate disposable PostgreSQL database successfully upgraded to head, downgraded to base, then upgraded again; that disposable database was removed afterward.
- `npm run build`: production compilation and TypeScript checks passed with Next.js **16.4.3**.
- `npm run test:e2e`: **1 passed** Chromium workflow against the running Next.js production server and actual PostgreSQL/Redis-backed API. It registers an account, checks Strict Match by default, saves and reloads a profile, preserves unknown authorization, visits application tracking, queries the empty stored catalogue, checks a 390px mobile layout for horizontal overflow, changes theme, and deletes the test account. Browser runtime errors: none. No test accounts or fabricated jobs remain in the development database.
- API `GET /health`: HTTP 200; database, Redis, and encryption prerequisites available. AI, employer sources, and email configuration flags are all **false**.
- Production frontend HTTP 200. Default development launcher also started successfully and served the frontend and API with HTTP 200.
- Launcher shutdown/restart check: terminating the launcher stopped API, worker and frontend, leaving ports 3000 and 8000 free before restart. The default development launcher is running at completion; processes must restart in future tasks.
- `npm audit` including development dependencies: **0 known vulnerabilities** after upgrading Next.js and overriding the transitive PostCSS selector parser to a patched compatible release. The final build and browser test ran after the changes.
- `pip-audit -r backend/requirements.lock`: **No known vulnerabilities found** after replacing vulnerable versions and re-freezing the installed dependencies. All Python package versions are pinned in the lock file.
- `.env`, virtual environment, node_modules, build outputs and browser test results are ignored by Git. New application files remain uncommitted for review; the source repository had an unborn branch and no existing files.

## Blocked or unrun

- Direct read-only requests to `boards-api.greenhouse.io` and `api.lever.co` returned **HTTP CONNECT 403** from the current environment network policy. No feeds were claimed to work and no real postings were inserted.
- AI extraction, embeddings and real-resume extraction were not run: `AI_API_KEY` is absent. Controlled extraction tests validate schemas/evidence handling, not provider semantics or completeness.
- SMTP delivery, search-engine integrations, hosted deployment, production end-to-end tests, load tests, security audit and real-provider evidence-quality benchmarks were not run. See LIMITATIONS.md for feature gaps requiring implementation in addition to credentials.

## Saved environment draft

Saved `install_script`, `start_skill`, additional allowed domains `boards-api.greenhouse.io`, `api.lever.co`, `api.openai.com`, an `AI_API_KEY` secret requirement scoped to `api.openai.com`, and `GREENHOUSE_BOARDS` / `LEVER_SITES` variable requirements. Saving was confirmed. It did not apply network changes to the running instance, supply credential values, or publish the environment. Review and save these settings, enter values securely, and publish the cloud environment to retain the prepared setup. This publication is separate from deploying the application to Vercel and backend hosting.
