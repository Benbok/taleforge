import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PortraitPreview from './PortraitPreview';

vi.mock('../lib/authedImage', () => ({ useAuthedImage: () => 'blob:test-portrait' }));
const originals = ['showModal', 'close'].map(key => [key, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, key)] as const);
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open'); } });
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, key, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, key);
  }
});

it('opens the complete portrait and closes with Escape without closing a parent window', () => {
  const parent = vi.fn();
  render(<div onKeyDown={parent}><PortraitPreview url='/api/portraits/hp1' name='Ива' /></div>);
  const trigger = screen.getByRole('button', { name: 'Рассмотреть портрет: Ива' });
  trigger.focus(); fireEvent.click(trigger);
  const dialog = screen.getByRole('dialog', { name: 'Портрет: Ива' });
  expect(within(dialog).getByRole('img').className).toContain('object-contain');
  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(parent).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(trigger);
});

it('keeps the viewer open on image clicks and supports the close button and backdrop', () => {
  render(<PortraitPreview url='/api/portraits/hp1' name='Ива' />);
  const trigger = screen.getByRole('button', { name: 'Рассмотреть портрет: Ива' });
  fireEvent.click(trigger);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('img'));
  expect(screen.getByRole('dialog')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть портрет' }));
  expect(screen.queryByRole('dialog')).toBeNull();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole('dialog'));
  expect(screen.queryByRole('dialog')).toBeNull();
});
