import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AuthorWorkspace from "../author/AuthorWorkspace";
import StudioWorkspace from "../author/StudioWorkspace";
import Header from "../components/Header";
import { authoring, authorKeys } from "../lib/authoring";

export default function AuthorProjectPage() {
  const { projectId } = useParams();
  const [params, setParams] = useSearchParams();

  // Mode: "studio" (3-step universal) or "classic" (full pipeline)
  const modeParam = params.get("mode");
  const [mode, setMode] = useState<"studio" | "classic">(() => {
    if (modeParam === "classic") return "classic";
    try {
      const saved = localStorage.getItem("author:view_mode");
      if (saved === "classic") return "classic";
    } catch {
      // ignore
    }
    return "studio";
  });

  const projectQuery = useQuery({
    queryKey: authorKeys.project(projectId ?? "", "summary"),
    queryFn: () => authoring.getProject(projectId!, "summary"),
    enabled: !!projectId,
  });

  const switchMode = (next: "studio" | "classic") => {
    setMode(next);
    try {
      localStorage.setItem("author:view_mode", next);
    } catch {
      // ignore
    }
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("mode", next);
      return p;
    });
  };

  const project = projectQuery.data?.project;
  const projectTitle = project?.title ?? "";
  const projectPremise = project?.brief?.wishes ?? "";

  const initialVersion =
    project?.status === "published" && project.latest_version
      ? {
          version: `v${project.latest_version}`,
          published_at: new Date().toISOString(),
          adventure_id: projectId!,
          draft_revision: project.draft_revision,
        }
      : null;

  return (
    <>
      <Header>
        <div className="flex items-center gap-3">
          <Link className="btn btn-outline-copper h-8 px-2.5 text-xs font-mono" to="/author">
            ← Проекты
          </Link>
          <div className="flex rounded-lg border border-line bg-surface p-0.5 text-xs font-mono">
            <button
              type="button"
              onClick={() => switchMode("studio")}
              className={`rounded-md px-2.5 py-1 transition-all ${
                mode === "studio"
                  ? "bg-accent text-white font-semibold shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              Студия (3 шага)
            </button>
            <button
              type="button"
              onClick={() => switchMode("classic")}
              className={`rounded-md px-2.5 py-1 transition-all ${
                mode === "classic"
                  ? "bg-accent text-white font-semibold shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              Классический верстак
            </button>
          </div>
        </div>
      </Header>
      {projectId ? (
        mode === "studio" ? (
          <StudioWorkspace
            projectId={projectId}
            initialDraft={{ title: projectTitle, premise: projectPremise }}
            initialVersion={initialVersion}
          />
        ) : (
          <AuthorWorkspace projectId={projectId} />
        )
      ) : null}
    </>
  );
}
