import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {
  activeCaptionCue,
  captionCuesFromLineTimings,
  captionCuesFromWordTimings,
  type PlannedLineTiming,
  type PlannedWordTiming,
} from '../scene-plan';
import {DISPLAY_FONT, type Theme} from './theme';

export const CaptionLayer = ({
  lineTimings,
  wordTimings,
  theme,
  maxWords = 4,
}: {
  lineTimings: PlannedLineTiming[];
  wordTimings: PlannedWordTiming[];
  theme: Theme;
  maxWords?: number;
}) => {
  const frame = useCurrentFrame();
  const {fps, height, width} = useVideoConfig();
  const second = frame / fps;
  const cues = wordTimings.length
    ? captionCuesFromWordTimings(wordTimings, maxWords)
    : captionCuesFromLineTimings(lineTimings, maxWords);
  const cue = activeCaptionCue(cues, second);
  if (!cue) return null;

  const cueFrame = frame - Math.round(cue.start * fps);
  const enter = spring({
    frame: cueFrame,
    fps,
    config: {damping: 17, stiffness: 240, mass: 0.55},
  });
  const y = interpolate(enter, [0, 1], [34, 0]);

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: height * 0.055,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
        zIndex: 30,
      }}
    >
      <div
        style={{
          maxWidth: width * 0.78,
          minHeight: 86,
          padding: '13px 22px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 14,
          flexWrap: 'wrap',
          background: theme.ink,
          color: theme.inkDark,
          opacity: enter,
          transform: `translateY(${y}px)`,
        }}
      >
        {cue.words.map((word, index) => {
          const active = second >= word.start && second < word.end;
          const spoken = second >= word.end;
          const wordFrame = frame - Math.round(word.start * fps);
          const wordEnter = spring({
            frame: wordFrame,
            fps,
            config: {damping: 16, stiffness: 260, mass: 0.5},
          });
          return (
            <span
              key={`${word.text}-${index}`}
              style={{
                display: 'inline-block',
                padding: active ? '4px 8px 6px' : '4px 2px 6px',
                background: active ? theme.accent : 'transparent',
                color: active ? theme.inkDark : spoken ? theme.inkDark : '#6F7682',
                fontFamily: DISPLAY_FONT,
                fontSize: height * 0.047,
                fontWeight: 700,
                letterSpacing: '-0.025em',
                lineHeight: 1,
                textTransform: 'uppercase',
                transform: `translateY(${active ? -7 : 0}px) scale(${
                  0.92 + wordEnter * 0.08
                })`,
              }}
            >
              {word.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
