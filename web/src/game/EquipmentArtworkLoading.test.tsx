import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import EquipmentArtwork from './EquipmentArtwork';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('recovers thumbnail and original downloads without regenerating the image', async () => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute('open'); } });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:downloaded');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  const attempts = { thumbnail: 0, original: 0 };
  const fetcher = vi.fn(async (url: string) => {
    if (url === '/thumbnail' || url === '/original') {
      const key = url.slice(1) as keyof typeof attempts;
      attempts[key] += 1;
      return attempts[key] === 1 ? new Response('temporary failure', { status: 503 }) : new Response(new Blob(['image']));
    }
    return new Response(JSON.stringify({ status: 'ready', image_url: '/original', thumbnail_url: '/thumbnail', enabled: true, can_generate: false, error: null }));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<EquipmentArtwork campaignId='c' heroId='hero' itemId='sword' name='Меч' />);
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку' }));
  expect(await screen.findByRole('img', { name: 'Предмет «Меч»' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Рассмотреть Меч' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(await within(dialog).findByRole('button', { name: 'Повторить загрузку' }));
  expect(await within(dialog).findByRole('img')).toBeTruthy();
  expect(attempts).toEqual({ thumbnail: 2, original: 2 });
});
