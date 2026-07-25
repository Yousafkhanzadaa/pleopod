import type {PodcastVideoProps} from '../types';
import type {Emphasis} from '../scene-plan';

export {BODY_FONT, DISPLAY_FONT, MONO_FONT} from './fonts';

export type Theme = {
  background: string;
  surface: string;
  surfaceRaised: string;
  ink: string;
  inkDark: string;
  muted: string;
  line: string;
  primary: string;
  accent: string;
  accentAlt: string;
  positive: string;
  negative: string;
  chartTrack: string;
  chartColors: string[];
};

const EMPHASIS_ACCENT: Record<Emphasis, string | null> = {
  calm: null,
  curious: '#F4C95D',
  urgent: '#FF6B57',
  technical: '#5B7CFA',
  reflective: '#B69CFF',
};

export const makeTheme = (
  brand: PodcastVideoProps['brand'],
  emphasis: Emphasis = 'calm',
): Theme => {
  const primary = brand.primaryColor || '#5B7CFA';
  const accent = EMPHASIS_ACCENT[emphasis] ?? brand.accentColor ?? '#F4C95D';
  return {
    background: brand.backgroundColor || '#0B0D10',
    surface: '#171A20',
    surfaceRaised: '#22262E',
    ink: '#F5F1E8',
    inkDark: '#0B0D10',
    muted: '#9CA5B5',
    line: '#343A46',
    primary,
    accent,
    accentAlt: '#4BC6A5',
    positive: '#4BC6A5',
    negative: '#FF6B57',
    chartTrack: '#292E37',
    chartColors: [accent, primary, '#4BC6A5', '#B69CFF', '#F28CB1', '#F08A4B'],
  };
};

export const formatNumber = (value: number): string => {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return trim(value / 1_000_000_000) + 'B';
  if (abs >= 1_000_000) return trim(value / 1_000_000) + 'M';
  if (abs >= 1_000) return trim(value / 1_000) + 'K';
  return trim(value);
};

const trim = (value: number): string => {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
};

export const niceMax = (value: number): number => {
  if (value <= 0) return 1;
  const power = Math.pow(10, Math.floor(Math.log10(value)));
  const n = value / power;
  const step =
    n <= 1 ? 1 : n <= 1.5 ? 1.5 : n <= 2 ? 2 : n <= 3 ? 3 : n <= 5 ? 5 : 10;
  return step * power;
};

export const easeOutCubic = (value: number): number => {
  const clamped = Math.max(0, Math.min(1, value));
  return 1 - Math.pow(1 - clamped, 3);
};
