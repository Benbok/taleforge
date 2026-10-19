import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";
import { useAuthedImage } from "../lib/authedImage";
import { TTS_VOICES, type VoiceStudioProfile } from "../lib/campaign";

interface IntroVoice {
  id: string;
  duration?: number | null;
}

interface IntroSaved {
  text: string;
  provider: string | null;
  voice: string | null;
  voices: IntroVoice[];
  saved_at?: string;
}

interface IntroDraft extends IntroSaved {
  hook_id: string | null;
  status: "working" | "ready" | "failed";
  error: string | null;
}

export interface IntroState {
  published: boolean;
  hooks: { id: string; title: string }[];
  saved: Record<string, IntroSaved>;
  draft: IntroDraft | null;
}

const PROVIDERS = [
  { value: "gemini", label: "Gemini" },
  { value: "voicestudio", label: "Voice Studio" },
];

function voiceName(
  provider: string | null,
  voice: string | null,
  vs: VoiceStudioProfile[],
): string {
  if (!voice) return provider === "voicestudio" ? "Voice Studio" : "Gemini";
  const name =
    provider === "voicestudio" ? vs.find((p) => p.id === voice)?.name : voice;
  return `${provider === "voicestudio" ? "Voice Studio" : "Gemini"} · ${name ?? voice}`;
}

/** Запись вступления: файл берётся с токеном, как картинка карты. */
function Part({
  moduleId,
  v,
  n,
}: {
  moduleId: string;
  v: IntroVoice;
  n: number;
}) {
  const src = useAuthedImage(
    `/api/admin/modules/${moduleId}/intro/voice/${v.id}`,
  );
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0 font-mono text-xs text-muted">
        Часть {n}
      </span>
      {src ? (
        <audio
          controls
          preload="none"
          src={src}
          className="h-8 w-full max-w-md"
        />
      ) : (
        <span className="text-xs text-muted">Загружаю запись…</span>
      )}
    </div>
  );
}

function Voices({
  moduleId,
  voices,
}: {
  moduleId: string;
  voices: IntroVoice[];
}) {
  if (!voices.length) return <p className="text-xs text-warn">Без озвучки.</p>;
  return (
    <div className="flex flex-col gap-1">
      {voices.map((v, i) => (
        <Part key={v.id} moduleId={moduleId} v={v} n={i + 1} />
      ))}
    </div>
  );
}

/** Вступление приключения: одно на все кампании по нему. Черновик читается и слушается здесь, а новые
 *  кампании берут только сохранённое. */
