export default function StartingEquipmentList({ items }: { items: Record<string, unknown>[] }) {
  return <ul className='grid gap-3 sm:grid-cols-2' aria-label='Стартовое снаряжение'>{items.map((item, index) =>
    <li key={index} className='rounded-xl border border-line bg-surface-2 p-3'>
      <p className='text-xs font-semibold uppercase tracking-wider text-patina'>{item.kind === 'weapon' ? 'Оружие' : item.kind === 'armor' ? 'Броня' : 'Снаряжение'} · обычное</p>
      <p className='mt-1 text-sm font-semibold text-ink'>{String(item.name ?? '')}</p>
      <p className='mt-2 text-xs leading-relaxed text-muted'>{String(item.description ?? '')}</p>
      <p className='mt-2 text-xs text-accent'>{item.kind === 'weapon' ? `Базовый урон ${String(item.damage_dice ?? '1d6')} · ${item.attack_ability === 'dex' ? 'Ловкость' : 'Сила'}` : `Защита +${String(item.defense_bonus ?? '1')}`}</p>
      {!!item.reason && <p className='mt-2 border-t border-line-soft pt-2 text-xs leading-relaxed text-muted'>{String(item.reason)}</p>}
    </li>)}</ul>;
}
