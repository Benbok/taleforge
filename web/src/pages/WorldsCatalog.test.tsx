import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import WorldsCatalog from './WorldsCatalog';

const calls: { path: string; body?: unknown }[] = [];
const entries = [
  { version_id: 'av1', project_id: 'p1', title: 'Стеклянные острова', author_name: 'Arty', version: 2, published_at: '2026-10-27T10:00:00Z', public_summary: { title: 'Стеклянные острова', intro: 'Гавань ждёт.' } },
  { version_id: 'av2', project_id: 'p2', title: 'Туманный остров', author_name: 'root', version: 1, published_at: '2026-10-26T10:00:00Z', public_summary: { title: 'Туманный остров', intro: '' } },
];
let release: (() => void) | null = null;
vi.mock('../lib/api', () => ({
  api: async (path: string, init?: { body?: unknown }) => {
    calls.push({ path, body: init?.body });
    if (path === '/api/adventures/catalog') return entries;
    if (path.endsWith('/games')) {
      await new Promise<void>((resolve) => { release = resolve; });
      return { campaign_id: 'c1', adventure_version_id: 'av1', url: '/c/c1' };
    }
    return [];
  },
}));

let client: QueryClient;
beforeEach(() => { calls.length = 0; release = null; });
afterEach(() => { cleanup(); client?.clear(); });

function show(isAdmin: boolean) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/']}><Routes>
    <Route path='/' element={<WorldsCatalog isAdmin={isAdmin} />} />
    <Route path='/c/:id/manage' element={<h1>Кабинет</h1>} />
  </Routes></MemoryRouter></QueryClientProvider>);
}

it('показывает карточку каждого опубликованного мира с автором и описанием', async () => {
  show(true);
  expect(await screen.findByText('Стеклянные острова')).toBeDefined();
  expect(screen.getByText('Туманный остров')).toBeDefined();
  expect(screen.getByText('Гавань ждёт.')).toBeDefined();
  expect(screen.getByText(/Arty/)).toBeDefined();
});

it('кнопка запуска есть только у администратора', async () => {
  show(false);
  await screen.findByText('Стеклянные острова');
  expect(screen.queryByRole('button', { name: 'Запустить' })).toBeNull();
});

it('запуск без опций открывает кабинет сессии, повторный клик не создаёт вторую игру', async () => {
  show(true);
  await screen.findByText('Стеклянные острова');
  const [first] = screen.getAllByRole('button', { name: 'Запустить' });
  fireEvent.click(first);
  fireEvent.click(first);
  await waitFor(() => expect(release).not.toBeNull());
  release!();
  expect(await screen.findByRole('heading', { name: 'Кабинет' })).toBeDefined();
  const launches = calls.filter((c) => c.path === '/api/adventures/av1/games');
  expect(launches).toHaveLength(1);
  expect(Object.keys(launches[0].body as object)).toEqual(['request_key']);
});

it('пустой каталог объясняет, что миров ещё нет', async () => {
  entries.length = 0;
  show(true);
  expect(await screen.findByText(/пока нет опубликованных миров/i)).toBeDefined();
});
