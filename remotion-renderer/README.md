# Pleopod Remotion Renderer

Independent Remotion system for turning a generated Pleopod episode into a
professional short-form motion-graphics video.

This package is intentionally separate from the Python backend. The backend should
finish the podcast pipeline, write a small JSON payload, then invoke this renderer
or send the payload to a separate rendering worker.

The video is rendered entirely by Remotion. The backend Scene Director writes a
grounded, engine-independent `scene_plan.json`; AI never draws frames.

## What It Renders

- 1920x1080, 30fps H.264/AAC MP4
- modern editorial motion graphics using solid colors only
- kinetic headlines and hard-edged wipe transitions
- grounded bar, line, donut, comparison, and stat visuals
- bullet, statement, timeline, quote, diagram, source, and outro scenes
- word-synchronized kinetic captions, with line-timing fallback
- restrained continuous geometry and a deterministic progress indicator
- final narration audio

The `PresentationEpisode` source contains no CSS or SVG gradients. The palette is
made from plain, high-contrast fills.

## Install

```bash
cd remotion-renderer
npm install
```

## Preview

```bash
npm run studio
```

## Render A Sample

```bash
npm run render:sample
npm run render:sample:planned
npm run render:presentation
```

The sample payload has no audio file, so it renders a silent video. To render a real
episode, provide `audioUrl` and usually `thumbnailUrl` in the payload.

## Legacy Video Plan

`PodcastEpisode` still supports the older camel-case `video_plan.json` contract:

```bash
GEMINI_API_KEY=... npm run plan -- \
  --props ./payloads/my-episode.json \
  --out ./payloads/my-episode.video-plan.json \
  --model gemini-2.5-flash-lite
```

For local development without Gemini:

```bash
npm run plan:fallback
```

## Render A Real Podcast Payload

```bash
npm run render -- \
  --props ./payloads/my-episode.json \
  --scene-plan ./payloads/my-episode.scene-plan.json \
  --sources ./payloads/my-episode.sources.json \
  --composition PresentationEpisode \
  --out ./out/my-episode.mp4
```

`audioUrl` and `thumbnailUrl` may be HTTPS URLs or local `file://` URLs. For local
files the CLI exposes only those exact assets through a temporary loopback server
for the duration of the render.

## Payload Contract

The renderer consumes JSON validated by `src/types.ts`.

```json
{
  "jobId": "uuid",
  "episodeId": "uuid",
  "title": "Episode title",
  "summary": "Short app summary",
  "description": "Longer episode description",
  "category": "Tech",
  "language": "en",
  "durationSeconds": 600,
  "audioUrl": "https://cdn.example.com/audio/final.mp3",
  "thumbnailUrl": "https://cdn.example.com/thumbnail/cover.png",
  "speakers": [
    {"name": "Arman", "role": "Host", "voiceName": "Charon"},
    {"name": "Maya", "role": "Analyst", "voiceName": "Aoede"}
  ],
  "wordTimings": [
    {"word": "Welcome", "startSeconds": 0.2, "endSeconds": 0.63}
  ],
  "transcript": "Arman: Welcome back...\nMaya: Let's unpack it...",
  "chapters": [
    {"title": "Intro", "startSeconds": 0}
  ],
  "brand": {
    "name": "Pleopod",
    "tagline": "Factual tech podcasts, generated with evidence.",
    "primaryColor": "#5B7CFA",
    "accentColor": "#F4C95D",
    "backgroundColor": "#0B0D10"
  }
}
```

## Scene Plan Contract

The presentation plan is snake-case JSON validated by `src/scene-plan.ts`, matching
`app/schemas/video_plan.py` directly.

```json
{
  "version": 1,
  "director_model": "gemini-2.5-flash-lite",
  "duration_seconds": 60,
  "line_timings": [
    {
      "id": "line_001",
      "speaker": "Arman",
      "text": "Welcome back...",
      "start_seconds": 0,
      "end_seconds": 5.4
    }
  ],
  "word_timings": [
    {"word": "Welcome", "start_seconds": 0.2, "end_seconds": 0.63}
  ],
  "scenes": [
    {
      "id": "scene_001",
      "start_seconds": 0,
      "end_seconds": 18,
      "layout": "title",
      "headline": "The AI Podcast Pipeline",
      "caption_line_ids": ["line_001"],
      "bullets": [],
      "diagram_items": [],
      "source_urls": [],
      "emphasis": "calm"
    }
  ],
  "production_notes": []
}
```

Allowed layouts:

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

Every non-stat multi-value chart must declare one shared `unit`. The backend
grounds values against the verified claim bank. The renderer also downgrades
older unitless multi-value charts to separate facts rather than placing unlike
metrics on one scale.

## Integration Notes

1. The Python worker writes `video_payload.json` and grounded `scene_plan.json`.
2. The render payload embeds the scene plan and asset URLs.
3. The worker invokes `PresentationEpisode`, uploads the MP4, and records the
   `video_mp4` artifact.
4. Rendering can later move to a dedicated worker without changing either JSON
   contract.

## License Reminder

Remotion has a commercial license model. Before using this in production for a
company larger than the free-license threshold, confirm the required Remotion
license.
