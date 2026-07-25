import type {ReactNode} from 'react';
import {linearTiming, TransitionSeries} from '@remotion/transitions';
import {wipe, type WipeDirection} from '@remotion/transitions/wipe';
import {
  AbsoluteFill,
  Audio,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {PodcastVideoProps} from './types';
import {
  sanitizeScenePlanForPresentation,
  type PlannedScene,
  type ScenePlan,
} from './scene-plan';
import {SceneContent} from './presentation/scenes';
import {CaptionLayer} from './presentation/captions';
import {BODY_FONT, MONO_FONT, makeTheme, type Theme} from './presentation/theme';

const buildFallbackPlan = (props: PodcastVideoProps): ScenePlan => ({
  version: 1,
  director_model: 'inline-fallback',
  duration_seconds: props.durationSeconds,
  line_timings: props.lineTimings.map((line) => ({
    id: line.id,
    speaker: line.speaker,
    text: line.text,
    start_seconds: line.startSeconds,
    end_seconds: line.endSeconds,
  })),
  word_timings: props.wordTimings.map((word) => ({
    word: word.word,
    start_seconds: word.startSeconds,
    end_seconds: word.endSeconds,
  })),
  scenes: [
    {
      id: 'fallback_title',
      start_seconds: 0,
      end_seconds: Math.max(1, props.durationSeconds * 0.24),
      layout: 'title',
      headline: props.title,
      subheadline: props.summary ?? null,
      bullets: [],
      diagram_items: [],
      source_urls: [],
      caption_line_ids: [],
      emphasis: 'curious',
    },
    {
      id: 'fallback_body',
      start_seconds: Math.max(1, props.durationSeconds * 0.24),
      end_seconds: props.durationSeconds,
      layout: 'statement',
      headline: props.summary || props.title,
      subheadline: null,
      bullets: [],
      diagram_items: [],
      source_urls: [],
      caption_line_ids: [],
      emphasis: 'technical',
    },
  ],
  production_notes: [],
});

const TRANSITION_DIRECTIONS: WipeDirection[] = [
  'from-right',
  'from-bottom',
  'from-left',
  'from-top-right',
];

export const PresentationEpisode = (props: PodcastVideoProps) => {
  const {fps, durationInFrames} = useVideoConfig();
  const frame = useCurrentFrame();
  const plan = sanitizeScenePlanForPresentation(
    props.scenePlan ?? buildFallbackPlan(props),
  );
  const sceneFrames = framesForScenes(plan.scenes, fps, durationInFrames);
  const transitionFrames = Math.max(
    1,
    Math.min(12, ...sceneFrames.map((frames) => Math.max(1, frames - 1))),
  );
  const timeline: ReactNode[] = [];

  plan.scenes.forEach((scene, index) => {
    const sequenceFrames = sceneFrames[index] + (index > 0 ? transitionFrames : 0);
    timeline.push(
      <TransitionSeries.Sequence
        key={`scene-${scene.id}`}
        durationInFrames={sequenceFrames}
        name={`${index + 1} / ${scene.layout}`}
      >
        <SceneStage
          scene={scene}
          index={index}
          brand={props.brand}
          durationFrames={sequenceFrames}
        />
      </TransitionSeries.Sequence>,
    );
    if (index < plan.scenes.length - 1) {
      timeline.push(
        <TransitionSeries.Transition
          key={`transition-${scene.id}`}
          presentation={wipe({
            direction: TRANSITION_DIRECTIONS[index % TRANSITION_DIRECTIONS.length],
          })}
          timing={linearTiming({
            durationInFrames: transitionFrames,
            easing: (value) => 1 - Math.pow(1 - value, 3),
          })}
        />,
      );
    }
  });

  const baseTheme = makeTheme(props.brand);
  const progress = frame / Math.max(1, durationInFrames - 1);
  return (
    <AbsoluteFill
      style={{
        background: baseTheme.background,
        color: baseTheme.ink,
        fontFamily: BODY_FONT,
        overflow: 'hidden',
      }}
    >
      {props.audioUrl.trim() ? <Audio src={props.audioUrl.trim()} /> : null}
      <TransitionSeries>{timeline}</TransitionSeries>
      <CaptionLayer
        lineTimings={plan.line_timings}
        wordTimings={plan.word_timings}
        theme={baseTheme}
      />
      <BrandMark brand={props.brand.name || 'Pleopod'} theme={baseTheme} />
      <ProgressLine progress={progress} theme={baseTheme} />
    </AbsoluteFill>
  );
};

const SceneStage = ({
  scene,
  index,
  brand,
  durationFrames,
}: {
  scene: PlannedScene;
  index: number;
  brand: PodcastVideoProps['brand'];
  durationFrames: number;
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const theme = makeTheme(brand, scene.emphasis);
  const reveal = spring({
    frame,
    fps,
    config: {damping: 20, stiffness: 180, mass: 0.72},
  });
  const travel = interpolate(frame, [0, durationFrames], [0, 18], {
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{background: theme.background, overflow: 'hidden'}}>
      <FlatMotionField
        theme={theme}
        frame={frame}
        durationFrames={durationFrames}
        variant={index}
      />
      <AbsoluteFill style={{transform: `translate3d(${travel}px, ${-travel * 0.28}px, 0)`}}>
        <SceneContent
          scene={scene}
          index={index}
          theme={theme}
          brand={brand}
          reveal={reveal}
          localFrame={frame}
          fps={fps}
          width={width}
          height={height}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const FlatMotionField = ({
  theme,
  frame,
  durationFrames,
  variant,
}: {
  theme: Theme;
  frame: number;
  durationFrames: number;
  variant: number;
}) => {
  const {width, height} = useVideoConfig();
  const progress = frame / Math.max(1, durationFrames);
  const x = interpolate(progress, [0, 1], [-180, width + 120]);
  const y = interpolate(progress, [0, 1], [height * 0.78, height * 0.18]);
  const rotate = interpolate(progress, [0, 1], [-10, 18]);
  return (
    <AbsoluteFill>
      <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
        {Array.from({length: 11}).map((_, index) => (
          <line
            key={`v-${index}`}
            x1={(width / 10) * index}
            y1={0}
            x2={(width / 10) * index}
            y2={height}
            stroke={theme.line}
            strokeWidth={1}
          />
        ))}
        {Array.from({length: 7}).map((_, index) => (
          <line
            key={`h-${index}`}
            x1={0}
            y1={(height / 6) * index}
            x2={width}
            y2={(height / 6) * index}
            stroke={theme.line}
            strokeWidth={1}
          />
        ))}
      </svg>
      <div
        style={{
          position: 'absolute',
          left: x,
          top: variant % 2 ? y : height - y,
          width: 210,
          height: 210,
          background: variant % 3 === 0 ? theme.primary : theme.accent,
          transform: `rotate(${rotate}deg)`,
          opacity: 0.16,
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 86 + (variant % 4) * 42,
          bottom: 104 + (variant % 3) * 36,
          width: 110,
          height: 110,
          borderRadius: 999,
          background: theme.accentAlt,
          opacity: 0.16,
          transform: `translateY(${Math.sin(progress * Math.PI * 2) * 28}px)`,
        }}
      />
    </AbsoluteFill>
  );
};

const BrandMark = ({brand, theme}: {brand: string; theme: Theme}) => (
  <div
    style={{
      position: 'absolute',
      right: 54,
      top: 46,
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      color: theme.muted,
      fontFamily: MONO_FONT,
      fontSize: 19,
      fontWeight: 600,
      letterSpacing: 3,
      zIndex: 40,
    }}
  >
    <span style={{width: 13, height: 13, background: theme.accent}} />
    {brand.toUpperCase()}
  </div>
);

const ProgressLine = ({progress, theme}: {progress: number; theme: Theme}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      height: 7,
      background: theme.chartTrack,
      zIndex: 40,
    }}
  >
    <div
      style={{
        width: `${Math.min(100, Math.max(0, progress * 100))}%`,
        height: '100%',
        background: theme.accent,
      }}
    />
  </div>
);

const framesForScenes = (
  scenes: PlannedScene[],
  fps: number,
  durationInFrames: number,
): number[] => {
  const frames = scenes.map((scene) =>
    Math.max(1, Math.round(scene.end_seconds * fps) - Math.round(scene.start_seconds * fps)),
  );
  const difference = durationInFrames - frames.reduce((sum, value) => sum + value, 0);
  if (frames.length) {
    frames[frames.length - 1] = Math.max(1, frames[frames.length - 1] + difference);
  }
  return frames;
};
