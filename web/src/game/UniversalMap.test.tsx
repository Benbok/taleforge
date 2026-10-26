import {afterEach,it,expect,vi} from 'vitest';
import {cleanup,render,fireEvent,screen} from '@testing-library/react';
import {LocationMap} from './LocationMap';
import {useMapWindow,type MapLocationPlan,type MapState} from './map';
import {useDraft} from './draft';
import {useInspector} from './inspector';
import OrientationMap from './OrientationMap';
afterEach(()=>{cleanup();vi.restoreAllMocks();});

it('orientation map keeps ground and passage clicks free of game commands and draft edits',()=>{
 const step=vi.fn(),traverse=vi.fn(),insert=vi.fn(),inspect=vi.fn();
 useMapWindow.setState({stepTo:step,traverseTo:traverse});useDraft.setState({insert});useInspector.setState({open:inspect});
 const sketch={shape:'room' as const,cols:2,rows:2,party:[0,0] as [number,number],walls:[],features:[],exits:[{name:'Арка',at:0,side:'e' as const,kind:'arch' as const,state:'open' as const,cells:[[1,0] as [number,number]],to:'next',passage_ref:'arch'}]};
 const map:MapLocationPlan={root_id:'here',here_id:'here',areas:[{id:'here',name:'Зал',status:'here',level:0,offset:[0,0],revision:1,sketch}]};
 const m={here:{id:'here',name:'Зал'},sketch,scene_view:[],party:[],around:[],exits:[],places:[],links:[],areas:[],bearings:{},mode:'free'} as unknown as MapState;
 const {container}=render(<LocationMap map={map} m={m} orientationOnly />);
 const ground=container.querySelector('svg rect[fill="transparent"][pointer-events="all"]');if(ground)fireEvent.click(ground);
 fireEvent.click(screen.getByRole('button',{name:'Проход: Арка'}));
 expect(screen.queryByRole('button',{name:'Перейти'})).toBeNull();
 expect(step).not.toHaveBeenCalled();expect(traverse).not.toHaveBeenCalled();expect(insert).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Увеличить'}));
 expect(screen.getByText('125%')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Зал'}));expect(inspect).toHaveBeenCalled();
});

it('keeps known landmarks inspectable when no geometric map exists',()=>{
 const inspect=vi.fn(),step=vi.fn(),traverse=vi.fn();useInspector.setState({open:inspect});useMapWindow.setState({stepTo:step,traverseTo:traverse});
 const map={here:{id:'here',name:'Берег'},around:[{id:'bell',name:'Колокол'}],exits:[{id:'grove',name:'Роща'}]} as unknown as MapState;
 render(<OrientationMap map={map}/>);
 expect(screen.getByText(/Точная схема ещё не известна/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Колокол'}));
 fireEvent.click(screen.getByRole('button',{name:'Роща'}));
 expect(inspect).toHaveBeenCalledTimes(2);expect(step).not.toHaveBeenCalled();expect(traverse).not.toHaveBeenCalled();
});
