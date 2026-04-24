import type {CSSProperties, ReactNode} from 'react';
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
import {activeChapterTitle, currentDialogueLine, parseDialogue} from './dialogue';
import type {PodcastVideoProps} from './types';
import {
  findLineAtSecond,
  findSceneAtSecond,
  normalizeVideoPlan,
  type LineTiming,
  type VideoScene,
} from './video-plan';

type CaptionLine = Pick<LineTiming, 'speaker' | 'text'> | ReturnType<typeof currentDialogueLine>;

type Palette = {
  background: string;
  primary: string;
  accent: string;
  ink: string;
  muted: string;
  panel: string;
  panelStrong: string;
  line: string;
  coral: string;
  green: string;
};

const baseFont =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

export const PodcastEpisode = (props: PodcastVideoProps) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const currentSecond = frame / fps;
  const progress = frame / Math.max(1, durationInFrames - 1);
  const palette = makePalette(props.brand);
  const dialogue = parseDialogue(props.transcript);
  const plan = normalizeVideoPlan(props.videoPlan ?? buildFallbackVideoPlan(props));
  const currentScene = findSceneAtSecond(plan, currentSecond);
  const currentLine = findLineAtSecond(plan, currentSecond) ?? currentDialogueLine(props, currentSecond);
  const chapter = currentScene?.headline ?? activeChapterTitle(props, currentSecond);
  const sceneIndex = Math.max(0, plan.scenes.findIndex((scene) => scene.id === currentScene?.id));
  const sceneProgress = sceneLocalProgress(currentScene, currentSecond);
  const entrance = spring({frame, fps, config: {damping: 88, stiffness: 120}});
  const audioUrl = props.audioUrl.trim();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.background,
        color: palette.ink,
        fontFamily: baseFont,
        overflow: 'hidden',
      }}
    >
      {audioUrl ? <Audio src={audioUrl} /> : null}
      <Backdrop
        palette={palette}
        thumbnailUrl={props.thumbnailUrl}
        progress={progress}
        sceneProgress={sceneProgress}
      />
      <Header
        brandName={props.brand.name}
        category={props.category}
        chapter={chapter}
        progress={progress}
        currentSecond={currentSecond}
        durationSeconds={props.durationSeconds}
        palette={palette}
      />
      <main
        style={{
          position: 'absolute',
          left: 86,
          right: 86,
          top: 130,
          bottom: 112,
          display: 'grid',
          gridTemplateColumns: '118px minmax(0, 1fr) 480px',
          gap: 34,
          opacity: interpolate(entrance, [0, 1], [0, 1]),
          transform: `translateY(${interpolate(entrance, [0, 1], [18, 0])}px)`,
        }}
      >
        <SignalRail
          scenes={plan.scenes}
          activeIndex={sceneIndex}
          progress={progress}
          palette={palette}
        />
        <SceneStage
          props={props}
          scene={currentScene}
          line={currentLine}
          sceneIndex={sceneIndex}
          sceneProgress={sceneProgress}
          palette={palette}
        />
        <EpisodePoster
          props={props}
          scene={currentScene}
          line={currentLine}
          dialogueCount={plan.lineTimings.length || dialogue.length}
          progress={progress}
          palette={palette}
        />
      </main>
      <LowerThird
        line={currentLine}
        fallback={props.summary || props.description || props.title}
        speakers={props.speakers}
        progress={progress}
        palette={palette}
      />
      <ProgressRail progress={progress} palette={palette} />
    </AbsoluteFill>
  );
};

