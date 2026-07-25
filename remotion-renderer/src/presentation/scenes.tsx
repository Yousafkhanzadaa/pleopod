import type {ReactNode} from 'react';
import {interpolate, spring} from 'remotion';
import type {PodcastVideoProps} from '../types';
import type {PlannedScene} from '../scene-plan';
import {ChartFigure} from './charts';
import {BODY_FONT, DISPLAY_FONT, MONO_FONT, type Theme} from './theme';

export type SceneContentProps = {
  scene: PlannedScene;
  index: number;
  theme: Theme;
  brand: PodcastVideoProps['brand'];
  reveal: number;
  localFrame: number;
  fps: number;
  width: number;
  height: number;
};

const clamp = (value: number, min = 0, max = 1) => Math.max(min, Math.min(max, value));

const LABELS: Record<PlannedScene['layout'], string> = {
  title: 'OPEN',
  statement: 'IDEA',
  bullets: 'BREAKDOWN',
  chart: 'DATA',
  timeline: 'SEQUENCE',
  quote: 'CONTEXT',
  diagram: 'SYSTEM',
  source: 'EVIDENCE',
  outro: 'CLOSE',
};

const domainOf = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url.replace(/^https?:\/\//, '').split('/')[0];
  }
};

const itemSpring = (frame: number, fps: number, index = 0) =>
  spring({
    frame: frame - index * 5,
    fps,
    config: {damping: 18, stiffness: 190, mass: 0.65},
  });

export const SceneContent = (props: SceneContentProps) => {
  switch (props.scene.layout) {
    case 'title':
      return <TitleScene {...props} />;
    case 'chart':
      return <ChartScene {...props} />;
    case 'bullets':
      return <BulletsScene {...props} />;
    case 'timeline':
      return <TimelineScene {...props} />;
    case 'quote':
      return <QuoteScene {...props} />;
    case 'diagram':
      return <DiagramScene {...props} />;
    case 'source':
      return <SourceScene {...props} />;
    case 'outro':
      return <OutroScene {...props} />;
    case 'statement':
    default:
      return <StatementScene {...props} />;
  }
};

const SceneShell = ({
  scene,
  index,
  theme,
  children,
}: {
  scene: PlannedScene;
  index: number;
  theme: Theme;
  children: ReactNode;
}) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      padding: '88px 112px 176px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      fontFamily: BODY_FONT,
    }}
  >
    <div
      style={{
        position: 'absolute',
        left: 112,
        top: 72,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        fontFamily: MONO_FONT,
        fontSize: 22,
        fontWeight: 600,
        letterSpacing: 3,
        color: theme.muted,
      }}
    >
      <span style={{color: theme.accent}}>{String(index + 1).padStart(2, '0')}</span>
      <span style={{width: 46, height: 3, background: theme.accent}} />
      <span>{LABELS[scene.layout]}</span>
    </div>
    {children}
  </div>
);

const KineticHeadline = ({
  text,
  theme,
  frame,
  fps,
  size,
  maxWidth = 1580,
  accentWord,
}: {
  text: string;
  theme: Theme;
  frame: number;
  fps: number;
  size: number;
  maxWidth?: number;
  accentWord?: number;
}) => {
  const words = text.split(/\s+/).filter(Boolean);
  const longestIndex = words.reduce(
    (best, word, index) => (word.length > (words[best]?.length ?? 0) ? index : best),
    0,
  );
  const coloredIndex = accentWord ?? longestIndex;
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        columnGap: '0.22em',
        rowGap: '0.02em',
        maxWidth,
        fontFamily: DISPLAY_FONT,
        fontSize: size,
        fontWeight: 700,
        lineHeight: 0.94,
        letterSpacing: '-0.045em',
      }}
    >
      {words.map((word, index) => {
        const enter = itemSpring(frame, fps, index);
        const y = interpolate(enter, [0, 1], [80, 0]);
        const rotate = interpolate(enter, [0, 1], [3, 0]);
        return (
          <span
            key={`${word}-${index}`}
            style={{
              display: 'inline-block',
              color: index === coloredIndex ? theme.accent : theme.ink,
              opacity: enter,
              transform: `translateY(${y}px) rotate(${rotate}deg)`,
              transformOrigin: 'left bottom',
            }}
          >
            {word}
          </span>
        );
      })}
    </div>
  );
};

