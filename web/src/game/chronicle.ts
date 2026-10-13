import type { ChatMessage } from "../lib/types";

export interface ChronicleEntry {
  message: ChatMessage;
  divider: boolean;
}

interface ChronicleOptions {
  onlyStory?: boolean;
  hideOoc?: boolean;
}

const STORY_KINDS = new Set(["narration", "action", "speech"]);

function participates(message: ChatMessage): boolean {
  return STORY_KINDS.has(message.kind) && message.scope !== "private" && !message.whisper;
}

function episodeKey(message: ChatMessage): string | null {
  if (!participates(message) || !message.scene_context?.location_id) return null;
  return `${message.scene_context.location_id}:${message.scope ?? "public"}`;
}

export function chronicleEntries(messages: ChatMessage[], options: ChronicleOptions = {}): ChronicleEntry[] {
  const { onlyStory = false, hideOoc = false } = options;
  let previousKey: string | null = null;
  return messages
    .filter((message) => (onlyStory ? message.kind === "narration" && !message.whisper : !(hideOoc && message.kind === "ooc")))
    .map((message) => {
      const key = episodeKey(message);
      const divider = key !== null && previousKey !== null && key !== previousKey;
      if (key !== null) previousKey = key;
      return { message, divider };
    });
}
