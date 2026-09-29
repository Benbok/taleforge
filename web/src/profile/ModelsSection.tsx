import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { PROVIDER_RU, type ModelCheck, type ModelProfile, type Provider } from "../lib/campaign";

const DATE = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function CheckLine({ c }: { c: ModelCheck | null | undefined }) {
  if (!c?.at) return <span className="text-muted">не проверялась</span>;
  const when = DATE.format(new Date(c.at));
  if (c.ok)
    return (
      <span>
        <span className="text-ok">✓ отвечает</span>
        <span className="text-muted">
          {" "}
          · {c.latency_ms ?? "?"} мс · «{c.reply}» · {when}
        </span>
      </span>
    );
  const err = c.error ?? "";
  return (
    <span>
      <span className="text-bad">✗ {err.replace(/ \(.*$/s, "")}</span>
      <span className="text-muted"> · {when}</span>
      {err.includes(" (") && (
        <details>
          <summary className="cursor-pointer text-muted">подробности</summary>
          <code className="break-all text-xs">{err}</code>
        </details>
      )}
    </span>
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
        ? { id: m.id, name: m.name, provider: m.provider, model: m.model, api_base: m.api_base ?? "", temperature: m.temperature, is_default: m.is_default }
        : { id: null, name: "", provider: "claude", model: "", api_base: "", temperature: 0.8, is_default: false },
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
    <section className="card flex flex-col gap-4 p-4" aria-label="Модели ИИ">
      <div>
        <h2 className="text-base font-semibold">Модели ИИ</h2>
        <p className="text-sm text-muted">Их выбирают мастером кампании. Ключи провайдеров хранятся только в окружении сервера: здесь видно лишь, задан ли ключ.</p>
      </div>
      {providers.data && (
        <ul className="flex flex-col gap-1 text-sm">
          {providers.data.map((p) => (
            <li key={p.id} className="flex flex-wrap justify-between gap-2">
              <span>
                {p.title}
                {p.default_model && <span className="text-muted"> · по умолчанию {p.default_model}</span>}
              </span>
              {p.key_set === null ? (
                <span className="text-muted">ключ не нужен · {p.api_base}</span>
              ) : p.key_set ? (
                <span className="text-ok">ключ задан</span>
              ) : (
                <span className="text-bad">нет ключа: задайте {p.key_env} в окружении сервера</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {models.isError && <p className="text-bad">Не удалось загрузить модели: {(models.error as Error).message}</p>}
      {models.isSuccess && models.data.length === 0 && <p className="text-sm text-muted">Моделей пока нет. Добавьте первую: её можно будет выбрать мастером кампании.</p>}
      <ul className="flex flex-col divide-y divide-line">
        {(models.data ?? []).map((m) => (
          <li key={m.id} className="flex flex-wrap items-start gap-2 py-2">
            <span className="min-w-0 flex-1 text-sm">
              <span className="font-semibold">{m.name}</span>
              {m.is_default && <span className="ml-1.5 rounded-full border border-accent px-2 text-xs text-accent">по умолчанию</span>}
              <span className="block text-xs text-muted">
                {PROVIDER_RU[m.provider]} · {m.resolved_model || m.model} · t={m.temperature}
                {m.api_base ? ` · ${m.api_base}` : ""}
                {m.campaigns ? ` · кампаний: ${m.campaigns}` : ""}
              </span>
              <span className="block text-xs">
                <CheckLine c={m.last_check} />
              </span>
            </span>
            <span className="flex flex-wrap gap-1.5">
              <ActionButton
                className="px-2 py-0.5 text-xs"
                run={async () => {
                  await api(`/api/admin/models/${m.id}/check`, { method: "POST" });
                  await refresh();
                }}
              >
                Проверить
              </ActionButton>
              <button className="btn px-2 py-0.5 text-xs" onClick={() => open(m)}>
                Изменить
              </button>
              {superAdmin && !m.is_default && (
                <ActionButton
                  className="px-2 py-0.5 text-xs"
                  run={async () => {
                    await api(`/api/admin/models/${m.id}`, { method: "PATCH", body: { is_default: true } });
                    await refresh();
                  }}
                  done={`${m.name} — модель по умолчанию`}
                >
                  Сделать основной
                </ActionButton>
              )}
              {(superAdmin || !m.is_default) && (
                <ActionButton
                  danger
                  className="px-2 py-0.5 text-xs"
                  confirm="Удалить модель? Кампании, где она уже выбрана, продолжат работать на ней."
                  run={async () => {
                    await api(`/api/admin/models/${m.id}`, { method: "DELETE" });
                    await refresh();
                  }}
                  done="Модель удалена"
                >
                  Удалить
                </ActionButton>
              )}
            </span>
          </li>
        ))}
      </ul>

      {!form ? (
        <div>
          <button className="btn btn-primary" onClick={() => open(null)}>
            Добавить модель
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3 rounded-md border border-line p-3">
          <h3 className="font-semibold">{form.id ? "Изменить модель" : "Новая модель"}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Название">
              <input className="field" maxLength={64} placeholder="например «Opus для кампаний»" value={form.name} onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="Провайдер">
              <select className="field" value={form.provider} onChange={(e) => set({ provider: e.target.value as Form["provider"] })}>
                <option value="claude">Claude (Anthropic)</option>
                <option value="gemini">Gemini (Google)</option>
                <option value="local">Локальная (LM Studio)</option>
              </select>
            </Field>
            <Field label="Модель">
              <input
                className="field"
                list="lm-models"
                placeholder={
                  form.provider === "claude"
                    ? `пусто — ${info?.default_model ?? "модель по умолчанию"}`
                    : form.provider === "gemini"
                      ? "например gemini-2.5-pro"
                      : "имя модели, загруженной в LM Studio"
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
            <Field label="Температура" hint="0 — строго, 1 и выше — свободнее.">
              <input className="field" type="number" min={0} max={2} step={0.1} value={form.temperature} onChange={(e) => set({ temperature: Number(e.target.value) })} />
            </Field>
          </div>
          {form.provider === "local" && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Адрес LM Studio" className="min-w-48 flex-1">
                <input className="field" placeholder={info?.api_base ?? "http://localhost:1234/v1"} value={form.api_base} onChange={(e) => set({ api_base: e.target.value })} />
              </Field>
              <ActionButton
                run={async () => {
                  const q = form.api_base.trim() ? `?api_base=${encodeURIComponent(form.api_base.trim())}` : "";
                  const list = await api<string[]>(`/api/admin/providers/local/models${q}`);
                  setLocal(list);
                  if (!list.length) throw new Error("LM Studio отвечает, но модели не загружены");
                }}
                done="Модели LM Studio загружены: выберите в поле «Модель»"
              >
                Загрузить модели из LM Studio
              </ActionButton>
            </div>
          )}
          {superAdmin && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.is_default} onChange={(e) => set({ is_default: e.target.checked })} />
              Модель по умолчанию для новых кампаний
            </label>
          )}
          {checked && (
            <p className="text-sm">
              <CheckLine c={checked} />
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <ActionButton
              run={async () => {
                const b = body(form);
                setChecked(await api<ModelCheck>("/api/admin/models/check", { body: { provider: b.provider, model: b.model, api_base: b.api_base } }));
              }}
            >
              Проверить связь
            </ActionButton>
            <ActionButton
              primary
              run={async () => {
                if (!form.name.trim()) throw new Error("Назовите модель");
                await api(form.id ? `/api/admin/models/${form.id}` : "/api/admin/models", { method: form.id ? "PATCH" : "POST", body: body(form) });
                setForm(null);
                await refresh();
              }}
              done="Модель сохранена"
            >
              Сохранить
            </ActionButton>
            <button className="btn" onClick={() => setForm(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
