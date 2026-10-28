import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { useSession } from '../stores/session';
import Home from './Home';

vi.mock('../components/Header', () => ({ default: ({ children }: { children?: unknown }) => <header>TaleForge{children as never}</header> }));
vi.mock('../lib/api', () => ({ api: async () => [] }));

let client: QueryClient;
afterEach(() => { cleanup(); client?.clear(); useSession.setState({ user: null }); });

function open(path: string, role: 'admin' | 'player') {
  useSession.setState({ user: { id: 'u', name: 'Админ', platform_role: role } as never });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes>
    <Route path='/' element={<Home />} />
  </Routes></MemoryRouter></QueryClientProvider>);
}

it('у администратора нет кнопки новой кампании: игра начинается только из вкладки Миры', async () => {
  open('/', 'admin');
  await screen.findByText('TaleForge');
  expect(screen.queryByText(/\+ Новая кампания/)).toBeNull();
});

it('пустое состояние столов ведёт к выбору мира', async () => {
  open('/', 'admin');
  const link = await screen.findByRole('link', { name: 'Выбрать мир' });
  expect(link.getAttribute('href')).toBe('/?tab=worlds');
});

it('вкладка Миры показывает каталог, а не встроенные пакеты', async () => {
  open('/?tab=worlds', 'admin');
  expect(await screen.findByText(/Пока нет опубликованных миров/)).toBeDefined();
  expect(screen.queryByText(/D&D 5e SRD/)).toBeNull();
});
