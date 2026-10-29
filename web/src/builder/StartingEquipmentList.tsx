import { EquipmentArtworkAt } from '../game/EquipmentArtwork';
import type { ReactNode } from 'react';

export default function StartingEquipmentList({ items, artworkBase, artworkFor }: {
  items: Record<string, unknown>[]; artworkBase?: string; artworkFor?: (item: Record<string, unknown>) => ReactNode;
}) {
  if (!items || !items.length) return null;

  return (
    <ul className='flex flex-col gap-2' aria-label='Стартовое снаряжение'>
      {items.map((item, index) => {
        const kind = String(item.kind ?? 'gear');
        const kindLabel = kind === 'weapon' ? 'Оружие' : kind === 'armor' ? 'Броня' : 'Снаряжение';
        const kindIcon = kind === 'weapon' ? '⚔' : kind === 'armor' ? '🛡' : '🎒';
        const statBadge = kind === 'weapon'
          ? `${String(item.damage_dice ?? '1d6')} · ${item.attack_ability === 'dex' ? 'Ловкость' : 'Сила'}`
          : kind === 'armor'
            ? `+${String(item.defense_bonus ?? '1')} КД`
            : null;
        const hasArtwork = Boolean(artworkFor || (artworkBase && (kind === 'weapon' || kind === 'armor')));
        const hasDetails = Boolean(item.description || item.reason || kind === 'weapon' || kind === 'armor' || hasArtwork);

        return (
          <li key={index}>
            <details className='group rounded-xl border border-line bg-surface-2/40 transition-colors hover:border-line-soft overflow-hidden'>
              <summary className='flex cursor-pointer items-center justify-between gap-3 px-3.5 py-2.5 select-none hover:bg-surface-2/80 transition-colors'>
                <div className='flex items-center gap-2.5 min-w-0'>
                  <span
                    className='flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-line bg-surface text-xs'
                    aria-hidden='true'
                  >
                    {kindIcon}
                  </span>
                  <div className='min-w-0 flex items-baseline gap-2 flex-wrap'>
                    <span className='font-medium text-sm text-ink truncate'>
                      {String(item.name ?? '')}
                    </span>
                    <span className='text-[11px] text-muted'>
                      {kindLabel}
                    </span>
                  </div>
                </div>

                <div className='flex items-center gap-2 shrink-0'>
                  {statBadge && (
                    <span className='rounded bg-surface border border-line-soft px-2 py-0.5 font-mono text-[11px] font-semibold text-accent'>
                      {statBadge}
                    </span>
                  )}
                  {hasDetails && (
                    <span className='text-xs text-muted transition-transform group-open:rotate-180'>
                      ▼
                    </span>
                  )}
                </div>
              </summary>

              {hasDetails && (
                <div className='border-t border-line-soft bg-surface/50 p-3.5 text-xs'>
                  <div className='flex flex-col sm:flex-row gap-4 items-start'>
                    {hasArtwork && (
                      <div className='shrink-0 self-center sm:self-start'>
                        {artworkFor
                          ? artworkFor(item)
                          : artworkBase && (kind === 'weapon' || kind === 'armor') && (
                              <EquipmentArtworkAt
                                endpoint={`${artworkBase}/${kind}/artwork`}
                                name={String(item.name ?? '')}
                                description={String(item.description ?? '')}
                              />
                            )}
                      </div>
                    )}

                    <div className='flex-1 min-w-0 space-y-2.5'>
                      {item.description ? (
                        <p className='leading-relaxed text-ink-2'>{String(item.description)}</p>
                      ) : null}

                      {kind === 'weapon' ? (
                        <p className='text-accent font-medium'>
                          Базовый урон {String(item.damage_dice ?? '1d6')} · {item.attack_ability === 'dex' ? 'Ловкость' : 'Сила'}
                        </p>
                      ) : kind === 'armor' ? (
                        <p className='text-accent font-medium'>
                          Защита +{String(item.defense_bonus ?? '1')}
                        </p>
                      ) : null}

                      {item.reason ? (
                        <div className='border-t border-line-soft/80 pt-2 text-muted leading-relaxed'>
                          <span className='font-semibold text-patina'>Обоснование: </span>
                          {String(item.reason)}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              )}
            </details>
          </li>
        );
      })}
    </ul>
  );
}
