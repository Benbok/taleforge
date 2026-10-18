import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { IntroOut } from "../lib/api.gen";
import { useAuthedImage } from "../lib/authedImage";
import { authoring, newRequestKey } from "../lib/authoring";
import { TTS_VOICES, type VoiceStudioProfile } from "../lib/campaign";

type Provider = "voicestudio" | "gemini" | "none";

const SOURCES: { id: Provider; label: string; note: string }[] = [
  { id: "voicestudio", label: "Локально — Voice Studio", note: "бесплатно, голос с вашей видеокарты" },
  { id: "gemini", label: "Облако — Gemini", note: "платно, оплачивается по длине текста" },
  { id: "none", label: "Без озвучки", note: "только текст" },
];

function Part({ projectId, id, n }: { projectId: string; id: string; n: number }) {
  const src = useAuthedImage(`/api/author/projects/${projectId}/intro/voice/${id}`);
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-xs text-muted">Часть {n}</span>
      {src ? <audio controls preload="none" src={src} className="h-9 w-full max-w-md" /> : <span className="text-xs text-muted">Загружаю запись…</span>}
    </div>
  );
}

interface Props {
  projectId: string;
  revision: number;
  running: boolean;
  status: string;
  errorCode: string | null;
  onQueued(message: string): void;
}

