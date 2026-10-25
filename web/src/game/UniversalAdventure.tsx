import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import ConnectionBanner from '../components/ConnectionBanner';
import Header from '../components/Header';
import UniversalHeroCard from '../builder/UniversalHeroCard';
import { formatCount } from '../lib/counts';
import { abilityKeys, abilityNames, type AbilityKey, energyThemes, universalCard } from '../lib/universal';
import { useGame } from '../stores/game';
import ChatFeed from './ChatFeed';
import CabinetLink from './CabinetLink';
import Composer from './Composer';
import { useDraft } from './draft';
import { loadChatFontSize, saveChatFontSize, type ChatFontSize } from './scenePreferences';
import ExplorationPanel, { type ExplorationState } from './ExplorationPanel';
import SessionControls from './SessionControls';
import SoundControl from './SoundControl';

/** Exploration uses the same authenticated socket, draft, voice and chat as the main table. */
export default function UniversalAdventure({
  campaignId,
  exploration: propExploration,
  canManage = false,
}: {
  campaignId: string;
  exploration?: ExplorationState | null;
  canManage?: boolean;
}) {
  const snapshot = useGame(s => s.snapshot);
  const scene = useGame(s => s.scene);
  const sheet = useGame(s => s.sheet);
  const exploration = propExploration ?? (sheet as unknown as { exploration?: ExplorationState } | null)?.exploration ?? null;
  const card = universalCard(sheet);
  const abilities = card?.learned_abilities ?? [];
  const [showCardModal, setShowCardModal] = useState(false);
  const [isChatFullscreen, setIsChatFullscreen] = useState(false);
  const [isLocationExpanded, setIsLocationExpanded] = useState(false);
  const [chatFontSize, setChatFontSize] = useState<ChatFontSize>(loadChatFontSize);
  const locationText = scene?.location?.description ?? snapshot?.campaign.public_intro ?? '';
  const isLongLocation = locationText.length > 180 || locationText.split('\n').length > 3;

  const handleFontSizeChange = (size: ChatFontSize) => {
    setChatFontSize(size);
    saveChatFontSize(size);
  };

  useEffect(() => {
    if (!showCardModal && !isChatFullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCardModal) {
          setShowCardModal(false);
        } else if (isChatFullscreen) {
          setIsChatFullscreen(false);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showCardModal, isChatFullscreen]);

  return (
    <div className='flex h-dvh flex-col bg-bg'>
      <Header><Link to='/' className='btn btn-outline-copper'>← К столам</Link></Header>
      <div className='flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3'>
        <div>
          <p className='text-xs text-patina'>Исследовательское приключение</p>
          <h1 className='font-heading text-xl text-ink'>{snapshot?.campaign.name}</h1>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <SoundControl />
          <CabinetLink campaignId={campaignId} canManage={canManage} />
          <SessionControls campaignId={campaignId} compact />
        </div>
      </div>
      <ConnectionBanner />
      <div className='grid min-h-0 flex-1 gap-4 p-3 lg:grid-cols-[21rem_1fr] lg:p-5'>
        <aside className='flex min-h-0 max-h-[38vh] flex-col gap-3.5 overflow-y-auto pr-1 lg:max-h-full' aria-label='Герой и место'>
          {/* 1. Карточка героя (HUD) — главный фокус игрока */}
          {card ? (
            <section className='card space-y-3.5 p-4' aria-label='Состояние героя'>
              <div className='flex items-center gap-3'>
                {card.portrait_url ? (
                  <img
                    src={card.portrait_url}
                    alt={card.name}
                    className='h-12 w-12 shrink-0 rounded-xl border border-line object-cover shadow-sm'
                  />
                ) : (
                  <div
                    className='flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-line bg-surface-2 font-heading text-lg font-bold text-accent shadow-inner'
                    aria-hidden='true'
                  >
                    {card.name.slice(0, 1).toUpperCase() || '✧'}
                  </div>
                )}
                <div className='min-w-0 flex-1'>
                  <div className='flex items-center justify-between gap-1'>
                    <h2 className='truncate font-heading text-base font-bold text-ink' title={card.name}>
                      {card.name}
                    </h2>
                    <span className='shrink-0 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[11px] font-semibold text-accent'>
                      {formatCount(card.level ?? '1')} ур.
                    </span>
                  </div>
                  {card.sheet?.description?.identity && (
                    <p className='truncate text-xs text-muted' title={card.sheet.description.identity}>
                      {card.sheet.description.identity}
                    </p>
                  )}
                </div>
              </div>

              {/* Жизненные силы и КД */}
              <div className='space-y-1.5 rounded-lg border border-line-soft bg-surface-2/40 p-2.5'>
                <div className='flex items-center justify-between text-xs'>
                  <span className='font-semibold text-patina'>Жизненные силы</span>
                  <div className='flex items-center gap-2'>
                    <span className='font-mono font-bold text-ink'>
                      HP {formatCount(card.hp ?? '0')} / {formatCount(card.derived?.hp_max ?? '1')}
                    </span>
                    {card.derived?.ac !== undefined && (
                      <span className='rounded border border-line-soft bg-surface px-1.5 py-0.5 font-mono text-[10px] font-bold text-accent'>
                        КД {formatCount(card.derived.ac)}
                      </span>
                    )}
                  </div>
                </div>
                <div className='h-2 w-full overflow-hidden rounded-full border border-line-soft bg-surface'>
                  <div
                    className='h-full rounded-full transition-all duration-300'
                    style={{
                      width: `${Math.min(100, Math.max(0, Math.round((Number(card.hp ?? 0) / Math.max(1, Number(card.derived?.hp_max ?? 1))) * 100)))}%`,
                      background: 'linear-gradient(90deg, var(--tf-ember), var(--tf-patina))',
                    }}
                  />
                </div>
              </div>

              {/* 5 резервов энергий */}
              <div className='space-y-1.5'>
                <div className='flex items-center justify-between text-[11px] text-muted'>
                  <span className='font-bold uppercase tracking-wider text-patina'>Резервы сил</span>
                  <span>{formatCount(card.sheet?.xp ?? '0')} XP</span>
                </div>
                <div className='grid grid-cols-5 gap-1'>
                  {abilityKeys.filter(key => key !== 'con').map(key => {
                    const cur = Number(card.energies?.[key as keyof typeof card.energies] ?? 0);
                    const max = Math.max(1, Number(card.derived?.energy_max?.[key as keyof typeof card.energies] ?? 1));
                    const pct = Math.min(100, Math.max(0, Math.round((cur / max) * 100)));
                    const theme = energyThemes[key] ?? { color: 'var(--tf-patina)', short: key.toUpperCase() };
                    return (
                      <div
                        key={key}
                        className='flex flex-col items-center rounded-md border border-line-soft bg-surface-2/30 p-1 text-center min-w-0'
                        title={`${abilityNames[key]}: ${cur} / ${max}`}
                      >
                        <span className='text-[10px] font-medium text-muted'>{theme.short}</span>
                        <span className='font-mono text-xs font-bold text-ink'>{cur}</span>
                        <div className='mt-1 h-1 w-full overflow-hidden rounded-full bg-surface'>
                          <div className='h-full transition-all' style={{ width: `${pct}%`, backgroundColor: theme.color }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <p className='text-xs text-muted'>Ресурсы и последствия сохраняются после каждого действия.</p>

              {/* Действующие эффекты, ограничения формы и интерактивные предметы */}
              {exploration && <ExplorationPanel state={exploration} />}

              {/* Кнопка открытия полной карточки в модальном окне */}
              <button
                type='button'
                className='btn btn-outline-copper flex w-full items-center justify-center gap-2 py-2 text-xs font-semibold'
                onClick={() => setShowCardModal(true)}
              >
                <span>⤢ Карточка героя и снаряжение</span>
              </button>
            </section>
          ) : (
            <Link className='btn btn-primary' to={`/c/${campaignId}/hero`}>
              Выбрать или создать героя
            </Link>
          )}

          {/* 2. Карточка текущего места с возможностью раскрыть подробное описание */}
          <section className='card space-y-2 p-4' aria-label='Текущее место'>
            <div className='flex items-center justify-between'>
              <span className='text-[10px] font-bold uppercase tracking-wider text-patina'>Текущее место</span>
              {isLongLocation && (
                <button
                  type='button'
                  onClick={() => setIsLocationExpanded(v => !v)}
                  className='text-[11px] font-semibold text-accent hover:underline'
                  aria-expanded={isLocationExpanded}
                >
                  {isLocationExpanded ? 'Свернуть ▲' : 'Подробнее ▼'}
                </button>
              )}
            </div>
            <h2 className='font-heading text-lg font-bold text-ink'>{scene?.location?.name ?? 'Начало пути'}</h2>
            <div className={isLocationExpanded || !isLongLocation ? '' : 'line-clamp-3'}>
              <p className='whitespace-pre-wrap text-sm leading-relaxed text-ink-2'>{locationText}</p>
            </div>
          </section>

          {/* 3. Изученные способности */}
          {card && (
            <section className='card space-y-2 p-4' aria-label='Изученные способности'>
              <h2 className='font-heading text-base text-ink'>Изученные способности</h2>
              {abilities.length ? (
                abilities.map(ability => {
                  const limits = ability.limits as { targets?: string; duration?: string; conditions?: string[] } | undefined;
                  return (
                    <div key={String(ability.id)} className='space-y-1 rounded-lg border border-line p-2'>
                      <button
                        type='button'
                        className='btn btn-outline-copper w-full text-left'
                        title='Подставить намерение в сообщение. Мастер проверит применение в текущей сцене.'
                        onClick={() => useDraft.getState().setText(`Применяю способность «${String(ability.name)}».`)}
                      >
                        {String(ability.name)}
                      </button>
                      {ability.cost !== undefined && (
                        <p className='text-xs text-patina'>
                          Цена: {formatCount(String(ability.cost))} · {abilityNames[String(ability.resource_key) as AbilityKey] ?? 'Ресурс'}
                        </p>
                      )}
                      {limits && (
                        <p className='text-xs text-muted'>
                          Целей: {limits.targets} · Длительность: {limits.duration} сек · {limits.conditions?.join('; ') || 'Без особых условий'}
                        </p>
                      )}
                    </div>
                  );
                })
              ) : (
                <p className='text-sm text-muted'>Способность появится здесь после успешного применения в игре.</p>
              )}
            </section>
          )}
        </aside>

        <main
          className={
            isChatFullscreen
              ? `fixed inset-0 z-40 flex flex-col bg-surface tf-chat-font-${chatFontSize}`
              : `flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface tf-chat-font-${chatFontSize}`
          }
        >
          {isChatFullscreen ? (
            <div className='flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 bg-surface-2/40'>
              <div className='flex items-center gap-3 min-w-0'>
                <div className='flex items-center gap-2'>
                  <span className='text-xs font-bold uppercase tracking-wider text-patina'>
                    {scene?.location?.name ?? 'Приключение'}
                  </span>
                  <span className='text-muted hidden sm:inline'>·</span>
                  <span className='text-xs text-ink-2 truncate hidden sm:inline'>
                    {snapshot?.campaign.name}
                  </span>
                </div>
                {card && (
                  <button
                    type='button'
                    className='flex items-center gap-2 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink hover:border-accent transition-colors'
                    onClick={() => setShowCardModal(true)}
                    title='Открыть карточку героя'
                  >
                    <span className='font-semibold'>{card.name}</span>
                    <span className='font-mono font-bold text-accent'>
                      HP {formatCount(card.hp ?? '0')}/{formatCount(card.derived?.hp_max ?? '1')}
                    </span>
                    {card.derived?.ac && (
                      <span className='text-muted font-mono'>КД {formatCount(card.derived.ac)}</span>
                    )}
                  </button>
                )}
                {exploration && (exploration.effects?.length > 0 || exploration.constraints?.form) && (
                  <div
                    className='flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-semibold text-accent'
                    title={
                      exploration.constraints?.form === 'plant_bush'
                        ? 'Вы в форме куста: нельзя двигаться и говорить'
                        : exploration.effects?.map(e => `${e.label} (${e.remaining_seconds} с)`).join(', ')
                    }
                  >
                    {exploration.constraints?.form === 'plant_bush' ? (
                      <>
                        <span aria-hidden='true'>🌿</span>
                        <span>В форме куста</span>
                      </>
                    ) : (
                      <>
                        <span aria-hidden='true'>✦</span>
                        <span>
                          {exploration.effects.length} {exploration.effects.length === 1 ? 'эффект' : 'эффекта'}
                        </span>
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className='flex items-center gap-2.5 shrink-0'>
                <div className='flex items-center gap-0.5 rounded-lg border border-line-soft bg-surface-2/60 p-0.5' role='group' aria-label='Размер шрифта'>
                  <button
                    type='button'
                    className={`rounded px-2 py-0.5 font-bold transition-colors ${chatFontSize === 'small' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-[11px] leading-none`}
                    onClick={() => handleFontSizeChange('small')}
                    title='Мелкий шрифт (помещается максимум текста)'
                    aria-pressed={chatFontSize === 'small'}
                  >
                    A−
                  </button>
                  <button
                    type='button'
                    className={`rounded px-2 py-0.5 font-bold transition-colors ${chatFontSize === 'medium' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-xs leading-none`}
                    onClick={() => handleFontSizeChange('medium')}
                    title='Обычный шрифт'
                    aria-pressed={chatFontSize === 'medium'}
                  >
                    A
                  </button>
                  <button
                    type='button'
                    className={`rounded px-2 py-0.5 font-bold transition-colors ${chatFontSize === 'large' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-sm leading-none`}
                    onClick={() => handleFontSizeChange('large')}
                    title='Крупный шрифт'
                    aria-pressed={chatFontSize === 'large'}
                  >
                    A+
                  </button>
                </div>
                <SoundControl />
                <SessionControls campaignId={campaignId} compact />
                <button
                  type='button'
                  className='btn btn-outline-copper flex items-center gap-1.5 px-3 py-1 text-xs font-semibold'
                  onClick={() => setIsChatFullscreen(false)}
                  title='Вернуть обычный вид (Esc)'
                  aria-label='Свернуть чат'
                >
                  <span aria-hidden='true'>🗗</span>
                  <span>Свернуть</span>
                </button>
              </div>
            </div>
          ) : (
            <div className='flex items-center justify-between gap-3 border-b border-line px-4 py-2.5 text-xs text-muted'>
              <span className='truncate pr-2'>
                Опишите, что хотите сделать. Мастер учитывает законы мира и сохраняет результат проверки.
              </span>
              <div className='flex items-center gap-2 shrink-0'>
                <div className='flex items-center gap-0.5 rounded-lg border border-line-soft bg-surface-2/60 p-0.5' role='group' aria-label='Размер шрифта'>
                  <button
                    type='button'
                    className={`rounded px-1.5 py-0.5 font-bold transition-colors ${chatFontSize === 'small' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-[11px] leading-none`}
                    onClick={() => handleFontSizeChange('small')}
                    title='Мелкий шрифт (помещается максимум текста)'
                    aria-pressed={chatFontSize === 'small'}
                  >
                    A−
                  </button>
                  <button
                    type='button'
                    className={`rounded px-1.5 py-0.5 font-bold transition-colors ${chatFontSize === 'medium' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-xs leading-none`}
                    onClick={() => handleFontSizeChange('medium')}
                    title='Обычный шрифт'
                    aria-pressed={chatFontSize === 'medium'}
                  >
                    A
                  </button>
                  <button
                    type='button'
                    className={`rounded px-1.5 py-0.5 font-bold transition-colors ${chatFontSize === 'large' ? 'bg-accent/20 text-accent font-semibold' : 'text-muted hover:text-ink'} text-sm leading-none`}
                    onClick={() => handleFontSizeChange('large')}
                    title='Крупный шрифт'
                    aria-pressed={chatFontSize === 'large'}
                  >
                    A+
                  </button>
                </div>
                <button
                  type='button'
                  className='btn btn-ghost flex items-center gap-1.5 px-2 py-1 text-xs text-ink-2 hover:text-ink'
                  onClick={() => setIsChatFullscreen(true)}
                  title='Раскрыть чат на весь экран'
                  aria-label='Раскрыть чат на весь экран'
                >
                  <span aria-hidden='true'>⤢</span>
                  <span>На весь экран</span>
                </button>
              </div>
            </div>
          )}
          <ChatFeed campaignId={campaignId} />
          <Composer />
        </main>
      </div>

      {/* Модальное окно полной карточки героя */}
      {showCardModal && card && (
        <div
          className='fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-xs md:p-6'
          role='dialog'
          aria-modal='true'
          aria-label='Лист героя'
          onMouseDown={e => e.target === e.currentTarget && setShowCardModal(false)}
        >
          <div className='flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl'>
            <header className='flex items-center justify-between border-b border-line px-5 py-3.5 bg-surface-2/40'>
              <div className='min-w-0'>
                <h2 className='truncate font-heading text-lg font-bold text-ink'>
                  {card.name} · Полная карточка героя
                </h2>
                <p className='text-xs text-muted'>
                  Уровень {formatCount(card.level ?? '1')} · Универсальная система v1
                </p>
              </div>
              <button
                type='button'
                className='flex h-8 w-8 items-center justify-center rounded-lg border border-line text-lg leading-none text-muted hover:border-accent hover:text-ink transition-colors'
                onClick={() => setShowCardModal(false)}
                aria-label='Закрыть'
              >
                ×
              </button>
            </header>
            <div className='min-h-0 flex-1 overflow-y-auto p-4 md:p-6'>
              <UniversalHeroCard card={card} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