export default function ModuleIntro({ moduleId }: { moduleId: string }) {
  const qc = useQueryClient();
  const key = ["module-intro", moduleId];
  const q = useQuery({
    queryKey: key,
    queryFn: () => api<IntroState>(`/api/admin/modules/${moduleId}/intro`),
    refetchInterval: (s) =>
      s.state.data?.draft?.status === "working" ? 3000 : false,
  });
  const { data: vs = [] } = useQuery<VoiceStudioProfile[]>({
    queryKey: ["vsProfiles"],
    queryFn: () => api<VoiceStudioProfile[]>("/api/voice/vs-profiles"),
  });
  const st = q.data;
  const [hook, setHook] = useState<string>("");
  const [provider, setProvider] = useState("gemini");
  const [voice, setVoice] = useState<string>("");
  const [text, setText] = useState<string | null>(null);
  const draft = st?.draft ?? null;

  useEffect(() => {
    if (!hook && st?.hooks.length) setHook(draft?.hook_id || st.hooks[0].id);
  }, [st, hook, draft?.hook_id]);
  useEffect(() => setText(null), [draft?.text, draft?.status]);

  if (q.isError)
    return (
      <p className="text-sm text-bad">
        Вступление не открылось: {(q.error as Error).message}
      </p>
    );
  if (!st) return <p className="text-sm text-muted">Загружаю вступление…</p>;

  const hookId = hook || st.hooks[0]?.id || "-";
  const saved = st.saved[hookId];
  const options =
    provider === "voicestudio"
      ? vs.map((p) => ({ value: p.id, label: p.name }))
      : TTS_VOICES.map((v) => ({
          value: v.id,
          label: `${v.name} — ${v.description}`,
        }));
  const working = draft?.status === "working";
  const edited = text !== null && draft !== null && text.trim() !== draft.text;

  async function set(next: IntroState) {
    qc.setQueryData(key, next);
  }
  function body(own?: string) {
    return {
      hook_id: hookId === "-" ? null : hookId,
      provider,
      voice: voice || null,
      ...(own ? { text: own } : {}),
    };
  }

  return (
    <div className="flex flex-col gap-3 rounded-[8px] border border-line p-3">
      <div>
        <h4 className="font-heading text-sm font-bold text-ink">
          Вступление приключения
        </h4>
        <p className="text-xs text-muted">
          Одно на все кампании по этому приключению. Создайте его, прочитайте и
          послушайте, при желании пересоздайте или поправьте текст, затем
          сохраните. Новые кампании берут только сохранённое; приветствие
          мастера и знакомство героев пишутся в каждой игре свои.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        {st.hooks.length > 1 && (
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Зацепка книги</span>
            <select
              className="field h-8 py-0 text-xs"
              value={hookId}
              onChange={(e) => setHook(e.target.value)}
            >
              {st.hooks.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.title}
                  {st.saved[h.id] ? " ✓" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Источник озвучки</span>
          <select
            className="field h-8 py-0 text-xs"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setVoice("");
            }}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Голос</span>
          <select
            className="field h-8 py-0 text-xs"
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
          >
            <option value="">По умолчанию</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-muted">
        Кампании с тем же голосом получают готовые записи; с другим голосом
        текст озвучивается заново при старте.
      </p>

      <div>
        <ActionButton
          primary={!draft && !saved}
          confirm={
            draft?.status === "ready"
              ? "Заменить несохранённый черновик новым?"
              : undefined
          }
          run={async () =>
            set(
              await api<IntroState>(
                `/api/admin/modules/${moduleId}/intro/draft`,
                { body: body() },
              ),
            )
          }
          done="Пишу и озвучиваю вступление"
        >
          {saved || draft ? "ПЕРЕСОЗДАТЬ ВСТУПЛЕНИЕ" : "СОЗДАТЬ ВСТУПЛЕНИЕ"}
        </ActionButton>
      </div>

      {draft && (
        <div className="flex flex-col gap-2 rounded-[8px] border border-accent/40 bg-accent/5 p-3">
          <h5 className="font-heading text-sm font-semibold text-ink">
            Черновик ·{" "}
            {st.hooks.find((h) => h.id === draft.hook_id)?.title ??
              "без зацепки"}{" "}
            · {voiceName(draft.provider, draft.voice, vs)}
          </h5>
          {working && (
            <p className="text-sm text-muted" role="status">
              Пишу текст и озвучиваю его… Блок обновится сам.
            </p>
          )}
          {draft.status === "failed" && (
            <p role="alert" className="text-sm text-bad">
              Не получилось: {draft.error}
            </p>
          )}
          {draft.status === "ready" && (
            <>
              <textarea
                className="field min-h-40 font-narration text-sm leading-relaxed"
                value={text ?? draft.text}
                maxLength={8000}
                onChange={(e) => setText(e.target.value)}
                aria-label="Текст вступления"
              />
              {edited ? (
                <p className="text-xs text-warn">
                  Текст изменён: озвучьте его, чтобы сохранить с новым голосом.
                </p>
              ) : (
                <Voices moduleId={moduleId} voices={draft.voices} />
              )}
              {draft.error && (
                <p className="text-xs text-warn">{draft.error}</p>
              )}
            </>
          )}
          {!working && (
            <div className="flex flex-wrap gap-3">
              {draft.status === "ready" && !edited && (
                <ActionButton
                  primary
                  confirm={
                    saved ? "Заменить сохранённое вступление этим?" : undefined
                  }
                  run={async () =>
                    set(
                      await api<IntroState>(
                        `/api/admin/modules/${moduleId}/intro/save`,
                        { method: "POST" },
                      ),
                    )
                  }
                  done="Вступление сохранено: новые кампании возьмут его"
                >
                  СОХРАНИТЬ
                </ActionButton>
              )}
              {edited && (
                <ActionButton
                  primary
                  run={async () =>
                    set(
                      await api<IntroState>(
                        `/api/admin/modules/${moduleId}/intro/draft`,
                        {
                          body: {
                            ...body(text!.trim()),
                            hook_id:
                              draft.hook_id === "-" ? null : draft.hook_id,
                          },
                        },
                      ),
                    )
                  }
                  done="Озвучиваю ваш текст"
                >
                  ОЗВУЧИТЬ МОЙ ТЕКСТ
                </ActionButton>
              )}
              <ActionButton
                danger
                confirm="Удалить черновик вступления?"
                run={async () =>
                  set(
                    await api<IntroState>(
                      `/api/admin/modules/${moduleId}/intro/draft`,
                      { method: "DELETE" },
                    ),
                  )
                }
                done="Черновик удалён"
              >
                УДАЛИТЬ ЧЕРНОВИК
              </ActionButton>
            </div>
          )}
        </div>
      )}

      {saved ? (
        <div className="flex flex-col gap-2">
          <h5 className="font-heading text-sm font-semibold text-ink">
            Сохранено · {voiceName(saved.provider, saved.voice, vs)}
          </h5>
          <p className="whitespace-pre-line font-narration text-sm leading-relaxed text-ink-2">
            {saved.text}
          </p>
          <Voices moduleId={moduleId} voices={saved.voices} />
        </div>
      ) : (
        <p className="text-xs text-muted">
          Для этой зацепки вступление не сохранено: каждая новая кампания пишет
          своё сама.
        </p>
      )}
    </div>
  );
}
