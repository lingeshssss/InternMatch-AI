# Credentials and external integrations

Nothing below is required to run InternMatch AI locally with local AI. Public ATS board identifiers are
configuration, not secrets. Never paste secret values into chat, issues, screenshots or Git; never put them in
`NEXT_PUBLIC_*` variables. Locally they live in the ignored `.env` (mode 600); in production, in the host's
secret store. Server environment changes need a restart, not a frontend rebuild.

| Integration | Needed for | Credential | Status on this Mac (2026-10-25) |
| --- | --- | --- | --- |
| Local AI (Ollama) | extraction, resume drafts, embeddings | none | working (see LOCAL_AI.md) |
| Greenhouse / Lever public feeds | discovery | none (board identifiers) | reachable; none configured yet — your choice of employers |
| Encryption key | encrypted profiles/resumes | `DATA_ENCRYPTION_KEY` (you generate it) | generated in `.env` by install.sh |
| Hosted AI fallback (optional) | extraction when Ollama is unavailable | `AI_API_KEY` | not configured, not enabled |
| SMTP email (optional) | email digests | `SMTP_PASSWORD` (+ host/user) | not configured |
| Hosting (optional) | public URL | Render account (dashboard login) | not created — awaiting your cost approval |

## Encryption key (`DATA_ENCRYPTION_KEY`)

Generated locally, never acquired from a provider. `scripts/install.sh` creates one only if `.env` has no key and
refuses to overwrite an empty-but-present key. Back it up in a password manager. Losing it makes every encrypted
profile, resume and evaluation unreadable; rotating it without re-encrypting has the same effect. Production needs its
own key, generated with:
`.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`

## Hosted AI fallback (OpenAI) — optional, off by default

What it does: if `AI_ALLOW_HOSTED_FALLBACK=true` and `AI_FALLBACK_PROVIDER=openai`, extraction and embeddings fall
back to OpenAI when the local runtime is unavailable. Job descriptions and resume text are then sent to OpenAI.
Validation is identical: hosted output is checked against the source the same way and cannot by itself verify anything.

1. Sign in at https://platform.openai.com → Settings → Billing: API usage is prepaid; add credit before keys work.
2. API keys (https://platform.openai.com/api-keys) → Create new secret key → owned by a dedicated project →
   Permissions: **Restricted**, with *Model capabilities* set to allow requests (shown as "Request" or "Write" in the
   current UI) and everything else *None*. Forum reports indicate the UI labelling of this scope has changed; if the
   first request fails with a missing-scope error, adjust Model capabilities and retry.
3. Put it in `.env` (local) or the host secret store (production): `AI_API_KEY=…`, `AI_ALLOW_HOSTED_FALLBACK=true`,
   `AI_FALLBACK_PROVIDER=openai`. Defaults `AI_MODEL=gpt-4.1-mini`, `EMBEDDING_MODEL=text-embedding-3-small`.
4. Restart (`Ctrl+C`, then `scripts/run.py`). Verify: stop Ollama, upload a resume; Settings shows the fallback; the
   resume provenance shows `openai:`.

Prices at the time of writing (https://developers.openai.com/api/docs/pricing): gpt-4.1-mini $0.40 / 1M input
tokens, $1.60 / 1M output; text-embedding-3-small $0.02 / 1M. A posting extraction is roughly 3–5k input tokens and
≤1k output, so about $0.002–0.004 per posting; 1,000 postings ≈ $2–4. Set a monthly budget limit in the dashboard.

## SMTP email — optional

What it does: daily/weekly digests of in-app notifications for users who opt in. Delivery is at-most-once.
Recommended: a transactional email provider with domain verification (SPF/DKIM) rather than a personal mailbox.
Any provider offering SMTP with STARTTLS on port 587 works:

- `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USERNAME`, `SMTP_PASSWORD` (secret), `EMAIL_FROM` (a verified sender).
- Restart the worker. Verify by enabling Email digest in Settings and checking `email_outbox` status becomes `sent`.

Tell me which provider you want and I will look up its current steps, limits and pricing before you create anything.
Before public use, email ownership verification and password reset are still missing (see LIMITATIONS.md).

## Hosting (Render) — optional, paid

No API key is needed by the app. You create a Render account and approve the Blueprint in the dashboard; Render
injects `DATABASE_URL` automatically. You enter `APP_ORIGINS` and `DATA_ENCRYPTION_KEY` when prompted. Costs and
steps: DEPLOYMENT.md §2.

## Existing Vercel projects

`frontend` and `backend` under the `lingesh8` team are unconfigured and not functional (DEPLOYMENT.md). They were not
modified. If you adopt the single-container deployment you can delete them in the Vercel dashboard; nothing depends on them.
