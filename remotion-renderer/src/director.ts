import {readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {buildFallbackVideoPlan} from './fallback-plan';
import {podcastVideoSchema, type PodcastVideoProps} from './types';
import {normalizeVideoPlan, videoPlanSchema} from './video-plan';

type DirectorArgs = {
  propsPath: string;
  outPath: string;
  model: string;
  fallback: boolean;
};

const parseArgs = (argv: string[]): DirectorArgs => {
  const args = new Map<string, string>();
  const flags = new Set<string>();

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) {
      continue;
    }

    const [key, inlineValue] = token.slice(2).split('=', 2);
    if (key === 'fallback') {
      flags.add(key);
      continue;
    }

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
    outPath: args.get('out') ?? './sample-video-plan.json',
    model: args.get('model') ?? 'gemini-2.5-flash',
    fallback: flags.has('fallback'),
  };
};

const loadPodcastPayload = async (propsPath: string) => {
  const absolutePropsPath = path.resolve(process.cwd(), propsPath);
  const raw = await readFile(absolutePropsPath, 'utf8');
  return podcastVideoSchema.parse(JSON.parse(raw));
};

const main = async () => {
  const args = parseArgs(process.argv.slice(2));
  const payload = await loadPodcastPayload(args.propsPath);
  const plan = args.fallback
    ? normalizeVideoPlan(buildFallbackVideoPlan(payload))
    : await generateVideoPlan(payload, args.model);
  const outputPath = path.resolve(process.cwd(), args.outPath);

  await writeFile(outputPath, `${JSON.stringify(plan, null, 2)}\n`);
  console.info(`Wrote video plan to ${outputPath}`);
};

const generateVideoPlan = async (payload: PodcastVideoProps, model: string) => {
  if (!process.env.GEMINI_API_KEY) {
    throw new Error(
      'GEMINI_API_KEY is required. Use --fallback to generate a deterministic local plan.',
    );
  }

  const {GoogleGenAI} = await import('@google/genai');
  const ai = new GoogleGenAI({apiKey: process.env.GEMINI_API_KEY});
  const fallbackPlan = buildFallbackVideoPlan(payload, model);
  const response = await ai.models.generateContent({
    model,
    contents: directorPrompt(payload, fallbackPlan),
    config: {
      responseMimeType: 'application/json',
      responseJsonSchema: geminiVideoPlanResponseSchema,
    },
  });

  const parsed = videoPlanSchema.parse(JSON.parse(response.text ?? '{}'));
  return normalizeVideoPlan({
    ...parsed,
    directorModel: model,
  });
};

const directorPrompt = (payload: PodcastVideoProps, fallbackPlan: unknown) => {
  return `
You are the Video Director Agent for Pleopod.

Create a video_plan JSON object for a Remotion-rendered podcast video.

The video will NOT use AI video generation. Remotion will render deterministic layouts.
Your job is to decide what should appear on screen at each moment based on the transcript.

Rules:
- Use only the allowed layouts from the schema.
- Align scenes to what is being discussed in the transcript.
- Keep scene boundaries within durationSeconds.
- Cover the complete 16:9 YouTube video from 0 through durationSeconds; never leave gaps.
- Treat durationSeconds as the final video length and keep the last scene ending exactly there.
- Prefer clear concepts, diagrams, speaker focus, quote cards, and source cards.
- Do not invent facts. Use only the transcript, summary, metadata, and supplied fallback timings.
- Captions should reference line ids from lineTimings using captionLineIds.
- Use very short readable headlines, never full paragraphs.
- Bullets should be concise, high-contrast, and safe inside a YouTube 1920x1080 frame.
- Prioritize clarity over decoration: large type, few words, no crowded cards.
- Return JSON only.

Podcast payload:
${JSON.stringify(payload, null, 2)}

Fallback line timing and scene draft:
${JSON.stringify(fallbackPlan, null, 2)}
`.trim();
};

const sceneLayouts = [
  'episode_intro',
  'chapter_card',
  'speaker_focus',
  'concept_card',
  'bullet_card',
  'source_card',
  'timeline',
  'quote_card',
  'diagram_card',
  'thumbnail_focus',
  'closing_card',
] as const;

const emphasisValues = ['calm', 'curious', 'urgent', 'technical', 'reflective'] as const;

// Gemini's JSON schema endpoint rejects top-level $ref schemas. Keep this schema
// inline and validate the returned plan with Zod before Remotion sees it.
const geminiVideoPlanResponseSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['version', 'durationSeconds', 'lineTimings', 'scenes', 'productionNotes'],
  properties: {
    version: {
      type: 'number',
      enum: [1],
    },
    directorModel: {
      type: 'string',
    },
    durationSeconds: {
      type: 'number',
      minimum: 5,
      maximum: 7200,
    },
    lineTimings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'speaker', 'text', 'startSeconds', 'endSeconds'],
        properties: {
          id: {type: 'string'},
          speaker: {type: 'string'},
          text: {type: 'string'},
          startSeconds: {type: 'number', minimum: 0},
          endSeconds: {type: 'number', minimum: 0},
        },
      },
    },
    scenes: {
      type: 'array',
      minItems: 1,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [
          'id',
          'startSeconds',
          'endSeconds',
          'layout',
          'headline',
          'bullets',
          'diagramItems',
          'sourceUrls',
          'captionLineIds',
          'visualKeywords',
          'emphasis',
        ],
        properties: {
          id: {type: 'string'},
          startSeconds: {type: 'number', minimum: 0},
          endSeconds: {type: 'number', minimum: 0},
          layout: {type: 'string', enum: [...sceneLayouts]},
          headline: {type: 'string'},
          subheadline: {type: 'string'},
          speakerName: {type: 'string'},
          quote: {type: 'string'},
          bullets: {
            type: 'array',
            maxItems: 5,
            items: {type: 'string'},
          },
          diagramItems: {
            type: 'array',
            maxItems: 6,
            items: {type: 'string'},
          },
          sourceUrls: {
            type: 'array',
            maxItems: 4,
            items: {type: 'string'},
          },
          captionLineIds: {
            type: 'array',
            items: {type: 'string'},
          },
          visualKeywords: {
            type: 'array',
            maxItems: 8,
            items: {type: 'string'},
          },
          emphasis: {type: 'string', enum: [...emphasisValues]},
        },
      },
    },
    productionNotes: {
      type: 'array',
      items: {type: 'string'},
    },
  },
} as const;

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
