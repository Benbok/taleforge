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
  const base = (packs.data ?? []).find((p) => p.is_base);
  const selected = pack || (base ? `${base.id}@${base.version}` : ""); // базовый мир по умолчанию
  const projects = useQuery({ queryKey: authorKeys.projects, queryFn: authoring.listProjects });
  const create = useMutation({
    mutationFn: () => {
      const chosen = (packs.data ?? []).find((p) => `${p.id}@${p.version}` === selected);
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
      <main className="mx-auto flex max-w-3xl flex-col gap-6 p-4">
        <h1 className="font-heading text-2xl text-ink">Пространство автора</h1>
        <ul className="flex flex-col gap-2" aria-label="Проекты">
          {(projects.data ?? []).map((p) => (
            <li key={p.id}><Link className="btn min-h-11 w-full justify-start px-3" to={`/author/${p.id}`}>{p.title}</Link></li>
          ))}
          {projects.data?.length === 0 && <li className="text-sm text-muted">Проектов пока нет.</li>}
        </ul>
        <form className="flex flex-col gap-3 rounded-lg border border-line bg-raised p-4" onSubmit={(e) => { e.preventDefault(); if (title.trim() && !create.isPending) create.mutate(); }}>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Название приключения</span>
            <input className="min-h-11 rounded-lg border border-line bg-surface px-2" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Мир (пакет контента)</span>
            <select className="min-h-11 rounded-lg border border-line bg-surface px-2" value={selected} onChange={(e) => setPack(e.target.value)}>
              {(packs.data ?? []).map((p) => (
                <option key={`${p.id}@${p.version}`} value={`${p.id}@${p.version}`}>{p.name} · {p.version}</option>
              ))}
            </select>
          </label>
          <CampaignBriefFields value={brief} onChange={setBrief} />
          {create.error && <p className="text-sm text-warn" role="alert">{create.error instanceof ApiError ? create.error.message : "не удалось создать проект"}</p>}
          <button className="btn btn-primary min-h-11 self-start px-4" type="submit" disabled={!title.trim() || create.isPending}>Создать проект</button>
        </form>
        <p className="text-sm text-muted">Обычное создание кампании по-прежнему на странице <Link to="/new">«Новая кампания»</Link>.</p>
      </main>
    </>
  );
}
