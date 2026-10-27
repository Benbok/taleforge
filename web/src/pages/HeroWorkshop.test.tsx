import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import LibraryHeroPage from './LibraryHeroPage';
import CampaignHeroPage from './CampaignHeroPage';

const description = { name: 'Ива', identity: 'Маг растений', appearance: '', personality: '', capabilities: 'Лозы' };
const abilities = { str: '8', dex: '12', con: '14', int: '13', wis: '15', cha: '10' };
const explanations = { str: 'Слаба', dex: 'Координация', con: 'Походы', int: 'Знания', wis: 'Магия', cha: 'Общение' };
const equipment = {
  weapon: { kind: 'weapon', name: 'Посох травницы', description: 'Дорожный посох', reason: 'Для лесных походов', attack_ability: 'str', damage_dice: '1d6' },
  armor: { kind: 'armor', name: 'Стёганый жилет', description: 'Дорожная защита', reason: 'Для путешествий', defense_bonus: '1' },
};
const original = { id: 'lc1', name: 'Ива', revision: 1, level: '1', editable: true,
  sheet: { description, abilities, xp: '0', trained: [], rules_version: 'universal.v1' },
  derived: { hp_max: '24', ac: '13', modifiers: { str: '-1', dex: '1', con: '2', int: '1', wis: '2', cha: '0' },
    energy_max: { str: '18', dex: '22', int: '23', wis: '25', cha: '20' } },
  hp: '24', energies: { str: '18', dex: '22', int: '23', wis: '25', cha: '20' }, equipment: [], learned_abilities: [] };
const clients: QueryClient[] = [];
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

