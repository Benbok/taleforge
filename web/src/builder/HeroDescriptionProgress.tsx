import type { HeroDescription } from '../lib/universal';
import { descriptionFields } from './HeroDescriptionForm';

export default function HeroDescriptionProgress({ description }: { description: HeroDescription }) {
  const filled = descriptionFields.filter(({ key }) => description[key]?.trim()).length;
  const percent = filled * 20;
  const ready = !!description.identity.trim();
  return <aside className='workshop-companion card p-6' aria-label='Готовность описания'>
    <div className='flex items-center gap-4'>
      <div className='workshop-progress' role='progressbar' aria-label='Заполненность описания' aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}
        aria-valuetext={`${percent}% — заполнено ${filled} из 5 полей`} style={{ background: `conic-gradient(var(--tf-patina) ${percent}%, var(--tf-border) 0)` }}>
        <span>{percent}<small>%</small></span>
      </div>
      <div><p className='font-heading text-lg'>Образ обретает форму</p><p className='mt-1 text-xs text-muted'>Заполнено {filled} из 5 полей</p></div>
    </div>
    <p className='mt-5 text-sm leading-relaxed text-muted'>{ready ? 'Уже можно начать беседу. Остальные детали добавляйте по желанию.' : 'Начните с поля «Кто ваш герой?». Остальное можно придумать вместе с мастером.'}</p>
    <ul className='my-5 space-y-3 border-y border-line py-5'>{descriptionFields.map(({ key, label }) => {
      const done = !!description[key]?.trim();
      return <li key={key} className={`flex items-center gap-3 text-sm ${done ? 'text-ink' : 'text-muted'}`}>
        <span className={`workshop-check ${done ? 'is-filled' : ''}`} aria-hidden='true'>{done ? '✓' : '·'}</span>
        <span className='flex-1'>{label}</span><span className='sr-only'>{done ? 'Заполнено' : 'Не заполнено'}</span>
      </li>;
    })}</ul>
    <div className='flex gap-3'><span className='workshop-rule-number' aria-hidden='true'>1</span><div><p className='text-sm font-semibold'>Начало большой истории</p>
      <p className='mt-1 text-xs leading-relaxed text-muted'>Каждый герой начинает с первого уровня. Процент показывает полноту описания и не влияет на характеристики.</p></div></div>
    <p className='mt-5 text-xs leading-relaxed text-muted'>После беседы вы увидите предложение мастера и сможете подтвердить карточку.</p>
  </aside>;
}