const Backdrop = ({
  palette,
  thumbnailUrl,
  progress,
  sceneProgress,
}: {
  palette: Palette;
  thumbnailUrl: string;
  progress: number;
  sceneProgress: number;
}) => {
  const imageUrl = thumbnailUrl.trim();
  const drift = interpolate(progress, [0, 1], [-80, 80]);
  const scan = interpolate(sceneProgress, [0, 1], [-120, 120]);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            `linear-gradient(118deg, ${palette.background} 0%, #11161a 36%, #171719 70%, #090a0c 100%)`,
        }}
      />
      {imageUrl ? (
        <Img
          src={imageUrl}
          style={{
            position: 'absolute',
            inset: '-8%',
            width: '116%',
            height: '116%',
            objectFit: 'cover',
            opacity: 0.12,
            filter: 'blur(30px) saturate(0.9)',
            transform: `scale(1.04) translateX(${drift * 0.18}px)`,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.032) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.032) 1px, transparent 1px)',
          backgroundSize: '72px 72px',
          opacity: 0.62,
          transform: `translateX(${drift * 0.1}px)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: -180,
          right: -180,
          top: 644,
          height: 210,
          background:
            `linear-gradient(90deg, transparent 0%, ${palette.primary}4a 34%, ${palette.accent}54 64%, transparent 100%)`,
          transform: `rotate(-6deg) translateX(${scan}px)`,
          opacity: 0.48,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: -160,
          right: -160,
          top: 678,
          height: 2,
          background:
            `linear-gradient(90deg, transparent, ${palette.primary}, ${palette.accent}, transparent)`,
          transform: `rotate(-6deg) translateX(${-scan * 0.7}px)`,
          opacity: 0.82,
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(90deg, rgba(0,0,0,0.34), transparent 18%, transparent 78%, rgba(0,0,0,0.3))',
        }}
      />
    </AbsoluteFill>
  );
};

const Header = ({
  brandName,
  category,
  chapter,
  progress,
  currentSecond,
  durationSeconds,
  palette,
}: {
  brandName: string;
  category: string;
  chapter: string | null;
  progress: number;
  currentSecond: number;
  durationSeconds: number;
  palette: Palette;
}) => {
  return (
    <header
      style={{
        position: 'absolute',
        left: 86,
        right: 86,
        top: 50,
        display: 'grid',
        gridTemplateColumns: 'auto 1fr auto',
        alignItems: 'center',
        gap: 34,
        textTransform: 'uppercase',
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
        <div
          style={{
            width: 42,
            height: 42,
            display: 'grid',
            placeItems: 'center',
            border: `1px solid ${palette.line}`,
            background: palette.panelStrong,
            fontSize: 21,
            fontWeight: 900,
          }}
        >
          {brandName.slice(0, 1)}
        </div>
        <div style={{fontSize: 31, fontWeight: 900, letterSpacing: 0}}>{brandName}</div>
      </div>
      <div
        style={{
          height: 1,
          background: `linear-gradient(90deg, ${palette.line}, ${palette.primary}88, ${palette.line})`,
          opacity: 0.8,
        }}
      />
      <div style={{display: 'flex', alignItems: 'center', gap: 24, color: palette.muted}}>
        <div style={{fontSize: fitFont(`${category} ${chapter ?? ''}`, 22, 16, 54)}}>
          {chapter ? `${category} / ${chapter}` : category}
        </div>
        <div style={{fontSize: 22, color: palette.ink, fontWeight: 850}}>
          {formatDuration(currentSecond)} / {formatDuration(durationSeconds)}
        </div>
        <div
          style={{
            width: 108,
            height: 7,
            background: 'rgba(255,255,255,0.16)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${progress * 100}%`,
              height: '100%',
              background: `linear-gradient(90deg, ${palette.primary}, ${palette.accent})`,
            }}
          />
        </div>
      </div>
    </header>
  );
};

