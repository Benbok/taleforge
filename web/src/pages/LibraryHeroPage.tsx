import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Header from "../components/Header";
import Builder from "../builder/Builder";
import { api } from "../lib/api";
import { HERO_STATUS_RU, type BuilderOptions, type LibraryHero } from "../lib/builder";

/** Герой профиля: собирается по базовым правилам и потом копируется в любую кампанию. */
export default function LibraryHeroPage() {
  const param = useParams().hid;
  const hid = param === "new" ? undefined : param;
  const qc = useQueryClient();
  const navigate = useNavigate();
  // только что созданный герой: конструктор уже открыт с его данными, перезагружать его незачем
  const created = useRef(false);
  const opts = useQuery({ queryKey: ["options", "library"], queryFn: () => api<BuilderOptions>("/api/me/character-options") });
  const hero = useQuery({
    queryKey: ["library", hid],
    queryFn: () => api<LibraryHero>(`/api/me/characters/${hid}`),
    enabled: !!hid,
  });
  const problem = opts.error ?? hero.error;

  return (
    <>
      <Header>
        <Link className="btn px-3 py-1" to="/">
          ← Кампании
        </Link>
      </Header>
      <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6">
        <h1 className="text-2xl font-semibold">{hid ? "Герой профиля" : "Новый герой профиля"}</h1>
        <p className="text-sm text-muted">
          Героя профиля можно взять копией в любую кампанию. Там его проверит мастер и выдаст стартовое снаряжение.
        </p>
        {problem ? (
          <p className="text-bad">Не удалось загрузить: {(problem as Error).message}</p>
        ) : opts.isLoading || (hid && hero.isLoading && !created.current) ? (
          <p className="text-muted">Загружаем…</p>
        ) : (
          <>
            <Builder
              key="library"
              mode="library"
              opts={opts.data!}
              hero={hid ? (hero.data ?? null) : null}
              onSaved={(h) => {
                void qc.invalidateQueries({ queryKey: ["library"] });
                // новый герой получил адрес: дальше правим его, а не создаём ещё одного
                if (!hid) {
                  created.current = true;
                  navigate(`/heroes/${h.id}`, { replace: true });
                }
              }}
            />
            {hero.data?.copies && hero.data.copies.length > 0 && (
              <section className="card p-4">
                <h2 className="mb-2 text-base font-semibold">Копии в кампаниях</h2>
                <ul className="text-sm">
                  {hero.data.copies.map((c) => (
                    <li key={c.character_id}>
                      <Link to={`/c/${c.campaign_id}`}>{c.campaign_name}</Link>
                      <span className="text-muted">
                        {" "}
                        · {HERO_STATUS_RU[c.status] ?? c.status} · ур. {c.level}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
