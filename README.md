# InternMatch AI

Evidence-backed internship discovery and eligibility verification, with a Next.js interface and FastAPI/PostgreSQL/Redis backend.

An empty source repository has been implemented as a working development foundation. This is **not yet a completed production platform**. Live AI, employer feeds, email and hosted deployment require configuration and additional validation. See [delivery limitations](docs/LIMITATIONS.md) for the remaining acceptance criteria.

## Start

Python 3.12, uv, Node 24, and Docker Compose are required.

```sh
./scripts/install.sh
.venv/bin/python scripts/run.py
```

Set optional provider/source configuration in the ignored `.env` using `.env.example` as a reference. The install script generates a local encryption key only if `.env` does not already exist. If it exists without a key, add a securely generated key before startup. No API credentials are included or fabricated.

Default discovery mode is Strict Match. No employer feeds are configured by default and no fake postings are seeded. Configure public employer board identifiers and an AI provider to ingest and extract actual postings. Missing credentials or inaccessible sources produce explicit failures/Unverified results.

## Eligibility contract

Each requirement is PASS, FAIL, or UNKNOWN. Mandatory failures disqualify independently of fit. Missing facts remain unknown. Source evidence is preserved with retrieval time, exact character span and content hash. Incomplete, inaccessible, closed or stale descriptions are Unverified. Missing stated academic scope remains Potentially Eligible. Profiles and resume drafts do not infer a degree, work authorization or other sensitive attributes.

See [deployment instructions](docs/DEPLOYMENT.md), [limitations](docs/LIMITATIONS.md), and [validation results](docs/VALIDATION.md).
