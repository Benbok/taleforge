import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";
import { type ModelCheck, type Provider } from "../lib/campaign";

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

export default function ModelsSection({ superAdmin }: { superAdmin: boolean }) {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api<Provider[]>("/api/admin/providers") });
  const [checks, setChecks] = useState<Record<string, ModelCheck>>({});

  const refresh = () => qc.invalidateQueries({ queryKey: ["providers"] });

  async function checkProvider(p: Provider) {
    const res = await api<ModelCheck>("/api/admin/providers/check", {
      method: "POST",
      body: { provider: p.id, api_base: p.api_base },
    });
    setChecks(prev => ({ ...prev, [p.id]: res }));
  }

  return (
    <div className="flex flex-col gap-6" aria-label="Модели ИИ">
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div>
          <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
            Настройки провайдеров ИИ
          </h2>
          <p className="mt-1 text-sm text-muted max-w-2xl">
            Единый источник истины — файл <code>.env</code>. Выберите активного провайдера, который будет обслуживать все кампании. Основная модель генерирует сюжет, а техническая обрабатывает сводки и намерения игроков.
          </p>
        </div>
      </section>

      {providers.isError && (
        <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
          Ошибка загрузки провайдеров: {(providers.error as Error).message}
        </div>
      )}

      {providers.data && (
        <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {providers.data.map((p) => {
            const hasKey = p.key_set;
            const isLocal = p.key_set === null;
            const check = checks[p.id];
            
            return (
              <div
                key={p.id}
                className={`card p-5 flex flex-col justify-between gap-4 border transition-colors ${
                  p.is_active ? "border-accent bg-accent/5 ring-1 ring-accent" : "border-line bg-raised/40 hover:border-accent/40"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-heading text-lg font-bold text-ink">{p.title}</span>
                      {p.is_active && (
                        <span className="rounded-full border border-accent bg-accent/15 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-accent">
                          ★ АКТИВЕН
                        </span>
                      )}
                    </div>
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${
                        isLocal ? "bg-muted" : hasKey ? "bg-patina" : "bg-bad"
                      }`}
                      title={hasKey ? "Ключ задан" : "Ключ отсутствует"}
                    />
                  </div>

                  <div className="font-mono text-[11px] text-muted space-y-1">
                    {isLocal ? (
                      <div>API Base: {p.api_base}</div>
                    ) : hasKey ? (
                      <div className="text-patina-hi">✓ Ключ {p.key_env} задан</div>
                    ) : (
                      <div className="text-bad">✗ Задайте {p.key_env} в env</div>
                    )}
                    
                    <div className="pt-2">
                      <div className="flex items-center justify-between">
                        <span className="text-faint">Основная:</span>
                        <span className="text-ink font-medium truncate ml-2" title={p.main_model ?? ""}>{p.main_model ?? "—"}</span>
                      </div>
                      <div className="flex items-center justify-between mt-1">
                        <span className="text-faint">Техническая:</span>
                        <span className="text-ink font-medium truncate ml-2" title={p.technical_model ?? ""}>{p.technical_model ?? "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex flex-col gap-3 mt-auto pt-4 border-t border-line/50">
                  {check && (
                    <div className="rounded-[8px] bg-surface p-2.5 border border-line/60">
                      <CheckLine c={check} />
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    <ActionButton
                      className="px-3 py-1 text-xs font-mono"
                      run={() => checkProvider(p)}
                    >
                      Проверить
                    </ActionButton>

                    {!p.is_active && (isLocal || hasKey) && (
                      <ActionButton
                        primary
                        className="px-3 py-1 text-xs font-mono ml-auto"
                        run={async () => {
                          await api("/api/admin/providers/active", {
                            method: "PATCH",
                            body: { provider: p.id },
                          });
                          await refresh();
                        }}
                        done={`${p.title} сделан активным`}
                      >
                        Сделать активным
                      </ActionButton>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
