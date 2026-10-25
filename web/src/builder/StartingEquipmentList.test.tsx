import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import StartingEquipmentList from './StartingEquipmentList';

afterEach(() => cleanup());

it('отображает снаряжение в компактном виде с возможностью раскрыть детализацию', () => {
  const items = [
    { name: 'Двуручный меч', kind: 'weapon', damage_dice: '2d6', attack_ability: 'str', description: 'Тяжёлый стальной клинок.', reason: 'Наследие предков' },
    { name: 'Кожаный доспех', kind: 'armor', defense_bonus: '2', description: 'Лёгкая броня для подвижности.' },
    { name: 'Походный мешок', kind: 'gear' },
  ];

  render(<StartingEquipmentList items={items} />);

  // Проверяем наличие компактных строк
  expect(screen.getByText('Двуручный меч')).toBeDefined();
  expect(screen.getByText('Кожаный доспех')).toBeDefined();
  expect(screen.getByText('Походный мешок')).toBeDefined();

  // Проверяем бейджи параметров
  expect(screen.getByText('2d6 · Сила')).toBeDefined();
  expect(screen.getByText('+2 КД')).toBeDefined();

  // Проверяем наличие детализации внутри аккордеонов
  expect(screen.getByText('Тяжёлый стальной клинок.')).toBeDefined();
  expect(screen.getByText('Базовый урон 2d6 · Сила')).toBeDefined();
  expect(screen.getByText(/Наследие предков/)).toBeDefined();
});

