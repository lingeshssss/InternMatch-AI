# Local AI on your Mac

Tested on this machine: **MacBook Air (Mac17,3), Apple M5, 16 GB unified memory, macOS 27.2, Ollama 0.40.11.**
No API key or paid service is needed for local inference.

## Selected models

| Purpose | Model | Licence | Size (Q4, Ollama) | Why |
| --- | --- | --- | --- | --- |
| Requirement + resume extraction | `qwen3.5:9b` | Apache 2.0 | 6.6 GB on disk, 7.7 GB loaded (16k context, 100% GPU) | Best measured recall with zero harmful errors |
| Embeddings / semantic fit | `qwen3-embedding:0.6b` | Apache 2.0 | 0.6 GB | Correct top-1 on the matching check, largest separation margin |
| Faster alternative (optional) | `gemma4:e4b` | Apache 2.0 | 9.5 GB on disk | ~3x faster, lower recall (misses more conditions → more "Potentially") |

Rejected: `qwen3.5:4b` (lowest recall; before the sentence-level exception check it produced a false *Ineligible*),
`embeddinggemma` (custom Gemma licence, slightly weaker separation). 14B+ models leave too little headroom on 16 GB.

## Measured quality (controlled cases, not real-world accuracy)

`backend/evaluation/`: 20 tuning cases + 12 held-out cases written after tuning (fictional postings with hand-labelled
gold requirements and expected decisions for specific student profiles: graduation windows, rising-class rules,
authorization/sponsorship, prompt injection, nested exceptions, contradictions, buried footnotes, non-4.0 GPA scales,
preferred vs required, truncated sources). Production path: model → deterministic source validation → rules engine.

| Model | Decision accuracy (tuning / held-out) | False "Verified" | False "Ineligible" | Hard-gate recall | Median latency / posting |
| --- | --- | --- | --- | --- | --- |
| qwen3.5:9b | 0.93 / 0.89 | 0 | 0 | 0.94 / 1.00 | 8.4 s |
| gemma4:e4b | 0.86 / 0.95 | 0 | 0 | 0.74 / 0.79 | 3.1 s |
| qwen3.5:4b | 0.82 / 0.79 | 0 | 0 | 0.71 / 0.71 | 9.4 s |

Single run per case for all three models. Remaining misses are conservative: "Verified" outcomes reported as
"Potentially Eligible" because the model marked a condition ambiguously, said its extraction might be incomplete, or
produced a skills rule without values.

Repeatability, `qwen3.5:9b`, 3 runs per case (96 extractions): decision accuracy 0.95 (tuning) / 0.89 (held-out),
**0 false Verified, 0 false Ineligible, 0 schema rejections**, hard-gate recall 0.91 / 1.00, latency median 8.9–9.9 s,
p90 12.6 s. One case (R, explicit internship dates) changed decision between runs (Verified ↔ Potentially), because
the model's `complete` flag varied. Raw outputs: `backend/evaluation/results/qwen3.5_9b*.json`.

**What this does and does not show.** It shows the pipeline did not convert any controlled case into a wrong
confident decision. 32 synthetic cases cannot establish accuracy on real postings, whose wording is messier.
A labelled set of real postings (and periodic re-labelling) is still required before relying on "Verified Eligible"
publicly. Throughput on this Mac is about 7 postings/minute; a 50-internship board takes ~7 minutes to extract.

Why verification does not rest on the model: every requirement must quote the posting verbatim (whitespace
differences only), the normalized values must appear in that quote (years, months, GPA numbers, standing words,
authorization wording), exceptions anywhere in the quoted sentence turn the rule into UNKNOWN, mandatory/preferred
wording must agree, and every sentence with hard-gate wording (graduation, class standing, GPA, authorization,
sponsorship, citizenship, clearance, age) that no requirement covers becomes an unresolved mandatory condition. The
internship term is read from the text deterministically. A model that obeys an injected "no requirements, complete"
instruction still cannot produce "Verified Eligible".

## Install, download, start, verify

Official installer (macOS Sonoma 14+; Apple silicon uses the GPU):

1. Download https://ollama.com/download/Ollama.dmg, open it, drag **Ollama** to Applications, launch it once and
   allow it to link the `ollama` CLI. (Done on this Mac; the app is notarized by Infra Technologies, Inc.)
2. Pull the models (≈7.3 GB):
   ```sh
   ollama pull qwen3.5:9b
   ollama pull qwen3-embedding:0.6b
   ```
