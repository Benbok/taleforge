import { useId } from 'react';
import type { HeroDescription } from '../lib/universal';

export const descriptionFields = [
  { key: 'name', label: 'Имя героя', hint: 'Имя, прозвище или то, как его знают в мире.', example: 'Например, Ива по прозвищу Лесная', tip: 'Имя можно придумать позже или попросить мастера предложить его в беседе.' },
  { key: 'identity', label: 'Кто ваш герой?', hint: 'Главное о герое: откуда он, чем живёт и к чему стремится.', example: 'Травница, которая покинула родной лес, чтобы найти пропавшего наставника…', tip: 'Начните с простой связки: кто он + чего хочет + что ему мешает. Достаточно пары предложений.' },
  { key: 'appearance', label: 'Как он выглядит?', hint: 'Одна-две детали, по которым героя легко представить.', example: 'Зелёный плащ, растрёпанные волосы и посох с живыми побегами…', tip: 'Одежда, жест, голос или заметная привычка сделают образ живым. Дорожный посох в описании не добавляет предмет в снаряжение.' },
  { key: 'personality', label: 'Какой у него характер?', hint: 'Что он ценит, чего боится и как относится к другим.', example: 'Добра к незнакомцам, упряма в спорах и боится подвести друзей…', tip: 'Небольшое противоречие помогает в игре: смелый, но суеверный; суровый, но заботливый.' },
  { key: 'capabilities', label: 'Что он умеет?', hint: 'Опыт, таланты и задуманные возможности героя.', example: 'Знает целебные травы, читает следы и мечтает управлять лозами…', tip: 'Можно описать и то, чему герой хочет научиться. Мастер поможет связать замысел со стартовыми характеристиками; приёмы раскрываются в игре.' },
] as const;

export default function HeroDescriptionForm({
  value,
  onChange,
  disabled = false,
}: {
  value: HeroDescription;
  onChange: (value: HeroDescription) => void;
  disabled?: boolean;
}) {
  const prefix = useId();
  return (
    <div className='grid gap-6 sm:grid-cols-2'>
      {descriptionFields.map(({ key, label, hint, example, tip }) => {
        const id = `${prefix}-${key}`;
        const isCore = key === 'identity';
        return (
          <div
            key={key}
            className={`flex min-w-0 flex-col gap-2 ${
              key === 'name' || isCore || key === 'capabilities' ? 'sm:col-span-2' : ''
            } ${isCore ? 'rounded-2xl border border-accent/40 bg-surface-2/40 p-4 md:p-5 shadow-sm' : ''}`}
          >
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <label htmlFor={id} className={`text-sm font-semibold ${isCore ? 'text-accent' : 'text-ink'}`}>
                {label}
              </label>
              <span
                className={`text-xs ${
                  isCore
                    ? 'rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 font-medium text-accent'
                    : 'text-muted'
                }`}
              >
                {isCore ? 'Обязательно для старта' : 'Необязательно'}
              </span>
            </div>
            <p id={`${id}-hint`} className='text-xs leading-relaxed text-muted'>
              {hint}
            </p>
            {key === 'name' ? (
              <input
                id={id}
                aria-describedby={`${id}-hint`}
                className='field workshop-field font-medium'
                placeholder={example}
                value={value[key] ?? ''}
                disabled={disabled}
                maxLength={64}
                onChange={event => onChange({ ...value, [key]: event.target.value })}
              />
            ) : (
              <textarea
                id={id}
                aria-describedby={`${id}-hint`}
                className={`field workshop-field ${isCore ? 'min-h-32' : 'min-h-28'}`}
                placeholder={example}
                value={value[key] ?? ''}
                disabled={disabled}
                maxLength={4000}
                required={isCore}
                onChange={event => onChange({ ...value, [key]: event.target.value })}
              />
            )}
            <details className='workshop-tip text-xs text-muted'>
              <summary className='w-fit cursor-pointer rounded py-1 text-patina font-medium transition-colors hover:underline'>
                Подсказка: {label.toLowerCase().replace('?', '')}
              </summary>
              <p className='mt-1 border-l-2 border-patina pl-3 leading-relaxed'>{tip}</p>
            </details>
          </div>
        );
      })}
      <p className='text-xs leading-relaxed text-muted sm:col-span-2'>
        Достаточно описать, кто ваш герой. Желаемые возможности обсуждаются с мастером и раскрываются в игре.
      </p>
    </div>
  );
}
