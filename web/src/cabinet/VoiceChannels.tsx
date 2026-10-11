import { useEffect, useRef, useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { TTS_VOICES, type Room, type VoiceStudioProfile } from "../lib/campaign";

export type ChannelKind = "line" | "text" | "intro";
const KINDS: ChannelKind[] = ["line", "text", "intro"];
type Settings = Room["settings"];

const PROVIDERS: SelectOption[] = [
  { value: "gemini", label: "Gemini TTS (облако)" },
  { value: "voicestudio", label: "Voice Studio (локально)" },
];
const ABOUT: Record<ChannelKind, { title: string; hint: string }> = {
  line: { title: "Реплики мастера", hint: "Короткая реакция мастера на ход. Звучит первой, пока игроки читают текст." },
  text: { title: "Текст мастера", hint: "Весь ответ хода. Озвучивается в фоне после реплики, текст показывается сразу." },
  intro: {
    title: "Вступление и знакомство героев",
    hint: "Подготовка к игре: вступление кампании, знакомство героев, приветствие. Всегда облако Gemini.",
  },
};

/** Канал как его читает сервер (app/agents/voicing.py). У кампании до раздельных каналов — общие tts_provider и
 * tts_voice, реплики включены, текст выключен; её tts_enabled = false глушит все каналы. */
export function channelOf(st: Settings | undefined, kind: ChannelKind) {
  const s = (st ?? {}) as Record<string, unknown>;
  const key = `tts_${kind}_`;
  const on = s.tts_enabled !== false && ((s[`${key}enabled`] as boolean | undefined) ?? kind !== "text");
  if (kind === "intro") return { enabled: on, provider: "gemini", voice: (s.tts_intro_voice as string | null) ?? null };
  const own = `${key}provider` in s;
  return {
    enabled: on,
    provider: ((own ? s[`${key}provider`] : s.tts_provider) as string | null) || "gemini",
    voice: ((own ? s[`${key}voice`] : s.tts_voice) as string | null) ?? null,
  };
}

/** Тело PATCH для включения или выключения канала. Старый общий выключатель снимается при включении любого канала,
 * остальные каналы при этом остаются выключенными, как их и видел владелец. */
export function toggleBody(st: Settings | undefined, kind: ChannelKind): Record<string, unknown> {
  const ch = channelOf(st, kind);
  const body: Record<string, unknown> = { [`tts_${kind}_enabled`]: !ch.enabled };
  if (kind !== "intro") Object.assign(body, { [`tts_${kind}_provider`]: ch.provider, [`tts_${kind}_voice`]: ch.voice });
  if (!ch.enabled && (st as Record<string, unknown> | undefined)?.tts_enabled === false) {
    body.tts_enabled = true;
    for (const other of KINDS) if (other !== kind) body[`tts_${other}_enabled`] = false;
  }
  return body;
}

function geminiVoices(): SelectOption[] {
  return TTS_VOICES.map((v) => ({
    value: v.id,
    label: v.name,
    sublabel: `${v.gender} - ${v.description}`,
    badge: v.id === "Fenrir" ? "ПО УМОЛЧАНИЮ" : v.gender.toUpperCase(),
    badgeTone: v.id === "Fenrir" ? ("accent" as const) : ("patina" as const),
  }));
}

function studioVoices(profiles: VoiceStudioProfile[]): SelectOption[] {
  if (!profiles.length) {
    return [
      {
        value: "demo0001",
        label: "Демо-голос (demo0001)",
        sublabel: "Voice Studio не подключен или нет сохраненных профилей",
        badge: "НЕДОСТУПЕН",
        badgeTone: "muted" as const,
      },
    ];
  }
  const order = (p: VoiceStudioProfile) => (p.is_demo ? 3 : p.kind === "clone" ? 1 : p.kind === "design" ? 2 : 4);
  return [...profiles]
    .sort((a, b) => order(a) - order(b) || a.name.localeCompare(b.name, "ru"))
    .map((p) => {
      const [badge, badgeTone] = p.is_demo
        ? (["ДЕМО", "muted"] as const)
        : p.kind === "design"
          ? (["ДИЗАЙН", "accent"] as const)
          : p.kind === "clone"
            ? (["КЛОН", "patina"] as const)
            : (["VOICESTUDIO", "muted"] as const);
      let sublabel: string;
      if (p.kind === "design") {
        const lang = p.language && p.language !== "Auto" ? `${p.language} · ` : "";
        sublabel = p.instruct ? `${lang}${p.instruct}` : p.language ? `Дизайн · ${p.language}` : "Голосовой дизайн";
      } else if (p.kind === "clone") {
        const sample = p.ref_text && (p.ref_text.length > 55 ? `${p.ref_text.slice(0, 55).trim()}…` : p.ref_text);
        sublabel = p.description || (sample ? `«${sample}»` : p.language ? `Клон · ${p.language}` : "Голосовой клон");
      } else {
        sublabel = p.description || p.language || "Voice Studio";
      }
      return { value: p.id, label: p.name, sublabel, badge, badgeTone };
    });
}

/** Карточка канала озвучки: включение, источник и голос. Сохраняется сразу, действует со следующего хода. */
export function VoiceChannel({
  kind,
  campaignId,
  room,
  onRoom,
  profiles,
}: {
  kind: ChannelKind;
  campaignId: string;
  room?: Room;
  onRoom?: (r: Room) => void;
  profiles: VoiceStudioProfile[];
}) {
  const ch = channelOf(room?.settings, kind);
  const key = `tts_${kind}_`;
  const save = async (body: Record<string, unknown>) => {
    const updated = await api<Room>(`/api/campaigns/${campaignId}`, { method: "PATCH", body });
    onRoom?.(updated);
  };
  const options = ch.provider === "voicestudio" ? studioVoices(profiles) : geminiVoices();
  const voice = options.some((o) => o.value === ch.voice) ? ch.voice! : options[0]?.value ?? "";

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line/60 p-3" aria-label={ABOUT[kind].title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-heading text-base font-semibold text-ink">{ABOUT[kind].title}</h3>
          <p className="text-xs text-muted">{ABOUT[kind].hint}</p>
        </div>
        <ActionButton
          className="btn-outline-copper"
          done={ch.enabled ? `${ABOUT[kind].title}: озвучка выключена` : `${ABOUT[kind].title}: озвучка включена`}
          run={() => save(toggleBody(room?.settings, kind))}
        >
          {ch.enabled ? "Выключить" : "Включить"}
        </ActionButton>
      </div>
      {ch.enabled && (
        <>
          <Field label="Источник">
            {kind === "intro" ? (
              <p className="text-sm text-ink-2">Gemini TTS (облако)</p>
            ) : (
            <CustomSelect
              value={ch.provider}
              options={PROVIDERS}
              onChange={async (val) => {
                if (val === ch.provider) return;
                // голос другого источника не подходит: берём первый голос нового
                const next = val === "voicestudio" ? studioVoices(profiles)[0]?.value ?? "demo0001" : "Fenrir";
                await save({ [`${key}provider`]: val, [`${key}voice`]: next });
              }}
              ariaLabel={`Источник: ${ABOUT[kind].title}`}
            />
            )}
          </Field>
          <Field label="Голос">
            <CustomSelect
              value={voice}
              options={options}
              onChange={async (val) => {
                if (val === ch.voice) return;
                await save(kind === "intro" ? { tts_intro_voice: val } : { [`${key}provider`]: ch.provider, [`${key}voice`]: val });
              }}
              ariaLabel={`Голос: ${ABOUT[kind].title}`}
            />
          </Field>
          <TtsTestButton provider={ch.provider} voice={voice} />
        </>
      )}
    </div>
  );
}

