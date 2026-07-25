import {Composition} from 'remotion';
import {
  defaultPodcastVideoProps,
  podcastVideoSchema,
  type PodcastVideoProps,
} from './types';
import {PodcastEpisode} from './PodcastEpisode';
import {PresentationEpisode} from './PresentationEpisode';

const fps = 30;

const calculateMetadata = ({props}: {props: PodcastVideoProps}) => {
  const format = props.format ?? defaultPodcastVideoProps.format;
  const resolvedFps = format.fps || fps;
  return {
    durationInFrames: Math.ceil(props.durationSeconds * resolvedFps),
    fps: resolvedFps,
    width: format.width,
    height: format.height,
  };
};

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="PresentationEpisode"
        component={PresentationEpisode}
        durationInFrames={defaultPodcastVideoProps.durationSeconds * fps}
        fps={fps}
        width={1920}
        height={1080}
        schema={podcastVideoSchema}
        defaultProps={defaultPodcastVideoProps}
        calculateMetadata={calculateMetadata}
      />
      <Composition
        id="PodcastEpisode"
        component={PodcastEpisode}
        durationInFrames={defaultPodcastVideoProps.durationSeconds * fps}
        fps={fps}
        width={1920}
        height={1080}
        schema={podcastVideoSchema}
        defaultProps={defaultPodcastVideoProps}
        calculateMetadata={calculateMetadata}
      />
    </>
  );
};
