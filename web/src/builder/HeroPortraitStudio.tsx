import { useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { HeroCard } from '../lib/universal';

export default function HeroPortraitStudio({ card, endpoint, onSaved }: {
  card: HeroCard; endpoint: string; onSaved: (card: HeroCard) => void;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const requestKey = useRef<string | null>(null);
  const running = useRef(false);
  async function generate() {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setSaved(false);
    requestKey.current ??= crypto.randomUUID();
    try {
      const result = await api<HeroCard>(endpoint, { body: { request_key: requestKey.current, expected_revision: card.revision } });
      onSaved(result); requestKey.current = null; setSaved(true);
    } catch (err) {
      setError((err as Error).message);
      // An interrupted connection may hide a successful paid request. Replay its key safely.
      const pending = err instanceof ApiError && (err.data as { detail?: { code?: string } })?.detail?.code === 'portrait_pending';
      if (err instanceof ApiError && err.status < 500 && err.status !== 408 && !pending) requestKey.current = null;
    } finally { running.current = false; setBusy(false); }
  }
  return <div className='flex max-w-sm flex-col items-start gap-2' aria-label='Портрет героя'>
    <button type='button' className='btn btn-primary self-start' disabled={busy} onClick={() => void generate()}>
      {busy ? 'Создаю портрет…' : requestKey.current ? 'Проверить результат' : card.portrait_url ? 'Создать другой портрет' : 'Создать портрет'}
    </button>
    <details className='text-xs text-muted'><summary className='w-fit cursor-pointer text-patina'>О генерации портрета</summary>
      <p className='mt-2 leading-relaxed'>Портрет создаётся по сохранённому описанию и используется в игре. Генерация платная: ориентировочно $0,04 за вариант при стандартной модели. {card.editable ? 'Сначала сохраните правки образа. Копии в кампаниях сохраняют свой портрет.' : 'Портрет изменится только у этого игрового героя.'}</p></details>
    {busy && <p role='status' className='text-sm text-patina'>Художник работает над образом. Обычно это занимает некоторое время; прежний портрет остаётся на месте.</p>}
    {saved && <p role='status' className='text-sm text-patina'>Портрет сохранён и готов для игры.</p>}
    {error && <p role='alert' className='workshop-notice'>{error}</p>}
  </div>;
}
