# Remotion Video System

Reviewed: July 25, 2026.

Pleopod renders professional short-form motion graphics after the audio pipeline.
The renderer is deterministic: AI chooses structured content and timing, while
Remotion draws the final frames.

## Why Separate

Remotion is a Node/React video renderer. The current backend is Python/FastAPI.
Keeping video rendering separate preserves the current architecture:

- FastAPI remains a thin control plane.
- The podcast worker remains focused on AI/audio generation.
- Video rendering can scale separately because it is CPU, Chromium, and FFmpeg heavy.
- Failures in video rendering do not block audio publishing.

## Current Flow

```text
Audio Generation Agent
  -> writes final audio with aligned word and line timings

Video Render Agent
  -> writes video_payload.json
  -> asks the Scene Director for scene_plan.json
  -> grounds every chart number against the verified claim bank
  -> renders PresentationEpisode with Remotion
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
- exact word timings when alignment succeeds
- a grounded `scene_plan.json`

It should not need direct database access.

## Video Director Agent

Gemini decides content, not pixels. The backend Scene Director returns strict JSON
with:

- line timings
- word timings
- scene start and end times
- known layout names
- headlines, bullets, charts, diagrams, quotes, sources, and caption line ids

The renderer accepts only known layouts:

```text
title
statement
bullets
chart
timeline
quote
diagram
source
outro
```

Chart data passes a second backend gate. Ungrounded values are removed, and
multi-value charts without a shared unit become separate fact bullets rather than
a misleading visual comparison.

## Render Contract

The backend writes:

```text
jobs/{job_id}/video/video_payload.json
jobs/{job_id}/video/scene_plan.json
episodes/{episode_id}/video/final.mp4
```

The standalone CLI accepts both artifacts. It also serves exact `file://` media
inputs through a temporary loopback-only endpoint for local renders:

```bash
npm run render -- \
  --props video_payload.json \
  --scene-plan scene_plan.json \
  --composition PresentationEpisode \
  --out final.mp4
```

## Visual System

The `PresentationEpisode` composition uses:

- solid, flat color fields only—no gradients
- kinetic word entrances and hard-edged wipe transitions
- direct-to-canvas SVG charts with grounded values
- continuous but restrained geometric motion
- exact word-synchronized captions when alignment is present
- line-timing estimation as a resilient fallback

The palette and typography are deliberately high-contrast and editorial rather
than glassy, glossy, or template-like.

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

If no Gemini key is present, the backend uses a deterministic text-only fallback
plan so local fake-mode tests can still complete.

## Scaling Path

Start with local/server-side rendering in a single Node worker. Move to Remotion
Lambda if rendering volume grows or videos become long. Cloud Run exists in the
Remotion ecosystem, but current official docs mark it experimental/alpha, so it
should not be the first production choice.

## Narration And Caption Timing

`VOICE_PROVIDER=openai` uses `gpt-4o-mini-tts` for directed documentary
narration. With `ENABLE_WORD_ALIGNMENT=true`, the finished WAV is transcribed by
`whisper-1` using word timestamp granularity. The final-audio artifact stores the
aligned transcript, individual word spans, and word-derived line spans.

Alignment is best-effort. If it is unavailable, rendering continues with measured
audio-segment timings and estimated per-word spans.
