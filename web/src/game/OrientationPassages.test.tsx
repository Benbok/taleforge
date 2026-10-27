import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import OrientationMap from './OrientationMap';
import {useMapWindow,type MapState} from './map';
import {useDraft} from './draft';

afterEach(()=>{cleanup();vi.restoreAllMocks();});

it('shows public passage markers on the saved outline and inspects them without acting',()=>{
 const step=vi.fn(),traverse=vi.fn(),insert=vi.fn();useMapWindow.setState({stepTo:step,traverseTo:traverse});useDraft.setState({insert});
 const map={here:{id:'here',name:'Ущелье',description:'Впереди виден широкий туннель. Пути назад нет — там отвесная стена.'},sketch:{shape:'cave',cols:3,rows:3,party:[1,1],walls:[],features:[],exits:[]},around:[],exits:[]} as unknown as MapState;
 render(<OrientationMap map={map}/>);
 fireEvent.click(screen.getByRole('button',{name:'Проход: Туннель'}));
 expect(screen.getByText('Куда ведёт — неизвестно')).toBeTruthy();
 expect(screen.getByText('Впереди виден широкий туннель.')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Проход: Обратный путь'}));
 expect(screen.getByText(/Путь недоступен/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Перейти'})).toBeNull();
 expect(step).not.toHaveBeenCalled();expect(traverse).not.toHaveBeenCalled();expect(insert).not.toHaveBeenCalled();
});

it('updates the inspected state when the server changes a known passage',()=>{
 const map={here:{id:'here',name:'Зал',description:''},sketch:{shape:'room',cols:3,rows:3,party:[1,1],walls:[],features:[],exits:[]},around:[],exits:[{id:'next',name:'Роща',via:'Туннель',bearing:'n',visited:false,state:'open'}]} as unknown as MapState;
 const {rerender}=render(<OrientationMap map={map}/>);
 fireEvent.click(screen.getByRole('button',{name:'Проход: Туннель → Роща'}));
 rerender(<OrientationMap map={{...map,exits:map.exits.map(e=>({...e,state:'locked'}))}}/>);
 expect(screen.getByText(/Проход, заперт/)).toBeTruthy();
});
