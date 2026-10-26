# InternMatch AI

Evidence-backed internship discovery and eligibility verification: Next.js + FastAPI + PostgreSQL behind one URL,
with optional local AI (Ollama) for requirement extraction, resume drafts and semantic matching.

**Status:** works end to end on a Mac (verified in a real browser). Not production-ready. There is no public deployment
yet, and account recovery, email verification and upload isolation are still missing. See [limitations](docs/LIMITATIONS.md).

## Start (macOS)

```sh
brew install uv postgresql@17 caddy      # plus Node 24; optional: Ollama (docs/LOCAL_AI.md)
./scripts/install.sh                     # once; never overwrites existing .env keys
.venv/bin/python scripts/run.py          # PostgreSQL, migrations, API, worker, Next.js, Caddy
open http://localhost:8080
```

Everything is served from `http://localhost:8080`. The browser calls same-origin `/api/*`, which Caddy forwards to FastAPI.
Local AI: `ollama pull qwen3.5:9b && ollama pull qwen3-embedding:0.6b` (`AI_PROVIDER=ollama` is the installed default).
Employer feeds: set `GREENHOUSE_BOARDS` / `LEVER_SITES` in `.env` to public board identifiers, restart, then click
"Refresh opportunities". No sample jobs are seeded and no student profile is preloaded.

## Eligibility contract

Every mandatory requirement is PASS, FAIL or UNKNOWN; UNKNOWN never becomes PASS.

- **Verified Eligible**: every stated mandatory requirement passes, with source-validated evidence, from a fresh, open, complete posting.
- **Potentially Eligible**: no confirmed failure, but something is unresolved (unknown facts, unclear wording, an unreviewed condition, no stated academic scope).
- **Ineligible**: at least one confirmed mandatory failure. Technical fit never overrides it.
- **Unverified**: the source is inaccessible, stale (>48 h), closed, truncated, or has no validated requirements.

Academic standing is compared only for the internship term the employer's own text states. It is never taken from
the student's preferred date or inferred from graduation year. Degree, GPA, citizenship, work authorization,
certifications and credits are never inferred. Exact employer quotes, character spans, content hashes, URLs and
retrieval times are preserved. Model output is untrusted. Deterministic validation against the source decides what
counts as evidence (docs/LOCAL_AI.md).

## Documentation

- [Deployment](docs/DEPLOYMENT.md): architecture, the Vercel failure diagnosis, local and container deployment, env checklist, backups, worker monitoring
- [Local AI](docs/LOCAL_AI.md): model choice, benchmark results, install/verify, network constraints
- [Credentials](docs/CREDENTIALS.md): what needs a secret, how to obtain it, where it goes
- [Validation](docs/VALIDATION.md): what was tested and what passed
- [Limitations](docs/LIMITATIONS.md): what is incomplete

## Tests

```sh
cd backend && ../.venv/bin/python -m pytest -q          # unit/integration (SQLite, no services needed)
./scripts/e2e.sh                                         # Playwright against disposable same-origin stacks
cd backend && ../.venv/bin/python -m evaluation.benchmark --model qwen3.5:9b   # local model evaluation
```
