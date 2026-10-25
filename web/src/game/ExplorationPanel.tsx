export interface ExplorationState {
  game_seconds: string;
  effects: { id: string; kind: string; label: string; remaining_seconds: string }[];
  objects: { id: string; name: string; template: string; owner_id?: string | null;
    capacity_ml: string; contents_ml: string; temporary?: boolean }[];
  constraints: { form: string | null; can_speak: boolean };
}

// Один короткий ход игры равен 6 секундам; срок в ходах понятнее секунд.
function actionsLeft(seconds: string) {
  const n = Math.ceil(Number(seconds) / 6);
  if (!Number.isFinite(n) || n < 1) return '';
  const word = n % 10 === 1 && n % 100 !== 11 ? 'действие'
    : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'действия' : 'действий';
  return ` ≈ ${n} ${word}`;
}

export default function ExplorationPanel({ state }: { state?: ExplorationState | null }) {
  if (!state) return null;
  const hasEffects = Boolean(state.effects && state.effects.length > 0);
  const hasObjects = Boolean(state.objects && state.objects.length > 0);
  const isBush = state.constraints?.form === 'plant_bush';

  return (
    <section className='space-y-2.5 rounded-xl border border-line-soft bg-surface-2/40 p-3 text-xs' aria-label='Состояние приключения'>
      {/* Ограничение формы (например, форма куста) */}
      {isBush && (
        <div className='rounded-lg border border-accent/40 bg-accent/10 p-2.5 text-ink'>
          <div className='flex items-center gap-1.5 font-bold text-accent'>
            <span aria-hidden='true'>🌿</span>
            <span>Вы в форме куста</span>
          </div>
          <p className='mt-1 text-[11px] leading-relaxed text-ink-2'>
            Вы сохраняете чувства, но не можете двигаться, говорить и действовать руками. Дыхание по-прежнему необходимо.
          </p>
          <p className='mt-1.5 text-[10px] text-muted'>
            Чтобы снять превращение раньше срока, напишите об этом мастеру.
          </p>
        </div>
      )}

      {/* Заголовок со сводкой */}
      <div className='flex items-center justify-between text-[11px]'>
        <span className='font-bold uppercase tracking-wider text-patina flex items-center gap-1'>
          <span aria-hidden='true'>✦</span> Эффекты и окружение
        </span>
        <span className='font-mono text-[10px] text-muted'>
          {state.effects?.length ?? 0} эфф. · {state.objects?.length ?? 0} предм.
        </span>
      </div>

      {/* Действующие эффекты */}
      <div>
        <h3 className='text-[10px] font-bold uppercase tracking-wider text-muted mb-1'>Действующие эффекты</h3>
        {!hasEffects && (
          <p className='text-[11px] text-muted italic'>Сейчас нет действующих эффектов.</p>
        )}
        {state.effects?.map(effect => (
          <div key={effect.id} className='mt-1.5 rounded-lg border border-line bg-surface/80 p-2'>
            <div className='flex items-center justify-between gap-1.5'>
              <span className='font-semibold text-ink text-xs'>{effect.label}</span>
              <span className='shrink-0 rounded bg-patina/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-patina'>
                {effect.remaining_seconds} с{actionsLeft(effect.remaining_seconds)}
              </span>
            </div>
            {effect.kind === 'camouflage' && (
              <p className='mt-1 text-[11px] leading-tight text-muted'>
                Помогает скрываться при наличии укрытия. Свидетели помнят героя.
              </p>
            )}
            {effect.kind === 'illumination' && (
              <p className='mt-1 text-[11px] leading-tight text-muted'>
                Освещает место, помогая рассмотреть доступные детали.
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Предметы рядом и при себе */}
      <div>
        <h3 className='text-[10px] font-bold uppercase tracking-wider text-muted mb-1'>Предметы рядом и при себе</h3>
        {!hasObjects && (
          <p className='text-[11px] text-muted italic'>Пока нет известных предметов для взаимодействия.</p>
        )}
        {state.objects?.map(object => (
          <div key={object.id} className='mt-1.5 rounded-lg border border-line bg-surface/80 p-2'>
            <div className='flex items-center justify-between gap-1'>
              <span className='font-medium text-ink text-xs'>{object.name}</span>
              <span className='text-[10px] text-muted font-mono'>
                {object.owner_id ? 'При себе' : 'Рядом'}{object.temporary ? ' · Врем.' : ''}
              </span>
            </div>
            {object.template === 'vessel' && (
              <p className='mt-1 font-mono text-[11px] text-patina'>
                {object.contents_ml} из {object.capacity_ml} мл · вода
              </p>
            )}
          </div>
        ))}
        {hasObjects && (
          <p className='mt-2 text-[10px] leading-relaxed text-muted'>
            Можно попросить мастера взять, наполнить, передать или поставить предмет. Результат сохранится в игре.
          </p>
        )}
      </div>

      {/* Игровое время и примечание */}
      <div className='border-t border-line-soft pt-1.5 text-[10px] leading-tight text-muted'>
        <span className='font-mono'>Игровое время: {state.game_seconds} с.</span> Чтение и переподключение не сокращают срок эффектов.
      </div>
    </section>
  );
}
