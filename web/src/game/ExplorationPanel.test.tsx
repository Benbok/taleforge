import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import ExplorationPanel from './ExplorationPanel';

afterEach(cleanup);

it('shows authoritative effect lifetime and cup contents without a client timer', () => {
  render(<ExplorationPanel state={{ game_seconds: '24', effects: [
    { id: 'light', kind: 'illumination', label: 'Светлячки', remaining_seconds: '18' },
  ], objects: [{ id: 'cup', name: 'Кружка', template: 'vessel', owner_id: 'hero', capacity_ml: '300', contents_ml: '200' }],
    constraints: { form: null, can_speak: true } }} />);
  expect(screen.getByText('Светлячки')).toBeTruthy();
  expect(screen.getByText(/18 с/)).toBeTruthy();
  expect(screen.getByText(/≈ 3 действия/)).toBeTruthy();
  expect(screen.getByText(/200 из 300 мл/)).toBeTruthy();
  expect(screen.getByText(/Игровое время/)).toBeTruthy();
  expect(screen.getByText(/Чтение и переподключение/)).toBeTruthy();
});

it('explains the bush restrictions and cancellation through the master', () => {
  render(<ExplorationPanel state={{ game_seconds: '6', effects: [], objects: [], constraints: { form: 'plant_bush', can_speak: false } }} />);
  expect(screen.getByText(/не можете двигаться, говорить/)).toBeTruthy();
  expect(screen.getByText(/снять превращение/)).toBeTruthy();
});
