import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it } from 'vitest';
import CabinetLink from './CabinetLink';

afterEach(cleanup);

it('leads the table owner from the universal game to the cabinet', () => {
  render(<MemoryRouter><CabinetLink campaignId='c1' canManage /></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'Кабинет' }).getAttribute('href')).toBe('/c/c1/manage');
});

it('shows nothing to players who cannot manage the table', () => {
  render(<MemoryRouter><CabinetLink campaignId='c1' canManage={false} /></MemoryRouter>);
  expect(screen.queryByRole('link')).toBeNull();
});
