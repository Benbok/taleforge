import type { RollCard, UniversalRollEvidence } from '../lib/types';
import { abilityNames, type AbilityKey } from '../lib/universal';
import RichText from './RichText';

export default function UniversalRollProof({ card, proof }: { card: RollCard; proof: UniversalRollEvidence }) {
  const failed = ['fail', 'crit_fail', 'miss', 'fumble'].includes(card.outcome);
  const label = card.outcome === 'crit_success' ? 'Критический успех' : card.outcome === 'crit_fail' ? 'Критический провал' : failed ? 'Провал' : 'Успех';
  return (
    <section className='tf-pop tf-roll-proof mx-auto w-full max-w-xl rounded-xl border border-line bg-surface p-4 shadow-sm' aria-label={card.title}>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div>
          <p className='text-[10px] font-semibold uppercase tracking-wider text-patina'>{proof.automatic ? 'Результат сервера' : 'Бросок сервера'} · {card.who ?? 'Герой'}</p>
          <h3 className='font-heading font-semibold text-ink'>{card.title}</h3>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${failed ? 'border-bad/40 text-bad' : 'border-ok/40 text-ok'}`}>
          {label}
        </span>
      </div>
      <div className='mt-3 flex flex-wrap gap-2' aria-label='Выпавшие кубики'>
        {proof.draws.map((die, index) => (
          <span key={index} aria-label={`d${die.sides}: выпало ${die.value}`} className='flex h-14 min-w-14 flex-col items-center justify-center rounded-lg border border-accent/50 bg-raised px-2 font-mono'>
            <span className='text-[9px] text-muted'>d{die.sides}</span>
            <span className='text-xl font-bold text-accent'>{die.value}</span>
          </span>
        ))}
      </div>
      {proof.checks.map((check, index) => {
        const modifier = BigInt(check.modifier);
        const equation = `${check.natural} ${modifier < 0n ? '−' : '+'} ${modifier < 0n ? -modifier : modifier} = ${check.total}`;
        return (
          <div key={index} className='mt-3 rounded-lg border border-line bg-bg/50 px-3 py-2 text-sm'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <span className='font-mono font-semibold text-ink'>{equation}</span>
              <span className={check.success ? 'text-ok' : 'text-bad'}>{check.critical ? 'Критический успех' : check.critical_failure ? 'Критический провал' : check.success ? 'Успех' : 'Провал'}</span>
            </div>
            <p className='mt-1 text-xs text-muted'>
              {check.kind === 'resistance' ? 'Сопротивление · ' : ''}
              {abilityNames[check.attribute as AbilityKey] ?? check.attribute}
              {proof.checks.length > 1 && check.target_name ? ` · ${check.target_name}` : ''}
              {check.difficulty != null ? ` · Сложность ${check.difficulty}` : ''}
              {check.mode === 'advantage' ? ' · преимущество' : check.mode === 'disadvantage' ? ' · помеха' : ''}
            </p>
            {(check.critical || check.critical_failure) && <p className='mt-1 text-xs text-muted'>
              Натуральная {check.critical ? '20' : '1'} — {check.critical ? 'критический успех' : 'критический провал'} независимо от суммы и сложности.
            </p>}
          </div>
        );
      })}
      {proof.legacy && <p className='mt-2 text-xs text-muted'>Ранее сохранённые броски: {proof.legacy_draws?.join(', ')}{proof.legacy_total ? ` · итог ${proof.legacy_total}` : ''}. Подробный разбор в старой квитанции отсутствует.</p>}
      <p className='mt-3 text-xs text-muted'>Энергия: {proof.cost === '0' ? 'не потрачена' : `−${proof.cost}`}{proof.damage !== '0' ? ` · Урон: ${proof.damage}` : ''}</p>
      {proof.source_kind === 'supernatural' && <p className='mt-1 text-xs text-patina'>Магия · {proof.automatic ? 'Без проверки кубиком' : 'С проверкой'}{proof.ability_ref ? ' · Способность изучена' : ''}</p>}
      {proof.description && <div className='mt-3 rounded-lg border border-patina/30 bg-patina/5 p-3 text-sm leading-relaxed'>
        <p className='mb-1 text-[10px] font-semibold uppercase tracking-wider text-patina'>Результат действия</p>
        <RichText text={proof.description} />
      </div>}
      <details className='mt-2 text-[11px] text-muted'>
        <summary className='cursor-pointer'>Сохранённый результат</summary>
        <p className='mt-1 break-all font-mono'>Квитанция {proof.receipt_id} · версия правил {proof.revision}</p>
        <p>Числа взяты из журнала сервера. Повтор ответа мастера не перебрасывает кубики.</p>
      </details>
    </section>
  );
}
