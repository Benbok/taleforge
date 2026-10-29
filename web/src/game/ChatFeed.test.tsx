import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ChatFeed from './ChatFeed';
import { useGame } from '../stores/game';

vi.mock('./MessageView', () => ({ default: ({ m }: { m: { content: string } }) => <p>{m.content}</p> }));
vi.mock('./ChronicleDivider', () => ({ default: () => null }));
const observers = new Set<() => void>();
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
const message = (seq: number) => ({ id: `m${seq}`, seq, kind: 'narration', content: `История ${seq}`, seat_id: null,
  author: null, whisper: false, created_at: null });

beforeEach(() => {
  vi.useFakeTimers();
  observers.clear();
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: () => void) {}
    observe() { observers.add(this.callback); }
    disconnect() { observers.delete(this.callback); }
  });
  vi.stubGlobal('requestAnimationFrame', (callback: () => void) => setTimeout(callback, 16));
  vi.stubGlobal('cancelAnimationFrame', (id: ReturnType<typeof setTimeout>) => clearTimeout(id));
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn(function(this: HTMLElement) {
    const feed = this.closest('.tf-story-feed');
    if (feed) feed.scrollTop = feed.scrollHeight;
  }) });
  useGame.setState({ messages: [message(1)] as never, pending: [], notes: [], masterStage: null, seats: [], heroes: {}, snapshot: null });
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (originalScrollIntoView) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
});

function feed() {
  const page = render(<ChatFeed campaignId='c' />);
  const box = page.container.querySelector('.tf-story-feed') as HTMLDivElement;
  Object.defineProperties(box, { scrollHeight: { configurable: true, value: 2000 }, clientHeight: { configurable: true, value: 400 } });
  box.scrollTo = vi.fn(({ top }: ScrollToOptions) => { box.scrollTop = top ?? 0; }) as typeof box.scrollTo;
  return box;
}

it('keeps the reading position when the master starts thinking', () => {
  const box = feed();
  act(() => vi.advanceTimersByTime(100));
  box.scrollTop = 400; fireEvent.scroll(box);
  act(() => useGame.setState({ masterStage: 'remembering' }));
  act(() => vi.advanceTimersByTime(100));
  expect(box.scrollTop).toBe(400);
});

it('allows scrolling during thinking across stage changes, resizing and new messages', () => {
  useGame.setState({ masterStage: 'listening' });
  const box = feed();
  act(() => vi.advanceTimersByTime(100));
  box.scrollTop = 400; fireEvent.scroll(box);
  act(() => useGame.setState({ masterStage: 'rolling', messages: [message(1), message(2)] as never }));
  act(() => { for (const resize of observers) resize(); vi.advanceTimersByTime(100); });
  expect(box.scrollTop).toBe(400);
  fireEvent.click(screen.getByRole('button', { name: 'Новые сообщения ↓' }));
  expect(box.scrollTop).toBe(2000);
});

it('does not let delayed automatic scrolling undo a manual scroll', () => {
  useGame.setState({ masterStage: 'remembering' });
  const box = feed();
  box.scrollTop = 400; fireEvent.scroll(box);
  act(() => vi.advanceTimersByTime(100));
  expect(box.scrollTop).toBe(400);
});

it('follows updates while the reader remains at the bottom', () => {
  const box = feed();
  act(() => vi.advanceTimersByTime(100));
  box.scrollTop = 1600; fireEvent.scroll(box);
  act(() => useGame.setState({ masterStage: 'describing', messages: [message(1), message(2)] as never }));
  act(() => vi.advanceTimersByTime(100));
  expect(box.scrollTop).toBe(2000);
});
