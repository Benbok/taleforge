import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { HeroCard } from '../lib/universal';
import HeroPortraitStudio from './HeroPortraitStudio';

const card = { id: 'lc1', name: 'Ива', revision: 3, editable: true, portrait_url: '/api/portraits/old' } as HeroCard;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('generates only on an explicit click and blocks overlapping submissions', async () => {
  let finish!: (value: Response) => void;
  const fetch = vi.fn((_url: string, _init: RequestInit) => new Promise<Response>(resolve => { finish = resolve; }));
  vi.stubGlobal('fetch', fetch);
  const onSaved = vi.fn();
  const page = render(<HeroPortraitStudio card={card} endpoint='/portrait' onSaved={onSaved} />);
  page.rerender(<HeroPortraitStudio card={{ ...card, name: 'Другое имя' }} endpoint='/portrait' onSaved={onSaved} />);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Создать другой портрет' }));
  expect((screen.getByRole('button', { name: 'Создаю портрет…' }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
  const body = JSON.parse(String(fetch.mock.calls[0][1].body));
  expect(body.expected_revision).toBe(3);
  expect(body.request_key).toBeTruthy();
  finish(new Response(JSON.stringify({ ...card, portrait_url: '/api/portraits/new' })));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ portrait_url: '/api/portraits/new' })));
});

it('reuses the paid request key after a lost connection', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('Соединение прервано'))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: 'portrait_pending', message: 'Ещё создаётся' } }), { status: 409 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(card)));
  vi.stubGlobal('fetch', fetch);
  render(<HeroPortraitStudio card={card} endpoint='/portrait' onSaved={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Создать другой портрет' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
  await screen.findByText('Ещё создаётся');
  fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
  await screen.findByText('Портрет сохранён и готов для игры.');
  expect(JSON.parse(fetch.mock.calls[0][1].body).request_key).toBe(JSON.parse(fetch.mock.calls[1][1].body).request_key);
  expect(JSON.parse(fetch.mock.calls[0][1].body).request_key).toBe(JSON.parse(fetch.mock.calls[2][1].body).request_key);
});