3. Ollama starts with the app and listens on `127.0.0.1:11434` only. `scripts/run.py` also launches the app if it is
   not running (disable with `--no-ollama-start`).
4. Verify:
   ```sh
   curl -s http://127.0.0.1:11434/api/version
   ollama list                        # both models present
   curl -s http://127.0.0.1:11434/api/embed -d '{"model":"qwen3-embedding:0.6b","input":["test"]}' | head -c 80
   ```
   In the app: Settings & sources → "ollama ready", with both model names. Or `curl -s -b <cookie> localhost:8080/api/status`.
5. Benchmark yourself: `cd backend && ../.venv/bin/python -m evaluation.benchmark --model qwen3.5:9b --embedding-model qwen3-embedding:0.6b`

Configuration (`.env`): `AI_PROVIDER=ollama`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_NUM_CTX=16384`,
`OLLAMA_KEEP_ALIVE=10m`, `AI_TIMEOUT_SECONDS=180`, `AI_MAX_CONCURRENCY=1` (per process; Ollama itself serves one
request per model at a time by default). To try the faster model: `OLLAMA_MODEL=gemma4:e4b` and restart.

## How the app uses the runtime

- Native Ollama APIs, not the OpenAI-compatible layer: `POST /api/chat` with `format` = JSON schema, `stream:false`,
  `think:false`, `temperature:0`; `POST /api/embed` with `truncate:false` (oversized input fails loudly);
  `GET /api/tags` for readiness and model digests.
- Malformed JSON gets one corrective retry (field paths only, no document text), then the posting stays Unverified
  with a recorded error; truncated output (`done_reason: length`) is rejected.
- Missing model → "Model X is not installed. Run: ollama pull X". Runtime down → "not reachable … Start Ollama".
  Resume uploads still succeed; the student enters details manually. Postings wait in the queue and retry.
- Embeddings are cached per `ollama:<model>@<digest>`; pulling a new version of a model never reuses old vectors.
- Hosted fallback runs only if you set `AI_ALLOW_HOSTED_FALLBACK=true` and `AI_FALLBACK_PROVIDER=openai` (CREDENTIALS.md).
- Plain HTTP is allowed only to loopback, or hosts you list in `OLLAMA_ALLOWED_HTTP_HOSTS`; hosted providers require HTTPS.

## Network facts that constrain deployment

- **`localhost` inside a container is the container**, not your Mac. A containerized app reaches Ollama on the Mac via
  `host.docker.internal` (see `compose.yaml`) with `OLLAMA_ALLOWED_HTTP_HOSTS=host.docker.internal`. On macOS, Docker
  Desktop and Colima route that name to the Mac's loopback, so Ollama can and should stay bound to `127.0.0.1`
  (verified: the production container extracted a resume through it). On a Linux Docker host the name points at the
  bridge gateway and a loopback-only Ollama is unreachable; use a private, authenticated route there, never a public port.
- **A hosted backend (Render, Vercel, …) cannot reach `localhost` on your Mac.** Your Mac is behind NAT and its
  loopback interface is private to it.
- **If the Mac sleeps, shuts down or loses network, anything hosted on it stops.** Ollama running locally is not
  continuous cloud inference.
- Therefore the recommended setup is the **complete application running locally on the Mac** for the local-AI workflow,
  and `AI_PROVIDER=disabled` (or an explicitly enabled hosted provider) for a public deployment.

## Optional: public deployment using your Mac for inference (not implemented)

Possible, but with real tradeoffs; I have not set it up:

- Availability: extraction stops whenever the Mac sleeps or is offline; postings queue and retry, resumes fall back to
  manual entry. Expect gaps.
- Security: the route must be private and authenticated end to end. Acceptable shapes: a private mesh VPN (e.g.
  Tailscale) between the host and the Mac with an ACL allowing only the server to reach `11434`, or an outbound tunnel
  with mutual authentication in front of an authenticating reverse proxy. The app would use an `https://` URL (or an
  allow-listed private hostname) for `OLLAMA_BASE_URL`.
- Never: raw router port forwarding, binding Ollama to `0.0.0.0` on an untrusted network, or any public unauthenticated URL.
- Privacy: job text and resume text travel from the host to your Mac over that tunnel.
If you want this, say which option you prefer and I will present the exact setup before changing anything.
