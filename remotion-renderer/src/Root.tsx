import {Composition} from 'remotion';
import {
  defaultPodcastVideoProps,
  podcastVideoSchema,
  type PodcastVideoProps,
} from './types';
import {PodcastEpisode} from './PodcastEpisode';

const fps = 30;

export const RemotionRoot = () => {
  return (
    <Composition
      id="PodcastEpisode"
      component={PodcastEpisode}
      durationInFrames={defaultPodcastVideoProps.durationSeconds * fps}
      fps={fps}
      width={1920}
      height={1080}
      schema={podcastVideoSchema}
      defaultProps={defaultPodcastVideoProps}
      calculateMetadata={({props}: {props: PodcastVideoProps}) => {
        const format = props.format ?? defaultPodcastVideoProps.format;
        const resolvedFps = format.fps || fps;
        return {
          durationInFrames: Math.ceil(props.durationSeconds * resolvedFps),
          fps: resolvedFps,
          width: format.width,
          height: format.height,
        };
      }}
    />
  );
};
