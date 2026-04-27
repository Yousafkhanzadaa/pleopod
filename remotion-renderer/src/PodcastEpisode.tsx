import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {buildFallbackVideoPlan} from './fallback-plan';
import {currentDialogueLine, parseDialogue} from './dialogue';
import type {PodcastVideoProps} from './types';
import {
  findLineAtSecond,
  findSceneAtSecond,
  normalizeVideoPlan,
  type LineTiming,
  type VideoScene,
} from './video-plan';

type CaptionLine = Pick<LineTiming, 'speaker' | 'text'> | ReturnType<typeof currentDialogueLine>;

type NewsPalette = {
  stage: string;
  stageAlt: string;
  paper: string;
  paperDim: string;
  ink: string;
  muted: string;
  line: string;
  accent: string;
  accentDark: string;
};

const sansFont =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const serifFont = 'Georgia, "Times New Roman", serif';

export const PodcastEpisode = (props: PodcastVideoProps) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const currentSecond = frame / fps;
  const progress = frame / Math.max(1, durationInFrames - 1);
  const plan = normalizeVideoPlan(props.videoPlan ?? buildFallbackVideoPlan(props));
  const scene = findSceneAtSecond(plan, currentSecond);
  const line = findLineAtSecond(plan, currentSecond) ?? currentDialogueLine(props, currentSecond);
  const sceneIndex = Math.max(0, plan.scenes.findIndex((item) => item.id === scene?.id));
  const sceneProgress = sceneLocalProgress(scene, currentSecond);
  const palette = makePalette(sceneIndex);
  const entrance = spring({frame, fps, config: {damping: 92, stiffness: 104}});
  const dialogue = parseDialogue(props.transcript);
  const audioUrl = props.audioUrl.trim();

  return (
    <AbsoluteFill
      style={{
        background: palette.stage,
        color: palette.ink,
        fontFamily: sansFont,
        overflow: 'hidden',
      }}
    >
      {audioUrl ? <Audio src={audioUrl} /> : null}
      <NewsstandBackdrop palette={palette} progress={progress} sceneProgress={sceneProgress} />
      <SurroundingPrints props={props} scene={scene} line={line} palette={palette} />
      <FrontPage
        props={props}
        scene={scene}
        line={line}
        dialogue={dialogue}
        sceneIndex={sceneIndex}
        sceneProgress={sceneProgress}
        progress={progress}
        currentSecond={currentSecond}
        durationSeconds={props.durationSeconds}
        palette={palette}
        entrance={entrance}
      />
    </AbsoluteFill>
  );
};

