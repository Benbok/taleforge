import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import CampaignBriefFields from "../components/CampaignBriefFields";
import Header from "../components/Header";
import { ApiError, api } from "../lib/api";
import type { BriefIn } from "../lib/api.gen";
import type { Pack } from "../lib/campaign";
import { authoring, authorKeys } from "../lib/authoring";

export default function AuthorProjectsPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState<BriefIn>({});
  const [pack, setPack] = useState("");
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => api<Pack[]>("/api/packs") });

  const newer = (a: string, b: string) => {
    const pa = a.split(".").map(Number);
    const pb = b.split(".").map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pa[i] ?? 0) > (pb[i] ?? 0);
    return false;
  };

  const latest = Object.values(
    (packs.data ?? []).reduce<Record<string, Pack>>((acc, p) => {
      if (!acc[p.id] || newer(p.version, acc[p.id].version)) acc[p.id] = p;
      return acc;
    }, {}),
  ).filter((p) => !p.id.startsWith("campaign."));

  const base = latest.find((p) => p.is_base);
  const selected = pack || (base ? `${base.id}@${base.version}` : "");
  const projects = useQuery({ queryKey: authorKeys.projects, queryFn: authoring.listProjects });

  const create = useMutation({
    mutationFn: () => {
      const chosen = latest.find((p) => `${p.id}@${p.version}` === selected);
      return authoring.createProject({
        title: title.trim(),
        brief,
        ...(chosen ? { pack_id: chosen.id, pack_version: chosen.version } : {}),
      });
    },
    onSuccess: (p) => {
      void client.invalidateQueries({ queryKey: authorKeys.projects });
      navigate(`/author/${p.id}`);
    },
  });

  return (
    <>
      <Header />
      <main className="mx-auto flex max-w-4xl flex-col gap-8 p-4 sm:p-6">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent">
            <span>Мастерская TaleForge</span>
            <span>•</span>
            <span>Story Studio</span>
          </div>
          <h1 className="font-heading text-3xl font-bold tracking-tight text-ink">Пространство автора</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-ink-2">
            Здесь создаются авторские сюжеты, локации и карты для настольных ролевых приключений.
            Вы можете генерировать мир целиком, подключать внешние языковые модели или детально редактировать каждый элемент вручную.
          </p>
        </header>

        <section aria-labelledby="projects-heading" className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 id="projects-heading" className="font-heading text-lg text-ink">Ваши проекты</h2>
            {projects.data && (
              <span className="text-xs text-muted">Всего: {projects.data.length}</span>
            )}
          </div>

          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Проекты">
            {(projects.data ?? []).map((p) => (
              <li key={p.id}>
                <Link
                  className="group flex min-h-24 flex-col justify-between rounded-xl border border-line bg-surface p-4 transition-all hover:border-accent/60 hover:bg-raised hover:shadow-md"
                  to={`/author/${p.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-heading text-base font-medium text-ink transition-colors group-hover:text-accent">
                      {p.title}
                    </span>
                    <span className="rounded bg-line-soft px-2 py-0.5 text-xs text-muted">Черновик</span>
                  </div>
                  <div className="mt-4 flex items-center justify-between text-xs text-muted">
                    <span>Открыть мастерскую</span>
                    <span className="transition-transform group-hover:translate-x-1">→</span>
                  </div>
                </Link>
              </li>
            ))}
            {projects.data?.length === 0 && (
              <li className="col-span-full rounded-xl border border-dashed border-line bg-surface/50 p-8 text-center">
                <p className="font-heading text-base text-ink">У вас пока нет созданных проектов</p>
                <p className="mt-1 text-sm text-muted">Заполните форму ниже, чтобы начать разработку первого приключения.</p>
              </li>
            )}
          </ul>
        </section>

        <section className="rounded-2xl border border-line bg-surface p-5 shadow-sm sm:p-6">
          <div className="mb-4 flex items-center gap-2 border-b border-line-soft pb-3">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">✦</span>
            <div>
              <h2 className="font-heading text-lg font-semibold text-ink">Создать новое приключение</h2>
              <p className="text-xs text-muted">Задайте базовые параметры: сюжет и лор можно будет сгенерировать или вставить на следующем шаге</p>
            </div>
          </div>

          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (title.trim() && !create.isPending) create.mutate();
            }}
          >
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-ink">Название приключения</span>
              <input
                className="min-h-11 rounded-xl border border-line bg-raised px-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                placeholder="Например: Тени над Озёрным краем"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-ink">Базовый мир (пакет контента)</span>
              <select
                className="min-h-11 rounded-xl border border-line bg-raised px-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                value={selected}
                onChange={(e) => setPack(e.target.value)}
              >
                {latest.map((p) => (
                  <option key={`${p.id}@${p.version}`} value={`${p.id}@${p.version}`}>
                    {p.name} · {p.version} {p.is_base ? "(базовый)" : ""}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted">Определяет правила, доступные расы, бестиарий и стиль повествования.</span>
            </label>

            <div className="rounded-xl border border-line-soft bg-raised/50 p-4">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted">Вводная анкета (необязательно)</span>
              <CampaignBriefFields value={brief} onChange={setBrief} />
            </div>

            {create.error && (
              <p className="rounded-lg border border-bad/30 bg-ember-bg p-3 text-sm text-bad" role="alert">
                {create.error instanceof ApiError ? create.error.message : "не удалось создать проект"}
              </p>
            )}

            <div className="flex items-center justify-between pt-2">
              <p className="text-xs text-muted">
                Обычное создание кампании для игры — на странице <Link className="text-accent underline hover:opacity-80" to="/new">«Новая кампания»</Link>.
              </p>
              <button
                className="btn btn-primary min-h-11 px-6 text-sm font-medium"
                type="submit"
                disabled={!title.trim() || create.isPending}
              >
                {create.isPending ? "Создание проекта…" : "Создать проект"}
              </button>
            </div>
          </form>
        </section>
      </main>
    </>
  );
}
