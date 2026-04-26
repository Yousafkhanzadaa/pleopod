# Remotion Video System

Reviewed: April 24, 2026.

Pleopod can add video generation as a separate execution-plane system without
changing the core podcast generation flow.

## Why Separate

Remotion is a Node/React video renderer. The current backend is Python/FastAPI.
Keeping video rendering separate preserves the current architecture:

- FastAPI remains a thin control plane.
- The podcast worker remains focused on AI/audio generation.
- Video rendering can scale separately because it is CPU, Chromium, and FFmpeg heavy.
- Failures in video rendering do not block audio publishing.

## Proposed Flow

```text
Publisher Agent
  -> writes episode metadata and audio assets
  -> writes video_payload.json artifact

Video Director Agent
  -> reads video_payload.json, verified transcript, and optional timing data
  -> calls Gemini 2.5 Flash
  -> writes video_plan.json

Remotion Renderer Worker
  -> loads video_payload.json and video_plan.json
  -> renders MP4 with remotion-renderer
  -> uploads video to R2
  -> records video artifact / episode asset
  -> marks generation job completed
```

The current backend wires this as a `video_render` worker step after `publish` when:

```env
ENABLE_VIDEO_RENDERING=true
```

## Payload Inputs

The Remotion renderer needs only public or signed asset URLs plus episode metadata:

- title, summary, description
- final audio URL
- thumbnail URL
- duration seconds
- transcript
- speakers
- chapters
- brand colors
- optional `video_plan.json` from Gemini

It should not need direct database access.

## Video Director Agent

Gemini 2.5 Flash should decide content, not render video. The agent returns strict
JSON with:

- line timings
- scene start and end times
- Remotion layout names
- headlines, bullets, diagrams, quote cards, source cards, and caption line ids

The renderer accepts only known layouts:

```text
episode_intro
chapter_card
speaker_focus
concept_card
bullet_card
source_card
timeline
quote_card
diagram_card
thumbnail_focus
closing_card
```

This keeps the creative decision-making flexible while keeping the video output
deterministic, brand-safe, and retryable.

## Recommended First Implementation

1. Keep `remotion-renderer/` as a standalone package.
2. The backend `VideoRenderAgent` writes:

```text
jobs/{job_id}/video/video_payload.json
```

3. The renderer director step writes:

```text
jobs/{job_id}/video/video_plan.json
```

4. The renderer worker accepts:

```bash
npm run render -- --props payload.json --plan video_plan.json --out final.mp4
```

5. Upload the result to:

```text
episodes/{episode_id}/video/final.mp4
```

6. Record an `episode_assets` row with `asset_type='video'`.

## Local Setup

Install the independent renderer once:

```bash
cd remotion-renderer
npm install
```

Then enable the backend stage:

```env
ENABLE_VIDEO_RENDERING=true
REMOTION_RENDERER_PATH=remotion-renderer
REMOTION_VIDEO_DIRECTOR_MODEL=gemini-2.5-flash-lite
```

If `GEMINI_API_KEY` is present, the director step uses Gemini. If no Gemini key is
present, the backend calls the renderer's deterministic fallback director so local
fake-mode tests can still complete.

## Scaling Path

Start with local/server-side rendering in a single Node worker. Move to Remotion
Lambda if rendering volume grows or videos become long. Cloud Run exists in the
Remotion ecosystem, but current official docs mark it experimental/alpha, so it
should not be the first production choice.

## Caption Caveat

The current transcript is dialogue text, not word-timed captions. The director can
make approximate line timings immediately. For true captions, add one of:

- TTS word timing if the provider exposes it
- post-generation transcription
- manual segment timestamps derived during audio chunking
