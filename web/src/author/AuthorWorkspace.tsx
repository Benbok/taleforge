import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../lib/api";
import type { DraftPatch, EditProposal, ValidationIssue, ValidationReport } from "../lib/api.gen";
import { authoring, authorKeys, newRequestKey } from "../lib/authoring";
import ContentEditor, { type DraftContent } from "./ContentEditor";
import GeographyView from "./GeographyView";
import ManualPanel from "./ManualPanel";
import MapPreview from "./MapPreview";
import StagePanel from "./StagePanel";
import ValidationPanel from "./ValidationPanel";

type Plot = { regions?: never[]; locations?: { id: string; name: string; region?: string | null }[]; routes?: never[] };

export default function AuthorWorkspace({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  // Спойлеры закрыты по умолчанию: полный запрос не отправляется, пока автор явно не раскроет содержимое.
  const [revealed, setRevealed] = useState(false);
  const [location, setLocation] = useState<string | null>(null);
  const [proposal, setProposal] = useState<EditProposal | null>(null);
  const [affected, setAffected] = useState<string[]>([]);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [publishIssues, setPublishIssues] = useState<ValidationIssue[] | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const summary = useQuery({
    queryKey: authorKeys.project(projectId, "summary"),
    queryFn: () => authoring.getProject(projectId, "summary"),
    refetchInterval: (q) =>
      (q.state.data?.preparation.stages ?? []).some((s) => s.status === "queued" || s.status === "running") ? 3000 : false,
  });
  const full = useQuery({
    queryKey: authorKeys.project(projectId, "full"),
    queryFn: () => authoring.getProject(projectId, "full"),
    enabled: revealed,
  });
  const map = useQuery({
    queryKey: authorKeys.map(projectId, location ?? ""),
    queryFn: () => authoring.getMap(projectId, location as string),
    enabled: revealed && !!location,
  });

  const refresh = () => client.invalidateQueries({ queryKey: ["author", projectId] });
  const revision = summary.data?.project.draft_revision ?? 0;
  const fail = (e: unknown) => setMessage(e instanceof ApiError ? e.message : "не удалось выполнить действие");

  const prepare = useMutation({
    mutationFn: (v: { stage: string; regenerate: boolean }) =>
      authoring.prepare(projectId, { stage: v.stage, expected_revision: revision, request_key: newRequestKey(), regenerate: v.regenerate }),
    onSuccess: (receipt) => {
      setMessage(receipt.status === "ready" ? "Этап уже готов с теми же входными данными — результат не изменился." : "Этап поставлен в очередь.");
      void refresh();
    },
    onError: fail,
  });
  const edit = useMutation({
    mutationFn: (patch: DraftPatch) =>
      authoring.applyEdits(projectId, { patch, expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: (r) => {
      setAffected((r.affected ?? []).map((a) => `${a.kind}:${a.ref}`));
      setProposal(null);
      void refresh();
    },
    onError: fail,
  });
  const accept = useMutation({
    mutationFn: (ref: string) =>
      authoring.acceptStale(projectId, { refs: [ref], expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: refresh,
    onError: fail,
  });
  const propose = useMutation({
    mutationFn: (instruction: string) => authoring.previewEdit(projectId, { instruction, base_revision: revision }),
    onSuccess: setProposal,
    onError: fail,
  });
  const validate = useMutation({
    mutationFn: () => authoring.validate(projectId, revealed ? "full" : "summary"),
    onSuccess: (r) => {
      setReport(r);
      setPublishIssues(null);
      setPublishError(null);
      void refresh();
    },
    onError: fail,
  });
  const publish = useMutation({
    mutationFn: () => authoring.publish(projectId, { expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: (v) => {
      setPublishError(null);
      setPublishIssues(null);
      setMessage(`Опубликована версия ${v.version}`);
    },
    onError: (e) => {
      setPublishError(e instanceof ApiError ? e.message : "ошибка публикации");
      const data = e instanceof ApiError ? (e.data as { issues?: ValidationIssue[] } | undefined) : undefined;
      setPublishIssues(data?.issues ?? null);
    },
  });

  if (summary.isLoading) return <p className="p-4 text-muted">Загрузка…</p>;
  if (summary.error || !summary.data) return <p className="p-4 text-warn" role="alert">Проект недоступен.</p>;
  const { project, preparation } = summary.data;
  const content = (full.data?.preparation.content ?? null) as (DraftContent & { plot?: Plot }) | null;
  const plot = (content?.plot ?? {}) as { regions?: { id: string; name: string }[]; locations?: { id: string; name: string; region?: string | null }[]; routes?: { ref: string; from: string; to: string }[] };
  const busy = prepare.isPending || edit.isPending || accept.isPending || propose.isPending || validate.isPending || publish.isPending;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-2xl text-ink">{project.title}</h1>
        <span className="text-sm text-muted">ревизия {project.draft_revision}</span>
        <button className="btn ml-auto min-h-11 px-3 text-sm" type="button" aria-pressed={revealed} onClick={() => setRevealed((v) => !v)}>
          {revealed ? "Скрыть содержимое" : "Показать содержимое (спойлеры)"}
        </button>
      </header>
      {message && <p className="rounded-lg border border-line bg-raised p-3 text-sm" role="status">{message}</p>}
      <StagePanel view={preparation} busy={busy} onPrepare={(stage, regenerate) => prepare.mutate({ stage, regenerate })} onAcceptStale={(ref) => accept.mutate(ref)} />
      {revealed && content && (
        <>
          <GeographyView regions={plot.regions ?? []} locations={plot.locations ?? []} routes={plot.routes ?? []} selected={location} onSelect={setLocation} />
          {location && map.data && <MapPreview map={map.data} />}
          <ManualPanel
            projectId={projectId}
            revision={revision}
            plot={(content.plot ?? {}) as Record<string, unknown>}
            busy={busy}
            onChanged={(text) => {
              setMessage(text);
              void refresh();
            }}
            onLore={(fields) => edit.mutate({ operations: [{ op: "set_lore", fields: fields as never }] })}
            onPlotText={(fields) => edit.mutate({ operations: [{ op: "set_plot_text", fields }] })}
          />
          <ContentEditor
            content={content}
            busy={busy}
            proposal={proposal}
            affected={affected}
            onRename={(ref, name) => edit.mutate({ operations: [{ op: "update_plot_object", ref, fields: { name } }] })}
            onLore={(fields) => edit.mutate({ operations: [{ op: "set_lore", fields: fields as never }] })}
            onPropose={(text) => propose.mutate(text)}
            onApplyProposal={() => proposal && edit.mutate(proposal.patch)}
            onDismissProposal={() => setProposal(null)}
          />
        </>
      )}
      <ValidationPanel report={report} publishIssues={publishIssues} publishError={publishError} busy={busy} onValidate={() => validate.mutate()} onPublish={() => publish.mutate()} />
    </div>
  );
}
