import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { useSession } from '../stores/session';
import Home from './Home';

vi.mock('../components/Header', () => ({ default: () => <header>TaleForge</header> }));
vi.mock('../lib/api', () => ({ api: async (path: string) => path === '/api/me/characters' ? [
  { id: 'new-hero', name: 'Ива', level: '1', editable: true, sheet: { rules_version: 'universal.v1' } },
  { id: 'old-hero', name: 'Бран', level: 1, errors: ['Нужно имя'] },
] : [] }));

let client: QueryClient;
afterEach(() => { cleanup(); client?.clear(); useSession.setState({ user: null }); });

it('открывает библиотеку универсальных героев без legacy errors и позволяет начать создание', async () => {
  useSession.setState({ user: { id: 'u', name: 'Игрок', platform_role: 'player' } as never });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/?tab=heroes']}><Routes>
    <Route path='/' element={<Home />} />
    <Route path='/heroes/new' element={<h1>Создание героя</h1>} />
  </Routes></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole('link', { name: 'Ива' })).toBeDefined();
  expect(screen.getByText('1 незаполненных параметров')).toBeDefined();
  fireEvent.click(screen.getByRole('link', { name: '+ Собрать нового героя' }));
  expect(await screen.findByRole('heading', { name: 'Создание героя' })).toBeDefined();
});
