import {mkdir, readFile} from 'node:fs/promises';
import {createServer, type Server} from 'node:http';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {scenePlanSchema} from './scene-plan';
import {podcastVideoSchema, type PodcastVideoProps} from './types';
import {normalizeVideoPlan, videoPlanSchema} from './video-plan';

type RenderArgs = {
  propsPath: string;
  planPath?: string;
  scenePlanPath?: string;
  sourcesPath?: string;
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
    scenePlanPath: args.get('scene-plan'),
    sourcesPath: args.get('sources'),
    outPath: args.get('out') ?? './out/podcast-video.mp4',
    compositionId: args.get('composition') ?? 'PodcastEpisode',
  };
};

const loadInputProps = async (
  propsPath: string,
  planPath?: string,
  scenePlanPath?: string,
  sourcesPath?: string,
) => {
  const absolutePropsPath = path.resolve(process.cwd(), propsPath);
  const raw = await readFile(absolutePropsPath, 'utf8');
  let payload = podcastVideoSchema.parse(JSON.parse(raw));
  if (planPath) {
    const absolutePlanPath = path.resolve(process.cwd(), planPath);
    const planRaw = await readFile(absolutePlanPath, 'utf8');
    payload = podcastVideoSchema.parse({
      ...payload,
      videoPlan: normalizeVideoPlan(videoPlanSchema.parse(JSON.parse(planRaw))),
    });
  }

  if (scenePlanPath) {
    const absoluteScenePlanPath = path.resolve(process.cwd(), scenePlanPath);
    const scenePlanRaw = await readFile(absoluteScenePlanPath, 'utf8');
    payload = podcastVideoSchema.parse({
      ...payload,
      scenePlan: scenePlanSchema.parse(JSON.parse(scenePlanRaw)),
    });
  }

  if (sourcesPath && payload.scenePlan) {
    const absoluteSourcesPath = path.resolve(process.cwd(), sourcesPath);
    const sourcesRaw = await readFile(absoluteSourcesPath, 'utf8');
    const sourcesJson: unknown = JSON.parse(sourcesRaw);
    const sourceUrls = Array.isArray(sourcesJson)
      ? sourcesJson
          .map((source) => {
            if (typeof source === 'string') {
              return source;
            }
            if (source && typeof source === 'object' && 'url' in source) {
              return String(source.url);
            }
            return '';
          })
          .filter((url) => /^https?:\/\//.test(url))
          .slice(0, 4)
      : [];
    payload = podcastVideoSchema.parse({
      ...payload,
      scenePlan: {
        ...payload.scenePlan,
        scenes: payload.scenePlan.scenes.map((scene) =>
          scene.layout === 'source' && !scene.source_urls.length
            ? {
                ...scene,
                headline: scene.headline || 'Sources',
                source_urls: sourceUrls,
              }
            : scene,
        ),
      },
    });
  }

  return payload;
};

const toPercent = (progress: number) => {
  return Math.max(0, Math.min(100, Math.round(progress <= 1 ? progress * 100 : progress)));
};

const contentTypeForPath = (filePath: string) => {
  switch (path.extname(filePath).toLowerCase()) {
    case '.mp3':
      return 'audio/mpeg';
    case '.wav':
      return 'audio/wav';
    case '.aac':
      return 'audio/aac';
    case '.m4a':
      return 'audio/mp4';
    case '.jpg':
    case '.jpeg':
      return 'image/jpeg';
    case '.webp':
      return 'image/webp';
    case '.png':
    default:
      return 'image/png';
  }
};

const closeServer = (server: Server) =>
  new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });

const serveLocalMedia = async (
  payload: PodcastVideoProps,
): Promise<{payload: PodcastVideoProps; close: () => Promise<void>}> => {
  const mediaFields = ['audioUrl', 'thumbnailUrl'] as const;
  const localFiles = mediaFields.flatMap((field) => {
    const value = payload[field].trim();
    if (!value.startsWith('file://')) {
      return [];
    }
    return [{field, filePath: fileURLToPath(value)}];
  });
  if (!localFiles.length) {
    return {payload, close: async () => undefined};
  }

  const server = createServer(async (request, response) => {
    const match = /^\/asset\/(\d+)$/.exec(request.url ?? '');
    const asset = match ? localFiles[Number(match[1])] : undefined;
    if (!asset || request.method !== 'GET') {
      response.writeHead(404).end();
      return;
    }
    try {
      const bytes = await readFile(asset.filePath);
      response.writeHead(200, {
        'Content-Length': bytes.byteLength,
        'Content-Type': contentTypeForPath(asset.filePath),
        'Cache-Control': 'no-store',
      });
      response.end(bytes);
    } catch (error) {
      console.error(`Unable to serve local render asset ${asset.filePath}`, error);
      response.writeHead(500).end();
    }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') {
    await closeServer(server);
    throw new Error('Local render asset server did not expose a TCP port');
  }

  const rewritten = {...payload};
  localFiles.forEach((asset, index) => {
    rewritten[asset.field] = `http://127.0.0.1:${address.port}/asset/${index}`;
  });
  return {payload: rewritten, close: () => closeServer(server)};
};

const main = async () => {
  const args = parseArgs(process.argv.slice(2));
  const loadedProps = await loadInputProps(
    args.propsPath,
    args.planPath,
    args.scenePlanPath,
    args.sourcesPath,
  );
  const localMedia = await serveLocalMedia(loadedProps);
  const inputProps = localMedia.payload;
  const entryPoint = path.resolve(process.cwd(), 'src/index.ts');
  const outputLocation = path.resolve(process.cwd(), args.outPath);

  try {
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

    // Bound parallelism to keep peak RAM low on small hosts (Railway hobby).
    // Override with REMOTION_CONCURRENCY when running on a larger box.
    const concurrency = process.env.REMOTION_CONCURRENCY
      ? Math.max(1, Number(process.env.REMOTION_CONCURRENCY))
      : 2;

    let lastRenderPercent = -1;
    await renderMedia({
      audioBitrate: '192k',
      audioCodec: 'aac',
      codec: 'h264',
      composition,
      concurrency,
      crf: 20,
      imageFormat: 'jpeg',
      serveUrl,
      inputProps,
      outputLocation,
      pixelFormat: 'yuv420p',
      x264Preset: 'medium',
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
  } finally {
    await localMedia.close();
  }
};

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
