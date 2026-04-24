import {z} from 'zod';
import {videoPlanSchema} from './video-plan';

export const speakerSchema = z.object({
  name: z.string().min(1),
  role: z.string().optional(),
  voiceName: z.string().optional(),
  style: z.string().optional(),
});

export const chapterSchema = z.object({
  title: z.string().min(1),
  startSeconds: z.number().min(0),
});

export const brandSchema = z.object({
  name: z.string().min(1).default('Pleopod'),
  tagline: z.string().optional(),
  primaryColor: z.string().default('#22d3ee'),
  accentColor: z.string().default('#f59e0b'),
  backgroundColor: z.string().default('#101216'),
});

export const videoFormatSchema = z.object({
  platform: z.literal('youtube').default('youtube'),
  aspectRatio: z.literal('16:9').default('16:9'),
  width: z.literal(1920).default(1920),
  height: z.literal(1080).default(1080),
  fps: z.literal(30).default(30),
  tailPadSeconds: z.number().min(0).max(10).default(1),
});

export const podcastVideoSchema = z.object({
  jobId: z.string().optional(),
  episodeId: z.string().optional(),
  title: z.string().min(1),
  summary: z.string().optional(),
  description: z.string().optional(),
  category: z.string().default('Tech'),
  language: z.string().default('en'),
  durationSeconds: z.number().min(5).max(7200),
  audioDurationSeconds: z.number().min(0).optional().nullable(),
  audioUrl: z.string().default(''),
  thumbnailUrl: z.string().default(''),
  publishedAt: z.string().optional(),
  speakers: z.array(speakerSchema).min(1).max(2).default([]),
  transcript: z.string().default(''),
  chapters: z.array(chapterSchema).default([]),
  videoPlan: videoPlanSchema.optional(),
  format: videoFormatSchema.default({
    platform: 'youtube',
    aspectRatio: '16:9',
    width: 1920,
    height: 1080,
    fps: 30,
    tailPadSeconds: 1,
  }),
  brand: brandSchema.default({
    name: 'Pleopod',
    tagline: 'Factual tech podcasts, generated with evidence.',
    primaryColor: '#22d3ee',
    accentColor: '#f59e0b',
    backgroundColor: '#101216',
  }),
});

export type PodcastVideoProps = z.infer<typeof podcastVideoSchema>;

export const defaultPodcastVideoProps: PodcastVideoProps = {
  title: 'The AI Podcast Pipeline',
  summary: 'A practical look at research, verification, and audio generation.',
  description: 'A sample Pleopod episode video payload.',
  category: 'Tech',
  language: 'en',
  durationSeconds: 45,
  audioDurationSeconds: undefined,
  audioUrl: '',
  thumbnailUrl: '',
  speakers: [
    {
      name: 'Arman',
      role: 'Host',
      voiceName: 'Charon',
      style: 'clear, warm',
    },
    {
      name: 'Maya',
      role: 'Analyst',
      voiceName: 'Puck',
      style: 'curious, energetic',
    },
  ],
  transcript:
    'Arman: Welcome back. Today we are looking at how an AI podcast pipeline should work.\n' +
    'Maya: The key is simple: research first, verify every important claim, then generate audio.',
  chapters: [
    {title: 'Research', startSeconds: 0},
    {title: 'Verification', startSeconds: 15},
    {title: 'Publishing', startSeconds: 30},
  ],
  videoPlan: undefined,
  format: {
    platform: 'youtube',
    aspectRatio: '16:9',
    width: 1920,
    height: 1080,
    fps: 30,
    tailPadSeconds: 1,
  },
  brand: {
    name: 'Pleopod',
    tagline: 'Factual tech podcasts, generated with evidence.',
    primaryColor: '#22d3ee',
    accentColor: '#f59e0b',
    backgroundColor: '#101216',
  },
};
