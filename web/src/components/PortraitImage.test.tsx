import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Avatar from './Avatar';
import { setToken } from '../lib/api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setToken(null); });

it('loads a protected player portrait with the session token and retains initials on image failure', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('image', { headers: { 'Content-Type': 'image/png' } }));
  vi.stubGlobal('fetch', fetch);
  URL.createObjectURL = vi.fn(() => 'blob:portrait');
  URL.revokeObjectURL = vi.fn();
  setToken('test-only');
  render(<Avatar name='Ива Лесная' role='player' occupant='human' presence={null} portraitUrl='/api/portraits/hp1' />);
  const image = await screen.findByRole('img', { name: 'Портрет: Ива Лесная' });
  expect(image.getAttribute('src')).toBe('blob:portrait');
  expect(fetch).toHaveBeenCalledWith('/api/portraits/hp1', { headers: { Authorization: 'Bearer test-only' } });
  fireEvent.error(image);
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByText('ИЛ')).toBeTruthy();
});
