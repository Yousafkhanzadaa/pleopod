// Real typography is the single biggest lever between "cheap" and "premium".
// Space Grotesk gives headlines character, Inter carries body copy cleanly, and
// IBM Plex Mono on numbers/labels reads as considered, technical data design.
// Loaded via @remotion/google-fonts so the render waits for fonts (delayRender).

import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadIBMPlexMono} from '@remotion/google-fonts/IBMPlexMono';
import {loadFont as loadSpaceGrotesk} from '@remotion/google-fonts/SpaceGrotesk';

const inter = loadInter('normal', {
  weights: ['400', '500', '600', '700', '800'],
  subsets: ['latin'],
});
const grotesk = loadSpaceGrotesk('normal', {
  weights: ['500', '600', '700'],
  subsets: ['latin'],
});
const mono = loadIBMPlexMono('normal', {
  weights: ['400', '500', '600'],
  subsets: ['latin'],
});

export const DISPLAY_FONT = `${grotesk.fontFamily}, "Helvetica Neue", Arial, sans-serif`;
export const BODY_FONT = `${inter.fontFamily}, "Helvetica Neue", Arial, sans-serif`;
export const MONO_FONT = `${mono.fontFamily}, ui-monospace, "SF Mono", monospace`;