const TitleScene = ({scene, theme, localFrame, fps, brand}: SceneContentProps) => {
  const enter = itemSpring(localFrame, fps);
  const blockWidth = interpolate(enter, [0, 1], [0, 410]);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '122px 112px 156px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        fontFamily: BODY_FONT,
      }}
    >
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          width: blockWidth,
          height: 220,
          background: theme.primary,
        }}
      />
      <div
        style={{
          fontFamily: MONO_FONT,
          fontSize: 25,
          fontWeight: 600,
          letterSpacing: 5,
          color: theme.accent,
          marginBottom: 42,
          opacity: enter,
        }}
      >
        {(brand.name || 'PLEOPOD').toUpperCase()} / SOURCE-BACKED
      </div>
      <KineticHeadline
        text={scene.headline}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={138}
        maxWidth={1540}
      />
      {scene.subheadline ? (
        <div
          style={{
            marginTop: 42,
            maxWidth: 1120,
            fontSize: 39,
            lineHeight: 1.25,
            color: theme.muted,
            opacity: itemSpring(localFrame - 12, fps),
          }}
        >
          {scene.subheadline}
        </div>
      ) : null}
    </div>
  );
};

const StatementScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, index} = props;
  const enter = itemSpring(localFrame, fps);
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <div style={{display: 'flex', alignItems: 'stretch', gap: 46}}>
        <div
          style={{
            width: 18,
            background: theme.accent,
            transform: `scaleY(${enter})`,
            transformOrigin: 'bottom',
          }}
        />
        <div>
          <KineticHeadline
            text={scene.headline}
            theme={theme}
            frame={localFrame}
            fps={fps}
            size={116}
            maxWidth={1450}
          />
          {scene.subheadline ? (
            <div
              style={{
                marginTop: 38,
                maxWidth: 1260,
                color: theme.muted,
                fontSize: 38,
                lineHeight: 1.28,
                opacity: itemSpring(localFrame - 14, fps),
              }}
            >
              {scene.subheadline}
            </div>
          ) : null}
        </div>
      </div>
    </SceneShell>
  );
};

const BulletsScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, index} = props;
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <KineticHeadline
        text={scene.headline}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={80}
        maxWidth={1500}
      />
      <div
        style={{
          marginTop: 52,
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: 20,
        }}
      >
        {scene.bullets.slice(0, 4).map((bullet, bulletIndex) => {
          const enter = itemSpring(localFrame - 10, fps, bulletIndex);
          return (
            <div
              key={bulletIndex}
              style={{
                minHeight: 124,
                display: 'flex',
                alignItems: 'center',
                gap: 24,
                padding: '22px 28px',
                background: bulletIndex === 0 ? theme.accent : theme.surface,
                color: bulletIndex === 0 ? theme.inkDark : theme.ink,
                opacity: enter,
                transform: `translateX(${(1 - enter) * 60}px)`,
              }}
            >
              <span
                style={{
                  fontFamily: MONO_FONT,
                  fontSize: 25,
                  fontWeight: 600,
                  color: bulletIndex === 0 ? theme.inkDark : theme.accent,
                }}
              >
                {String(bulletIndex + 1).padStart(2, '0')}
              </span>
              <span style={{fontSize: 36, fontWeight: 600, lineHeight: 1.14}}>{bullet}</span>
            </div>
          );
        })}
      </div>
    </SceneShell>
  );
};

const ChartScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, width, index} = props;
  const chartProgress = clamp((localFrame - fps * 0.35) / (fps * 1.1));
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <div style={{display: 'flex', alignItems: 'end', justifyContent: 'space-between'}}>
        <KineticHeadline
          text={scene.headline}
          theme={theme}
          frame={localFrame}
          fps={fps}
          size={72}
          maxWidth={1180}
        />
        {scene.chart?.unit ? (
          <div
            style={{
              padding: '12px 18px',
              background: theme.accent,
              color: theme.inkDark,
              fontFamily: MONO_FONT,
              fontSize: 24,
              fontWeight: 700,
            }}
          >
            UNIT / {scene.chart.unit}
          </div>
        ) : null}
      </div>
      {scene.chart ? (
        <div style={{marginTop: 18}}>
          <ChartFigure
            chart={scene.chart}
            theme={theme}
            progress={chartProgress}
            width={width - 224}
            height={570}
          />
        </div>
      ) : null}
    </SceneShell>
  );
};

const TimelineScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, index} = props;
  const items = (scene.diagram_items.length ? scene.diagram_items : scene.bullets).slice(0, 5);
  const track = clamp((localFrame - fps * 0.35) / (fps * 1.2));
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <KineticHeadline
        text={scene.headline}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={78}
      />
      <div style={{position: 'relative', marginTop: 100, display: 'flex'}}>
        <div
          style={{
            position: 'absolute',
            left: 34,
            right: 34,
            top: 32,
            height: 6,
            background: theme.chartTrack,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 34,
            top: 32,
            width: `calc(${track * 100}% - 68px)`,
            height: 6,
            background: theme.accent,
          }}
        />
        {items.map((item, itemIndex) => {
          const enter = itemSpring(localFrame - 10, fps, itemIndex);
          return (
            <div
              key={itemIndex}
              style={{
                flex: 1,
                position: 'relative',
                paddingTop: 78,
                paddingRight: 26,
                opacity: enter,
                transform: `translateY(${(1 - enter) * 38}px)`,
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: 18,
                  top: 15,
                  width: 40,
                  height: 40,
                  background: itemIndex === 0 ? theme.accent : theme.surfaceRaised,
                  border: `6px solid ${theme.background}`,
                }}
              />
              <div
                style={{
                  fontFamily: MONO_FONT,
                  color: theme.accent,
                  fontSize: 22,
                  marginBottom: 12,
                }}
              >
                {String(itemIndex + 1).padStart(2, '0')}
              </div>
              <div style={{fontSize: 30, lineHeight: 1.2, color: theme.ink, fontWeight: 600}}>
                {item}
              </div>
            </div>
          );
        })}
      </div>
    </SceneShell>
  );
};

const QuoteScene = ({scene, theme, localFrame, fps}: SceneContentProps) => {
  const enter = itemSpring(localFrame, fps);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        padding: '90px 140px 150px',
        fontFamily: DISPLAY_FONT,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: interpolate(enter, [0, 1], [0, 80]),
          background: theme.accent,
        }}
      />
      <div>
        <div
          style={{
            width: 82,
            height: 82,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: theme.accent,
            color: theme.inkDark,
            fontSize: 80,
            fontWeight: 700,
            lineHeight: 1,
          }}
        >
          “
        </div>
        <div
          style={{
            marginTop: 32,
            maxWidth: 1510,
            color: theme.ink,
            fontSize: 86,
            fontWeight: 650,
            lineHeight: 1.07,
            letterSpacing: '-0.035em',
            opacity: enter,
            transform: `translateY(${(1 - enter) * 54}px)`,
          }}
        >
          {scene.quote || scene.headline}
        </div>
      </div>
    </div>
  );
};

const DiagramScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, index} = props;
  const items = (scene.diagram_items.length ? scene.diagram_items : scene.bullets).slice(0, 5);
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <KineticHeadline
        text={scene.headline}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={74}
      />
      <div
        style={{
          marginTop: 72,
          display: 'flex',
          alignItems: 'stretch',
          gap: 12,
        }}
      >
        {items.map((item, itemIndex) => {
          const enter = itemSpring(localFrame - 8, fps, itemIndex);
          return (
            <div key={itemIndex} style={{display: 'flex', alignItems: 'center', flex: 1}}>
              <div
                style={{
                  flex: 1,
                  minHeight: 174,
                  padding: '28px 24px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  background: itemIndex % 2 === 0 ? theme.surfaceRaised : theme.surface,
                  borderTop: `10px solid ${
                    theme.chartColors[itemIndex % theme.chartColors.length]
                  }`,
                  opacity: enter,
                  transform: `scale(${0.88 + enter * 0.12})`,
                }}
              >
                <span style={{fontFamily: MONO_FONT, color: theme.muted, fontSize: 20}}>
                  {String(itemIndex + 1).padStart(2, '0')}
                </span>
                <span style={{color: theme.ink, fontSize: 29, fontWeight: 650, lineHeight: 1.15}}>
                  {item}
                </span>
              </div>
              {itemIndex < items.length - 1 ? (
                <div style={{width: 26, height: 6, background: theme.accent}} />
              ) : null}
            </div>
          );
        })}
      </div>
    </SceneShell>
  );
};

const SourceScene = (props: SceneContentProps) => {
  const {scene, theme, localFrame, fps, index} = props;
  const urls = scene.source_urls.slice(0, 4);
  return (
    <SceneShell scene={scene} index={index} theme={theme}>
      <KineticHeadline
        text={scene.headline || 'Evidence'}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={88}
      />
      <div style={{marginTop: 54, display: 'flex', flexDirection: 'column', gap: 12}}>
        {!urls.length ? (
          <div
            style={{
              width: 1120,
              padding: '30px 36px',
              background: theme.surface,
              borderLeft: `14px solid ${theme.accent}`,
              color: theme.ink,
              fontFamily: MONO_FONT,
              fontSize: 32,
              fontWeight: 600,
              opacity: itemSpring(localFrame - 10, fps),
            }}
          >
            VERIFIED CLAIM BANK / SOURCES ATTACHED TO JOB
          </div>
        ) : null}
        {urls.map((url, urlIndex) => {
          const enter = itemSpring(localFrame - 10, fps, urlIndex);
          return (
            <div
              key={urlIndex}
              style={{
                display: 'flex',
                alignItems: 'center',
                width: 1120,
                height: 88,
                background: urlIndex === 0 ? theme.accent : theme.surface,
                color: urlIndex === 0 ? theme.inkDark : theme.ink,
                opacity: enter,
                transform: `translateX(${(1 - enter) * 80}px)`,
              }}
            >
              <div
                style={{
                  width: 92,
                  textAlign: 'center',
                  fontFamily: MONO_FONT,
                  fontSize: 23,
                  fontWeight: 700,
                }}
              >
                {String(urlIndex + 1).padStart(2, '0')}
              </div>
              <div style={{fontFamily: MONO_FONT, fontSize: 34, fontWeight: 600}}>
                {domainOf(url)}
              </div>
            </div>
          );
        })}
      </div>
    </SceneShell>
  );
};

const OutroScene = ({scene, theme, localFrame, fps, brand}: SceneContentProps) => {
  const enter = itemSpring(localFrame, fps);
  const bar = interpolate(enter, [0, 1], [0, 520]);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: '80px 150px 150px',
        fontFamily: DISPLAY_FONT,
      }}
    >
      <div style={{width: bar, height: 16, background: theme.accent, marginBottom: 42}} />
      <KineticHeadline
        text={scene.headline || 'Stay curious'}
        theme={theme}
        frame={localFrame}
        fps={fps}
        size={126}
        maxWidth={1500}
      />
      <div
        style={{
          marginTop: 52,
          fontFamily: MONO_FONT,
          fontSize: 27,
          fontWeight: 600,
          letterSpacing: 5,
          color: theme.muted,
          opacity: enter,
        }}
      >
        {(brand.name || 'PLEOPOD').toUpperCase()} / FACTS BEFORE FRAMES
      </div>
    </div>
  );
};
