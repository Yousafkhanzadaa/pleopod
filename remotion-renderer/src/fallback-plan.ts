import {parseDialogue} from './dialogue';
import type {PodcastVideoProps} from './types';
import type {LineTiming, VideoPlan, VideoScene} from './video-plan';

const minSceneSeconds = 5;

export const buildFallbackVideoPlan = (
  props: PodcastVideoProps,
  directorModel = 'deterministic-fallback',
): VideoPlan => {
  const lineTimings = buildApproximateLineTimings(props);
  const usableChapters = props.chapters.filter(
    (chapter) => chapter.startSeconds < props.durationSeconds - 1,
  );
  const chapterScenes = usableChapters
    .map((chapter, index) => {
      const nextChapter = usableChapters[index + 1];
      const startSeconds = clamp(chapter.startSeconds, 0, props.durationSeconds - 1);
      const endSeconds = clamp(
        nextChapter?.startSeconds ?? props.durationSeconds,
        startSeconds + minSceneSeconds,
        props.durationSeconds,
      );
      return {
        id: `scene_chapter_${index + 1}`,
        startSeconds,
        endSeconds,
        layout: index === 0 ? 'episode_intro' : 'chapter_card',
        headline: chapter.title,
        subheadline: props.summary,
        bullets: [],
        diagramItems: [],
        sourceUrls: [],
        captionLineIds: lineTimings
          .filter((line) => line.startSeconds >= startSeconds && line.startSeconds < endSeconds)
          .map((line) => line.id),
        visualKeywords: [props.category, chapter.title],
        emphasis: 'calm',
      } satisfies VideoScene;
    })
    .filter((scene) => scene.endSeconds > scene.startSeconds);

  const scenes =
    chapterScenes.length > 1
      ? chapterScenes
      : buildEvenScenes(props, lineTimings);

  return {
    version: 1,
    directorModel,
    durationSeconds: props.durationSeconds,
    lineTimings,
    scenes: normalizeScenes(scenes, props.durationSeconds),
    productionNotes: [
      'Fallback plan generated without Gemini. Use the director CLI for AI-directed scenes.',
    ],
  };
};

const buildEvenScenes = (
  props: PodcastVideoProps,
  lineTimings: LineTiming[],
): VideoScene[] => {
  const sceneCount = Math.max(1, Math.min(6, Math.ceil(props.durationSeconds / 25)));
  const sceneDuration = props.durationSeconds / sceneCount;
  const layouts = [
    'episode_intro',
    'speaker_focus',
    'concept_card',
    'bullet_card',
    'diagram_card',
    'closing_card',
  ] as const;

  return Array.from({length: sceneCount}, (_, index) => {
    const startSeconds = Math.round(index * sceneDuration * 10) / 10;
    const endSeconds =
      index === sceneCount - 1
        ? props.durationSeconds
        : Math.round((index + 1) * sceneDuration * 10) / 10;
    const coveredLineIds = lineTimings
      .filter((line) => line.startSeconds >= startSeconds && line.startSeconds < endSeconds)
      .map((line) => line.id);

    return {
      id: `scene_${index + 1}`,
      startSeconds,
      endSeconds,
      layout: layouts[index] ?? 'concept_card',
      headline: index === 0 ? props.title : headlineFromLines(lineTimings, coveredLineIds),
      subheadline: index === 0 ? props.summary : undefined,
      bullets: index === sceneCount - 1 ? ['Generated with evidence', 'Rendered by Remotion'] : [],
      diagramItems: [],
      sourceUrls: [],
      captionLineIds: coveredLineIds,
      visualKeywords: [props.category],
      emphasis: 'calm',
    };
  });
};

const buildApproximateLineTimings = (props: PodcastVideoProps): LineTiming[] => {
  if (props.lineTimings.length > 0) {
    return props.lineTimings
      .map((line) => ({
        ...line,
        startSeconds: roundSecond(clamp(line.startSeconds, 0, props.durationSeconds)),
        endSeconds: roundSecond(clamp(line.endSeconds, 0, props.durationSeconds)),
      }))
      .filter((line) => line.endSeconds > line.startSeconds);
  }

  const dialogue = parseDialogue(props.transcript);
  if (dialogue.length === 0) {
    return [];
  }

  const totalChars = dialogue.reduce((sum, line) => sum + Math.max(24, line.text.length), 0);
  let cursor = 0;

  return dialogue.map((line, index) => {
    const weight = Math.max(24, line.text.length) / totalChars;
    const rawDuration = props.durationSeconds * weight;
    const startSeconds = cursor;
    const endSeconds =
      index === dialogue.length - 1
        ? props.durationSeconds
        : Math.min(props.durationSeconds, cursor + Math.max(1.8, rawDuration));
    cursor = endSeconds;

    return {
      id: `line_${String(index + 1).padStart(3, '0')}`,
      speaker: line.speaker,
      text: line.text,
      startSeconds: roundSecond(startSeconds),
      endSeconds: roundSecond(endSeconds),
    };
  });
};

const normalizeScenes = (scenes: VideoScene[], durationSeconds: number): VideoScene[] => {
  return scenes.map((scene, index) => {
    const startSeconds = clamp(scene.startSeconds, 0, durationSeconds - 0.1);
    const endSeconds =
      index === scenes.length - 1
        ? durationSeconds
        : clamp(scene.endSeconds, startSeconds + 0.1, durationSeconds);
    return {
      ...scene,
      startSeconds: roundSecond(startSeconds),
      endSeconds: roundSecond(endSeconds),
    };
  });
};

const headlineFromLines = (lines: LineTiming[], ids: string[]) => {
  const line = lines.find((item) => ids.includes(item.id));
  if (!line) {
    return 'Key idea';
  }
  const words = line.text.split(/\s+/).slice(0, 7).join(' ');
  return words.length < line.text.length ? `${words}...` : words;
};

const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value));
};

const roundSecond = (value: number) => {
  return Math.round(value * 10) / 10;
};
