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
import WorldIntroPlayer from "../components/WorldIntroPlayer";

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
    if (c) toast.ok("Вы заняли место за столом. Соберите героя, чтобы вступить в игру.");
    if (c) navigate(`/c/${c.id}`, { replace: true });
  }

  const p = preview.data;

  return (
    <>
      <Header />
      <main className="mx-auto flex max-w-lg flex-col gap-6 px-4 py-8 md:py-12">
        {preview.isLoading && (
          <div className="card p-8 text-center text-muted font-mono text-sm">
            Проверяем судовой реестр приглашений…
          </div>
        )}

        {preview.isError && (
          <div className="card border-bad/40 bg-bad/5 p-6 text-center text-bad font-mono text-sm">
            Приглашение не найдено или срок его действия истёк.
          </div>
        )}

        {p && (
          <section className="card p-6 sm:p-7 border-2 border-accent/40 bg-surface shadow-2xl relative overflow-hidden flex flex-col gap-4">
            <div className="pointer-events-none absolute -right-6 -top-6 h-28 w-28 rounded-full bg-accent/10 blur-xl" />

            <div className="flex items-center justify-between border-b border-line pb-3">
              <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-accent font-semibold">
                Приглашение в экспедицию
              </span>
              {p.valid && (
                <span className="font-mono text-xs text-patina-hi border border-patina/40 bg-patina/10 px-2.5 py-0.5 rounded-full">
                  Мест свободно: {p.free_seats}
                </span>
              )}
            </div>

            <div>
              <h1 className="font-heading text-2xl sm:text-3xl font-bold text-ink">
                {p.campaign_name || "Безымянная кампания"}
              </h1>
              {(!p.pack_id || p.pack_id === "echo-leviathans") && (
                <div className="mt-4">
                  <WorldIntroPlayer />
                </div>
              )}
              {p.public_intro && (
                <div className="mt-3 rounded-[8px] bg-raised/50 p-4 font-narration text-base leading-relaxed text-ink-2 whitespace-pre-line border border-line/60">
                  «{p.public_intro}»
                </div>
              )}
            </div>

            {!p.valid && (
              <div className="rounded-[8px] border border-bad/40 bg-bad/10 p-3 font-mono text-xs text-bad">
                Войти нельзя: {p.problem}
              </div>
            )}
          </section>
        )}

        {p?.valid &&
          (user ? (
            <div className="flex flex-col gap-3">
              <button
                type="button"
                className="btn btn-primary font-mono text-xs tracking-wider py-3 shadow-lg"
                disabled={busy}
                aria-busy={busy}
                onClick={accept}
              >
                {busy && <Spinner />}
                СЕСТЬ ЗА СТОЛ КАК {user.name.toUpperCase()} →
              </button>
              {error && (
                <p className="font-mono text-xs text-bad text-center" role="alert">
                  Ошибка входа: {error}
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-center font-mono text-xs text-muted">
                Создайте учётную запись или войдите, чтобы занять место за этим столом:
              </p>
              <AuthForm
                inviteToken={token}
                initial="signup"
                onDone={(joined) => (joined ? navigate("/", { replace: true }) : void accept())}
              />
            </div>
          ))}
      </main>
    </>
  );
}
