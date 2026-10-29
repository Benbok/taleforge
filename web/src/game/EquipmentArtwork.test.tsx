import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EquipmentArtwork from './EquipmentArtwork';

const loaded: string[] = [];
vi.mock('../lib/authedImage', () => ({ useAuthedImageResource: (url: string) => { loaded.push(url); return { src: `blob:${url}`, error: false, retry: () => {} }; } }));
const idle = { status: 'idle', image_url: null as string | null, thumbnail_url: null as string | null, enabled: true, can_generate: true, error: null };
const ready = { ...idle, status: 'ready', image_url: '/original', thumbnail_url: '/thumbnail', can_generate: false };
const props = { campaignId: 'c', heroId: 'hero', itemId: 'sword', name: 'Меч' };
beforeEach(() => {
  loaded.length = 0;
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute('open'); } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('generates only on demand, loads a thumbnail first and opens the original inside the app', async () => {
  let state = idle;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') state = ready;
    return new Response(JSON.stringify(state));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<EquipmentArtwork {...props} />);
  const button = await screen.findByRole('button', { name: 'Создать изображение Меч' });
  expect(fetcher.mock.calls.every(([, init]) => init?.method !== 'POST')).toBe(true);
  fireEvent.click(button);
  expect(await screen.findByRole('img', { name: 'Предмет «Меч»' })).toBeTruthy();
  expect(loaded).toContain('/thumbnail');
  expect(loaded).not.toContain('/original');
  fireEvent.click(screen.getByRole('button', { name: 'Рассмотреть Меч' }));
  expect(await screen.findByRole('dialog', { name: 'Предмет «Меч»' })).toBeTruthy();
  expect(loaded).toContain('/original');
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть иллюстрацию' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('polls an existing pending job without a second generation request', async () => {
  vi.useFakeTimers();
  let state = { ...idle, status: 'pending' };
  const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(state)));
  vi.stubGlobal('fetch', fetcher);
  await act(async () => { render(<EquipmentArtwork {...props} />); });
  expect(screen.getByRole('button').hasAttribute('disabled')).toBe(true);
  state = ready;
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(screen.getByRole('img')).toBeTruthy();
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
});

it('ignores late replies when switching items', async () => {
  let finish: (value: Response) => void = () => undefined;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/sword/')
    ? new Promise<Response>(resolve => { finish = resolve; })
    : new Response(JSON.stringify({ ...ready, image_url: '/armor', thumbnail_url: '/armor-small' }))));
  const page = render(<EquipmentArtwork key='sword' {...props} />);
  page.rerender(<EquipmentArtwork key='armor' {...props} itemId='armor' name='Броня' />);
  expect(await screen.findByRole('img', { name: 'Предмет «Броня»' })).toBeTruthy();
  await act(async () => { finish(new Response(JSON.stringify(ready))); });
  expect(screen.queryByRole('img', { name: 'Предмет «Меч»' })).toBeNull();
});

it('offers a retry after a failed job and hides controls when generation is disabled', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...idle, status: 'failed', error: 'Ошибка генерации' }))));
  const page = render(<EquipmentArtwork {...props} />);
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Создать изображение Меч' })).toBeTruthy();
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...idle, enabled: false, can_generate: false }))));
  page.rerender(<EquipmentArtwork key='disabled' {...props} />);
  await act(async () => {});
  expect(screen.queryByRole('button')).toBeNull();
});

it('lets an admin replace the image while retaining the old thumbnail during generation', async () => {
  let state = { ...ready, can_regenerate: true };
  let finish: (value: Response) => void = () => undefined;
  let body: { regenerate?: boolean } = {};
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      body = JSON.parse(init.body as string);
      state = { ...state, status: 'pending' };
      return new Promise<Response>(resolve => { finish = resolve; });
    }
    return new Response(JSON.stringify(state));
  }));
  render(<EquipmentArtwork {...props} />);
  const button = await screen.findByRole('button', { name: 'Пересоздать изображение Меч' });
  fireEvent.click(button);
  expect(body.regenerate).toBe(true);
  expect(button.hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('img').getAttribute('src')).toBe('blob:/thumbnail');
  state = { ...ready, can_regenerate: true, image_url: '/replacement', thumbnail_url: '/replacement-small' };
  await act(async () => { finish(new Response(JSON.stringify(state))); });
  await waitFor(() => expect(screen.getByRole('img').getAttribute('src')).toBe('blob:/replacement-small'));
});

it('does not offer replacement without administrator permission', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...ready, can_regenerate: false }))));
  render(<EquipmentArtwork {...props} />);
  await screen.findByRole('img');
  expect(screen.queryByRole('button', { name: /Пересоздать изображение/ })).toBeNull();
});