const NewsstandBackdrop = ({
  palette,
  progress,
  sceneProgress,
}: {
  palette: NewsPalette;
  progress: number;
  sceneProgress: number;
}) => {
  const light = interpolate(progress, [0, 1], [-240, 280]);
  const sweep = interpolate(sceneProgress, [0, 1], [-110, 110]);

  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            `linear-gradient(126deg, ${palette.stage} 0%, ${palette.stageAlt} 52%, #181816 100%)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px)',
          backgroundSize: '104px 104px',
          opacity: 0.42,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: light,
          top: -260,
          width: 520,
          height: 1500,
          transform: 'rotate(23deg)',
          background: 'rgba(255,255,255,0.2)',
          filter: 'blur(42px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 202,
          top: 156,
          width: 1518,
          height: 806,
          background: 'rgba(0,0,0,0.42)',
          filter: 'blur(30px)',
          transform: `translateX(${sweep * 0.04}px) translateY(38px)`,
        }}
      />
    </AbsoluteFill>
  );
};

const SurroundingPrints = ({
  props,
  scene,
  line,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  palette: NewsPalette;
}) => {
  const words = moduleItems(scene, line, props);

  return (
    <AbsoluteFill>
      <PeripheralSheet
        x={-84}
        y={-72}
        width={456}
        height={218}
        rotate={-1.5}
        palette={palette}
        title={props.category}
        variant="photo"
      />
      <PeripheralSheet
        x={408}
        y={-62}
        width={610}
        height={208}
        rotate={0.7}
        palette={palette}
        title={words[0] ?? props.title}
        variant="headline"
      />
      <PeripheralSheet
        x={1398}
        y={-38}
        width={480}
        height={236}
        rotate={1.1}
        palette={palette}
        title={line?.speaker ?? props.brand.name}
        variant="photo"
      />
      <PeripheralSheet
        x={-146}
        y={760}
        width={560}
        height={258}
        rotate={0.8}
        palette={palette}
        title={words[1] ?? 'Notes'}
        variant="columns"
      />
      <PeripheralSheet
        x={1278}
        y={790}
        width={620}
        height={246}
        rotate={-0.8}
        palette={palette}
        title={words[2] ?? 'Edition'}
        variant="headline"
      />
    </AbsoluteFill>
  );
};

const PeripheralSheet = ({
  x,
  y,
  width,
  height,
  rotate,
  palette,
  title,
  variant,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  rotate: number;
  palette: NewsPalette;
  title: string;
  variant: 'headline' | 'photo' | 'columns';
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width,
        height,
        transform: `rotate(${rotate}deg)`,
        background: variant === 'headline' ? palette.accentDark : palette.paper,
        border: `10px solid ${variant === 'headline' ? '#1b1b19' : '#11110f'}`,
        boxShadow: '0 22px 36px rgba(0,0,0,0.34)',
        overflow: 'hidden',
        opacity: 0.88,
      }}
    >
      {variant === 'headline' ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: 36,
              bottom: 28,
              maxWidth: width - 90,
              fontSize: fitFont(title, 58, 31, 18),
              lineHeight: 0.9,
              fontWeight: 950,
              textTransform: 'uppercase',
              color: palette.paper,
            }}
          >
            {title}
          </div>
          <div
            style={{
              position: 'absolute',
              right: 24,
              top: 24,
              width: 170,
              height: 60,
              border: `1px solid rgba(244,241,231,0.36)`,
            }}
          />
        </>
      ) : variant === 'photo' ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: '48%',
              background:
                'radial-gradient(circle at 52% 38%, rgba(30,30,28,0.18), transparent 33%), linear-gradient(135deg, #d7d4ca, #88887f)',
              filter: 'grayscale(1)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              right: 28,
              top: 26,
              width: '42%',
              color: palette.ink,
              fontSize: 12,
              lineHeight: 1.18,
              fontWeight: 780,
            }}
          >
            {repeatCopy(title, 24)}
          </div>
          <Barcode palette={palette} left={width - 190} top={height - 50} width={136} />
        </>
      ) : (
        <>
          <div
            style={{
              position: 'absolute',
              left: 34,
              top: 32,
              right: 34,
              fontSize: 26,
              lineHeight: 1,
              fontWeight: 950,
              textTransform: 'uppercase',
            }}
          >
            {title}
          </div>
          <MiniColumns palette={palette} left={34} top={92} width={width - 68} columns={4} />
        </>
      )}
    </div>
  );
};

const FrontPage = ({
  props,
  scene,
  line,
  dialogue,
  sceneIndex,
  sceneProgress,
  progress,
  currentSecond,
  durationSeconds,
  palette,
  entrance,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  dialogue: ReturnType<typeof parseDialogue>;
  sceneIndex: number;
  sceneProgress: number;
  progress: number;
  currentSecond: number;
  durationSeconds: number;
  palette: NewsPalette;
  entrance: number;
}) => {
  const headline = scene?.headline || props.title;
  const kicker = scene ? layoutLabel(scene.layout) : props.category;
  const edition = String(sceneIndex + 1).padStart(2, '0');
  const lift = interpolate(entrance, [0, 1], [24, 0]);
  const rotate = interpolate(sceneProgress, [0, 1], [-0.18, 0.12]);

  return (
    <div
      style={{
        position: 'absolute',
        left: 202,
        top: 104,
        width: 1516,
        height: 854,
        background: palette.paper,
        color: palette.ink,
        boxShadow: '0 44px 84px rgba(0,0,0,0.46)',
        overflow: 'hidden',
        opacity: interpolate(entrance, [0, 1], [0, 1]),
        transform: `translateY(${lift}px) rotate(${rotate}deg)`,
      }}
    >
      <PaperGrain />
      <FrontPageMasthead
        props={props}
        sceneIndex={sceneIndex}
        currentSecond={currentSecond}
        durationSeconds={durationSeconds}
        palette={palette}
      />
      <div
        style={{
          position: 'absolute',
          left: 52,
          right: 52,
          top: 132,
          height: 2,
          background: palette.ink,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 52,
          right: 52,
          top: 145,
          height: 22,
          display: 'grid',
          gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center',
          color: palette.muted,
          fontSize: 12,
          fontWeight: 780,
          textTransform: 'uppercase',
          letterSpacing: 0,
          borderBottom: `1px solid ${palette.line}`,
        }}
      >
        <span>{props.category}</span>
        <span>Volume {edition} / Free Edition / {formatDuration(currentSecond)}</span>
        <span style={{textAlign: 'right'}}>{kicker}</span>
      </div>
      <HeroNewsBlock
        props={props}
        scene={scene}
        headline={headline}
        line={line}
        sceneIndex={sceneIndex}
        palette={palette}
      />
      <ColumnDeck
        props={props}
        scene={scene}
        line={line}
        dialogue={dialogue}
        palette={palette}
      />
      <BottomRail
        props={props}
        scene={scene}
        line={line}
        progress={progress}
        palette={palette}
      />
    </div>
  );
};

const PaperGrain = () => {
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'repeating-linear-gradient(0deg, rgba(20,20,18,0.025) 0, rgba(20,20,18,0.025) 1px, transparent 1px, transparent 4px)',
          opacity: 0.6,
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          boxShadow: 'inset 0 0 0 16px rgba(20,20,18,0.04)',
        }}
      />
    </AbsoluteFill>
  );
};

const FrontPageMasthead = ({
  props,
  sceneIndex,
  currentSecond,
  durationSeconds,
  palette,
}: {
  props: PodcastVideoProps;
  sceneIndex: number;
  currentSecond: number;
  durationSeconds: number;
  palette: NewsPalette;
}) => {
  return (
    <header
      style={{
        position: 'absolute',
        left: 52,
        right: 52,
        top: 36,
        height: 86,
        display: 'grid',
        gridTemplateColumns: '176px 1fr 176px',
        columnGap: 22,
        alignItems: 'center',
      }}
    >
      <MastheadBox text="Real ideas are worth holding onto" palette={palette} />
      <div
        style={{
          textAlign: 'center',
          fontFamily: serifFont,
          fontSize: fitFont(`${props.brand.name} Times`, 70, 44, 18),
          lineHeight: 0.9,
          fontWeight: 900,
          color: palette.ink,
        }}
      >
        The {props.brand.name} Times
      </div>
      <MastheadBox
        text={`Special edition ${String(sceneIndex + 1).padStart(2, '0')} / ${formatDuration(currentSecond)} of ${formatDuration(durationSeconds)}`}
        palette={palette}
      />
    </header>
  );
};

const MastheadBox = ({text, palette}: {text: string; palette: NewsPalette}) => {
  return (
    <div
      style={{
        height: 64,
        border: `2px solid ${palette.line}`,
        display: 'grid',
        placeItems: 'center',
        padding: '0 14px',
        textAlign: 'center',
        fontSize: 12,
        lineHeight: 1.1,
        textTransform: 'uppercase',
        fontWeight: 850,
        color: palette.muted,
      }}
    >
      {text}
    </div>
  );
};

const HeroNewsBlock = ({
  props,
  scene,
  headline,
  line,
  sceneIndex,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  headline: string;
  line: CaptionLine;
  sceneIndex: number;
  palette: NewsPalette;
}) => {
  const items = moduleItems(scene, line, props);
  return (
    <section
      style={{
        position: 'absolute',
          left: 52,
          right: 52,
          top: 180,
          height: 276,
        display: 'grid',
        gridTemplateColumns: '1fr 434px',
        columnGap: 28,
        borderBottom: `2px solid ${palette.ink}`,
      }}
    >
      <div style={{minWidth: 0, overflow: 'hidden'}}>
        <div
          style={{
            fontSize: 14,
            fontWeight: 950,
            textTransform: 'uppercase',
            color: palette.accent,
            marginBottom: 10,
          }}
        >
          Extra / Scene {String(sceneIndex + 1).padStart(2, '0')}
        </div>
        <h1
          style={{
            margin: 0,
            fontSize: headlineFont(headline),
            lineHeight: 0.82,
            letterSpacing: 0,
            fontWeight: 950,
            textTransform: 'uppercase',
            maxWidth: 946,
          }}
        >
          {headline}
        </h1>
      </div>
      <div style={{position: 'relative', borderLeft: `1px solid ${palette.line}`, paddingLeft: 22}}>
        <ImagePanel props={props} headline={headline} palette={palette} />
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: 204,
            width: 188,
            height: 58,
            fontSize: 12,
            lineHeight: 1.16,
            color: palette.ink,
            fontWeight: 760,
            overflow: 'hidden',
          }}
        >
          {repeatCopy(items.join(' ') || props.summary || headline, 34)}
        </div>
      </div>
    </section>
  );
};

const ImagePanel = ({
  props,
  headline,
  palette,
}: {
  props: PodcastVideoProps;
  headline: string;
  palette: NewsPalette;
}) => {
  const thumbnailUrl = props.thumbnailUrl.trim();
  return (
    <div
      style={{
        position: 'relative',
        width: 410,
        height: 190,
        overflow: 'hidden',
        background: palette.paperDim,
        border: `1px solid ${palette.line}`,
      }}
    >
      {thumbnailUrl ? (
        <Img
          src={thumbnailUrl}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: 'grayscale(1) contrast(1.15)',
          }}
        />
      ) : (
        <IllustratedNewsPhoto title={headline} palette={palette} />
      )}
      <div
        style={{
          position: 'absolute',
          left: 12,
          top: 10,
          background: palette.paper,
          border: `1px solid ${palette.ink}`,
          padding: '4px 7px',
          fontSize: 10,
          fontWeight: 950,
          textTransform: 'uppercase',
        }}
      >
        CP-0{headline.length % 8}
      </div>
    </div>
  );
};

const IllustratedNewsPhoto = ({title, palette}: {title: string; palette: NewsPalette}) => {
  return (
    <div style={{position: 'absolute', inset: 0, background: '#d9d6cc'}}>
      <div
        style={{
          position: 'absolute',
          left: 22,
          top: 22,
          width: 142,
          height: 142,
          borderRadius: 999,
          background: '#b9b8ae',
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 34,
          top: 24,
          width: 120,
          height: 120,
          borderRadius: 999,
          background: `${palette.accent}55`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 68,
          bottom: 0,
          width: 126,
          height: 168,
          borderRadius: '66px 66px 0 0',
          background: '#22221f',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 222,
          top: 44,
          width: 138,
          fontSize: fitFont(title, 24, 16, 20),
          lineHeight: 0.94,
          fontWeight: 950,
          textTransform: 'uppercase',
          color: '#22221f',
        }}
      >
        {title}
      </div>
    </div>
  );
};

const ColumnDeck = ({
  props,
  scene,
  line,
  dialogue,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  dialogue: ReturnType<typeof parseDialogue>;
  palette: NewsPalette;
}) => {
  const items = moduleItems(scene, line, props);
  const bodyText =
    [props.summary, line?.text, props.description, ...dialogue.map((item) => item.text)]
      .filter(Boolean)
      .join(' ') || props.title;

  return (
    <section
      style={{
        position: 'absolute',
        left: 52,
        right: 52,
        top: 484,
        height: 188,
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        columnGap: 18,
        overflow: 'hidden',
      }}
    >
      {Array.from({length: 5}, (_, index) => (
        <div key={index} style={{position: 'relative', minWidth: 0, overflow: 'hidden'}}>
          <div
            style={{
              fontFamily: serifFont,
              fontSize: 15,
              lineHeight: 1.16,
              color: index === 0 ? palette.ink : palette.muted,
            }}
          >
            {repeatCopy(bodyText, index === 0 ? 82 : 95)}
          </div>
          {index < items.length ? (
            <div
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 0,
                borderTop: `1px solid ${palette.line}`,
                paddingTop: 8,
                fontSize: 12,
                lineHeight: 1,
                fontWeight: 950,
                textTransform: 'uppercase',
              }}
            >
              {String(index + 1).padStart(2, '0')}. {items[index]}
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
};

const BottomRail = ({
  props,
  scene,
  line,
  progress,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  progress: number;
  palette: NewsPalette;
}) => {
  const speaker = line?.speaker || props.speakers[0]?.name || props.brand.name;
  const items = moduleItems(scene, line, props);

  return (
    <footer
      style={{
        position: 'absolute',
        left: 52,
        right: 52,
        bottom: 34,
        height: 106,
        display: 'grid',
        gridTemplateColumns: '330px 1fr 230px',
        gap: 18,
        borderTop: `2px solid ${palette.ink}`,
        background: palette.paper,
        zIndex: 3,
      }}
    >
      <div
        style={{
          borderRight: `1px solid ${palette.line}`,
          paddingTop: 14,
        }}
      >
        <div style={{fontSize: 11, color: palette.muted, fontWeight: 950, textTransform: 'uppercase'}}>
          Speaking now
        </div>
        <div style={{fontSize: 28, lineHeight: 0.96, fontWeight: 950, marginTop: 5}}>
          {speaker}
        </div>
        <Barcode palette={palette} left={0} top={76} width={220} />
      </div>
      <div style={{position: 'relative', paddingTop: 12, minWidth: 0}}>
        <div
          style={{
            fontSize: fitFont(line?.text || props.summary || props.title, 25, 16, 112),
            lineHeight: 1.05,
            fontWeight: 920,
          }}
        >
          {line?.text || props.summary || props.title}
        </div>
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 2,
            height: 7,
            background: palette.line,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${progress * 100}%`,
              height: '100%',
              background: palette.ink,
            }}
          />
        </div>
      </div>
      <div style={{paddingTop: 14}}>
        {items.slice(0, 3).map((item, index) => (
          <div
            key={`${item}-${index}`}
            style={{
              display: 'grid',
              gridTemplateColumns: '34px 1fr',
              gap: 10,
              alignItems: 'baseline',
              minHeight: 28,
              borderBottom: `1px solid ${palette.line}`,
              fontSize: 12,
              fontWeight: 900,
              textTransform: 'uppercase',
            }}
          >
            <span>{String(index + 1).padStart(2, '0')}</span>
            <span>{item}</span>
          </div>
        ))}
      </div>
    </footer>
  );
};

