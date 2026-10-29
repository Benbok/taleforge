import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import StartingEquipmentList from './StartingEquipmentList';

vi.mock('../lib/authedImage', () => ({ useAuthedImageResource: (url: string) => ({ src: `blob:${url}`, error: false, retry: () => {} }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows generation and saved art inside the library equipment details', async () => {
  let ready = false;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') ready = true;
    return new Response(JSON.stringify({ status: ready ? 'ready' : 'idle', enabled: true, can_generate: !ready,
      image_url: ready ? '/original' : null, thumbnail_url: ready ? '/small' : null, error: null }));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<StartingEquipmentList artworkBase='/api/me/characters/lc_hero/equipment' items={[
    { kind: 'weapon', name: 'Тесак', description: 'Изогнутый клинок' },
  ]} />);
  fireEvent.click(screen.getByText('Тесак'));
  fireEvent.click(await screen.findByRole('button', { name: 'Создать изображение Тесак' }));
  expect(await screen.findByRole('img', { name: 'Предмет «Тесак»' })).toBeTruthy();
  expect(fetcher.mock.calls.some(([url, init]) => url === '/api/me/characters/lc_hero/equipment/weapon/artwork' && init?.method === 'POST')).toBe(true);
});
