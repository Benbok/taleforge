import type { HeroDescription } from '../lib/universal';

const fields = [
  ['name', 'Имя героя'], ['identity', 'Кто ваш герой?'], ['appearance', 'Как он выглядит?'],
  ['personality', 'Какой у него характер?'], ['capabilities', 'Что он умеет?'],
] as const;

export default function HeroDescriptionForm({ value, onChange, disabled = false }: {
  value: HeroDescription; onChange: (value: HeroDescription) => void; disabled?: boolean;
}) {
  return <div className='grid gap-4 sm:grid-cols-2'>{fields.map(([key, label]) =>
    <label key={key} className={`flex flex-col gap-1 text-sm ${key === 'identity' ? 'sm:col-span-2' : ''}`}>
      <span>{label}</span>
      {key === 'name' ? <input className='field' value={value[key] ?? ''} disabled={disabled} maxLength={64}
        onChange={event => onChange({ ...value, [key]: event.target.value })} /> :
        <textarea className='field min-h-24' value={value[key] ?? ''} disabled={disabled} maxLength={4000}
          required={key === 'identity'} onChange={event => onChange({ ...value, [key]: event.target.value })} />}
    </label>)}
    <p className='text-xs text-muted sm:col-span-2'>Достаточно описать, кто ваш герой. Желаемые возможности обсуждаются с мастером и раскрываются в игре.</p>
  </div>;
}
