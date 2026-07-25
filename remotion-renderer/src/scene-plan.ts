import {z} from 'zod';

// Mirrors app/schemas/video_plan.py (snake_case) so the backend's ScenePlan can
// be embedded directly in the render props with no case conversion.

export const sceneLayoutSchema = z.enum([
  'title',
  'statement',
  'bullets',
  'chart',
  'timeline',
  'quote',
  'diagram',
  'source',
  'outro',
]);

export const chartTypeSchema = z.enum(['bar', 'line', 'donut', 'stat', 'comparison']);

export const emphasisSchema = z.enum(['calm', 'curious', 'urgent', 'technical', 'reflective']);

export const chartDatumSchema = z.object({
  label: z.string().default(''),
  value: z.number(),
  claim_index: z.number().nullable().optional(),
  source_url: z.string().nullable().optional(),
});

export const sceneChartSchema = z.object({
  type: chartTypeSchema,
  title: z.string().default(''),
  unit: z.string().default(''),
  data: z.array(chartDatumSchema).default([]),
  caption: z.string().default(''),
});

export const plannedLineTimingSchema = z.object({
  id: z.string(),
  speaker: z.string().default(''),
  text: z.string().default(''),
  start_seconds: z.number(),
  end_seconds: z.number(),
});

export const plannedWordTimingSchema = z.object({
  word: z.string(),
  start_seconds: z.number(),
  end_seconds: z.number(),
});

export const plannedSceneSchema = z.object({
  id: z.string(),
  start_seconds: z.number(),
  end_seconds: z.number(),
  layout: sceneLayoutSchema,
  headline: z.string().default(''),
  subheadline: z.string().nullable().optional(),
  bullets: z.array(z.string()).default([]),
  chart: sceneChartSchema.nullable().optional(),
  quote: z.string().nullable().optional(),
  diagram_items: z.array(z.string()).default([]),
  source_urls: z.array(z.string()).default([]),
  caption_line_ids: z.array(z.string()).default([]),
  emphasis: emphasisSchema.default('calm'),
});

export const scenePlanSchema = z.object({
  version: z.literal(1).default(1),
  director_model: z.string().default('manual'),
  duration_seconds: z.number().min(1),
  line_timings: z.array(plannedLineTimingSchema).default([]),
  word_timings: z.array(plannedWordTimingSchema).default([]),
  scenes: z.array(plannedSceneSchema).min(1),
  production_notes: z.array(z.string()).default([]),
});

export type Emphasis = z.infer<typeof emphasisSchema>;
export type ChartDatum = z.infer<typeof chartDatumSchema>;
export type SceneChart = z.infer<typeof sceneChartSchema>;
export type PlannedLineTiming = z.infer<typeof plannedLineTimingSchema>;
export type PlannedWordTiming = z.infer<typeof plannedWordTimingSchema>;
export type PlannedScene = z.infer<typeof plannedSceneSchema>;
export type ScenePlan = z.infer<typeof scenePlanSchema>;

export const sanitizeScenePlanForPresentation = (plan: ScenePlan): ScenePlan => ({
  ...plan,
  scenes: plan.scenes.map((scene) => {
    const chart = scene.chart;
    if (
      scene.layout !== 'chart' ||
      !chart ||
      chart.type === 'stat' ||
      chart.data.length < 2 ||
      chart.unit.trim()
    ) {
      return scene;
    }
    return {
      ...scene,
      layout: 'bullets',
      bullets: chart.data.map((datum) => datum.label),
      chart: null,
    };
  }),
});

export const findSceneAtSecond = (plan: ScenePlan, second: number): PlannedScene => {
  const sorted = [...plan.scenes].sort((a, b) => a.start_seconds - b.start_seconds);
  return (
    sorted.find((scene) => second >= scene.start_seconds && second < scene.end_seconds) ??
    sorted.at(-1) ??
    sorted[0]
  );
};

// --- Word-group caption cues (mirrors app/services/motion_video.py) --- //

export type CaptionCue = {
  start: number;
  end: number;
  words: Array<{
    text: string;
    start: number;
    end: number;
  }>;
  emphasisIndex: number;
};