const MiniColumns = ({
  palette,
  left,
  top,
  width,
  columns,
}: {
  palette: NewsPalette;
  left: number;
  top: number;
  width: number;
  columns: number;
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        width,
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        columnGap: 14,
      }}
    >
      {Array.from({length: columns}, (_, index) => (
        <div
          key={index}
          style={{
            height: 86,
            background:
              `repeating-linear-gradient(0deg, ${palette.muted} 0, ${palette.muted} 2px, transparent 2px, transparent 8px)`,
            opacity: 0.48,
          }}
        />
      ))}
    </div>
  );
};

const Barcode = ({
  palette,
  left,
  top,
  width,
}: {
  palette: NewsPalette;
  left: number;
  top: number;
  width: number;
}) => {
  const bars = Array.from({length: 25}, (_, index) => index);

  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        width,
        height: 34,
        display: 'flex',
        alignItems: 'stretch',
        gap: 3,
      }}
    >
      {bars.map((index) => (
        <div
          key={index}
          style={{
            width: index % 4 === 0 ? 6 : index % 3 === 0 ? 4 : 2,
            background: palette.ink,
            opacity: index % 5 === 0 ? 0.46 : 1,
          }}
        />
      ))}
    </div>
  );
};

const moduleItems = (
  scene: VideoScene | null,
  line: CaptionLine,
  props: PodcastVideoProps,
) => {
  if (scene?.bullets.length) {
    return scene.bullets;
  }
  if (scene?.diagramItems.length) {
    return scene.diagramItems;
  }
  if (scene?.visualKeywords.length) {
    return scene.visualKeywords;
  }
  return keyPhrases(line?.text || props.summary || props.title);
};