/** Каналы звучат разными голосами — мастер в одном ответе заговорит двумя голосами. */
export function differentVoices(st: Settings | undefined): boolean {
  const line = channelOf(st, "line");
  const text = channelOf(st, "text");
  // голос не выбран — у Gemini это Fenrir, тот же голос, что выбранный явно
  const same = (v: string | null, provider: string) => v ?? (provider === "gemini" ? "Fenrir" : "");
  return line.enabled && text.enabled && (line.provider !== text.provider || same(line.voice, line.provider) !== same(text.voice, text.provider));
}

function TtsTestButton({ provider, voice }: { provider: string; voice: string }) {
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const testAudio = async () => {
    if (playing && audioRef.current) {
      audioRef.current.pause();
      return;
    }
    setPlaying(true);
    setError(null);
    try {
      const { getToken } = await import("../lib/api");
      const res = await fetch(`/api/voice/tts-test?provider=${provider}&voice=${voice}`, {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Ошибка сети");
      }
      const audio = new Audio(URL.createObjectURL(await res.blob()));
      audioRef.current = audio;
      audio.onended = () => setPlaying(false);
      audio.onerror = () => {
        setPlaying(false);
        setError("Не удалось воспроизвести аудио");
      };
      audio.onpause = () => setPlaying(false);
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPlaying(false);
    }
  };

  useEffect(() => () => audioRef.current?.pause(), []);

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={testAudio}
        className="flex w-max items-center justify-center gap-2 rounded border border-line bg-surface px-4 py-2 text-sm font-semibold text-ink shadow-sm transition-colors hover:bg-line/20"
      >
        {playing ? "⏹ Остановить проверку" : "▶ Проверить голос"}
      </button>
      {error && <p className="text-xs text-warn">{error}</p>}
    </div>
  );
}