/** Вступление приключения: текст пишет модель мастера один раз, озвучивает выбранный источник — игры берут готовое. */
export default function IntroStep({ projectId, revision, running, status, errorCode, onQueued }: Props) {
  const client = useQueryClient();
  const key = ["author", projectId, "intro"];
  const intro = useQuery({ queryKey: key, queryFn: () => api<IntroOut>(`/api/author/projects/${projectId}/intro`) });
  const profiles = useQuery({ queryKey: ["vsProfiles"], queryFn: () => api<VoiceStudioProfile[]>("/api/voice/vs-profiles") });
  const [provider, setProvider] = useState<Provider>("voicestudio");
  const [voice, setVoice] = useState("");
  const [text, setText] = useState<string | null>(null);
  const data = intro.data;
  const available = (p: Provider) => p === "none" || !!data?.providers?.[p];

  useEffect(() => {
    // по умолчанию — бесплатный локальный голос, если он подключён
    if (data && !available(provider)) setProvider(available("voicestudio") ? "voicestudio" : available("gemini") ? "gemini" : "none");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  useEffect(() => {
    if (!running) void client.invalidateQueries({ queryKey: key });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const prepare = useMutation({
    mutationFn: (mode: { rewrite: boolean; voiced: boolean }) =>
      authoring.prepareIntro(projectId, {
        provider,
        voice: voice || null,
        rewrite: mode.rewrite,
        voiced: mode.voiced,
        expected_revision: revision,
        request_key: newRequestKey(),
      }),
    onSuccess: () => {
      onQueued("Вступление готовится.");
      void client.invalidateQueries({ queryKey: ["author", projectId] });
    },
    onError: (e) => onQueued(e instanceof ApiError ? e.message : "не удалось запустить"),
  });
  const save = useMutation({
    mutationFn: (value: string) => authoring.setIntroText(projectId, { text: value, expected_revision: revision }),
    onSuccess: (next) => {
      client.setQueryData(key, next);
      setText(null);
      onQueued("Текст сохранён. Старая запись удалена — озвучьте вступление заново.");
      void client.invalidateQueries({ queryKey: ["author", projectId, "project"] });
    },
    onError: (e) => onQueued(e instanceof ApiError ? e.message : "не удалось сохранить"),
  });

  const voices =
    provider === "voicestudio"
      ? (profiles.data ?? []).map((p) => ({ value: p.id, label: p.name }))
      : provider === "gemini"
        ? TTS_VOICES.map((v) => ({ value: v.id, label: `${v.name} — ${v.description}` }))
        : [];
  const hasText = !!data?.text;
  const busy = prepare.isPending || save.isPending || running;

  return (
    <div className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3">
        <legend className="font-heading text-base text-ink">Кто озвучит вступление</legend>
        {SOURCES.map((s) => (
          <label key={s.id} className={`flex min-h-11 items-center gap-3 rounded-lg px-2 ${available(s.id) ? "cursor-pointer" : "opacity-50"}`}>
            <input type="radio" name="intro-source" value={s.id} checked={provider === s.id} disabled={!available(s.id)} onChange={() => { setProvider(s.id); setVoice(""); }} />
            <span className="flex flex-col">
              <span className="text-sm text-ink">{s.label}</span>
              <span className="text-xs text-muted">{available(s.id) ? s.note : "не подключено на этом сервере"}</span>
            </span>
          </label>
        ))}
        {voices.length > 0 && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Голос</span>
            <select className="min-h-11 rounded-lg border border-line bg-raised px-2" value={voice} onChange={(e) => setVoice(e.target.value)}>
              <option value="">По умолчанию</option>
              {voices.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
            </select>
          </label>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {hasText ? (
            <>
              <button
                className="btn btn-primary min-h-11 px-4 text-sm"
                type="button"
                disabled={busy || provider === "none"}
                onClick={() => prepare.mutate({ rewrite: false, voiced: true })}
                title="Тот же текст, новая запись выбранным голосом; модель не вызывается"
              >
                {running ? "Готовлю…" : "Переозвучить"}
              </button>
              <button
                className="btn min-h-11 px-4 text-sm"
                type="button"
                disabled={busy}
                onClick={() => {
                  if (window.confirm("Модель напишет новый текст; текущая запись к нему не подойдёт и будет удалена. Продолжить?")) {
                    prepare.mutate({ rewrite: true, voiced: false });
                  }
                }}
              >
                Переписать только текст
              </button>
              <button className="btn min-h-11 px-4 text-sm" type="button" disabled={busy || provider === "none"} onClick={() => prepare.mutate({ rewrite: true, voiced: true })}>
                Переписать и озвучить
              </button>
            </>
          ) : (
            <button className="btn btn-primary min-h-11 px-4 text-sm" type="button" disabled={busy} onClick={() => prepare.mutate({ rewrite: true, voiced: provider !== "none" })}>
              {running ? "Готовлю вступление…" : provider === "none" ? "Написать текст" : "Написать и озвучить"}
            </button>
          )}
        </div>
        {hasText && (
          <p className="text-xs text-muted">«Переозвучить» не вызывает модель: меняется только запись. «Переписать только текст» — новый текст без записи; озвучить его можно следом.</p>
        )}
        <p className="text-xs text-muted">Текст пишет модель мастера (доли цента). Записанное вступление переносится в каждую игру по этому приключению — игры не платят за него снова.</p>
      </fieldset>

      {status === "failed" && !running && (
        <p className="rounded-lg border border-bad/40 bg-ember-bg p-3 text-sm" role="alert">
          Вступление не получилось: {errorCode === "voice_unavailable" ? "выбранный источник голоса не подключён" : errorCode === "voice_failed" ? "озвучка не удалась — попробуйте ещё раз или другой источник" : errorCode ?? "ошибка"}.
        </p>
      )}

      <section aria-label="Текст вступления" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-3">
          <h3 className="font-heading text-base text-ink">Текст вступления</h3>
          {hasText && !data?.current && <span className="text-sm text-warn">написано для прежней версии сюжета — игры его не возьмут</span>}
        </div>
        {hasText || text !== null ? (
          <>
            <textarea
              aria-label="Текст вступления"
              className="min-h-56 rounded-lg border border-line bg-raised p-3 text-sm leading-relaxed"
              value={text ?? data?.text ?? ""}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="flex gap-2">
              <button className="btn min-h-11 px-3 text-sm" type="button" disabled={busy || text === null || !text.trim() || text === data?.text} onClick={() => text && save.mutate(text)}>Сохранить свой текст</button>
              {text !== null && <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => setText(null)}>Отменить</button>}
            </div>
          </>
        ) : (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-muted">Вступления пока нет. Его можно сгенерировать выше или написать самому.</p>
            <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => setText("")}>Написать вручную</button>
          </div>
        )}
      </section>

      {hasText && (
        <section aria-label="Запись вступления" className="flex flex-col gap-2">
          <h3 className="font-heading text-base text-ink">Запись</h3>
          {(data?.voices ?? []).length ? (
            <>
              <p className="text-xs text-muted">
                {data?.provider === "voicestudio" ? "Voice Studio" : data?.provider === "gemini" ? "Gemini" : "без озвучки"}
                {data?.voice ? ` · ${data.voice}` : ""} · частей {(data?.voices ?? []).length}
                {data?.parts && (data?.voices ?? []).length < data.parts ? ` из ${data.parts}: часть не озвучилась` : ""}
              </p>
              {(data?.voices ?? []).map((v, i) => <Part key={v.id} projectId={projectId} id={v.id} n={i + 1} />)}
            </>
          ) : (
            <p className="text-sm text-muted">Без записи: игра прочитает текст и озвучит его сама своим голосом.</p>
          )}
        </section>
      )}
    </div>
  );
}
