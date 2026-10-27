import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import Header from "../components/Header";
import UniversalHeroCard from '../builder/UniversalHeroCard';
import HeroPortraitStudio from '../builder/HeroPortraitStudio';
import { universalCard, emptyDescription, type HeroDialogue } from '../lib/universal';
import HeroCreationDialogue from '../builder/HeroCreationDialogue';
import HeroDescriptionForm from '../builder/HeroDescriptionForm';
import { api } from "../lib/api";
import { type CampaignHero, type LibraryHero } from "../lib/builder";

interface Room {
  id: string;
  name: string;
  my_seat_id: string | null;
  my_role: string | null;
  pack_id: string | null;
  ruleset_id?: string;
}

/** Герой в кампании: выбрать готового, взять из профиля или собрать; дальше — проверка мастером. */
export default function CampaignHeroPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const room = useQuery({ queryKey: ["room", id], queryFn: () => api<Room>(`/api/campaigns/${id}`) });
  const list = useQuery({
    queryKey: ["characters", id],
    queryFn: () => api<CampaignHero[]>(`/api/campaigns/${id}/characters`),
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "submitted") ? 5000 : false),
  });
  const seat = room.data?.my_seat_id;
  const player = room.data?.my_role === "player";
  const library = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryHero[]>("/api/me/characters"),
    enabled: player,
  });
  const mine = list.data?.find((c) => seat && c.seat_id === seat && !["dead", "retired", "premade"].includes(c.status));
  const full = useQuery({
    queryKey: ["character", id, mine?.id],
    queryFn: () => api<CampaignHero>(`/api/campaigns/${id}/characters/${mine!.id}`),
    enabled: !!mine,
    refetchInterval: (q) => q.state.data?.status === "submitted" ? 3000 : false,
  });
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["characters", id] }),
      qc.invalidateQueries({ queryKey: ["character", id] }),
      qc.invalidateQueries({ queryKey: ["my-campaigns"] }),
    ]);

  const hero = mine ? full.data ?? null : null;
  const problem = room.error ?? list.error ?? full.error;
  const loading = room.isLoading || list.isLoading || (!!mine && full.isLoading);

  let body;
  if (problem) {
    body = (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось загрузить данные: {(problem as Error).message}
      </div>
    );
  } else if (loading) {
    body = (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Сверяем судовые списки и правила кампании…
      </div>
    );
  } else if (!player) {
    body = (
      <section className="card flex flex-col items-start gap-4 p-6 border-line bg-surface">
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">Место игрока не занято</h2>
          <p className="mt-1 text-sm text-muted">
            Чтобы играть героем за этим столом, необходимо занять свободное место в составе отряда.
          </p>
        </div>
        <ActionButton
          primary
          className="font-mono text-xs tracking-wider"
          run={async () => {
            await api(`/api/campaigns/${id}/seats/take`, { method: "POST" });
            await qc.invalidateQueries({ queryKey: ["room", id] });
            await refresh();
          }}
          done="Вы заняли место за столом"
        >
          ЗАНЯТЬ МЕСТО ИГРОКА
        </ActionButton>
      </section>
    );
  } else if (universalCard(hero)) {
    body = <UniversalHeroCard card={universalCard(hero)!} portraitActions={
      <HeroPortraitStudio card={universalCard(hero)!} endpoint={`/api/campaigns/${id}/characters/${hero!.id}/portrait`} onSaved={() => { void refresh(); }} />} />;
  } else if (!hero) {
    body = <UniversalAdmission id={id} library={library.data ?? []} onDone={refresh} />;
  } else {
    body = <p role="alert">Карточка использует неподдерживаемые правила.</p>;
  }

  return (
    <>
      <Header>
        <button
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          onClick={() => navigate(`/c/${id}`)}
          aria-label="Вернуться к столу кампании"
        >
          <span>←</span>
          <span className="truncate max-w-[180px] sm:max-w-xs">{room.data?.name ?? "Кампания"}</span>
        </button>
      </Header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Судовая канцелярия · Персонаж</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                Герой кампании
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Создайте нового исследователя с мастером или добавьте независимую копию героя из библиотеки.
              </p>
            </div>

            {room.data && (
              <div className="self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
                СТОЛ: <span className="font-semibold text-accent">{room.data.name}</span>
              </div>
            )}
          </div>
        </div>

        {body}
      </main>
    </>
  );
}

function UniversalAdmission({ id, library, onDone }: { id: string; library: LibraryHero[]; onDone: () => Promise<unknown> }) {
  const [dialogueId, setDialogueId] = useState<string | null>(null);
  const [description, setDescription] = useState(emptyDescription);
  const pending = useQuery({ queryKey: ['hero-drafts'], queryFn: () => api<HeroDialogue[]>('/api/hero-creation/dialogues') });
  const drafts = (pending.data ?? []).filter(draft => draft.campaign_id === id && ['questions', 'ready'].includes(draft.status));
  const active = dialogueId ?? drafts[0]?.id;
  const finish = () => { setDialogueId(null); void pending.refetch(); void onDone(); };
  if (active) return <HeroCreationDialogue id={active} onCreated={finish} onDeleted={() => { setDialogueId(null); void pending.refetch(); }} />;
  return <div className="flex flex-col gap-5">
    <section className="card p-5 flex flex-col gap-4">
      <h2 className="font-heading text-xl">Создать героя для этого мира</h2>
      <p className="text-sm text-muted">Опишите героя своими словами. Мастер учтёт законы мира и предложит характеристики и снаряжение.</p>
      <HeroDescriptionForm value={description} onChange={setDescription} />
      <ActionButton primary disabled={!description.identity.trim()} run={async () => {
        const draft = await api<HeroDialogue>('/api/hero-creation/dialogues', { body: { description, campaign_id: id } });
        setDialogueId(draft.id);
      }}>Обсудить героя с мастером</ActionButton>
    </section>
    <section className="card p-5 flex flex-col gap-3">
      <h2 className="font-heading text-xl">Взять героя из библиотеки</h2>
      <p className="text-sm text-muted">Мастер проверит совместимость героя с этим миром. Библиотечный оригинал останется без изменений.</p>
      {library.filter(hero => universalCard(hero)).map(hero => <ActionButton key={hero.id} run={async () => {
        const draft = await api<HeroDialogue>(`/api/campaigns/${id}/characters/from-library/${hero.id}/admission`, { method: 'POST' });
        setDialogueId(draft.id);
      }}>{hero.name}: проверить совместимость</ActionButton>)}
    </section>
  </div>;
}
