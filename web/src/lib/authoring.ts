// Клиент пространства автора. Только REST и собственные ключи запросов: игровой сокет и stores сюда не входят.
import type { LocationMapSvgProps } from "../game/LocationMap";
import { api } from "./api";
import type {
  AcceptStaleRequest,
  AuthorMapOut,
  AuthorProjectCreate,
  EditProposal,
  EditRequest,
  EditResult,
  EditsRequest,
  ImportPlotRequest,
  ImportResult,
  JobOut,
  LaunchReceipt,
  LaunchRequest,
  PrepareRequest,
  ProjectDetail,
  ProjectSummary,
  ProjectView,
  PublishRequest,
  StageReceipt,
  StageTask,
  ValidationReport,
  VersionOut,
  WorldOverview,
} from "./api.gen";

export type View = "summary" | "full";

export const authorKeys = {
  projects: ["author", "projects"] as const,
  project: (id: string, view: View) => ["author", id, "project", view] as const,
  jobs: (id: string) => ["author", id, "jobs"] as const,
  map: (id: string, ref: string) => ["author", id, "map", ref] as const,
  library: ["adventures"] as const,
};

/** Ключ идемпотентности: один на намерение, а не на нажатие, поэтому двойной клик не создаёт дубль. */
export function newRequestKey(): string {
  const c = globalThis.crypto;
  return c && "randomUUID" in c ? c.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const base = (id: string) => `/api/author/projects/${id}`;

export const authoring = {
  listProjects: () => api<ProjectSummary[]>("/api/author/projects"),
  createProject: (body: AuthorProjectCreate) => api<ProjectDetail>("/api/author/projects", { body }),
  getProject: (id: string, view: View) => api<ProjectView>(`${base(id)}?view=${view}`),
  prepare: (id: string, body: PrepareRequest) => api<StageReceipt>(`${base(id)}/prepare`, { body }),
  listJobs: (id: string) => api<JobOut[]>(`${base(id)}/jobs`),
  previewEdit: (id: string, body: EditRequest) => api<EditProposal>(`${base(id)}/edits/preview`, { body }),
  applyEdits: (id: string, body: EditsRequest) => api<EditResult>(`${base(id)}/edits`, { body }),
  acceptStale: (id: string, body: AcceptStaleRequest) => api<EditResult>(`${base(id)}/edits/accept-stale`, { body }),
  overview: (id: string) => api<WorldOverview>(`${base(id)}/overview`),
  getMap: (id: string, ref: string) => api<AuthorMapOut>(`${base(id)}/maps/${encodeURIComponent(ref)}`),
  validate: (id: string, view: View = "summary") =>
    api<ValidationReport>(`${base(id)}/validate?view=${view}`, { method: "POST" }),
  publish: (id: string, body: PublishRequest) => api<VersionOut>(`${base(id)}/publish`, { body }),
  task: (id: string, stage: "lore" | "plot") => api<StageTask>(`${base(id)}/tasks/${stage}`),
  importPlot: (id: string, body: ImportPlotRequest) => api<ImportResult>(`${base(id)}/plot/import`, { body }),
  library: () => api<VersionOut[]>("/api/adventures"),
  launch: (versionId: string, body: LaunchRequest) => api<LaunchReceipt>(`/api/adventures/${versionId}/games`, { body }),
};

/** Участок авторской карты как план одной комнаты: для просмотра, без героя и без знаний игрока. */
export function planOfArea(map: AuthorMapOut, areaRef: string): LocationMapSvgProps["map"] | null {
  const area = map.areas.find((a) => a.area_ref === areaRef);
  if (!area) return null;
  const id = `author:${map.location_ref}:${area.area_ref}`;
  return {
    root_id: `author:${map.location_ref}`,
    here_id: id,
    areas: [
      {
        id,
        name: area.name,
        level: 0,
        offset: [0, 0],
        revision: 0,
        status: "here",
        sketch: area.sketch,
      },
    ],
  } as unknown as LocationMapSvgProps["map"];
}

/** Синтетический «обзор» для списка этапов: стадия, которой нет в ответе, считается ещё не запрошенной. */
export const STAGE_LABELS: Record<string, string> = {
  lore: "Лор",
  plot: "Сюжет и NPC",
  geography: "География",
  materialize: "Места, NPC и предметы",
  maps: "Карты",
  validate: "Проверка",
};

export const STAGE_STATE_LABELS: Record<string, string> = {
  not_requested: "ещё не выполнен",
  queued: "в очереди",
  running: "выполняется",
  ready: "готово",
  blocked: "остановлено",
  failed: "ошибка",
  stale: "устарело",
  manual: "заполнено вручную",
};

/** Какой этап должен быть готов (сгенерирован или заполнен вручную) до запуска этого. */
export const UPSTREAM: Record<string, string> = { geography: "plot", materialize: "geography", maps: "materialize" };
