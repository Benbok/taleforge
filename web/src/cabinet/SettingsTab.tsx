import { useQuery } from "@tanstack/react-query";
import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import CustomSelect from "../components/CustomSelect";
import { Field, Segmented } from "../components/Form";
import BriefForm from "./BriefForm";
import { api } from "../lib/api";
import {
  cleanBrief,
  DIFFICULTY_RU,
  LEVELING_HINT,
  LEVELING_RU,
  splitThemes,
  TTS_VOICES,
  type Brief,
  type CampaignOptions,
  type Room,
} from "../lib/campaign";

const RANDOM_RU = { auto: "Мир живёт сам", manual: "Только по воле мастера" };
const RANDOM_HINT = {
  auto: "Пока идёт игровое время, сервер сам бросает встречи, события и находки по таблицам места. Исход бывает и плохим.",
  manual: "Случайности бывают, только когда мастер сам решает бросить.",
};

/** Настройки кампании (только владелец): название, вводная, темп игры, анкета, удаление. */
export default function SettingsTab({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  const navigate = useNavigate();
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const st = room.settings;
  const aiMaster = room.seats.some((s) => s.role === "master" && s.occupant_type === "agent");
  const ttsEnabled = (st.tts_enabled ?? true) !== false;
  const [f, setF] = useState({
    name: room.name,
    public_intro: room.public_intro,
    difficulty: room.difficulty,
    leveling: st.leveling ?? "xp",
    random_events: st.random_events ?? "auto",
    turn_timeout_sec: st.turn_timeout_sec ?? 300,
    collect_window_sec: st.collect_window_sec ?? 60,
    spend_limit_usd: st.spend_limit_usd == null ? "" : String(st.spend_limit_usd),
    excluded: (st.excluded_themes ?? []).join(", "),
  });
  const [brief, setBrief] = useState<Brief>(room.brief ?? {});
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));

  async function save() {
    if (!f.name.trim()) throw new Error("Название не может быть пустым");
    const limit = f.spend_limit_usd.trim() === "" ? null : Number(f.spend_limit_usd.replace(",", "."));
    if (limit != null && (!Number.isFinite(limit) || limit < 0)) {
      throw new Error("Лимит расходов — число в долларах, например 5");
    }
    onRoom(
      await api<Room>(`/api/campaigns/${room.id}`, {
        method: "PATCH",
        body: {
          name: f.name.trim(),
          public_intro: f.public_intro,
          difficulty: f.difficulty,
          leveling: f.leveling,
          random_events: f.random_events,
          turn_timeout_sec: f.turn_timeout_sec,
          collect_window_sec: f.collect_window_sec,
          spend_limit_usd: limit,
          excluded_themes: splitThemes(f.excluded),
          brief: cleanBrief(brief),
        },
      }),
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* General Settings */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-5">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Основные параметры стола</h2>
          <p className="text-xs text-muted">Видимые параметры, темп боевых раундов и лимиты расходов</p>
        </div>

        <Field label="Название кампании">
          <input
            className="field font-heading text-lg"
            maxLength={128}
            value={f.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>

        <Field label="Публичная вводная (афиша)" hint="Её видят игроки при входе по ссылке-приглашению и в лобби стола.">
          <textarea
            className="field min-h-24 text-sm"
            maxLength={10000}
            value={f.public_intro}
            onChange={(e) => set({ public_intro: e.target.value })}
          />
        </Field>

        <Field label="Сложность вызовов">
          <Segmented
            label="Сложность"
            value={f.difficulty}
            options={Object.entries(DIFFICULTY_RU)}
            onChange={(difficulty) => set({ difficulty })}
          />
        </Field>

        <Field label="Рост уровней" hint={LEVELING_HINT[f.leveling]}>
          <Segmented
            label="Рост уровней"
            value={f.leveling}
            options={Object.entries(LEVELING_RU)}
            onChange={(v) => set({ leveling: v as "xp" | "milestone" })}
          />
        </Field>

        <Field label="Случайности в пути" hint={RANDOM_HINT[f.random_events]}>
          <Segmented
            label="Случайности в пути"
            value={f.random_events}
            options={Object.entries(RANDOM_RU)}
            onChange={(v) => set({ random_events: v as "auto" | "manual" })}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Время на ход в бою (сек)" hint="От 30 до 300 секунд.">
            <input
              className="field font-mono text-sm"
              type="number"
              min={30}
              max={300}
              value={f.turn_timeout_sec}
              onChange={(e) => set({ turn_timeout_sec: Number(e.target.value) })}
            />
          </Field>

          <Field label="Окно сбора реплик (сек)" hint="Пауза перед ответом мастера, 0 — мгновенно.">
            <input
              className="field font-mono text-sm"
              type="number"
              min={0}
              max={300}
              value={f.collect_window_sec}
              onChange={(e) => set({ collect_window_sec: Number(e.target.value) })}
            />
          </Field>

          <Field label="Лимит расходов ($ USD)" hint="Пусто — без ограничения.">
            <input
              className="field font-mono text-sm"
              inputMode="decimal"
              placeholder="например: 10"
              value={f.spend_limit_usd}
              onChange={(e) => set({ spend_limit_usd: e.target.value })}
            />
          </Field>
        </div>

        <Field label="Запретные темы" hint="Укажите через запятую: мастер гарантированно не коснётся этих тем.">
          <input
            className="field text-sm"
            value={f.excluded}
            onChange={(e) => set({ excluded: e.target.value })}
          />
        </Field>
      </section>

      {/* Sound */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-3" aria-label="Звук">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Звуковое сопровождение</h2>
          <p className="text-xs text-muted">
            ИИ-мастер сам включает мелодию, ритм и атмосферу из библиотеки «Звук» по ходу сцен. Дорожки загружает
            Admin. Выключено — мастер не тратит на звук ни одного токена.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className={`font-mono text-xs ${st.audio_enabled ? "text-patina-hi" : "text-muted"}`}>
            {st.audio_enabled ? "● включено" : "○ выключено"}
          </span>
          <ActionButton
            className="btn-outline-copper"
            done={st.audio_enabled ? "Звук выключен: у игроков он смолкнет сразу" : "Звук включён: мастер начнёт вести его со следующего хода"}
            run={async () =>
              onRoom(
                await api<Room>(`/api/campaigns/${room.id}`, {
                  method: "PATCH",
                  body: { audio_enabled: !st.audio_enabled },
                }),
              )
            }
          >
            {st.audio_enabled ? "Выключить звук" : "Включить звук"}
          </ActionButton>
        </div>
      </section>

      {/* Master Voice */}
      {aiMaster && (
        <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-3" aria-label="Озвучка мастера">
          <div className="border-b border-line pb-3">
            <h2 className="font-heading text-xl font-bold text-ink">Озвучка мастера</h2>
            <p className="text-xs text-muted">
              Синтез речи (Gemini TTS) для реплик и описаний ИИ-мастера. Выключено — мастер отвечает только
              текстом, без генерации аудиодорожек.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className={`font-mono text-xs ${ttsEnabled ? "text-patina-hi" : "text-muted"}`}>
              {ttsEnabled ? "● включено" : "○ выключено"}
            </span>
            <ActionButton
              className="btn-outline-copper"
              done={ttsEnabled ? "Озвучка мастера выключена" : "Озвучка мастера включена: реплики мастера будут озвучиваться"}
              run={async () =>
                onRoom(
                  await api<Room>(`/api/campaigns/${room.id}`, {
                    method: "PATCH",
                    body: { tts_enabled: !ttsEnabled },
                  }),
                )
              }
            >
              {ttsEnabled ? "Выключить озвучку" : "Включить озвучку"}
            </ActionButton>
          </div>

          {ttsEnabled && (
            <>
              <div className="pt-2 border-t border-line/60 flex flex-col gap-2">
                <Field
                  label="Источник озвучки (TTS Provider)"
                  hint="Выберите сервис для синтеза речи (облачный Gemini или локальный XTTS / Silero)."
                >
                  <CustomSelect
                    value={st.tts_provider || "gemini"}
                    options={[
                      { value: "gemini", label: "Gemini TTS (Cloud)" },
                      { value: "xtts", label: "XTTS v2 (Local)" },
                      { value: "silero", label: "Silero TTS (Local)" },
                    ]}
                    onChange={async (val) => {
                      if (val === (st.tts_provider || "gemini")) return;
                      onRoom(
                        await api<Room>(`/api/campaigns/${room.id}`, {
                          method: "PATCH",
                          body: { tts_provider: val },
                        }),
                      );
                    }}
                    ariaLabel="Источник озвучки"
                  />
                </Field>
              </div>

              <div className="pt-2 border-t border-line/60 flex flex-col gap-2">
                <Field
                  label="Голос ИИ-мастера (Gemini)"
                  hint="Голос, которым озвучиваются описания сцен и реплики мастера в чате."
                >
                  <CustomSelect
                    value={st.tts_voice || "Fenrir"}
                    options={TTS_VOICES.map((v) => ({
                      value: v.id,
                      label: v.name,
                      sublabel: `${v.gender} · ${v.description}`,
                      badge: v.id === "Fenrir" ? "ПО УМОЛЧАНИЮ" : v.gender.toUpperCase(),
                      badgeTone: v.id === "Fenrir" ? ("accent" as const) : ("patina" as const),
                    }))}
                    onChange={async (val) => {
                      if (val === (st.tts_voice || "Fenrir")) return;
                      onRoom(
                        await api<Room>(`/api/campaigns/${room.id}`, {
                          method: "PATCH",
                          body: { tts_voice: val },
                        }),
                      );
                    }}
                    ariaLabel="Голос мастера"
                  />
                </Field>
                  <TtsTestButton provider={st.tts_provider || "gemini"} voice={st.tts_voice || "Fenrir"} />
              </div>
            </>
          )}
        </section>
      )}

      {/* Brief Form */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Анкета приключения и ожидания игроков</h2>
          <p className="text-xs text-muted">
            Настройки влияют на последующие редакции сюжета и фокус повествования мастера
          </p>
        </div>

        {opts.data ? (
          <BriefForm brief={brief} opts={opts.data.brief} onChange={setBrief} />
        ) : (
          <p className="text-muted font-mono text-xs">Загрузка опций анкеты…</p>
        )}
      </section>

      {/* Save Button */}
      <div>
        <ActionButton
          primary
          className="font-mono text-xs tracking-wider"
          run={save}
          done="Настройки стола успешно сохранены"
        >
          СОХРАНИТЬ НАСТРОЙКИ СТОЛА
        </ActionButton>
      </div>

      {/* Danger Zone */}
      <section className="card p-5 sm:p-6 border border-bad/50 bg-bad/5 flex flex-col items-start gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold text-bad">Опасная зона · Удаление кампании</h2>
          <p className="mt-1 text-xs sm:text-sm text-muted">
            Безвозвратно удаляет журнал чата, сюжетную арку и прогресс за столом.
            Персонажи игроков в их профилях сохранятся.
          </p>
        </div>

        <ActionButton
          danger
          className="font-mono text-xs"
          confirm={`Вы уверены, что хотите удалить кампанию «${room.name}» безвозвратно?`}
          run={async () => {
            await api(`/api/campaigns/${room.id}`, { method: "DELETE" });
            navigate("/", { replace: true });
          }}
          done="Кампания удалена"
        >
          УДАЛИТЬ КАМПАНИЮ НАВСЕГДА
        </ActionButton>
      </section>
    </div>
  );
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
      const { getToken } = await import('../lib/api');
      const res = await fetch(`/api/voice/tts-test?provider=${provider}&voice=${voice}`, {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Ошибка сети');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setPlaying(false);
      audio.onerror = () => {
        setPlaying(false);
        setError('Не удалось воспроизвести аудио');
      };
      audio.onpause = () => setPlaying(false);
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPlaying(false);
    }
  };

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
      }
    };
  }, []);

  return (
    <div className="mt-4 flex flex-col gap-2">
      <button
        type="button"
        onClick={testAudio}
        className="flex items-center justify-center gap-2 rounded border border-line bg-surface text-ink px-4 py-2 text-sm font-semibold shadow-sm hover:bg-line/20 transition-colors w-max"
      >
        {playing ? "⏹ Остановить проверку" : "▶ Проверить озвучку"}
      </button>
      {error && <p className="text-warn text-xs">{error}</p>}
    </div>
  );
}
