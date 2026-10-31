import {cleanup, fireEvent, render} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import OrientationMap from './OrientationMap';
import type {MapState, SceneTokenView, Sketch} from './map';
import {useInspector} from './inspector';
import {useGame} from '../stores/game';

afterEach(()=>{cleanup();vi.restoreAllMocks();});

function actor(id:string,type:SceneTokenView['type'],extra:Partial<SceneTokenView>={}):SceneTokenView{
 return {id,name:id,type,mine:false,down:false,zone:null,bearing:null,cell:null,...extra};
}
function world(sketch:Sketch|null,actors:SceneTokenView[]):MapState{
 return {here:{id:'hall',name:'Зал'},sketch,scene_view:actors,party:[],around:[],exits:[],places:[],links:[],bearings:{}} as unknown as MapState;
}
const sketch:Sketch={shape:'room',cols:5,rows:5,party:[2,2],walls:[],exits:[],features:[]};
const actors=[actor('Пупкинатор','hero',{mine:true}),actor('Союзник','hero',{down:true}),actor('Проводник','npc'),actor('Страж','creature')];

it('shows the controlled hero, allies, NPCs and enemies without tactical cells',()=>{
 useGame.setState({snapshot:null});
 const inspect=vi.fn();useInspector.setState({open:inspect});
 const map=world(sketch,[...actors,actor('Вещь','item')]);
 const before=JSON.stringify(map);
 const {container}=render(<OrientationMap map={map}/>);
 for(const a of actors)expect(container.querySelector(`[data-presence-id="${a.id}"]`)).not.toBeNull();
 expect(container.querySelector('[data-party-marker]')).toBeNull();
 expect(container.querySelector('[data-presence-id="Вещь"]')).toBeNull();
 expect(container.querySelector('[data-presence-id="Пупкинатор"] title')?.textContent).toContain('ваш герой');
 expect(container.querySelector('[data-presence-id="Союзник"] title')?.textContent).toContain('без сознания');
 fireEvent.click(container.querySelector('[data-presence-id="Проводник"]')!);
 expect(inspect.mock.calls[0].slice(0,2)).toEqual(['Проводник','Проводник']);
 expect(JSON.stringify(map)).toBe(before);
});

it('keeps all actor markers distinct even on a one-cell sketch',()=>{
 useGame.setState({snapshot:null});
 const tiny={...sketch,cols:1,rows:1,party:[0,0] as [number,number]};
 const {container}=render(<OrientationMap map={world(tiny,actors)}/>);
 const markers=Array.from(container.querySelectorAll('[data-presence-id]'));
 expect(markers).toHaveLength(4);
 expect(new Set(markers.map(e=>e.getAttribute('transform'))).size).toBe(4);
 for(const marker of markers){
  const [x,y]=marker.getAttribute('transform')!.match(/-?\d*\.?\d+/g)!.map(Number);
  expect(x).toBeGreaterThan(0);expect(x).toBeLessThan(1);
  expect(y).toBeGreaterThan(0);expect(y).toBeLessThan(1);
  expect(Number(marker.querySelector('circle')!.getAttribute('r'))).toBeLessThanOrEqual(.25);
 }
});

it('does not place approximate actors in walls or on an actor with a known cell',()=>{
 useGame.setState({snapshot:null});
 const room={...sketch,walls:[[1,2],[3,2],[2,3]] as [number,number][]};
 const {container}=render(<OrientationMap map={world(room,[actor('Враг','creature',{cell:[0,-1]}),actor('NPC','npc')])}/>);
 const marker=container.querySelector('[data-presence-id="NPC"]')!;
 const [x,y]=marker.getAttribute('transform')!.match(/-?\d*\.?\d+/g)!.map(Number);
 expect([x,y]).not.toEqual([2.5,1.5]);
 expect(room.walls).not.toContainEqual([Math.floor(x),Math.floor(y)]);
});

it('keeps actors inspectable before a geometric sketch exists',()=>{
 useGame.setState({snapshot:null});
 const inspect=vi.fn();useInspector.setState({open:inspect});
 const {getByRole}=render(<OrientationMap map={world(null,actors)}/>);
 for(const a of actors)fireEvent.click(getByRole('button',{name:new RegExp(a.name)}));
 expect(inspect.mock.calls.map(call=>call[0])).toEqual(actors.map(a=>a.id));
});

it('keeps the hero and a positioned enemy separate when both occupy the only cell',()=>{
 useGame.setState({snapshot:null});
 const tiny={...sketch,cols:1,rows:1,party:[0,0] as [number,number]};
 const {container}=render(<OrientationMap map={world(tiny,[actor('Герой','hero',{mine:true}),actor('Враг','creature',{cell:[0,0]})])}/>);
 const hero=container.querySelector('[data-presence-id="Герой"]')!;
 const enemy=container.querySelector('[data-presence-id="Враг"], [data-token-id="Враг"]')!;
 const [hx,hy]=hero.getAttribute('transform')!.match(/-?\d*\.?\d+/g)!.map(Number);
 const [ex,ey]=enemy.getAttribute('transform')!.match(/-?\d*\.?\d+/g)!.map(Number);
 const shift=enemy.hasAttribute('data-token-id')?.35:0;
 expect(Math.hypot(hx-ex-shift,hy-ey-shift)).toBeGreaterThan(.25);
});
