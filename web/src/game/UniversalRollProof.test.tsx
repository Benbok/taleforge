import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import RollCardView from './RollCardView';
import type { RollCard } from '../lib/types';

afterEach(cleanup);

it('shows a paid automatic spell and learning without inventing a die', () => {
  const card = { tool: 'universal_action', title: 'Искры', outcome: 'success', universal_proof: {
    receipt_id: 'auto', source_id: 'm', revision: '1', cost: '1', damage: '0', draws: [], checks: [],
    source_kind: 'supernatural', automatic: true, ability_ref: 'sparks',
  } } as RollCard;
  render(<RollCardView card={card} />);
  expect(screen.getByText(/Результат сервера/)).toBeTruthy();
  expect(screen.getByText(/Способность изучена/)).toBeTruthy();
  expect(screen.queryByText('d20')).toBeNull();
});

it.each([['crit_success', 20, true, false, 'Критический успех'], ['crit_fail', 1, false, true, 'Критический провал']] as const)(
  'displays %s for the actual natural die', (outcome, natural, critical, critical_failure, label) => {
    const card = { tool: 'universal_action', title: 'Проверка: Мудрость', outcome, universal_proof: {
      receipt_id: 'critical', source_id: 'm', revision: '1', cost: '0', damage: '0', draws: [{ sides: 20, value: natural }],
      checks: [{ natural, modifier: '2', total: String(natural + 2), difficulty: '12', success: critical,
        target_id: 'hero', attribute: 'wis', kind: 'check', mode: 'normal', critical, critical_failure }],
    } } as RollCard;
    render(<RollCardView card={card} />);
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  },
);

it('shows the real die, modifier, total, threshold and outcome without opening details', () => {
  const card = {
    tool: 'universal_action', title: 'Проверка: Мудрость', outcome: 'fail',
    universal_proof: {
      receipt_id: 'ev1', source_id: 'm1', revision: '1', cost: '0', damage: '0',
      draws: [{ sides: 20, value: 9 }], checks: [{
        natural: 9, modifier: '2', total: '11', difficulty: '12', success: false,
        target_id: 'hero', target_name: 'Пупкинатор', attribute: 'wis', kind: 'check', mode: 'normal',
      }],
    },
  } as RollCard;
  render(<RollCardView card={card} />);
  expect(screen.getByLabelText('d20: выпало 9')).toBeTruthy();
  expect(screen.getByText(/9 \+ 2 = 11/)).toBeTruthy();
  expect(screen.getByText(/Сложность 12/)).toBeTruthy();
  expect(screen.getAllByText('Провал').length).toBeGreaterThan(0);
});

it('preserves exact large totals and does not invent a hidden defense value', () => {
  const card = {
    tool: 'universal_action', title: 'Атака: Сила', outcome: 'success',
    universal_proof: {
      receipt_id: 'ev2', source_id: 'm2', revision: '1', cost: '0', damage: '1', draws: [],
      checks: [{ natural: 9, modifier: '9007199254740993', total: '9007199254741002',
        difficulty: null, success: true, target_id: 'enemy', attribute: 'str', kind: 'attack', mode: 'normal' }],
    },
  } as RollCard;
  render(<RollCardView card={card} />);
  expect(screen.getByText(/9007199254741002/)).toBeTruthy();
  expect(screen.queryByText(/Сложность/)).toBeNull();
});

it('shows what the hero actually learned from the successful check', () => {
  const card = { tool: 'universal_action', title: 'Проверка: Мудрость', outcome: 'success', universal_proof: {
    receipt_id: 'ev3', source_id: 'm3', revision: '1', cost: '0', damage: '0', draws: [], checks: [],
    description: 'Из тоннеля впереди слышны приближающиеся костяные шаги.',
  } } as RollCard;
  render(<RollCardView card={card} />);
  expect(screen.getByText('Результат действия')).toBeTruthy();
  expect(screen.getByText('Из тоннеля впереди слышны приближающиеся костяные шаги.')).toBeTruthy();
});

it('shows what was invested and keeps the equation honest', () => {
  const card = {
    tool: 'universal_action', title: 'Расспрос', outcome: 'success',
    universal_proof: {
      receipt_id: 'inv', source_id: 'm', revision: '2', cost: '9', damage: '0',
      draws: [{ sides: 20, value: 10 }], checks: [{
        natural: 10, modifier: '2', total: '12', difficulty: '12', success: true, invested: 3,
        target_id: 'hero', attribute: 'cha', kind: 'check', mode: 'normal',
      }],
    },
  } as RollCard;
  render(<RollCardView card={card} />);
  expect(screen.getByText(/10 − 1 \+ 3 = 12/)).toBeTruthy();
  expect(screen.getByText(/Вложено: \+3/)).toBeTruthy();
});
