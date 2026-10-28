import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { newRequestKey } from "../lib/authoring";
import type { CatalogEntryOut, LaunchReceipt } from "../lib/api.gen";

/** Вкладка «Миры»: опубликованные миры всех авторов. Запуск создаёт новую сессию и открывает её кабинет. */
export default function WorldsCatalog({ isAdmin }: { isAdmin: boolean }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  // Один ключ на один клик: двойной клик вернёт ту же игру, следующий запуск позже создаст новую.
  const key = useRef<{ version: string; key: string } | null>(null);
  const busy = useRef(false);

  const catalog = useQuery({
    queryKey: ["worlds-catalog"],
    queryFn: () => api<CatalogEntryOut[]>("/api/adventures/catalog"),
  });

  const launch = useMutation({
    mutationFn: (versionId: string) => {
      if (key.current?.version !== versionId) key.current = { version: versionId, key: newRequestKey() };
      return api<LaunchReceipt>(`/api/adventures/${versionId}/games`, { body: { request_key: key.current.key } });
    },
    onSettled: () => {
      busy.current = false;
    },
    onSuccess: async (receipt) => {
      key.current = null;
      await qc.invalidateQueries({ queryKey: ["my-campaigns"] });
      navigate(`/c/${receipt.campaign_id}/manage`);
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="border-b border-line pb-4">
        <h2 className="font-heading text-3xl font-semibold text-ink">Миры</h2>
        <p className="mt-1 text-sm text-muted font-ui">
          Опубликованные миры всех авторов. Запуск создаёт новую сессию мира, а настроить её можно в кабинете.
        </p>
      </div>

      {launch.error && (
        <p className="rounded-lg border border-bad/30 bg-ember-bg p-3 text-sm text-bad" role="alert">
          {launch.error instanceof ApiError ? launch.error.message : "не удалось запустить мир"}
        </p>
      )}

      {catalog.isLoading ? (
        <div className="card p-8 text-center text-muted font-mono text-sm">Загрузка каталога миров…</div>
      ) : !catalog.data || catalog.data.length === 0 ? (
        <div className="card p-8 text-center text-muted text-sm">
          Пока нет опубликованных миров. Мир появится здесь, когда автор опубликует его в студии.
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {catalog.data.map((w) => {
            const intro = String(w.public_summary.intro ?? "");
            return (
              <article key={w.version_id} className="card flex flex-col justify-between overflow-hidden border-line bg-surface p-6">
                <div className="flex flex-col gap-3">
                  <div className="font-mono text-xs tracking-widest text-muted">Автор: {w.author_name}</div>
                  <h3 className="font-heading text-3xl font-semibold text-ink">{w.title}</h3>
                  {intro && <p className="font-narration text-base leading-relaxed text-ink-2">{intro}</p>}
                </div>
                {isAdmin && (
                  <div className="mt-6 flex justify-end border-t border-line-soft pt-4">
                    <button
                      type="button"
                      className="btn btn-primary text-xs font-semibold"
                      disabled={launch.isPending}
                      onClick={() => {
                        if (busy.current) return;
                        busy.current = true;
                        launch.mutate(w.version_id);
                      }}
                    >
                      Запустить
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