const makePalette = (sceneIndex: number): NewsPalette => {
  const stages = [
    ['#1f201d', '#5b5a4a'],
    ['#b3a0c8', '#7d7f8f'],
    ['#c7635d', '#1f201d'],
    ['#31585c', '#759293'],
  ];
  const [stage, stageAlt] = stages[sceneIndex % stages.length] ?? stages[0];
  return {
    stage,
    stageAlt,
    paper: '#eeeae0',
    paperDim: '#d7d3c8',
    ink: '#242420',
    muted: 'rgba(36,36,32,0.58)',
    line: 'rgba(36,36,32,0.32)',
    accent: '#a5a060',
    accentDark: '#2d2d2a',
  };
};

const sceneLocalProgress = (scene: VideoScene | null, second: number) => {
  if (!scene) {
    return 0;
  }
  const duration = Math.max(0.1, scene.endSeconds - scene.startSeconds);
  return clamp((second - scene.startSeconds) / duration, 0, 1);
};

const layoutLabel = (layout: VideoScene['layout']) => {
  return layout
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
};

const keyPhrases = (text: string) => {
  const words = text
    .replace(/[^\w\s-]/g, '')
    .split(/\s+/)
    .filter((word) => word.length > 3)
    .slice(0, 14);
  if (words.length === 0) {
    return ['Edition', 'Signal', 'Archive'];
  }
  return [
    words.slice(0, 3).join(' '),
    words.slice(3, 6).join(' '),
    words.slice(6, 10).join(' '),
    words.slice(10, 14).join(' '),
  ].filter(Boolean);
};

const repeatCopy = (text: string, targetWords: number) => {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return '';
  }
  const output: string[] = [];
  for (let index = 0; output.length < targetWords; index += 1) {
    output.push(words[index % words.length]);
  }
  return `${output.join(' ')}.`;
};

const formatDuration = (seconds: number) => {
  const clamped = Math.max(0, seconds);
  const minutes = Math.floor(clamped / 60);
  const remainingSeconds = Math.floor(clamped % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
};

const headlineFont = (text: string) => {
  const length = text.length;
  if (length > 34) {
    return 74;
  }
  if (length > 26) {
    return 88;
  }
  if (length > 20) {
    return 98;
  }
  return 108;
};

const fitFont = (text: string | undefined, base: number, minimum: number, comfort = 80) => {
  const length = (text ?? '').length;
  if (length <= comfort) {
    return base;
  }
  return Math.max(minimum, base - (length - comfort) * 0.34);
};

const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value));
};
