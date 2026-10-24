import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { HeroCard } from '../lib/universal';
import HeroEquipmentStudio from './HeroEquipmentStudio';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const card = { id: 'hero', revision: 3, editable: true, equipment: [{ kind: 'weapon' }] } as unknown as HeroCard;
const equipment = {
  weapon: { name: 'Лесной клинок', description: 'Клинок путника', reason: 'Подходит образу', kind: 'weapon', damage_dice: '1d6' },
  armor: { name: 'Дорожный жилет', description: 'Плотный жилет', reason: 'Защищает в пути', kind: 'armor', defense_bonus: '1' },
};

it('показывает пересоздание, предпросмотр и сохраняет только после подтверждения', async () => {
  const saved = { ...card, revision: 4 };
  const onSaved = vi.fn();
  const fetch = vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/equipment-proposals')) {
      expect(JSON.parse(String(init.body))).toEqual({ expected_revision: 3 });
      return new Response(JSON.stringify({ id: 'proposal', edit: { starting_equipment: equipment } }));
    }
    expect(path).toBe('/api/me/characters/hero/edit-proposals/proposal/confirm');
    return new Response(JSON.stringify(saved));
  });
  vi.stubGlobal('fetch', fetch);
  render(<HeroEquipmentStudio card={card} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole('button', { name: 'Пересоздать снаряжение' }));
  expect(await screen.findByText('Лесной клинок')).toBeDefined();
  expect(onSaved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Заменить снаряжение' }));
  await screen.findByText('Новое снаряжение сохранено');
  expect(onSaved).toHaveBeenCalledWith(saved);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('сохраняет прежнее при ошибке и скрывает управление для игровой карточки', async () => {
  const onSaved = vi.fn();
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'Мастер недоступен' }), { status: 409 }));
  const page = render(<HeroEquipmentStudio card={card} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole('button', { name: 'Пересоздать снаряжение' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Прежний набор сохранён');
  expect(onSaved).not.toHaveBeenCalled();
  page.rerender(<HeroEquipmentStudio card={{ ...card, editable: false }} onSaved={onSaved} />);
  expect(screen.queryByRole('button')).toBeNull();
});
