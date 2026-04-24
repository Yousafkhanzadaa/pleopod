import {mkdir, readFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {podcastVideoSchema} from './types';
import {normalizeVideoPlan, videoPlanSchema} from './video-plan';

type RenderArgs = {
  propsPath: string;
  planPath?: string;
  outPath: string;
  compositionId: string;
};

const parseArgs = (argv: string[]): RenderArgs => {
  const args = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) {
      continue;
    }
    const [key, inlineValue] = token.slice(2).split('=', 2);
    const value = inlineValue ?? argv[index + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for --${key}`);
    }
    args.set(key, value);
    if (!inlineValue) {
      index += 1;
    }
  }

  return {
    propsPath: args.get('props') ?? './sample-payload.json',
    planPath: args.get('plan'),
    outPath: args.get('out') ?? './out/podcast-video.mp4',
    compositionId: args.get('composition') ?? 'PodcastEpisode',
  };
};

const loadInputProps = async (propsPath: string, planPath?: string) => {
  const absolutePropsPath = path.resolve(process.cwd(), propsPath);
  const raw = await readFile(absolutePropsPath, 'utf8');
  const payload = podcastVideoSchema.parse(JSON.parse(raw));
  if (!planPath) {
    return payload;
  }

  const absolutePlanPath = path.resolve(process.cwd(), planPath);
  const planRaw = await readFile(absolutePlanPath, 'utf8');
  return podcastVideoSchema.parse({
    ...payload,
    videoPlan: normalizeVideoPlan(videoPlanSchema.parse(JSON.parse(planRaw))),
  });
};

const toPercent = (progress: number) => {
  return Math.max(0, Math.min(100, Math.round(progress <= 1 ? progress * 100 : progress)));
};

const main = async () => {
  const args = parseArgs(process.argv.slice(2));
  const inputProps = await loadInputProps(args.propsPath, args.planPath);
  const entryPoint = path.resolve(process.cwd(), 'src/index.ts');
  const outputLocation = path.resolve(process.cwd(), args.outPath);

  await mkdir(path.dirname(outputLocation), {recursive: true});

  let lastBundlePercent = -1;
  const serveUrl = await bundle({
    entryPoint,
    onProgress: (progress) => {
      const percent = toPercent(progress);
      if (percent === lastBundlePercent || percent === 100) {
        return;
      }
      lastBundlePercent = percent;
      console.info(`Bundling Remotion project: ${percent}%`);
    },
  });

  const composition = await selectComposition({
    serveUrl,
    id: args.compositionId,
    inputProps,
  });

  let lastRenderPercent = -1;
  await renderMedia({
    audioBitrate: '192k',
    audioCodec: 'aac',
    codec: 'h264',
    composition,
    crf: 18,
    imageFormat: 'png',
    serveUrl,
    inputProps,
    outputLocation,
    pixelFormat: 'yuv420p',
    x264Preset: 'slow',
    onProgress: ({progress}) => {
      const percent = toPercent(progress);
      if (percent === lastRenderPercent) {
        return;
      }
      lastRenderPercent = percent;
      console.info(`Rendering ${args.compositionId}: ${percent}%`);
    },
  });

  console.info(`Rendered video to ${outputLocation}`);
};

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
