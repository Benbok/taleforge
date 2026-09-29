import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect from "../components/CustomSelect";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { PROVIDER_RU, type ModelCheck, type ModelProfile, type Provider } from "../lib/campaign";

const DATE = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function CheckLine({ c }: { c: ModelCheck | null | undefined }) {
  if (!c?.at) {
    return <span className="font-mono text-xs text-muted">не проверялась</span>;
  }
  const when = DATE.format(new Date(c.at));
  if (c.ok) {
    return (
      <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
        <span className="inline-flex items-center gap-1 text-patina-hi font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-patina animate-pulse" />
          ✓ отвечает
        </span>
        <span className="text-muted">
          · {c.latency_ms ?? "?"} мс
          {c.reply ? ` · «${c.reply}»` : ""}
          <span className="text-faint"> · {when}</span>
        </span>
      </div>
    );
  }
  const err = c.error ?? "ошибка соединения";
  return (
    <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
      <span className="inline-flex items-center gap-1 text-bad font-medium">
        <span className="h-1.5 w-1.5 rounded-full bg-bad" />
        ✗ {err.replace(/ \(.*$/s, "")}
      </span>
      <span className="text-faint">· {when}</span>
      {err.includes(" (") && (
        <details className="w-full mt-1">
          <summary className="cursor-pointer text-muted hover:text-ink">подробности ошибки</summary>
          <pre className="mt-1 max-h-32 overflow-x-auto rounded bg-raised p-2 text-[11px] text-bad">
            {err}
          </pre>
        </details>
      )}
    </div>
  );
}

interface Form {
  id: string | null;
  name: string;
  provider: "claude" | "gemini" | "local";
  model: string;
  api_base: string;
  temperature: number;
  is_default: boolean;
}

/** Модели ИИ: какой моделью может вести мастер. Ключи провайдеров — только в окружении сервера. */
export default function ModelsSection({ superAdmin }: { superAdmin: boolean }) {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api<Provider[]>("/api/admin/providers") });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<ModelProfile[]>("/api/admin/models") });
  const [form, setForm] = useState<Form | null>(null);
  const [checked, setChecked] = useState<ModelCheck | null>(null);
  const [local, setLocal] = useState<string[]>([]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["models"] });
  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f));
  const info = providers.data?.find((p) => p.id === form?.provider);

  function open(m: ModelProfile | null) {
    setChecked(null);
    setLocal([]);
    setForm(
      m
        ? {
            id: m.id,
            name: m.name,
            provider: m.provider,
            model: m.model,
            api_base: m.api_base ?? "",
            temperature: m.temperature,
            is_default: m.is_default,
          }
        : {
            id: null,
            name: "",
            provider: "claude",
            model: "",
            api_base: "",
            temperature: 0.8,
            is_default: false,
          },
    );
  }

  const body = (f: Form) => ({
    name: f.name.trim(),
    provider: f.provider,
    model: f.model.trim(),
    api_base: f.provider === "local" ? f.api_base.trim() || null : null,
    temperature: f.temperature,
    ...(superAdmin ? { is_default: f.is_default } : {}),
  });

  return (
    <div className="flex flex-col gap-6" aria-label="Модели ИИ">
      {/* Intro info box */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
              Нейросетевые модели мастера
            </h2>
            <p className="mt-1 text-sm text-muted max-w-2xl">
              Модели, доступные для ведения кампаний в роли ИИ-мастера.
              Ключи провайдеров хранятся только в окружении сервера и не передаются в браузер.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline-copper self-start sm:self-center text-xs font-mono tracking-wider"
            onClick={() => open(null)}
          >
            + ДОБАВИТЬ МОДЕЛЬ
          </button>
        </div>
      </section>

      {/* Provider Status Row */}
      {providers.data && (
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {providers.data.map((p) => {
            const hasKey = p.key_set;
            const isLocal = p.key_set === null;
            return (
              <div
                key={p.id}
                className="card p-4 flex flex-col justify-between gap-2 border border-line bg-raised/40"
              >
                <div className="flex items-center justify-between">
                  <span className="font-heading text-base font-bold text-ink">{p.title}</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      isLocal ? "bg-muted" : hasKey ? "bg-patina" : "bg-bad"
                    }`}
                  />
                </div>

                <div className="font-mono text-xs">
                  {isLocal ? (
                    <span className="text-muted">Ключ не нужен · {p.api_base}</span>
                  ) : hasKey ? (
                    <span className="text-patina-hi">✓ Ключ окружения задан ({p.key_env})</span>
                  ) : (
                    <span className="text-bad">✗ Задайте {p.key_env} в env</span>
                  )}
                </div>

                {p.default_model && (
                  <div className="font-mono text-[11px] text-faint truncate" title={p.default_model}>
                    По умолч.: {p.default_model}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}

      {/* Models List */}
      <section className="flex flex-col gap-4">
        <div className="flex items-center justify-between px-1">
          <h3 className="font-heading text-lg font-semibold tracking-wide text-ink">
            Настроенные профили моделей
          </h3>
          <span className="font-mono text-xs text-muted">
            Всего: {models.data?.length ?? 0}
          </span>
        </div>

        {models.isError && (
          <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
            Не удалось загрузить модели: {(models.error as Error).message}
          </div>
        )}

        {models.isSuccess && models.data.length === 0 && (
          <div className="card p-6 text-center text-muted">
            <p className="text-sm">Моделей пока нет в системе.</p>
            <p className="mt-1 text-xs text-faint">
              Добавьте первую модель, чтобы запустить игру с ИИ-мастером.
            </p>
          </div>
        )}

        <div className="grid gap-4">
          {(models.data ?? []).map((m) => (
            <div
              key={m.id}
              className="card group relative overflow-hidden p-5 transition hover:border-accent/60"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-3">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="font-heading text-lg font-bold text-ink group-hover:text-accent transition">
                    {m.name}
                  </span>
                  {m.is_default && (
                    <span className="rounded-full border border-accent bg-accent/15 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-accent">
                      ★ ПО УМОЛЧАНИЮ
                    </span>
                  )}
                  <span className="rounded-[6px] border border-line bg-raised px-2 py-0.5 font-mono text-[11px] text-muted">
                    {PROVIDER_RU[m.provider]}
                  </span>
                </div>

                <div className="flex items-center gap-2 self-start sm:self-center">
                  <span className="font-mono text-xs text-muted">
                    {m.campaigns ? `В кампаниях: ${m.campaigns}` : "Кампаний нет"}
                  </span>
                </div>
              </div>

              {/* Technical specs & Ping check */}
              <div className="mt-3 flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-3 font-mono text-xs text-muted">
                  <span className="text-ink font-medium">
                    {m.resolved_model || m.model || "(по умолчанию)"}
                  </span>
                  <span>·</span>
                  <span>температура: t = {m.temperature}</span>
                  {m.api_base && (
                    <>
                      <span>·</span>
                      <span className="truncate max-w-xs">{m.api_base}</span>
                    </>
                  )}
                </div>

                <div className="rounded-[8px] bg-raised/60 p-2.5 border border-line/60">
                  <CheckLine c={m.last_check} />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <ActionButton
                  className="px-3 py-1 text-xs font-mono"
                  run={async () => {
                    await api(`/api/admin/models/${m.id}/check`, { method: "POST" });
                    await refresh();
                  }}
                >
                  Проверить связь
                </ActionButton>

                <button
                  type="button"
                  className="btn px-3 py-1 text-xs font-mono"
                  onClick={() => open(m)}
                >
                  Изменить
                </button>

                {superAdmin && !m.is_default && (
                  <ActionButton
                    className="px-3 py-1 text-xs font-mono"
                    run={async () => {
                      await api(`/api/admin/models/${m.id}`, { method: "PATCH", body: { is_default: true } });
                      await refresh();
                    }}
                    done={`${m.name} назначена основной моделью`}
                  >
                    Сделать основной
                  </ActionButton>
                )}

                {(superAdmin || !m.is_default) && (
                  <ActionButton
                    danger
                    className="px-3 py-1 text-xs font-mono ml-auto"
                    confirm="Удалить модель? Кампании, где она уже выбрана, продолжат работу на ней."
                    run={async () => {
                      await api(`/api/admin/models/${m.id}`, { method: "DELETE" });
                      await refresh();
                    }}
                    done="Модель удалена"
                  >
                    Удалить
                  </ActionButton>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Model Add/Edit Form */}
      {form && (
        <section className="card p-5 sm:p-6 border-2 border-accent/60 bg-surface shadow-xl">
          <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
            <h3 className="font-heading text-xl font-bold text-ink">
              {form.id ? "Редактировать модель" : "Новая модель ИИ"}
            </h3>
            <button
              type="button"
              className="text-muted hover:text-ink text-sm font-mono px-2 py-1"
              onClick={() => setForm(null)}
            >
              ✕ ЗАКРЫТЬ
            </button>
          </div>

          <div className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Отображаемое название">
                <input
                  className="field"
                  maxLength={64}
                  placeholder="например: Claude Sonnet (быстрый)"
                  value={form.name}
                  onChange={(e) => set({ name: e.target.value })}
                />
              </Field>

              <Field label="Провайдер">
                <CustomSelect<Form["provider"]>
                  value={form.provider}
                  options={[
                    {
                      value: "claude",
                      label: "Claude (Anthropic)",
                      sublabel: "Флагманские модели Sonnet и Haiku через Anthropic API",
                      badge: "CLOUD",
                      badgeTone: "accent",
                    },
                    {
                      value: "gemini",
                      label: "Gemini (Google)",
                      sublabel: "Модели Gemini Pro и Flash с огромным контекстным окном",
                      badge: "CLOUD",
                      badgeTone: "patina",
                    },
                    {
                      value: "local",
                      label: "Локальная (LM Studio)",
                      sublabel: "Запуск на собственном ПК/сервере без передачи данных",
                      badge: "LOCAL",
                      badgeTone: "muted",
                    },
                  ]}
                  onChange={(val) => set({ provider: val })}
                  ariaLabel="Провайдер ИИ"
                />
              </Field>

              <Field label="Идентификатор модели">
                <input
                  className="field font-mono text-sm"
                  list="lm-models"
                  placeholder={
                    form.provider === "claude"
                      ? `пусто — ${info?.default_model ?? "модель по умолчанию"}`
                      : form.provider === "gemini"
                        ? "например: gemini-2.5-pro"
                        : "имя модели в LM Studio"
                  }
                  value={form.model}
                  onChange={(e) => set({ model: e.target.value })}
                />
                <datalist id="lm-models">
                  {local.map((x) => (
                    <option key={x} value={x} />
                  ))}
                </datalist>
              </Field>

              <Field label="Температура генерации" hint="0 — строгий канон правил, 1+ — более свободная фантазия.">
                <input
                  className="field font-mono"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={form.temperature}
                  onChange={(e) => set({ temperature: Number(e.target.value) })}
                />
              </Field>
            </div>

            {form.provider === "local" && (
              <div className="flex flex-col sm:flex-row sm:items-end gap-3 rounded-[10px] border border-line bg-raised/50 p-3">
                <Field label="Адрес сервера LM Studio" className="flex-1">
                  <input
                    className="field font-mono text-sm"
                    placeholder={info?.api_base ?? "http://localhost:1234/v1"}
                    value={form.api_base}
                    onChange={(e) => set({ api_base: e.target.value })}
                  />
                </Field>

                <ActionButton
                  className="text-xs font-mono"
                  run={async () => {
                    const q = form.api_base.trim() ? `?api_base=${encodeURIComponent(form.api_base.trim())}` : "";
                    const list = await api<string[]>(`/api/admin/providers/local/models${q}`);
                    setLocal(list);
                    if (!list.length) throw new Error("LM Studio отвечает, но активных моделей не обнаружено");
                  }}
                  done="Список моделей LM Studio загружен: выберите нужную в поле выше"
                >
                  Загрузить список из LM Studio
                </ActionButton>
              </div>
            )}

            {superAdmin && (
              <label className="flex items-center gap-2.5 text-sm cursor-pointer py-1">
                <input
                  type="checkbox"
                  className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                  checked={form.is_default}
                  onChange={(e) => set({ is_default: e.target.checked })}
                />
                <span className="font-medium text-ink">Назначать модель по умолчанию для новых кампаний</span>
              </label>
            )}

            {checked && (
              <div className="rounded-[8px] bg-raised p-3 border border-line">
                <CheckLine c={checked} />
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-line">
              <ActionButton
                className="font-mono text-xs"
                run={async () => {
                  const b = body(form);
                  setChecked(
                    await api<ModelCheck>("/api/admin/models/check", {
                      body: { provider: b.provider, model: b.model, api_base: b.api_base },
                    }),
                  );
                }}
              >
                Проверить связь
              </ActionButton>

              <ActionButton
                primary
                className="font-mono text-xs"
                run={async () => {
                  if (!form.name.trim()) throw new Error("Укажите название модели");
                  await api(form.id ? `/api/admin/models/${form.id}` : "/api/admin/models", {
                    method: form.id ? "PATCH" : "POST",
                    body: body(form),
                  });
                  setForm(null);
                  await refresh();
                }}
                done="Модель успешно сохранена"
              >
                Сохранить модель
              </ActionButton>

              <button
                type="button"
                className="btn text-xs font-mono text-muted hover:text-ink"
                onClick={() => setForm(null)}
              >
                Отмена
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
