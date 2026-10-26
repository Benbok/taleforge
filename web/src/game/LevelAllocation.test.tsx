import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import LevelAllocation from './LevelAllocation';
import {api} from '../lib/api';
import type {HeroCard} from '../lib/universal';
vi.mock('../lib/api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('allows both earned points into wisdom and submits only after confirmation',async()=>{
 const card={id:'h',revision:3,level:'2',sheet:{xp:'300',unspent_points:'2',abilities:{str:'8',dex:'10',con:'12',int:'13',wis:'14',cha:'15'}}} as HeroCard;
 vi.mocked(api).mockResolvedValue(card);
 render(<LevelAllocation campaignId='c' card={card} onUpdated={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Добавить Мудрость'}));
 fireEvent.click(screen.getByRole('button',{name:'Добавить Мудрость'}));
 expect(api).not.toHaveBeenCalled();
 expect((screen.getByRole('button',{name:'Добавить Мудрость'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Подтвердить распределение'}));
 await waitFor(()=>expect(api).toHaveBeenCalled());
 const body=JSON.parse(vi.mocked(api).mock.calls[0][1]?.body as string);
 expect(body.allocations).toEqual({wis:'2'});expect(body.expected_revision).toBe(3);
});

it('offers explicit admission recovery before earned points are available',async()=>{
 const card={id:'h',revision:1,level:'1',sheet:{xp:'0',unspent_points:'0',abilities:{str:'8',dex:'10',con:'12',int:'13',wis:'14',cha:'15'}},progression:{admission_pending:true}} as unknown as HeroCard;
 vi.mocked(api).mockResolvedValue({});
 const changed=vi.fn();
 render(<LevelAllocation campaignId='c' card={card} onUpdated={changed}/>);
 fireEvent.click(screen.getByRole('button',{name:'Завершить вступление'}));
 await waitFor(()=>expect(changed).toHaveBeenCalled());
 expect(vi.mocked(api).mock.calls[0][0]).toContain('/resume-admission');
});
