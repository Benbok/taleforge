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
  expect(screen.getByText(/Целей: 1 · Длительность: 1 сек/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Зелёный свет' }));
  expect(useDraft.getState().text).toBe('Применяю способность «Зелёный свет».');
});

it('открывает и закрывает полную карточку героя в модальном окне', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота.' } } as never,
    sheet: { name: 'Ива', hp: '19', derived: { hp_max: '22', ac: '14' }, sheet: { rules_version: 'universal.v1' } } as never,
  });
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  expect(screen.queryByRole('dialog', { name: 'Лист героя' })).toBeNull();

  // Открываем модальное окно
  fireEvent.click(screen.getByRole('button', { name: /Карточка героя и снаряжение/ }));
  expect(screen.getByRole('dialog', { name: 'Лист героя' })).toBeDefined();
  expect(screen.getByText('Ива · Полная карточка героя')).toBeDefined();

  // Закрываем кнопкой "×"
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
  expect(screen.queryByRole('dialog', { name: 'Лист героя' })).toBeNull();
});

it('раскрывает чат на весь экран и сворачивает обратно', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота.' } } as never,
    sheet: { name: 'Ива', hp: '19', derived: { hp_max: '22', ac: '14' }, sheet: { rules_version: 'universal.v1' } } as never,
  });
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);

  // Находим кнопку раскрытия на весь экран
  const expandBtn = screen.getByRole('button', { name: 'Раскрыть чат на весь экран' });
  expect(expandBtn).toBeDefined();

  // Раскрываем чат
  fireEvent.click(expandBtn);
  const collapseBtn = screen.getByRole('button', { name: 'Свернуть чат' });
  expect(collapseBtn).toBeDefined();

  // Сворачиваем обратно
  fireEvent.click(collapseBtn);
  expect(screen.getByRole('button', { name: 'Раскрыть чат на весь экран' })).toBeDefined();
});

it('переключает масштаб шрифта чата и сохраняет выбор в localStorage', () => {
  localStorage.clear();
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота.' } } as never,
    sheet: { name: 'Ива', hp: '19', derived: { hp_max: '22', ac: '14' }, sheet: { rules_version: 'universal.v1' } } as never,
  });
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);

  // Нажимаем A- для компактного шрифта
  const smallBtn = screen.getByRole('button', { name: 'A−' });
  fireEvent.click(smallBtn);
  expect(localStorage.getItem('tf_chat_font_size')).toBe('small');

  // Нажимаем A+ для крупного шрифта
  const largeBtn = screen.getByRole('button', { name: 'A+' });
  fireEvent.click(largeBtn);
  expect(localStorage.getItem('tf_chat_font_size')).toBe('large');
});

it('предлагает добавить героя и не выдумывает изученные способности', () => {
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'Выбрать или создать героя' }).getAttribute('href')).toBe('/c/c/hero');
  expect(screen.queryByRole('button', { name: 'Зелёный свет' })).toBeNull();
});

it('отображает активные эффекты и форму куста в карточке героя и в полноэкранном режиме', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота.' } } as never,
    sheet: {
      name: 'Ива',
      hp: '19',
      derived: { hp_max: '22', ac: '14' },
      sheet: { rules_version: 'universal.v1' },
      exploration: {
        game_seconds: '24',
        effects: [{ id: 'bush_ef', kind: 'camouflage', label: 'Превращение в куст', remaining_seconds: '18' }],
        objects: [{ id: 'cup', name: 'Кружка', template: 'vessel', owner_id: 'hero', capacity_ml: '300', contents_ml: '200' }],
        constraints: { form: 'plant_bush', can_speak: false },
      },
    } as never,
  });

  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);

  // В панели героя отображаются форма куста, эффект и предметы
  expect(screen.getByText('Вы в форме куста')).toBeDefined();
  expect(screen.getByText('Превращение в куст')).toBeDefined();
  expect(screen.getByText(/18 с/)).toBeDefined();
  expect(screen.getByText('Кружка')).toBeDefined();
  expect(screen.getByText(/200 из 300 мл/)).toBeDefined();

  // Раскрываем чат на весь экран
  fireEvent.click(screen.getByRole('button', { name: 'Раскрыть чат на весь экран' }));
  expect(screen.getByText('В форме куста')).toBeDefined();
});

it('кнопка «Кабинет» стоит в шапке игры для владельца стола и скрыта от остальных', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Перед вами ворота.' } } as never,
    sheet: null,
  });
  const { unmount } = render(<MemoryRouter><UniversalAdventure campaignId='c' canManage /></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'Кабинет' }).getAttribute('href')).toBe('/c/c/manage');
  unmount();
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  expect(screen.queryByRole('link', { name: 'Кабинет' })).toBeNull();
});

it('сворачивает длинное описание локации и разворачивает по клику', () => {
  useGame.setState({
    snapshot: { campaign: { name: 'Острова', public_intro: 'Путь в порт', ruleset_id: 'universal' } } as never,
    scene: { location: { id: 'port', name: 'Порт', description: 'Очень длинное описание локации.\nВторая строка с важными деталями.\nТретья строка про шум волн.\nЧетвёртая строка про крики чаек.' } } as never,
    sheet: { name: 'Ива', hp: '19', derived: { hp_max: '22', ac: '14' }, sheet: { rules_version: 'universal.v1' } } as never,
  });
  render(<MemoryRouter><UniversalAdventure campaignId='c' /></MemoryRouter>);
  const toggleBtn = screen.getByRole('button', { name: /Подробнее/ });
  expect(toggleBtn).toBeDefined();
  fireEvent.click(toggleBtn);
  expect(screen.getByRole('button', { name: /Свернуть/ })).toBeDefined();
});
