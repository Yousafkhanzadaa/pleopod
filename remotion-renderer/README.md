# Pleopod Remotion Renderer

Independent Remotion system for turning a generated Pleopod podcast episode into
a branded video asset.

This package is intentionally separate from the Python backend. The backend should
finish the podcast pipeline, write a small JSON payload, then invoke this renderer
or send the payload to a separate rendering worker.

The video is rendered entirely by Remotion. Gemini is used only as a Video Director
Agent that writes a structured `video_plan.json`.

## What It Renders

- 1920x1080 MP4 podcast video
- episode title, summary, category, duration, and current chapter
- thumbnail or generated cover placeholder
- speaker cards
- AI-directed scene layouts based on `video_plan.json`
- transcript or timing-driven caption card
- deterministic waveform/progress visuals
- optional final podcast audio

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
```

The sample payload has no audio file, so it renders a silent video. To render a real
episode, provide `audioUrl` and usually `thumbnailUrl` in the payload.

## Generate A Video Plan

Gemini 2.5 Flash-Lite can direct the on-screen content by producing a validated
`video_plan.json`:

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
  --plan ./payloads/my-episode.video-plan.json \
  --out ./out/my-episode.mp4
```

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
    {"name": "Maya", "role": "Analyst", "voiceName": "Puck"}
  ],
  "transcript": "Arman: Welcome back...\nMaya: Let's unpack it...",
  "chapters": [
    {"title": "Intro", "startSeconds": 0}
  ],
  "brand": {
    "name": "Pleopod",
    "tagline": "Factual tech podcasts, generated with evidence.",
    "primaryColor": "#22d3ee",
    "accentColor": "#f59e0b",
    "backgroundColor": "#101216"
  }
}
```

## Video Plan Contract

The director plan is validated by `src/video-plan.ts`. Gemini should return JSON,
not code.

```json
{
  "version": 1,
  "directorModel": "gemini-2.5-flash-lite",
  "durationSeconds": 600,
  "lineTimings": [
    {
      "id": "line_001",
      "speaker": "Arman",
      "text": "Welcome back...",
      "startSeconds": 0,
      "endSeconds": 5.4
    }
  ],
  "scenes": [
    {
      "id": "scene_001",
      "startSeconds": 0,
      "endSeconds": 18,
      "layout": "episode_intro",
      "headline": "The AI Podcast Pipeline",
      "captionLineIds": ["line_001"],
      "bullets": [],
      "diagramItems": [],
      "sourceUrls": [],
      "visualKeywords": ["pipeline", "audio"],
      "emphasis": "calm"
    }
  ],
  "productionNotes": []
}
```

Allowed layouts:

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

## Integration Notes

The Python backend should not import this package directly. Use one of these
handoff patterns:

1. Write `video_payload.json` as a job artifact.
2. Run the director step to write `video_plan.json`.
3. Enqueue a `video_render_queue` message.
4. Run a separate Node worker that reads the payload and plan, renders MP4, uploads to R2,
   and records `video_mp4` / `social_clip_mp4` artifacts.
5. Later, swap local server-side rendering for Remotion Lambda if volume grows.

## License Reminder

Remotion has a commercial license model. Before using this in production for a
company larger than the free-license threshold, confirm the required Remotion
license.