const SignalRail = ({
  scenes,
  activeIndex,
  progress,
  palette,
}: {
  scenes: VideoScene[];
  activeIndex: number;
  progress: number;
  palette: Palette;
}) => {
  return (
    <aside
      style={{
        position: 'relative',
        height: '100%',
        display: 'grid',
        gridTemplateRows: 'auto 1fr auto',
        alignItems: 'stretch',
      }}
    >
      <div>
        <div style={{fontSize: 18, color: palette.muted, textTransform: 'uppercase'}}>Scene</div>
        <div style={{fontSize: 56, fontWeight: 950, lineHeight: 0.94, marginTop: 8}}>
          {String(activeIndex + 1).padStart(2, '0')}
        </div>
      </div>
      <div
        style={{
          position: 'relative',
          margin: '34px 0',
          borderLeft: `1px solid ${palette.line}`,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: -2,
            top: 0,
            width: 3,
            height: `${progress * 100}%`,
            background: `linear-gradient(${palette.primary}, ${palette.accent})`,
          }}
        />
        {scenes.slice(0, 8).map((scene, index) => {
          const active = index === activeIndex;
          return (
            <div
              key={scene.id}
              style={{
                position: 'absolute',
                left: -8,
                top: `${(index / Math.max(1, scenes.length - 1)) * 100}%`,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div
                style={{
                  width: active ? 15 : 10,
                  height: active ? 15 : 10,
                  background: active ? palette.accent : 'rgba(255,255,255,0.38)',
                  border: active ? `2px solid ${palette.ink}` : 'none',
                }}
              />
              {active ? (
                <div
                  style={{
                    width: 72,
                    fontSize: 14,
                    color: palette.muted,
                    textTransform: 'uppercase',
                    lineHeight: 1.05,
                  }}
                >
                  {layoutLabel(scene.layout)}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <div
        style={{
          fontSize: 22,
          color: palette.muted,
          lineHeight: 1.15,
          writingMode: 'vertical-rl',
          transform: 'rotate(180deg)',
          textTransform: 'uppercase',
          justifySelf: 'start',
        }}
      >
        Evidence first audio stories
      </div>
    </aside>
  );
};

const SceneStage = ({
  props,
  scene,
  line,
  sceneIndex,
  sceneProgress,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  sceneIndex: number;
  sceneProgress: number;
  palette: Palette;
}) => {
  const headline = scene?.headline || props.title;
  const subheadline = scene?.subheadline || props.summary || props.description || line?.text || '';
  const slide = interpolate(sceneProgress, [0, 1], [16, -8]);
  return (
    <section
      style={{
        position: 'relative',
        minWidth: 0,
        height: '100%',
        padding: '22px 0 0',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: 132,
          height: 7,
          background: `linear-gradient(90deg, ${palette.primary}, ${palette.accent})`,
        }}
      />
      <div
        style={{
          color: palette.muted,
          fontSize: 22,
          textTransform: 'uppercase',
          letterSpacing: 0,
          marginTop: 34,
        }}
      >
        {scene ? layoutLabel(scene.layout) : 'Episode'}
      </div>
      <h1
        style={{
          margin: '20px 0 0',
          maxWidth: 1040,
          fontSize: fitFont(headline, 104, 54, 42),
          lineHeight: 0.92,
          letterSpacing: 0,
          fontWeight: 950,
          transform: `translateY(${slide}px)`,
        }}
      >
        {headline}
      </h1>
      <p
        style={{
          margin: '30px 0 0',
          maxWidth: 930,
          fontSize: fitFont(subheadline, 35, 24, 120),
          lineHeight: 1.18,
          color: 'rgba(245,247,250,0.76)',
          fontWeight: 650,
        }}
      >
        {subheadline}
      </p>
      <SceneBody
        props={props}
        scene={scene}
        line={line}
        sceneIndex={sceneIndex}
        sceneProgress={sceneProgress}
        palette={palette}
      />
    </section>
  );
};

const SceneBody = ({
  props,
  scene,
  line,
  sceneIndex,
  sceneProgress,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  sceneIndex: number;
  sceneProgress: number;
  palette: Palette;
}) => {
  if (!scene) {
    return <QuoteLayout text={line?.text || props.summary || props.title} speaker={line?.speaker} palette={palette} />;
  }

  if (scene.layout === 'bullet_card') {
    return <BulletLayout scene={scene} palette={palette} />;
  }
  if (scene.layout === 'diagram_card') {
    return <DiagramLayout scene={scene} palette={palette} />;
  }
  if (scene.layout === 'source_card') {
    return <SourceLayout scene={scene} palette={palette} />;
  }
  if (scene.layout === 'timeline') {
    return <TimelineLayout scene={scene} props={props} palette={palette} />;
  }
  if (scene.layout === 'quote_card' || scene.layout === 'speaker_focus') {
    return (
      <QuoteLayout
        text={scene.quote || line?.text || scene.subheadline || props.summary || props.title}
        speaker={scene.speakerName || line?.speaker}
        palette={palette}
      />
    );
  }

  return (
    <ConceptLayout
      keywords={scene.visualKeywords}
      bullets={scene.bullets}
      fallback={line?.text || props.summary || props.title}
      sceneIndex={sceneIndex}
      sceneProgress={sceneProgress}
      palette={palette}
    />
  );
};

const ConceptLayout = ({
  keywords,
  bullets,
  fallback,
  sceneIndex,
  sceneProgress,
  palette,
}: {
  keywords: string[];
  bullets: string[];
  fallback: string;
  sceneIndex: number;
  sceneProgress: number;
  palette: Palette;
}) => {
  const items = bullets.length ? bullets : keywords.length ? keywords : keyPhrases(fallback);
  return (
    <div
      style={{
        marginTop: 52,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 22,
        maxWidth: 980,
      }}
    >
      {items.slice(0, 4).map((item, index) => {
        const active = index === sceneIndex % Math.max(1, items.length);
        return (
          <div
            key={item}
            style={{
              borderTop: `1px solid ${active ? palette.accent : palette.line}`,
              padding: '20px 0 0',
              minHeight: 112,
              opacity: active ? 1 : 0.72,
              transform: `translateY(${active ? interpolate(sceneProgress, [0, 1], [10, 0]) : 0}px)`,
            }}
          >
            <div style={{fontSize: 18, color: palette.muted}}>0{index + 1}</div>
            <div
              style={{
                marginTop: 10,
                fontSize: fitFont(item, 32, 22, 42),
                lineHeight: 1.08,
                fontWeight: 850,
              }}
            >
              {item}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const BulletLayout = ({scene, palette}: {scene: VideoScene; palette: Palette}) => {
  const items = (scene.bullets.length ? scene.bullets : scene.diagramItems).slice(0, 5);
  return (
    <div style={{marginTop: 48, display: 'grid', gap: 18, maxWidth: 980}}>
      {items.map((item, index) => (
        <div
          key={item}
          style={{
            display: 'grid',
            gridTemplateColumns: '74px 1fr',
            gap: 22,
            alignItems: 'center',
            padding: '17px 0',
            borderBottom: `1px solid ${palette.line}`,
          }}
        >
          <div
            style={{
              width: 54,
              height: 54,
              display: 'grid',
              placeItems: 'center',
              background: index === 0 ? palette.accent : palette.panelStrong,
              color: index === 0 ? '#17120a' : palette.ink,
              fontSize: 22,
              fontWeight: 950,
            }}
          >
            {index + 1}
          </div>
          <div
            style={{
              fontSize: fitFont(item, 40, 25, 70),
              lineHeight: 1.05,
              fontWeight: 850,
            }}
          >
            {item}
          </div>
        </div>
      ))}
    </div>
  );
};

const DiagramLayout = ({scene, palette}: {scene: VideoScene; palette: Palette}) => {
  const items = (scene.diagramItems.length ? scene.diagramItems : scene.bullets).slice(0, 5);
  return (
    <div
      style={{
        marginTop: 58,
        position: 'relative',
        height: 230,
        maxWidth: 1020,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 34,
          right: 34,
          top: 86,
          height: 2,
          background: `linear-gradient(90deg, ${palette.primary}, ${palette.accent})`,
        }}
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.max(1, items.length)}, 1fr)`,
          gap: 18,
        }}
      >
        {items.map((item, index) => (
          <div key={item} style={{position: 'relative', minWidth: 0}}>
            <div
              style={{
                width: 74,
                height: 74,
                display: 'grid',
                placeItems: 'center',
                background: index === 0 ? palette.primary : palette.panelStrong,
                color: index === 0 ? '#061114' : palette.ink,
                border: `1px solid ${index === 0 ? palette.primary : palette.line}`,
                fontSize: 24,
                fontWeight: 950,
              }}
            >
              {String(index + 1).padStart(2, '0')}
            </div>
            <div
              style={{
                marginTop: 28,
                fontSize: fitFont(item, 27, 19, 34),
                lineHeight: 1.08,
                fontWeight: 850,
              }}
            >
              {item}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const SourceLayout = ({scene, palette}: {scene: VideoScene; palette: Palette}) => {
  const sources = (scene.sourceUrls.length ? scene.sourceUrls : ['Verified claim bank']).slice(0, 4);
  return (
    <div style={{marginTop: 48, display: 'grid', gap: 16, maxWidth: 980}}>
      {sources.map((source, index) => (
        <div
          key={source}
          style={{
            display: 'grid',
            gridTemplateColumns: '88px 1fr',
            gap: 22,
            alignItems: 'baseline',
            padding: '18px 0',
            borderBottom: `1px solid ${palette.line}`,
          }}
        >
          <div style={{fontSize: 18, color: index === 0 ? palette.accent : palette.muted}}>
            SRC {index + 1}
          </div>
          <div
            style={{
              fontSize: fitFont(source, 31, 20, 82),
              lineHeight: 1.12,
              fontWeight: 760,
              overflowWrap: 'anywhere',
            }}
          >
            {source}
          </div>
        </div>
      ))}
    </div>
  );
};

const TimelineLayout = ({
  scene,
  props,
  palette,
}: {
  scene: VideoScene;
  props: PodcastVideoProps;
  palette: Palette;
}) => {
  const items = props.chapters.length
    ? props.chapters.map((chapter) => chapter.title)
    : scene.diagramItems.length
      ? scene.diagramItems
      : scene.bullets;
  return (
    <div style={{marginTop: 48, display: 'grid', gap: 12, maxWidth: 920}}>
      {items.slice(0, 5).map((item, index) => (
        <div
          key={item}
          style={{
            display: 'grid',
            gridTemplateColumns: '90px 1fr',
            gap: 24,
            alignItems: 'center',
            minHeight: 62,
          }}
        >
          <div
            style={{
              fontSize: 18,
              color: palette.background,
              background: index === 0 ? palette.accent : 'rgba(255,255,255,0.74)',
              padding: '8px 10px',
              fontWeight: 900,
              textAlign: 'center',
            }}
          >
            PART {index + 1}
          </div>
          <div
            style={{
              fontSize: fitFont(item, 38, 24, 54),
              fontWeight: 850,
              borderBottom: `1px solid ${palette.line}`,
              paddingBottom: 14,
            }}
          >
            {item}
          </div>
        </div>
      ))}
    </div>
  );
};

const QuoteLayout = ({
  text,
  speaker,
  palette,
}: {
  text: string;
  speaker?: string;
  palette: Palette;
}) => {
  return (
    <div style={{marginTop: 58, maxWidth: 1010}}>
      <div
        style={{
          fontSize: fitFont(text, 58, 34, 118),
          lineHeight: 1.04,
          fontWeight: 900,
          color: 'rgba(255,255,255,0.92)',
        }}
      >
        {text}
      </div>
      {speaker ? (
        <div
          style={{
            marginTop: 28,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 14,
            color: palette.muted,
            fontSize: 22,
            textTransform: 'uppercase',
          }}
        >
          <span
            style={{
              width: 42,
              height: 5,
              background: `linear-gradient(90deg, ${palette.primary}, ${palette.accent})`,
            }}
          />
          {speaker}
        </div>
      ) : null}
    </div>
  );
};

const EpisodePoster = ({
  props,
  scene,
  line,
  dialogueCount,
  progress,
  palette,
}: {
  props: PodcastVideoProps;
  scene: VideoScene | null;
  line: CaptionLine;
  dialogueCount: number;
  progress: number;
  palette: Palette;
}) => {
  const thumbnailUrl = props.thumbnailUrl.trim();
  const keywords = scene?.visualKeywords.length ? scene.visualKeywords : [props.category, props.language];
  return (
    <aside
      style={{
        position: 'relative',
        minWidth: 0,
        display: 'grid',
        gridTemplateRows: '480px auto 1fr',
        gap: 28,
      }}
    >
      <div
        style={{
          position: 'relative',
          overflow: 'hidden',
          border: `1px solid ${palette.line}`,
          background: palette.panelStrong,
        }}
      >
        <FallbackPoster title={props.title} palette={palette} />
        {thumbnailUrl ? (
          <Img
            src={thumbnailUrl}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          />
        ) : null}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'linear-gradient(180deg, transparent 42%, rgba(0,0,0,0.76) 100%)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 28,
            right: 28,
            bottom: 28,
          }}
        >
          <div
            style={{
              color: palette.muted,
              fontSize: 18,
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            Episode cover
          </div>
          <div
            style={{
              fontSize: fitFont(props.title, 36, 24, 48),
              lineHeight: 1,
              fontWeight: 950,
            }}
          >
            {props.title}
          </div>
        </div>
      </div>
      <SpeakerStack speakers={props.speakers} activeSpeaker={line?.speaker} palette={palette} />
      <div
        style={{
          display: 'grid',
          alignContent: 'end',
          gap: 18,
          minHeight: 0,
        }}
      >
        <KeywordStack keywords={keywords} palette={palette} />
        <Waveform progress={progress} count={dialogueCount || 28} palette={palette} />
      </div>
    </aside>
  );
};

const FallbackPoster = ({title, palette}: {title: string; palette: Palette}) => {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'grid',
        placeItems: 'center',
        padding: 46,
        background:
          `linear-gradient(140deg, ${palette.primary}30, ${palette.green}28 42%, ${palette.accent}30)`,
      }}
    >
      <div
        style={{
          width: '78%',
          height: '78%',
          border: '2px solid rgba(255,255,255,0.28)',
          display: 'grid',
          placeItems: 'center',
          padding: 34,
          textAlign: 'center',
          fontSize: fitFont(title, 46, 28, 38),
          lineHeight: 1,
          fontWeight: 950,
        }}
      >
        {title}
      </div>
    </div>
  );
};

const SpeakerStack = ({
  speakers,
  activeSpeaker,
  palette,
}: {
  speakers: PodcastVideoProps['speakers'];
  activeSpeaker?: string;
  palette: Palette;
}) => {
  const resolved = speakers.length ? speakers : [{name: 'Pleopod', role: 'Podcast'}];
  return (
    <div style={{display: 'grid', gap: 12}}>
      {resolved.slice(0, 2).map((speaker, index) => {
        const active = speaker.name.toLowerCase() === (activeSpeaker || '').toLowerCase();
        return (
          <div
            key={speaker.name}
            style={{
              display: 'grid',
              gridTemplateColumns: '58px 1fr auto',
              alignItems: 'center',
              gap: 16,
              padding: '12px 0',
              borderBottom: `1px solid ${palette.line}`,
            }}
          >
            <div
              style={{
                width: 52,
                height: 52,
                display: 'grid',
                placeItems: 'center',
                background: active ? palette.accent : palette.panelStrong,
                color: active ? '#151008' : palette.ink,
                fontSize: 20,
                fontWeight: 950,
              }}
            >
              {initials(speaker.name)}
            </div>
            <div>
              <div style={{fontSize: 25, fontWeight: 900}}>{speaker.name}</div>
              <div style={{fontSize: 17, color: palette.muted, marginTop: 3}}>
                {speaker.role || speaker.style || 'Speaker'}
              </div>
            </div>
            <div style={{fontSize: 18, color: active ? palette.accent : palette.muted}}>
              {active ? 'LIVE' : `0${index + 1}`}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const KeywordStack = ({keywords, palette}: {keywords: string[]; palette: Palette}) => {
  return (
    <div style={{display: 'flex', flexWrap: 'wrap', gap: 10}}>
      {keywords.slice(0, 5).map((keyword, index) => (
        <div
          key={keyword}
          style={{
            border: `1px solid ${index === 0 ? palette.accent : palette.line}`,
            color: index === 0 ? palette.ink : palette.muted,
            background: index === 0 ? 'rgba(245,158,11,0.16)' : 'rgba(255,255,255,0.045)',
            padding: '8px 11px',
            fontSize: 16,
            fontWeight: 760,
            textTransform: 'uppercase',
          }}
        >
          {keyword}
        </div>
      ))}
    </div>
  );
};

const LowerThird = ({
  line,
  fallback,
  speakers,
  progress,
  palette,
}: {
  line: CaptionLine;
  fallback: string;
  speakers: PodcastVideoProps['speakers'];
  progress: number;
  palette: Palette;
}) => {
  const text = line?.text || fallback;
  const speaker = line?.speaker || speakers[0]?.name || 'Pleopod';
  return (
    <div
      style={{
        position: 'absolute',
        left: 86,
        right: 86,
        bottom: 38,
        display: 'grid',
        gridTemplateColumns: '210px 1fr',
        gap: 28,
        alignItems: 'center',
      }}
    >
      <div
        style={{
          height: 82,
          display: 'grid',
          gridTemplateColumns: '58px 1fr',
          alignItems: 'center',
          gap: 14,
          borderTop: `1px solid ${palette.line}`,
          borderBottom: `1px solid ${palette.line}`,
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            display: 'grid',
            placeItems: 'center',
            background: palette.primary,
            color: '#051114',
            fontWeight: 950,
            fontSize: 18,
          }}
        >
          {initials(speaker)}
        </div>
        <div>
          <div style={{fontSize: 17, color: palette.muted, textTransform: 'uppercase'}}>Speaking</div>
          <div style={{fontSize: fitFont(speaker, 25, 18, 16), fontWeight: 900}}>{speaker}</div>
        </div>
      </div>
      <div
        style={{
          minHeight: 82,
          display: 'grid',
          alignItems: 'center',
          borderTop: `1px solid ${palette.line}`,
          borderBottom: `1px solid ${palette.line}`,
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: 0,
            width: `${progress * 100}%`,
            height: 4,
            background: `linear-gradient(90deg, ${palette.primary}, ${palette.accent})`,
          }}
        />
        <div
          style={{
            fontSize: fitFont(text, 36, 22, 150),
            lineHeight: 1.1,
            fontWeight: 850,
            color: 'rgba(255,255,255,0.93)',
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
};

const Waveform = ({progress, count, palette}: {progress: number; count: number; palette: Palette}) => {
  const bars = Array.from({length: 44}, (_, index) => index);
  return (
    <div
      style={{
        height: 82,
        display: 'flex',
        alignItems: 'end',
        gap: 7,
        borderTop: `1px solid ${palette.line}`,
        paddingTop: 18,
      }}
    >
      {bars.map((index) => {
        const wave = Math.sin(index * 0.78 + count * 0.21);
        const active = index / bars.length <= progress;
        return (
          <div
            key={index}
            style={{
              width: 6,
              height: 18 + Math.abs(wave) * 50,
              background: active ? palette.primary : 'rgba(255,255,255,0.22)',
              opacity: active ? 1 : 0.52,
            }}
          />
        );
      })}
    </div>
  );
};

const ProgressRail = ({progress, palette}: {progress: number; palette: Palette}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: 86,
        right: 86,
        bottom: 18,
        height: 5,
        background: 'rgba(255,255,255,0.14)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${progress * 100}%`,
          height: '100%',
          background: `linear-gradient(90deg, ${palette.primary}, ${palette.green}, ${palette.accent})`,
        }}
      />
    </div>
  );
};

const makePalette = (brand: PodcastVideoProps['brand']): Palette => ({
  background: brand.backgroundColor || '#0a0c0f',
  primary: brand.primaryColor || '#22d3ee',
  accent: brand.accentColor || '#f59e0b',
  ink: '#f7f7f2',
  muted: 'rgba(247,247,242,0.62)',
  panel: 'rgba(255,255,255,0.075)',
  panelStrong: 'rgba(255,255,255,0.11)',
  line: 'rgba(255,255,255,0.16)',
  coral: '#ff6b5f',
  green: '#8bdc9f',
});

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
    .slice(0, 12);
  if (words.length === 0) {
    return ['Evidence', 'Timing', 'Publishing'];
  }
  return [
    words.slice(0, 3).join(' '),
    words.slice(3, 6).join(' '),
    words.slice(6, 9).join(' '),
  ].filter(Boolean);
};

const initials = (name: string) => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return 'P';
  }
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
};

const formatDuration = (seconds: number) => {
  const clamped = Math.max(0, seconds);
  const minutes = Math.floor(clamped / 60);
  const remainingSeconds = Math.floor(clamped % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
};

const fitFont = (text: string | undefined, base: number, minimum: number, comfort = 80) => {
  const length = (text ?? '').length;
  if (length <= comfort) {
    return base;
  }
  return Math.max(minimum, base - (length - comfort) * 0.24);
};

const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value));
};