const emphasisIndexOf = (words: string[]): number => {
  let bestIndex = -1;
  let bestLen = 0;
  words.forEach((word, index) => {
    const core = word.replace(/[^A-Za-z0-9]/g, '');
    if (core.length >= 5 && core.length > bestLen) {
      bestIndex = index;
      bestLen = core.length;
    }
  });
  return bestIndex;
};

const captionText = (line: PlannedLineTiming): string => {
  const speaker = line.speaker.trim();
  if (!speaker) {
    return line.text.trim();
  }
  const escaped = speaker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return line.text.replace(new RegExp(`\\b${escaped}\\s*:\\s*`, 'gi'), '').trim();
};

export const captionCuesFromWordTimings = (
  wordTimings: PlannedWordTiming[],
  maxWords = 4,
  pauseBoundarySeconds = 0.3,
): CaptionCue[] => {
  const valid = wordTimings
    .filter(
      (word) =>
        word.word.trim().length > 0 &&
        word.start_seconds >= 0 &&
        word.end_seconds > word.start_seconds,
    )
    .sort((a, b) => a.start_seconds - b.start_seconds);
  const groups: PlannedWordTiming[][] = [];
  let group: PlannedWordTiming[] = [];
  for (const word of valid) {
    const previous = group.at(-1);
    const hasPause =
      previous !== undefined &&
      word.start_seconds - previous.end_seconds >= pauseBoundarySeconds;
    const endsPhrase =
      previous !== undefined && /[.!?;:]$/.test(previous.word.trim());
    if (group.length >= maxWords || hasPause || endsPhrase) {
      groups.push(group);
      group = [];
    }
    group.push(word);
  }
  if (group.length) {
    groups.push(group);
  }

  return groups.map((items, index) => {
    const nextStart = groups[index + 1]?.[0]?.start_seconds;
    const last = items[items.length - 1];
    return {
      start: items[0].start_seconds,
      end: Math.max(
        last.end_seconds,
        nextStart === undefined ? last.end_seconds + 0.16 : nextStart - 0.02,
      ),
      words: items.map((item) => ({
        text: item.word,
        start: item.start_seconds,
        end: item.end_seconds,
      })),
      emphasisIndex: emphasisIndexOf(items.map((item) => item.word)),
    };
  });
};

export const captionCuesFromLineTimings = (
  lines: PlannedLineTiming[],
  maxWords = 3,
  minCueSeconds = 0.32,
  gapSeconds = 0.02,
): CaptionCue[] => {
  const cues: CaptionCue[] = [];
  for (const line of lines) {
    const {start_seconds: start, end_seconds: end} = line;
    const text = captionText(line);
    if (!(end > start) || !text) {
      continue;
    }
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      continue;
    }
    const groups: string[][] = [];
    for (let index = 0; index < words.length; index += maxWords) {
      groups.push(words.slice(index, index + maxWords));
    }
    const totalChars = groups.flat().reduce((sum, word) => sum + word.length, 0) || 1;
    const span = end - start;
    let cursor = start;
    let charsBefore = 0;
    for (const group of groups) {
      const groupChars = group.reduce((sum, word) => sum + word.length, 0);
      let groupStart = Math.max(start + (span * charsBefore) / totalChars, cursor);
      charsBefore += groupChars;
      let groupEnd = start + (span * charsBefore) / totalChars;
      if (groupEnd - groupStart < minCueSeconds) {
        groupEnd = groupStart + minCueSeconds;
      }
      const wordSpan = Math.max(0.05, (groupEnd - groupStart) / group.length);
      cues.push({
        start: groupStart,
        end: groupEnd,
        words: group.map((word, wordIndex) => ({
          text: word,
          start: groupStart + wordIndex * wordSpan,
          end: Math.min(groupEnd, groupStart + (wordIndex + 1) * wordSpan),
        })),
        emphasisIndex: emphasisIndexOf(group),
      });
      cursor = groupEnd + gapSeconds;
    }
  }
  cues.sort((a, b) => a.start - b.start);
  for (let index = 0; index < cues.length - 1; index += 1) {
    if (cues[index].end > cues[index + 1].start) {
      cues[index].end = Math.max(cues[index].start + 0.05, cues[index + 1].start - 0.01);
    }
  }
  return cues.filter((cue) => cue.end > cue.start);
};

export const activeCaptionCue = (cues: CaptionCue[], second: number): CaptionCue | null => {
  return cues.find((cue) => second >= cue.start && second < cue.end) ?? null;
};
