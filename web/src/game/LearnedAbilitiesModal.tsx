import { useState } from 'react';
import { formatCount } from '../lib/counts';
import { abilityNames, type AbilityKey, energyThemes } from '../lib/universal';
import { useDraft } from './draft';

export interface LearnedAbilityItem {
  id: string | number;
  name?: string;
  cost?: string | number;
  resource_key?: string;
  limits?: {
    targets?: string;
    duration?: string;
    conditions?: string[];
  };
  [key: string]: unknown;
}

export interface LearnedAbilitiesModalProps {
  isOpen: boolean;
  onClose: () => void;
  abilities: LearnedAbilityItem[];
  heroName?: string;
  onSelect?: (abilityName: string) => void;
}

export default function LearnedAbilitiesModal({
  isOpen,
  onClose,
  abilities,
  heroName,
  onSelect,
}: LearnedAbilitiesModalProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedResource, setSelectedResource] = useState<'all' | AbilityKey>('all');

  if (!isOpen) return null;

  // Ресурсы, которые встречаются среди способностей героя
  const availableResources = Array.from(
    new Set(
      abilities
        .map(a => String(a.resource_key ?? ''))
        .filter((k): k is AbilityKey => k in abilityNames)
    )
  );

  const filteredAbilities = abilities.filter(ability => {
    const nameMatch =
      !searchTerm ||
      String(ability.name ?? '')
        .toLowerCase()
        .includes(searchTerm.toLowerCase().trim());
    const resourceMatch =
      selectedResource === 'all' || ability.resource_key === selectedResource;
    return nameMatch && resourceMatch;
  });

  const handleApply = (name: string) => {
    if (onSelect) {
      onSelect(name);
    } else {
      useDraft.getState().setText(`Применяю способность «${name}».`);
    }
    onClose();
  };

  return (
    <div
      className='fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-xs md:p-6'
      role='dialog'
      aria-modal='true'
      aria-label='Изученные способности'
      onMouseDown={e => e.target === e.currentTarget && onClose()}
    >
      <div className='flex max-h-[90dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl'>
        {/* Шапка модального окна */}
        <header className='flex items-center justify-between border-b border-line px-5 py-3.5 bg-surface-2/40'>
          <div className='min-w-0'>
            <div className='flex items-center gap-2'>
              <span className='text-accent text-base' aria-hidden='true'>✦</span>
              <h2 className='truncate font-heading text-lg font-bold text-ink'>
                Изученные способности
              </h2>
              <span className='rounded-full border border-patina/40 bg-patina/10 px-2 py-0.5 font-mono text-xs font-bold text-patina'>
                {abilities.length}
              </span>
            </div>
            <p className='text-xs text-muted mt-0.5 truncate'>
              {heroName ? `${heroName} · ` : ''}Нажмите на способность, чтобы подставить её в поле действия
            </p>
          </div>
          <button
            type='button'
            className='flex h-8 w-8 items-center justify-center rounded-lg border border-line text-lg leading-none text-muted hover:border-accent hover:text-ink transition-colors'
            onClick={onClose}
            aria-label='Закрыть'
          >
            ×
          </button>
        </header>

        {/* Панель фильтров и поиска */}
        {abilities.length > 0 && (
          <div className='flex flex-wrap items-center justify-between gap-3 border-b border-line-soft bg-surface px-5 py-2.5'>
            <div className='relative flex-1 min-w-[180px] max-w-xs'>
              <input
                type='search'
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder='Поиск способности...'
                className='input text-xs w-full py-1.5 pl-3 pr-8'
                aria-label='Поиск способности'
              />
              {searchTerm && (
                <button
                  type='button'
                  onClick={() => setSearchTerm('')}
                  className='absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted hover:text-ink'
                  aria-label='Очистить поиск'
                >
                  ×
                </button>
              )}
            </div>
            {/* Быстрые фильтры по ресурсу */}
            {availableResources.length > 1 && (
              <div className='flex flex-wrap items-center gap-1 text-[11px]'>
                <button
                  type='button'
                  onClick={() => setSelectedResource('all')}
                  className={`rounded-md px-2 py-1 font-semibold transition-colors ${
                    selectedResource === 'all'
                      ? 'bg-patina/20 text-patina border border-patina/40'
                      : 'text-muted hover:text-ink border border-transparent'
                  }`}
                >
                  Все ({abilities.length})
                </button>
                {availableResources.map(resKey => {
                  const count = abilities.filter(a => a.resource_key === resKey).length;
                  const theme = energyThemes[resKey] ?? { short: resKey.toUpperCase() };
                  const isSelected = selectedResource === resKey;
                  return (
                    <button
                      key={resKey}
                      type='button'
                      onClick={() => setSelectedResource(isSelected ? 'all' : resKey)}
                      className={`rounded-md px-2 py-1 font-semibold transition-colors ${
                        isSelected
                          ? 'bg-accent/20 text-accent border border-accent/40'
                          : 'text-muted hover:text-ink border border-transparent'
                      }`}
                    >
                      {theme.short} ({count})
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Список способностей */}
        <div className='min-h-0 flex-1 overflow-y-auto p-4 md:p-6'>
          {abilities.length === 0 ? (
            <div className='flex flex-col items-center justify-center py-12 text-center text-muted'>
              <span className='mb-2 text-3xl text-accent/60' aria-hidden='true'>✦</span>
              <p className='font-heading text-base font-bold text-ink'>Способности пока не изучены</p>
              <p className='mt-1 max-w-md text-xs leading-relaxed'>
                В процессе приключения ваш герой открывает новые магические и боевые приёмы. Когда мастер подтвердит успешное использование в сцене, способность закрепится здесь и станет доступна для быстрого применения.
              </p>
            </div>
          ) : filteredAbilities.length === 0 ? (
            <div className='py-8 text-center text-sm text-muted'>
              Ничего не найдено по запросу «{searchTerm}».
            </div>
          ) : (
            <div className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
              {filteredAbilities.map(ability => {
                const limits = ability.limits as { targets?: string; duration?: string; conditions?: string[] } | undefined;
                const resKey = String(ability.resource_key ?? '');
                const theme = energyThemes[resKey];
                const resName = abilityNames[resKey as AbilityKey] ?? (resKey ? resKey.toUpperCase() : 'Ресурс');
                const name = String(ability.name ?? 'Безымянная способность');

                return (
                  <div
                    key={String(ability.id)}
                    className='group flex flex-col justify-between gap-3 rounded-xl border border-line bg-surface-2/30 p-3.5 transition hover:border-accent/50 hover:bg-surface-2/60'
                  >
                    <div className='space-y-1.5'>
                      <div className='flex items-start justify-between gap-2'>
                        <h3 className='font-heading text-sm font-bold text-ink group-hover:text-accent transition-colors'>
                          {name}
                        </h3>
                        {ability.cost !== undefined && (
                          <span
                            className='shrink-0 rounded-md border border-line-soft bg-surface px-2 py-0.5 text-[11px] font-semibold text-patina'
                            style={theme?.color ? { color: theme.color, borderColor: `${theme.color}40` } : undefined}
                          >
                            {formatCount(String(ability.cost))} {theme?.short ?? resName}
                          </span>
                        )}
                      </div>
                      {ability.cost !== undefined && (
                        <p className='text-xs text-patina'>
                          Цена: {formatCount(String(ability.cost))} · {resName}
                        </p>
                      )}
                      {limits && (
                        <p className='text-xs text-muted leading-relaxed'>
                          Целей: {limits.targets ?? '1'} · Длительность: {limits.duration ?? '0'} сек
                          {limits.conditions?.length ? ` · ${limits.conditions.join('; ')}` : ' · Без особых условий'}
                        </p>
                      )}
                    </div>
                    <button
                      type='button'
                      className='btn btn-outline-copper flex w-full items-center justify-center gap-1.5 py-1.5 text-xs font-semibold'
                      title='Подставить намерение в сообщение. Мастер проверит применение в текущей сцене.'
                      aria-label={name}
                      onClick={() => handleApply(name)}
                    >
                      <span>✦ Применить</span>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