it('не показывает служебные инструкции как реплики мастера в сохранённой беседе', async () => {
  const draft = { id: 'hd1', revision: 2, status: 'questions', description,
    proposal: null, campaign_id: null, hero_id: null,
    transcript: [
      { role: 'system', content: 'Adapt only this campaign copy; preserve starting scores and equipment.' },
      { role: 'assistant', content: 'Как герой использует свои знания в этом мире?' },
    ] };
  vi.stubGlobal('fetch', async () => response(draft));
  open('/heroes/new?dialogue=hd1');
  expect(await screen.findByText('Как герой использует свои знания в этом мире?')).toBeTruthy();
  expect(screen.queryByText(/Adapt only this campaign copy/)).toBeNull();
});
function open(path = '/heroes/new') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(qc);
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes>
    <Route path='/heroes/:hid' element={<LibraryHeroPage />} />
    <Route path='/c/:id/hero' element={<CampaignHeroPage />} />
  </Routes></MemoryRouter></QueryClientProvider>);
}
afterEach(() => { cleanup(); clients.splice(0).forEach(q => q.clear()); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('counts nonblank description fields without requiring optional details to start', async () => {
  vi.stubGlobal('fetch', async () => response([]));
  open();
  const progress = screen.getByRole('progressbar', { name: 'Заполненность описания' });
  const submit = screen.getByRole('button', { name: 'Обсудить с мастером' }) as HTMLButtonElement;
  expect(progress.getAttribute('aria-valuenow')).toBe('0');
  expect(submit.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Имя героя'), { target: { value: '   ' } });
  expect(progress.getAttribute('aria-valuenow')).toBe('0');
  fireEvent.change(screen.getByLabelText('Кто ваш герой?'), { target: { value: 'Травница' } });
  expect(progress.getAttribute('aria-valuenow')).toBe('20');
  expect(submit.disabled).toBe(false);
  for (const label of ['Имя героя', 'Как он выглядит?', 'Какой у него характер?', 'Что он умеет?']) {
    fireEvent.change(screen.getByLabelText(label), { target: { value: 'Деталь' } });
  }
  expect(progress.getAttribute('aria-valuenow')).toBe('100');
  fireEvent.change(screen.getByLabelText('Кто ваш герой?'), { target: { value: ' ' } });
  expect(progress.getAttribute('aria-valuenow')).toBe('80');
  expect(submit.disabled).toBe(true);
  await screen.findByText('Каким будет ваш герой?');
});

it('offers field examples and expandable hints while preserving entered text', async () => {
  vi.stubGlobal('fetch', async () => response([]));
  open();
  const identity = screen.getByLabelText('Кто ваш герой?') as HTMLTextAreaElement;
  expect(identity.placeholder).toContain('Травница');
  expect(identity.getAttribute('aria-describedby')).toBeTruthy();
  fireEvent.change(identity, { target: { value: 'Мой собственный замысел' } });
  const hint = screen.getByText('Подсказка: кто ваш герой');
  fireEvent.click(hint);
  expect(hint.closest('details')?.open).toBe(true);
  expect(screen.getByText(/Начните с простой связки/)).toBeTruthy();
  expect(identity.value).toBe('Мой собственный замысел');
  expect(screen.getByRole('list', { name: 'Этапы создания героя' }).querySelector('[aria-current="step"]')?.textContent).toContain('Замысел');
  await screen.findByText('Каким будет ваш герой?');
});

it('confirms deleting only the selected saved draft and keeps it deleted after reopening', async () => {
  let drafts = [{ id: 'hd1', revision: 2, status: 'ready', description, campaign_id: null },
    { id: 'hd2', revision: 1, status: 'questions', description: { ...description, name: 'Бран' }, campaign_id: null }];
  const deleted: string[] = [];
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    if (path === '/api/hero-creation/dialogues' && init.method === 'GET') return response(drafts);
    if (path === '/api/hero-creation/dialogues/hd1?expected_revision=2' && init.method === 'DELETE') {
      deleted.push('hd1'); drafts = drafts.filter(d => d.id !== 'hd1');
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected ${init.method} ${path}`);
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const page = open();
  const row = await screen.findByRole('article', { name: 'Черновик: Ива' });
  fireEvent.click(within(row).getByRole('button', { name: 'Удалить' }));
  expect(deleted).toEqual([]);
  confirm.mockReturnValue(true);
  fireEvent.click(within(row).getByRole('button', { name: 'Удалить' }));
  await waitFor(() => expect(screen.queryByRole('article', { name: 'Черновик: Ива' })).toBeNull());
  expect(deleted).toEqual(['hd1']);
  expect(screen.getByRole('button', { name: 'Продолжить: Бран' })).toBeTruthy();
  page.unmount(); open();
  expect(await screen.findByRole('button', { name: 'Продолжить: Бран' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Продолжить: Ива' })).toBeNull();
});

it('deletes an opened draft and returns to the creation form', async () => {
  const draft = { id: 'hd1', revision: 2, status: 'ready', description, transcript: [],
    proposal: { abilities, explanations, equipment }, campaign_id: null, hero_id: null };
  let deleted = false;
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    if (path === '/api/hero-creation/dialogues/hd1' && init.method === 'GET') return response(draft);
    if (path === '/api/hero-creation/dialogues/hd1?expected_revision=2' && init.method === 'DELETE') {
      deleted = true; return new Response(null, { status: 204 });
    }
    if (path === '/api/hero-creation/dialogues') return response([]);
    throw new Error(`Unexpected ${init.method} ${path}`);
  });
  open('/heroes/new?dialogue=hd1');
  fireEvent.click(await screen.findByRole('button', { name: 'Удалить' }));
  expect(await screen.findByRole('button', { name: 'Обсудить с мастером' })).toBeTruthy();
  expect(deleted).toBe(true);
  expect(screen.queryByRole('heading', { name: 'Беседа с мастером' })).toBeNull();
});

it('creates, previews manual and chat changes, confirms, and reloads the same hero', async () => {
  let card = structuredClone(original);
  const draft = { id: 'hd1', revision: 2, status: 'ready', description,
    proposal: { abilities, explanations, equipment }, transcript: [], campaign_id: null, hero_id: null };
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    const method = init.method;
    if (path === '/api/hero-creation/dialogues' && method === 'GET') return response([]);
    if (path === '/api/hero-creation/dialogues' || path === '/api/hero-creation/dialogues/hd1') return response(draft);
    if (path.endsWith('/hd1/confirm')) return response({ hero_id: 'lc1' });
    if (path === '/api/me/characters/lc1' && method === 'GET') return response(card);
    if (path === '/api/me/characters/lc1' && method === 'PATCH') {
      const body = JSON.parse(String(init.body));
      card = { ...card, revision: card.revision + 1, sheet: { ...card.sheet,
        description: { ...card.sheet.description, ...body.edit.description_patch }, abilities: body.edit.base_scores } };
      return response(card);
    }
    if (path.endsWith('/edit-proposals')) return response({ id: 'edit1', edit: { expected_revision: card.revision,
      description_patch: { ...card.sheet.description, name: 'Новая Ива' }, base_scores: card.sheet.abilities }, explanations });
    if (path.endsWith('/edit1/confirm')) {
      card = { ...card, name: 'Новая Ива', revision: card.revision + 1,
        sheet: { ...card.sheet, description: { ...card.sheet.description, name: 'Новая Ива' } } };
      return response(card);
    }
    throw new Error(`Unexpected ${method} ${path}`);
  });
  open();
  fireEvent.change(await screen.findByLabelText('Кто ваш герой?'), { target: { value: 'Маг растений' } });
  fireEvent.click(screen.getByRole('button', { name: 'Обсудить с мастером' }));
  expect(await screen.findByText('Слаба')).toBeTruthy();
  expect(screen.getByText('Посох травницы')).toBeTruthy();
  expect(screen.getByText('Стёганый жилет')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить героя' }));
  expect(await screen.findByRole('heading', { name: 'Ива', level: 2 })).toBeTruthy();
  expect(within(screen.getByRole('heading', { name: 'Ива', level: 2 }).closest('header')!)
    .getByRole('button', { name: 'Создать портрет' })).toBeTruthy();
  expect(screen.queryByRole('spinbutton')).toBeNull();
  fireEvent.change(screen.getByLabelText('Как он выглядит?'), { target: { value: 'Зелёный плащ' } });
  fireEvent.change(screen.getByLabelText('Сила: значение'), { target: { value: '12' } });
  expect((screen.getByLabelText('Ловкость: значение') as HTMLSelectElement).value).toBe('8');
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр правок' }));
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить правки' }));
  expect(await screen.findByText('Сохранено')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Правка через мастера'), { target: { value: 'Измени имя' } });
  fireEvent.click(screen.getByRole('button', { name: 'Предложить версию' }));
  expect(await screen.findByText('Новая Ива')).toBeTruthy();
  expect(card.name).toBe('Ива');
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить правки' }));
  expect(await screen.findByRole('heading', { name: 'Новая Ива', level: 2 })).toBeTruthy();
  cleanup(); open('/heroes/lc1');
  expect(await screen.findByRole('heading', { name: 'Новая Ива', level: 2 })).toBeTruthy();
  expect((screen.getByLabelText('Как он выглядит?') as HTMLTextAreaElement).value).toBe('Зелёный плащ');
});

it('keeps unsaved text when the server rejects a stale revision', async () => {
  vi.stubGlobal('fetch', async (_path: string, init: RequestInit) =>
    init.method === 'PATCH' ? response({ detail: 'Карточка изменилась' }, 409) : response(original));
  open('/heroes/lc1');
  fireEvent.change(await screen.findByLabelText('Как он выглядит?'), { target: { value: 'Мой черновик' } });
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр правок' }));
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить правки' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Карточка изменилась');
  expect((screen.getByLabelText('Как он выглядит?') as HTMLTextAreaElement).value).toBe('Мой черновик');
});

it('binds unsaved form values to their original revision across background refresh', async () => {
  let submittedRevision: number | null = null;
  vi.stubGlobal('fetch', async (_path: string, init: RequestInit) => {
    if (init.method === 'PATCH') {
      submittedRevision = JSON.parse(String(init.body)).edit.expected_revision;
      return response({ detail: 'Карточка изменилась' }, 409);
    }
    return response(original);
  });
  open('/heroes/lc1');
  fireEvent.change(await screen.findByLabelText('Как он выглядит?'), { target: { value: 'Мой черновик' } });
  await act(async () => { clients.at(-1)!.setQueryData(['library', 'lc1'], { ...original, name: 'Обновлённый образ', revision: 2 }); });
  await screen.findByRole('heading', { name: 'Обновлённый образ', level: 2 });
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр правок' }));
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить правки' }));
  await screen.findByRole('alert');
  expect(submittedRevision).toBe(1);
  expect((screen.getByLabelText('Как он выглядит?') as HTMLTextAreaElement).value).toBe('Мой черновик');
});

it('starts a compatibility dialogue before adding the library copy', async () => {
  const writes: string[] = [];
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    if (init.method !== 'GET') writes.push(path);
    if (path === '/api/campaigns/c1') return response({ id: 'c1', name: 'Тест', ruleset_id: 'universal', my_seat_id: 's1', my_role: 'player' });
    if (path === '/api/me/characters') return response([original]);
    if (path === '/api/campaigns/c1/characters') return response([]);
    if (path === '/api/hero-creation/dialogues') return response([]);
    if (path.endsWith('/from-library/lc1/admission')) return response({ id: 'admission1' }, 201);
    if (path === '/api/hero-creation/dialogues/admission1') return response({ id: 'admission1', status: 'questions', revision: 1, description: original.sheet.description, transcript: [{ role: 'assistant', content: 'Как герой оказался здесь?' }], proposal: null });
    throw new Error(`Unexpected ${init.method} ${path}`);
  });
  open('/c/c1/hero');
  fireEvent.click(await screen.findByRole('button', { name: 'Ива: проверить совместимость' }));
  expect(await screen.findByText('Как герой оказался здесь?')).toBeTruthy();
  expect(writes).toEqual(['/api/campaigns/c1/characters/from-library/lc1/admission']);
});
