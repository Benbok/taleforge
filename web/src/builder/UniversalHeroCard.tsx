import { formatCount } from '../lib/counts';
import { abilityKeys, abilityNames, energyThemes, type HeroCard } from '../lib/universal';
import type { ReactNode } from 'react';
import PortraitPreview from '../components/PortraitPreview';
import StartingEquipmentList from './StartingEquipmentList';

export { energyThemes };

export default function UniversalHeroCard({ card, portraitActions, equipmentActions, equipmentArtworkBase, equipmentArtworkFor, compact = false }: {
  card: HeroCard; portraitActions?: ReactNode; equipmentActions?: ReactNode; equipmentArtworkBase?: string; compact?: boolean;
  equipmentArtworkFor?: (item: Record<string, unknown>) => ReactNode;
}) {
  const description = card.sheet?.description ?? { identity: '', appearance: '', personality: '', capabilities: '' };
  const hpCur = Number(card.hp ?? 0);
  const hpMax = Math.max(1, Number(card.derived?.hp_max ?? 1));
  const hpPct = Math.min(100, Math.max(0, Math.round((hpCur / hpMax) * 100)));

  return (
    <section
      className={`card hero-card-sheet flex flex-col ${compact ? 'gap-3.5 p-3.5 sm:p-4' : 'gap-6 p-5 sm:p-6 md:p-8'}`}
      aria-label='Сохранённая карточка'
    >
      {/* 1. Заголовок героя, портрет и действия */}
      <header className={`flex items-center border-b border-line ${compact ? 'gap-3 pb-3.5' : 'flex-wrap gap-5 pb-6'}`}>
        {card.portrait_url ? (
          <div className='relative flex-shrink-0'>
            {compact ? (
              <img
                src={card.portrait_url}
                alt={card.name}
                className='h-12 w-12 rounded-xl border border-line object-cover shadow-sm'
              />
            ) : (
              <PortraitPreview key={card.portrait_url} url={card.portrait_url} name={card.name} />
            )}
          </div>
        ) : (
          <div
            className={`flex flex-shrink-0 items-center justify-center rounded-2xl border border-line bg-surface-2 font-heading font-bold text-accent shadow-inner ${
              compact ? 'h-12 w-12 text-xl' : 'h-20 w-20 text-3xl'
            }`}
            aria-hidden='true'
          >
            {card.name.slice(0, 1).toUpperCase() || '✧'}
          </div>
        )}
        <div className='min-w-0 flex-1'>
          <div className='flex flex-wrap items-start justify-between gap-x-4 gap-y-2'>
            <div className='min-w-0'>
              <h2 className={`break-words font-heading font-bold tracking-tight text-ink ${compact ? 'text-lg' : 'text-2xl md:text-3xl'}`}>
                {card.name}
              </h2>
              <p className='mt-0.5 text-xs text-muted'>
                Уровень {formatCount(card.level ?? '1')} · Опыт {formatCount(card.sheet?.xp ?? '0')}
              </p>
            </div>
            {portraitActions}
          </div>
          {!compact && (
            <div className='mt-3 flex flex-wrap items-center gap-2'>
              <span className='rounded-full border border-accent/40 bg-accent/10 px-2.5 py-0.5 text-xs font-semibold text-accent'>
                Уровень {formatCount(card.level ?? '1')}
              </span>
              <span className='rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-muted'>
                {formatCount(card.sheet?.xp ?? '0')} XP
              </span>
              <span className='rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-patina'>
                Универсальная система v1
              </span>
            </div>
          )}
        </div>
      </header>

      {/* 2. Нарративный образ */}
      <div className='flex flex-col gap-2.5'>
        <div className={`hero-narrative-quote rounded-xl border border-line-soft bg-surface-2/60 ${compact ? 'p-2.5' : 'p-4'}`}>
          <p className='text-[0.68rem] font-bold uppercase tracking-wider text-patina'>Образ героя</p>
          <p className={`mt-1 whitespace-pre-wrap font-serif leading-relaxed text-ink ${compact ? 'text-xs' : 'text-base'}`}>
            {description.identity}
          </p>
        </div>
        {(description.appearance || description.personality) && (
          <div className={`grid gap-2.5 ${compact ? 'grid-cols-1' : 'sm:grid-cols-2'}`}>
            {description.appearance && (
              <div className='rounded-xl border border-line-soft bg-surface-2/40 p-3'>
                <span className='text-[0.65rem] font-bold uppercase tracking-wider text-muted'>Внешность</span>
                <p className='mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-ink-2'>{description.appearance}</p>
              </div>
            )}
            {description.personality && (
              <div className='rounded-xl border border-line-soft bg-surface-2/40 p-3'>
                <span className='text-[0.65rem] font-bold uppercase tracking-wider text-muted'>Характер</span>
                <p className='mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-ink-2'>{description.personality}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. Жизненные показатели (HP и КД) */}
      <div className={`hero-vitals rounded-xl border border-line bg-surface-2/60 ${compact ? 'p-3' : 'p-4'}`}>
        <div className={compact ? 'flex flex-col gap-2.5' : 'grid grid-cols-1 items-center gap-4 sm:grid-cols-3'}>
          <div className={`${compact ? 'w-full' : 'sm:col-span-2'} flex flex-col gap-2`}>
            <div className='flex items-baseline justify-between'>
              <div className='flex items-center gap-2'>
                <span className='inline-block h-2.5 w-2.5 rounded-full bg-ember' aria-hidden='true' />
                <span className='text-xs font-bold uppercase tracking-wider text-patina'>Жизненные силы (HP)</span>
              </div>
              <p className='font-mono text-sm font-bold text-ink'>
                HP {formatCount(card.hp ?? '0')} / {formatCount(card.derived?.hp_max ?? '1')} {!compact && card.derived?.ac && `· КД ${formatCount(card.derived.ac)}`}
              </p>
            </div>
            <div className='h-3 w-full overflow-hidden rounded-full border border-line bg-surface'>
              <div
                className='h-full rounded-full transition-all duration-300'
                style={{
                  width: `${hpPct}%`,
                  background: 'linear-gradient(90deg, var(--tf-ember), var(--tf-patina))',
                }}
              />
            </div>
          </div>
          {card.derived?.ac && (
            <div className={`flex items-center justify-between rounded-lg border border-line bg-surface px-4 py-2 text-center ${compact ? '' : 'sm:flex-col sm:justify-center'}`}>
              <span className='text-[0.68rem] font-bold uppercase tracking-wider text-muted'>Класс доспеха</span>
              <span className='font-mono text-xl font-bold text-accent'>КД {formatCount(card.derived.ac)}</span>
            </div>
          )}
        </div>
      </div>

      {/* 4. Шесть характеристик */}
      <div>
        <div className='mb-2.5 flex items-center justify-between'>
          <h3 className='text-xs font-bold uppercase tracking-wider text-patina'>Характеристики</h3>
          <span className='text-[11px] text-muted'>Базовый набор</span>
        </div>
        <div className={`grid gap-2 ${compact ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2 sm:grid-cols-3 md:grid-cols-6'}`}>
          {abilityKeys.map(key => {
            const modStr = card.derived?.modifiers?.[key] ?? '0';
            const modVal = BigInt(modStr);
            const modSign = modVal >= 0n ? '+' : '';
            return (
              <div
                className={`hero-stat-card flex flex-col justify-between rounded-xl border border-line bg-surface transition-colors hover:border-patina min-w-0 ${
                  compact ? 'p-2' : 'p-3'
                }`}
                key={key}
              >
                <div className='flex items-center justify-between gap-1 min-w-0'>
                  <div className='text-xs text-muted truncate'>{abilityNames[key]}</div>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[0.68rem] font-mono font-bold ${
                      modVal > 0n
                        ? 'bg-patina/10 text-patina'
                        : modVal < 0n
                          ? 'bg-bad/10 text-bad'
                          : 'bg-surface-2 text-muted'
                    }`}
                  >
                    {modSign}{modStr}
                  </span>
                </div>
                <div className={`${compact ? 'my-1' : 'my-2'} text-center min-w-0 truncate`}>
                  <strong className={`${compact ? 'text-lg' : 'text-xl'} font-bold font-mono text-ink`}>
                    {formatCount(card.sheet?.abilities?.[key] ?? '10')}
                  </strong>
                  <span className='ml-1.5 text-xs text-muted'>
                    ({modSign}{modStr})
                  </span>
                </div>
                <div className='h-1 w-full overflow-hidden rounded-full bg-surface-2'>
                  <div
                    className='h-full bg-accent/60'
                    style={{ width: `${Math.min(100, (Number(card.sheet?.abilities?.[key] ?? 10) / 20) * 100)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 5. Резервы энергий (5 стихий действия) */}
      <div className={`rounded-xl border border-line bg-surface flex flex-col gap-2.5 ${compact ? 'p-3' : 'p-4'}`}>
        <div className='flex items-center justify-between border-b border-line pb-2'>
          <h3 className='text-xs font-bold uppercase tracking-wider text-patina'>Резервы энергий</h3>
          <span className='text-[11px] text-muted'>Пулы сил для действий</span>
        </div>
        <div className={`grid gap-2 ${compact ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5'}`}>
          {abilityKeys.filter(key => key !== 'con').map(key => {
            const cur = Number(card.energies?.[key as keyof typeof card.energies] ?? 0);
            const max = Math.max(1, Number(card.derived?.energy_max?.[key as keyof typeof card.energies] ?? 1));
            const pct = Math.min(100, Math.max(0, Math.round((cur / max) * 100)));
            const theme = energyThemes[key] ?? { color: 'var(--tf-patina)', label: '', short: key.toUpperCase() };
            return (
              <div className='rounded-lg border border-line-soft bg-surface-2/40 p-2.5 flex flex-col gap-1.5 min-w-0' key={key}>
                <div className='flex items-center justify-between gap-1 text-xs sm:text-sm font-medium leading-none text-ink'>
                  <span className='truncate'>{abilityNames[key]}</span>
                  <span className='shrink-0 font-mono text-xs'>
                    {formatCount(card.energies?.[key as keyof typeof card.energies] ?? '0')} / {formatCount(card.derived?.energy_max?.[key as keyof typeof card.energies] ?? '1')}
                  </span>
                </div>
                <div className='h-1.5 w-full overflow-hidden rounded-full bg-surface border border-line-soft'>
                  <div className='h-full transition-all' style={{ width: `${pct}%`, backgroundColor: theme.color }} />
                </div>
                <span className='text-[0.65rem] text-muted truncate'>{theme.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 6. Подробные секции: Возможности, Подготовка, Снаряжение, Освоенные приёмы */}
      <div className={`grid gap-3 ${compact ? 'grid-cols-1' : 'sm:grid-cols-2'}`}>
        <div className='rounded-xl border border-line bg-surface p-3.5 flex flex-col gap-1.5'>
          <h3 className='font-semibold text-xs uppercase tracking-wider text-ink'>Описательные возможности</h3>
          <p className='whitespace-pre-wrap text-xs leading-relaxed text-muted'>
            {description.capabilities || 'Пока не описаны'}
          </p>
        </div>

        <div className='rounded-xl border border-line bg-surface p-3.5 flex flex-col gap-1.5'>
          <h3 className='font-semibold text-xs uppercase tracking-wider text-ink'>Подготовка</h3>
          <p className='text-xs leading-relaxed text-muted'>
            {card.sheet?.trained?.length ? card.sheet.trained.join(', ') : 'Пока не подтверждена'}
          </p>
        </div>

        <div className='rounded-xl border border-line bg-surface p-3.5 flex flex-col gap-1.5'>
          <h3 className='font-semibold text-xs uppercase tracking-wider text-ink'>Снаряжение</h3>
          {card.equipment?.length ? (
            <StartingEquipmentList items={card.equipment} artworkBase={equipmentArtworkBase} artworkFor={equipmentArtworkFor} />
          ) : (
            <p className='text-xs leading-relaxed text-muted'>Пока нет снаряжения</p>
          )}
          {equipmentActions}
        </div>

        <div className='rounded-xl border border-line bg-surface p-3.5 flex flex-col gap-1.5'>
          <h3 className='font-semibold text-xs uppercase tracking-wider text-ink'>Освоенные приёмы</h3>
          {card.learned_abilities?.length ? (
            <div className='flex flex-wrap gap-1.5'>
              {card.learned_abilities.map((item, idx) => (
                <span key={idx} className='rounded-md border border-line bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink'>
                  {String(item.name ?? '')}
                </span>
              ))}
            </div>
          ) : (
            <p className='text-xs leading-relaxed text-muted'>Пока нет освоенных приёмов</p>
          )}
        </div>
      </div>
    </section>
  );
}
