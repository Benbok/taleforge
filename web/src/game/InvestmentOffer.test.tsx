import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { ChatMessage } from '../lib/types';
import { useGame } from '../stores/game';
import InvestmentOffer from './InvestmentOffer';

vi.mock('../lib/api', () => ({ api: vi.fn().mockResolvedValue({ status: 'accepted' }) }));
import { api } from '../lib/api';

beforeEach(() => {
  useGame.setState(useGame.getInitialState(), true);
  useGame.setState({ snapshot: { campaign: { id: 'c1' } } as never });
  vi.mocked(api).mockClear();
});
afterEach(cleanup);

const offer = (status: string): ChatMessage => ({
  id: 'invest_m', seq: 4, kind: 'investment', seat_id: null, author: null, content: 'Вложить усилие?', whisper: false,
  created_at: null, state: null, scope: 'public',
  data: {
    mid: 'm', seat_id: 's1', status, attribute: 'cha', natural: 10, modifier: -1, total: 9, difficulty: 12,
    shortfall: 3, price: 9, available: 18, deadline_ts: Math.floor(Date.now() / 1000) + 40,
  },
}) as unknown as ChatMessage;

it('offers the exact price with both buttons to the hero\'s own player', () => {
  render(<InvestmentOffer m={offer('offered')} mySeat='s1' heroName='Пупкин' />);
  expect(screen.getByText(/Не хватило 3/)).toBeTruthy();
  expect(screen.getByText(/9 Харизмы/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Вложить' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Принять провал' })).toBeTruthy();
});

it('shows the others only who is deciding, without buttons', () => {
  render(<InvestmentOffer m={offer('offered')} mySeat='s2' heroName='Пупкин' />);
  expect(screen.getByText(/Пупкин решает/)).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
});

it.each([['invested', /вложил/i], ['declined', /принял провал/i]])('settled as %s has no buttons', (status, text) => {
  render(<InvestmentOffer m={offer(status)} mySeat='s1' heroName='Пупкин' />);
  expect(screen.getByText(text)).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
});

it('posts the decision to the server', async () => {
  render(<InvestmentOffer m={offer('offered')} mySeat='s1' heroName='Пупкин' />);
  fireEvent.click(screen.getByRole('button', { name: 'Вложить' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith('/api/campaigns/c1/investments/m', { method: 'POST', body: { accept: true } }));
});
