import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import UniversalCombatPanel from './UniversalCombatPanel';
import { api } from '../lib/api';

vi.mock('../lib/api',()=>({api:vi.fn()}));
vi.mock('./EquipmentArtwork',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.clearAllMocks();});

it('shows authoritative defense and sends an equip action with a stable request key',async()=>{
  const changed=vi.fn();
  vi.mocked(api).mockResolvedValue({derived:{ac:'17'}});
  render(<UniversalCombatPanel campaignId='c' heroId='hero' onUpdated={changed} state={{
    life_state:'conscious',ac:'14',game_seconds:'6',inventory:[{
      id:'armor',name:'Кираса',kind:'armor',status_name:'Обычный',quantity:'1',equipped:false,defense_bonus:'3',
    }],enemies:[],
  }} />);
  expect(screen.getByText(/КД 14/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Надеть Кираса'}));
  await waitFor(()=>expect(changed).toHaveBeenCalled());
  expect(vi.mocked(api).mock.calls[0][0]).toContain('/universal-actions');
});

it('explains unconsciousness without displaying hidden rescue counters',()=>{
  render(<UniversalCombatPanel campaignId='c' heroId='hero' state={{
    life_state:'unconscious',ac:'14',game_seconds:'6',inventory:[],enemies:[],
  }} />);
  expect(screen.getByText(/Без сознания/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Защищаться'})).toBeNull();
});

it('resumes the original server request after remounting the page',async()=>{
  vi.mocked(api).mockResolvedValue({});
  render(<UniversalCombatPanel campaignId='c' heroId='hero' state={{
    life_state:'conscious',ac:'14',game_seconds:'6',inventory:[],enemies:[],
    pending_request:{kind:'guard',request_key:'saved-before-reload'},
  }} />);
  fireEvent.click(screen.getByRole('button',{name:'Завершить сохранённое действие'}));
  await waitFor(()=>expect(api).toHaveBeenCalled());
  expect(JSON.parse(vi.mocked(api).mock.calls[0][1]?.body as string).request_key).toBe('saved-before-reload');
});
