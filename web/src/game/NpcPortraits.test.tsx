import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import NpcPortraits from './NpcPortraits';

vi.mock('../lib/authedImage', () => ({ useAuthedImageResource: (url: string) => ({ src: `blob:${url}`, error: false, retry: () => {} }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const idle = { status: 'idle', selected_id: null as string | null, variants: [] as {id:string;image_url:string;thumbnail_url:string}[], can_generate: true, can_select: true, enabled: true, error: null };

it('generates a candidate without applying it, then explicitly selects a variant', async () => {
  let state = idle;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') state = { ...idle, status: 'ready', variants: [{ id:'one',image_url:'/one',thumbnail_url:'/one-small' }] };
    if (init?.method === 'PUT') state = { ...state, selected_id: JSON.parse(init.body as string).image_id };
    return new Response(JSON.stringify(state));
  });
  vi.stubGlobal('fetch',fetcher);
  render(<NpcPortraits campaignId='c' npcId='npc' name='Лесничий' />);
  fireEvent.click(await screen.findByRole('button', { name:'Создать портрет' }));
  expect(await screen.findByRole('button', { name:'Применить вариант 1' })).toBeTruthy();
  expect(state.selected_id).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Применить вариант 1'}));
  await waitFor(()=>expect(state.selected_id).toBe('one'));
  expect(await screen.findByText('Выбранный портрет')).toBeTruthy();
});

it('ignores late replies from the previous NPC', async () => {
  let finish: (response:Response)=>void = ()=>{};
  vi.stubGlobal('fetch',vi.fn(async (url:string)=>url.includes('/old/') ? new Promise<Response>(resolve=>{finish=resolve})
    : new Response(JSON.stringify({...idle,status:'ready',selected_id:'new',variants:[{id:'new',image_url:'/new',thumbnail_url:'/new-small'}]}))));
  const page=render(<NpcPortraits campaignId='c' npcId='old' name='Старый' />);
  page.rerender(<NpcPortraits campaignId='c' npcId='new' name='Новый' />);
  await screen.findByRole('img');
  await act(async()=>{finish(new Response(JSON.stringify(idle)))});
  expect(screen.getByRole('img').getAttribute('src')).toBe('blob:/new-small');
});
