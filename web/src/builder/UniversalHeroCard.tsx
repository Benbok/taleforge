import { formatCount } from '../lib/counts';
import { abilityKeys, abilityNames, type HeroCard } from '../lib/universal';

export default function UniversalHeroCard({ card }: { card: HeroCard }) {
  const description = card.sheet.description;
  return <section className='card flex flex-col gap-4 p-5' aria-label='Сохранённая карточка'>
    <header><h2 className='font-heading text-2xl'>{card.name}</h2>
      <p className='text-sm text-muted'>Уровень {formatCount(card.level)} · Опыт {formatCount(card.sheet.xp ?? '0')}</p></header>
    <p className='whitespace-pre-wrap'>{description.identity}</p>
    {description.appearance && <p className='whitespace-pre-wrap'>Внешность: {description.appearance}</p>}
    {description.personality && <p className='whitespace-pre-wrap'>Характер: {description.personality}</p>}
    <div className='grid grid-cols-2 gap-2 sm:grid-cols-3'>{abilityKeys.map(key =>
      <div className='rounded-lg border border-line p-3' key={key}><div className='text-xs text-muted'>{abilityNames[key]}</div>
        <strong className='text-xl'>{formatCount(card.sheet.abilities[key])}</strong>
        <span className='ml-2 text-sm'>({BigInt(card.derived.modifiers[key]) >= 0n ? '+' : ''}{card.derived.modifiers[key]})</span>
      </div>)}</div>
    <p>HP {formatCount(card.hp)} / {formatCount(card.derived.hp_max)} · КД {formatCount(card.derived.ac)}</p>
    <div className='grid grid-cols-2 gap-2 sm:grid-cols-3'>{abilityKeys.filter(key => key !== 'con').map(key =>
      <p className='text-sm' key={key}>{abilityNames[key]}: {formatCount(card.energies[key as keyof typeof card.energies])} / {formatCount(card.derived.energy_max[key as keyof typeof card.energies])}</p>)}</div>
    <div><h3 className='font-semibold'>Описательные возможности</h3><p className='whitespace-pre-wrap'>{description.capabilities || 'Пока не описаны'}</p></div>
    <div><h3 className='font-semibold'>Подготовка</h3><p>{card.sheet.trained?.join(', ') || 'Пока не подтверждена'}</p></div>
    <div><h3 className='font-semibold'>Снаряжение</h3><p>{card.equipment?.length ? card.equipment.map(item => String(item.name ?? '')).join(', ') : 'Пока нет снаряжения'}</p></div>
    <div><h3 className='font-semibold'>Освоенные приёмы</h3><p>{card.learned_abilities?.length ? card.learned_abilities.map(item => String(item.name ?? '')).join(', ') : 'Пока нет освоенных приёмов'}</p></div>
  </section>;
}
