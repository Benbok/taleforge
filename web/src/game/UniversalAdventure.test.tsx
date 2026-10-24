import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { useGame } from '../stores/game';
import { useDraft } from './draft';
import UniversalAdventure from './UniversalAdventure';

vi.mock('../components/Header', () => ({ default: ({ children }: { children: React.ReactNode }) => <header>{children}</header> }));
vi.mock('../components/ConnectionBanner', () => ({ default: () => null }));
vi.mock('./ChatFeed', () => ({ default: () => <div>Лента приключения</div> }));
vi.mock('./Composer', () => ({ default: () => <textarea aria-label='Намерение' /> }));
vi.mock('./SessionControls', () => ({ default: () => null }));
vi.mock('./SoundControl', () => ({ default: () => null }));
vi.mock('../builder/UniversalHeroCard', () => ({ default: () => <div>Полная карточка</div> }));

afterEach(() => { cleanup(); useGame.setState(useGame.getInitialState(), true); useDraft.setState(useDraft.getInitialState(), true); });

it('показывает сохранённое состояние, полное место и изученную способность после reconnect', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота и мост над туманом.' } } as never,
    sheet: { name: 'Ива', hp: '19', derived: { hp_max: '22' }, sheet: { rules_version: 'universal.v1' },
      learned_abilities: [{ id: 'a', name: 'Зелёный свет', profile_ref: 'green', profile_revision: '1',
        cost: '3', resource_key: 'wis', limits: { targets: '1', duration: '1', conditions: [] } }] } as never,
  });
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  expect(screen.getByText('Перед вами ворота и мост над туманом.')).toBeDefined();
  expect(screen.getByText('HP 19 / 22')).toBeDefined();
  expect(screen.getByText('Цена: 3 · Мудрость')).toBeDefined();
  expect(screen.getByText(/Целей: 1 · Длительность: 1 шаг/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Зелёный свет' }));
  expect(useDraft.getState().text).toBe('Применяю способность «Зелёный свет».');
});

it('предлагает добавить героя и не выдумывает изученные способности', () => {
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'Выбрать или создать героя' }).getAttribute('href')).toBe('/c/c/hero');
  expect(screen.queryByRole('button', { name: 'Зелёный свет' })).toBeNull();
});
