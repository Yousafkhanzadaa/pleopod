# Pleopod Backend Architecture

Docs checked: April 24, 2026.

Official docs used while designing this backend:

- FastAPI background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
- FastAPI Docker deployment: https://fastapi.tiangolo.com/deployment/docker/
- Supabase Queues: https://supabase.com/docs/guides/queues
- Supabase Edge Function limits: https://supabase.com/docs/guides/functions/limits
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase JWT signing keys: https://supabase.com/docs/guides/auth/signing-keys
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Cloudflare R2 presigned URLs: https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- Gemini API speech generation: https://ai.google.dev/gemini-api/docs/speech-generation
- Gemini structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Gemini grounding with Google Search: https://ai.google.dev/gemini-api/docs/google-search
- Gemini URL context: https://ai.google.dev/gemini-api/docs/url-context
- Gemini image generation: https://ai.google.dev/gemini-api/docs/image-generation

Important doc-backed decisions:

- FastAPI background tasks are not used for durable long-running generation. This backend uses a separate worker instead.
- Supabase Queues are used for durable pipeline messages via `pgmq`.
- Supabase JWTs are verified through the JWKS discovery endpoint for modern signing keys.
- The legacy JWT secret is only supported as an explicit migration fallback.
- Long media-generation work does not live inside hosted Supabase Edge Functions.
- R2 is used for generated artifacts and published media because it is S3-compatible and avoids egress fees.
- Gemini 3.1 Flash TTS Preview is treated as the default two-speaker MVP path,
  chunked for longer episodes, with Gemini 2.5 Flash Preview TTS as a fallback.
- Gemini 2.5 Flash Lite is used for the title orchestration step before job creation.
- Gemini structured outputs are used where the configured model/tool combination supports them.
- Gemini Google Search grounding and URL context are used by the research layer, with
  backend schema validation after JSON extraction.

## System Shape

```text
Client/Admin
    |
FastAPI
    |
Orchestration Agent
    |
Supabase Postgres + PGMQ
    |
Worker
    |
Gemini/Search/TTS/Image APIs
    |
Cloudflare R2
```

## Why Pipeline Steps Instead of Free-Form Agents

The product needs trust. A black-box multi-agent chat is hard to inspect, retry, price, and debug.

Each agent here is a durable step:

- explicit input artifacts
- explicit output artifacts
- database state
- queue handoff
- retry count
- dead-letter path
- human approval gates

That makes the system sellable, not just impressive in a demo.

## Artifact Strategy

Every important output is saved:

- `memory.md`
- `research.json`
- `claim_bank.json`
- `script_v1.json`
- `script_verified.json`
- `verification_report.md`
- thumbnail image
- TTS config
- audio segments
- final audio
- episode metadata

Markdown exists for humans. JSON exists for machines.

## Human Approval Gates

Set:

```env
REQUIRE_HUMAN_APPROVAL=true
```

Then the pipeline pauses:

- after script verification

Use admin endpoints to approve and continue.

This should stay on until the verification system proves itself.
