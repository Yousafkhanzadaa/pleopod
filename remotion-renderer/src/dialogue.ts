import type {PodcastVideoProps} from './types';

export type DialogueLine = {
  speaker: string;
  text: string;
};

const ttsPreamblePattern =
  /^\s*TTS\s+the\s+following\s+conversation\s+between\s+[^:\n]+:\s*/i;

export const parseDialogue = (transcript: string): DialogueLine[] => {
  const cleaned = transcript.replace(ttsPreamblePattern, '').trim();
  const lines = cleaned
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  return lines
    .map((line) => {
      const match = line.match(/^([^:]{1,48}):\s*(.+)$/);
      if (!match) {
        return null;
      }
      return {
        speaker: match[1].trim(),
        text: match[2].trim(),
      };
    })
    .filter((line): line is DialogueLine => Boolean(line));
};

export const currentDialogueLine = (
  props: PodcastVideoProps,
  currentSecond: number,
): DialogueLine | null => {
  const dialogue = parseDialogue(props.transcript);
  if (dialogue.length === 0) {
    return null;
  }

  const progress = Math.min(0.999, Math.max(0, currentSecond / props.durationSeconds));
  return dialogue[Math.floor(progress * dialogue.length)] ?? dialogue[0];
};

export const activeChapterTitle = (
  props: PodcastVideoProps,
  currentSecond: number,
): string | null => {
  if (props.chapters.length === 0) {
    return null;
  }

  const active = [...props.chapters]
    .sort((a, b) => a.startSeconds - b.startSeconds)
    .filter((chapter) => chapter.startSeconds <= currentSecond)
    .at(-1);

  return active?.title ?? props.chapters[0]?.title ?? null;
};
