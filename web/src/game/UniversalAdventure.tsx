import { Link } from 'react-router-dom';
import ConnectionBanner from '../components/ConnectionBanner';
import Header from '../components/Header';
import UniversalHeroCard from '../builder/UniversalHeroCard';
import { formatCount } from '../lib/counts';
import { abilityNames, type AbilityKey, universalCard } from '../lib/universal';
import { useGame } from '../stores/game';
import ChatFeed from './ChatFeed';
import Composer from './Composer';
import { useDraft } from './draft';
import SessionControls from './SessionControls';
import SoundControl from './SoundControl';

/** Exploration uses the same authenticated socket, draft, voice and chat as the main table. */
export default function UniversalAdventure({ campaignId }: { campaignId: string }) {
  const snapshot = useGame(s => s.snapshot);
  const scene = useGame(s => s.scene);
  const card = universalCard(useGame(s => s.sheet));
  const abilities = card?.learned_abilities ?? [];
  return (
    <div className='flex h-dvh flex-col bg-bg'>
      <Header><Link to='/' className='btn btn-outline-copper'>← К столам</Link></Header>
      <div className='flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3'>
        <div><p className='text-xs text-patina'>Исследовательское приключение</p><h1 className='font-heading text-xl text-ink'>{snapshot?.campaign.name}</h1></div>
        <div className='flex flex-wrap items-center gap-2'><SoundControl /><SessionControls campaignId={campaignId} compact /></div>
      </div>
      <ConnectionBanner />
      <div className='grid min-h-0 flex-1 gap-4 p-3 lg:grid-cols-[20rem_1fr] lg:p-5'>
        <aside className='max-h-[35vh] space-y-4 overflow-y-auto lg:max-h-none' aria-label='Герой и место'>
          <section className='card space-y-2 p-4'>
            <h2 className='font-heading text-lg text-ink'>{scene?.location?.name ?? 'Начало пути'}</h2>
            <p className='whitespace-pre-wrap text-sm text-ink-2'>{scene?.location?.description ?? snapshot?.campaign.public_intro}</p>
          </section>
          {card ? <>
            <section className='card space-y-3 p-4' aria-label='Состояние героя'>
              <h2 className='font-heading text-lg text-ink'>{card.name}</h2>
              <p className='font-mono text-sm'>HP {formatCount(card.hp)} / {formatCount(card.derived.hp_max)}</p>
              <p className='text-xs text-muted'>Ресурсы и последствия сохраняются после каждого действия.</p>
              <details><summary className='cursor-pointer text-sm text-accent'>Карточка героя и снаряжение</summary><UniversalHeroCard card={card} /></details>
            </section>
            <section className='card space-y-2 p-4' aria-label='Изученные способности'>
              <h2 className='font-heading text-base text-ink'>Изученные способности</h2>
              {abilities.length ? abilities.map(ability => {
                const limits = ability.limits as { targets?: string; duration?: string; conditions?: string[] } | undefined;
                return <div key={String(ability.id)} className='space-y-1 rounded-lg border border-line p-2'>
                  <button type='button' className='btn btn-outline-copper w-full text-left'
                    title='Подставить намерение в сообщение. Мастер проверит применение в текущей сцене.'
                    onClick={() => useDraft.getState().setText(`Применяю способность «${String(ability.name)}».`)}>{String(ability.name)}</button>
                  {ability.cost !== undefined && <p className='text-xs text-patina'>Цена: {formatCount(String(ability.cost))} · {abilityNames[String(ability.resource_key) as AbilityKey] ?? 'Ресурс'}</p>}
                  {limits && <p className='text-xs text-muted'>Целей: {limits.targets} · Длительность: {limits.duration} шаг · {limits.conditions?.join('; ') || 'Без особых условий'}</p>}
                </div>;
              })
                : <p className='text-sm text-muted'>Способность появится здесь после успешного применения в игре.</p>}
            </section>
          </> : <Link className='btn btn-primary' to={`/c/${campaignId}/hero`}>Выбрать или создать героя</Link>}
        </aside>
        <main className='flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface'>
          <div className='border-b border-line px-4 py-3 text-xs text-muted'>Опишите, что хотите сделать. Мастер учитывает законы мира и сохраняет результат проверки.</div>
          <ChatFeed campaignId={campaignId} /><Composer />
        </main>
      </div>
    </div>
  );
}
