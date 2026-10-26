# Delivery status and remaining work

Audited 2026-10-25 against the code in branch `fix/same-origin-local-ai`. "Resolved" means implemented and covered
by tests listed in VALIDATION.md. It does not mean production-proven.

## Resolved in this branch

| Previous gap | Now |
| --- | --- |
| Frontend/backend split across Vercel projects; sign-in failed | One origin. Caddy routes `/api/*` to FastAPI unchanged; first-party `HttpOnly`/`SameSite=Lax` cookies (`__Host-`/`Secure` in production); CSP `connect-src 'self'`; no compile-time API URL. Verified in Chromium. |
| Redis required (6 tests failed without it) | Removed. PostgreSQL rate limits, scheduler lease and worker heartbeat. |
| No durable queue, lease renewal or dead letters | PostgreSQL task queue (`SKIP LOCKED` claims, renewed leases, exponential backoff, `dead` state with error, reclaim after worker crash). |
| SMTP could duplicate after a crash | Transactional outbox; interrupted sends become `uncertain` and are never resent automatically (at-most-once). |
| Version alerts fired for the initial saved version | Baseline hash stored at save time; alerts only for later changes. |
| Saved counts/views bounded to one page | `/api/saved` returns every saved posting; counts come from the database. |
| AI required a paid API key | Provider abstraction: local Ollama (no key), hosted OpenAI-compatible (HTTPS + key mandatory), disabled. Fallback only when explicitly enabled. |
| Resume extraction blocked the request | Background task with status polling; manual entry when AI is unavailable. Drafts never overwrite confirmed fields. |
| Exact quote ≠ correct interpretation | Deterministic validation: values must appear in the quote, exceptions anywhere in the quoted sentence → UNKNOWN, mandatory/preferred wording must agree, uncovered hard-gate sentences become unresolved conditions, contradictory windows → UNKNOWN, term read deterministically. |
| No real-provider/adversarial evaluation | 32 controlled cases (20 tuning + 12 held-out) incl. prompt injection, run against three local models (LOCAL_AI.md). |
| Inaccessible postings | Failed feed → postings `inaccessible` → Unverified until a successful refresh. |
| Timestamps on non-UTC hosts | Values from PostgreSQL were relabelled instead of converted (4-hour error in EDT: early session expiry, wrong staleness/heartbeat). Fixed: UTC sessions and conversion. |
| Launcher orphan processes | Rechecked: stop leaves no processes and frees all ports, including the PostgreSQL it started. |

## Not implemented or not validated

**Deployment**
- No public deployment exists. `render.yaml` + `Dockerfile` are prepared; creating them costs money and needs your approval.
- The two existing Vercel projects are unconfigured and non-functional; they were left untouched.

**Evaluation and AI**
- The evaluation set is synthetic (32 cases). No labelled set of **real** postings exists, so real-world extraction
  accuracy is unmeasured. Build one (≥100 real postings, independently labelled) before relying on "Verified Eligible" publicly.
- The coverage scanner is keyword-based: it can miss hard conditions phrased without its keywords, and it over-flags
  harmless sentences (more "Potentially Eligible"). It makes verification stricter, not complete.
- Unsupported semantics stay UNKNOWN: one-sided graduation bounds ("no later than June 2029"), credit-hour minimums,
  non-4.0 GPA scales, age, clearance, enrollment-type rules, majors with "or related field".
- Standing posted for "time of application" is resolved only by an exact date match; "sophomore" vs "rising junior"
  conventions are never treated as failures (UNKNOWN instead).
- Local throughput is ~7 postings/minute on this Mac; large boards take a while to extract. The Mac must be awake.
- "AI Analyst" is still keyword retrieval with citations, not conversational reasoning. Search-query suggestions are
  deterministic and not executed. Resume-specific truthful improvement advice is not implemented.

**Discovery and search**
- Only operator-configured Greenhouse and Lever boards. No Workday/Ashby/SmartRecruiters/university/government sources,
  authorized search APIs or autonomous company discovery.
- Search scans at most 1,000 SQL-filtered candidates per request (reported as truncated). No full-text/vector index,
  no compensation normalization, deduplication only by canonical URL.

**Security and operations**
- No email ownership verification, password reset or MFA. Do not open public registration before adding these.
- Resume parsing (pypdf/python-docx) runs in the API process with size/page/zip-expansion limits but no sandbox or
  malware scanning.
- No key-rotation tooling (a rotation would require re-encrypting all rows). No hosted error monitoring or alerting;
  monitoring is `/api/health`, `/api/status`, logs and SQL queries (DEPLOYMENT.md §4).
- Tenant isolation is enforced in API queries, not PostgreSQL row-level security. No independent security review or load test.
- Email delivery is not tested against a real SMTP provider (no credentials configured).

No generated sample jobs are shown to users. Controlled fixtures exist only in automated tests, the evaluation set
and the disposable e2e database. No student profile is preloaded, and no degree, GPA, citizenship, authorization,
certification or credits are inferred.
