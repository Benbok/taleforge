import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import * as api from '../lib/api';
import {useGame} from '../stores/game';
import {useMapWindow, type MapState} from './map';
import OrientationMap from './OrientationMap';

afterEach(()=>{cleanup();vi.restoreAllMocks();useGame.setState({snapshot:null,playAs:null});});

const map={here:{id:'here',name:'Ущелье'},around:[],exits:[]} as unknown as MapState;

it('creates a missing map for the current player and refreshes it, without sending an action',async()=>{
 useGame.setState({snapshot:{campaign:{id:'c'}} as never,playAs:'seat'});
 let finish:(value:unknown)=>void=()=>{};
 const request=vi.spyOn(api,'api').mockImplementation(()=>new Promise(resolve=>{finish=resolve;}) as never);
 const refresh=vi.fn();useMapWindow.setState({request:refresh});
 render(<OrientationMap map={map}/>);
 fireEvent.click(screen.getByRole('button',{name:'Создать схему'}));
 expect(request).toHaveBeenCalledWith('/api/campaigns/c/orientation-map?as_seat=seat',{body:{location_id:'here'}});
 expect(screen.getByRole('button',{name:'Создаю схему…'}).hasAttribute('disabled')).toBe(true);
 finish({created:true,location_id:'here'});
 await waitFor(()=>expect(refresh).toHaveBeenCalledTimes(1));
});

it('keeps the description and offers a retry when generation fails',async()=>{
 useGame.setState({snapshot:{campaign:{id:'c'}} as never});
 vi.spyOn(api,'api').mockRejectedValue(new Error('offline'));
 render(<OrientationMap map={map}/>);
 fireEvent.click(screen.getByRole('button',{name:'Создать схему'}));
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('Не удалось'));
 expect(screen.getByRole('button',{name:'Создать схему'}).hasAttribute('disabled')).toBe(false);
});

it('does not show generation for a map that is already saved',()=>{
 useGame.setState({snapshot:{campaign:{id:'c'}} as never});
 const sketch={shape:'room' as const,cols:2,rows:2,party:[0,0] as [number,number],walls:[],features:[],exits:[]};
 render(<OrientationMap map={{...map,sketch} as MapState}/>);
 expect(screen.queryByRole('button',{name:'Создать схему'})).toBeNull();
});
