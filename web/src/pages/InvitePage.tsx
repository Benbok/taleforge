import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import AuthForm from "../components/AuthForm";
import Header from "../components/Header";
import { api } from "../lib/api";
import type { CampaignCard, InvitePreview } from "../lib/types";
import { useAsync } from "../lib/useAsync";
import { useSession } from "../stores/session";
import { toast } from "../stores/toasts";
import { Spinner } from "../components/ActionButton";

/** Вход по ссылке: обложка кампании и публичная вводная, имя и пароль — и сразу в лобби. */
export default function InvitePage() {
  const { token = "" } = useParams();
  const user = useSession((s) => s.user);
  const navigate = useNavigate();
  const { busy, error, run } = useAsync();
  const preview = useQuery({
    queryKey: ["invite", token],
    queryFn: () => api<InvitePreview>(`/api/invites/${token}`),
  });

  async function accept() {
    const c = await run(() => api<Pick<CampaignCard, "id">>(`/api/invites/${token}/accept`, { method: "POST" }));
    if (c) toast.ok("Вы за столом. Соберите героя, чтобы вступить в игру.");
    if (c) navigate(`/c/${c.id}`, { replace: true });
  }

  const p = preview.data;
  return (
    <>
      <Header />
      <main className="mx-auto flex max-w-lg flex-col gap-5 px-4 py-8">
        {preview.isLoading && <p className="text-muted">Открываем приглашение…</p>}
        {preview.isError && <p className="text-bad">Приглашение не найдено.</p>}
        {p && (
          <section className="card flex flex-col gap-3 p-5">
            <p className="text-xs uppercase tracking-wide text-muted">Приглашение в кампанию</p>
            <h1 className="text-2xl font-semibold">{p.campaign_name || "Кампания"}</h1>
            {p.public_intro && <p className="font-narration text-lg leading-relaxed">{p.public_intro}</p>}
            {p.valid ? (
              <p className="text-muted">Свободных мест: {p.free_seats}</p>
            ) : (
              <p className="text-bad">Войти нельзя: {p.problem}</p>
            )}
          </section>
        )}
        {p?.valid &&
          (user ? (
            <div className="flex flex-col gap-2">
              <button className="btn btn-primary" disabled={busy} aria-busy={busy} onClick={accept}>
                {busy && <Spinner />}
                Сесть за стол как {user.name}
              </button>
              {error && <p className="text-bad" role="alert">Не получилось: {error}</p>}
            </div>
          ) : (
            <AuthForm
              inviteToken={token}
              initial="signup"
              onDone={(joined) => (joined ? navigate("/", { replace: true }) : void accept())}
            />
          ))}
      </main>
    </>
  );
}
