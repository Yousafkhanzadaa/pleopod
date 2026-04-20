# Pleopod Backend

AI-agent podcast generation backend built with **FastAPI**, **Supabase Postgres/Queues**, and **Cloudflare R2**.

The system generates factual Tech podcast episodes through a durable pipeline:

1. Research agent gathers fresh sourced information.
2. Research review agent verifies and repairs the claim bank.
3. Script agent writes a Gemini TTS-ready two-speaker script.
4. Fact verifier checks and fixes the script line by line.
5. Thumbnail agent creates the cover image.
6. Audio config agent chooses speaker voices and chunking.
7. Audio generation agent creates final audio and stores it in R2.
8. Publisher writes episode metadata into Supabase.

## Stack

- FastAPI for API and admin endpoints.
- Supabase Postgres for metadata.
- Supabase Queues / `pgmq` for durable pipeline jobs.
- Cloudflare R2 for audio, thumbnails, transcripts, research memory, and generated artifacts.
- Gemini for grounded research, script generation, image generation, and Gemini 3.1 Flash TTS.

## Setup

```bash
cp .env.example .env
```

Fill in:

- `DATABASE_URL`
- Supabase publishable/secret keys
- Supabase JWKS URL or inline JWKS if self-hosted
- R2 credentials
- `GEMINI_API_KEY`
- `ADMIN_API_KEY`

Apply Supabase migrations:

```bash
supabase db push
```

Run locally:

```bash
pip install -e ".[dev]"
pleopod-api
```

In another terminal:

```bash
pleopod-worker
```

Create a job:

```bash
curl -X POST http://localhost:8000/admin/generation-jobs \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $ADMIN_API_KEY" \
  -d '{
    "topic": "What developers need to know about AI agents in 2026",
    "category": "Tech",
    "target_duration_seconds": 600,
    "auto_publish": false
  }'
```

Fetch published episodes:

```bash
curl http://localhost:8000/episodes
```

Run a full local generation smoke test:

```bash
.venv/bin/python scripts/generate_podcast.py "How AI coding agents are changing software development in 2026"
```

The script creates a job, polls until the pipeline completes or fails, and prints
the final audio URL.

## Local Fake Mode

For offline development:

```env
AI_PROVIDER=fake
STORAGE_BACKEND=local
```

This runs the pipeline without external AI or R2 calls.

## Production Notes

- Use R2 for all generated artifacts and published media.
- Keep research/job artifacts private.
- Publish app-facing audio via a Cloudflare custom domain or signed URLs.
- Run API and worker as separate services.
- Keep `REQUIRE_HUMAN_APPROVAL=true` until you trust the automated research and verification quality.
- Use two speakers for the MVP because Gemini multi-speaker TTS currently supports up to two speakers.
