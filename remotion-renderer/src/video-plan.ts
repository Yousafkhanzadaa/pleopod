import {z} from 'zod';

export const sceneLayoutSchema = z.enum([
  'episode_intro',
  'chapter_card',
  'speaker_focus',
  'concept_card',
  'bullet_card',
  'source_card',
  'timeline',
  'quote_card',
  'diagram_card',
  'thumbnail_focus',
  'closing_card',
]);

export const lineTimingSchema = z.object({
  id: z.string().min(1),
  speaker: z.string().min(1),
  text: z.string().min(1),
  startSeconds: z.number().min(0),
  endSeconds: z.number().min(0),
});

export const videoSceneSchema = z
  .object({
    id: z.string().min(1),
    startSeconds: z.number().min(0),
    endSeconds: z.number().min(0),
    layout: sceneLayoutSchema,
    headline: z.string().min(1),
    subheadline: z.string().optional(),
    speakerName: z.string().optional(),
    quote: z.string().optional(),
    bullets: z.array(z.string()).max(5).default([]),
    diagramItems: z.array(z.string()).max(6).default([]),
    sourceUrls: z.array(z.string()).max(4).default([]),
    captionLineIds: z.array(z.string()).default([]),
    visualKeywords: z.array(z.string()).max(8).default([]),
    emphasis: z.enum(['calm', 'curious', 'urgent', 'technical', 'reflective']).default('calm'),
  })
  .refine((scene) => scene.endSeconds > scene.startSeconds, {
    message: 'Scene endSeconds must be greater than startSeconds',
    path: ['endSeconds'],
  });

export const videoPlanSchema = z.object({
  version: z.literal(1).default(1),
  directorModel: z.string().default('manual'),
  durationSeconds: z.number().min(5).max(7200),
  lineTimings: z.array(lineTimingSchema).default([]),
  scenes: z.array(videoSceneSchema).min(1),
  productionNotes: z.array(z.string()).default([]),
});

export type SceneLayout = z.infer<typeof sceneLayoutSchema>;
export type LineTiming = z.infer<typeof lineTimingSchema>;
export type VideoScene = z.infer<typeof videoSceneSchema>;
export type VideoPlan = z.infer<typeof videoPlanSchema>;

export const normalizeVideoPlan = (plan: VideoPlan): VideoPlan => {
  const durationSeconds = Math.max(5, plan.durationSeconds);
  const sourceScenes = [...plan.scenes]
    .filter((scene) => scene.endSeconds > scene.startSeconds)
    .sort((a, b) => a.startSeconds - b.startSeconds);
  const scenes = sourceScenes.length ? sourceScenes : plan.scenes;
  const totalSceneSeconds =
    scenes.reduce(
      (sum, scene) => sum + Math.max(0.1, scene.endSeconds - scene.startSeconds),
      0,
    ) || scenes.length;
  let cursor = 0;

  const normalizedScenes = scenes.map((scene, index) => {
    const remainingScenes = scenes.length - index;
    const remainingSeconds = durationSeconds - cursor;
    const proportionalSeconds =
      (Math.max(0.1, scene.endSeconds - scene.startSeconds) / totalSceneSeconds) *
      durationSeconds;
    const endSeconds =
      index === scenes.length - 1
        ? durationSeconds
        : Math.min(
            durationSeconds - Math.max(0.1, remainingScenes - 1),
            cursor + Math.max(0.1, proportionalSeconds),
          );
    const normalized = {
      ...scene,
      startSeconds: roundSecond(cursor),
      endSeconds: roundSecond(Math.max(cursor + 0.1, Math.min(durationSeconds, endSeconds))),
    };
    cursor = normalized.endSeconds;
    if (remainingSeconds <= 0) {
      return {
        ...normalized,
        startSeconds: roundSecond(Math.max(0, durationSeconds - 0.1)),
        endSeconds: roundSecond(durationSeconds),
      };
    }
    return normalized;
  });

  return {
    ...plan,
    durationSeconds,
    lineTimings: plan.lineTimings
      .map((line) => ({
        ...line,
        startSeconds: roundSecond(clamp(line.startSeconds, 0, durationSeconds)),
        endSeconds: roundSecond(clamp(line.endSeconds, 0, durationSeconds)),
      }))
      .filter((line) => line.endSeconds > line.startSeconds),
    scenes: normalizedScenes,
  };
};

export const findSceneAtSecond = (plan: VideoPlan | undefined, second: number) => {
  if (!plan) {
    return null;
  }

  const sorted = [...plan.scenes].sort((a, b) => a.startSeconds - b.startSeconds);
  if (sorted[0] && second < sorted[0].startSeconds) {
    return sorted[0];
  }
  return (
    sorted.find((scene) => second >= scene.startSeconds && second < scene.endSeconds) ??
    sorted.at(-1) ??
    null
  );
};

export const findLineAtSecond = (plan: VideoPlan | undefined, second: number) => {
  if (!plan) {
    return null;
  }

  return (
    plan.lineTimings.find((line) => second >= line.startSeconds && second < line.endSeconds) ??
    plan.lineTimings.at(-1) ??
    null
  );
};

const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value));
};

const roundSecond = (value: number) => {
  return Math.round(value * 10) / 10;
};
