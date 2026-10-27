import {expect,it} from 'vitest';
import {orientationPlan} from './orientationPassages';
import type {MapState} from './map';
import {mapForDisplay} from './map';

const sketch={shape:'cave' as const,cols:5,rows:5,party:[2,2] as [number,number],walls:[],mask:['#####','##.##','#...#','##.##','#####'],features:[],exits:[]};
const base={here:{id:'here',name:'Ущелье',description:''},sketch,around:[],exits:[],places:[],links:[]} as unknown as MapState;

it('projects known destinations onto the floor boundary without changing saved geometry',()=>{
 const m={...base,exits:[{id:'next',name:'Роща',via:'Лесная тропа',bearing:'e',state:'locked',visited:false}]} as MapState;
 const before=JSON.stringify(m);
 const plan=orientationPlan(m)!;
 expect(plan.areas[0].sketch.exits).toEqual([expect.objectContaining({name:'Лесная тропа → Роща',to:'next',state:'locked',side:'e',cells:[[3,2]]})]);
 expect(JSON.stringify(m)).toBe(before);
 expect(orientationPlan(m)).toEqual(plan);
});

it('keeps existing positions, omits hidden markers and does not duplicate destinations',()=>{
 const exit={name:'Арка',side:'n' as const,at:2,kind:'arch' as const,to:'next',state:'open' as const,cells:[[2,1]]};
 const m={...base,sketch:{...sketch,exits:[exit,{...exit,name:'SECRET',to:'secret',hidden:true}]},exits:[{id:'next',name:'Роща',via:'Арка',bearing:null,visited:false}]} as MapState;
 expect(orientationPlan(m)!.areas[0].sketch.exits).toEqual([exit]);
});

it('shows quoted public directions without inventing destinations or passability',()=>{
 const m={...base,here:{id:'here',name:'Ущелье',description:'Впереди виден широкий туннель. Пути назад нет — там отвесная стена.'}} as MapState;
 const exits=orientationPlan(m)!.areas[0].sketch.exits;
 expect(exits).toHaveLength(2);
 expect(exits).toEqual(expect.arrayContaining([expect.objectContaining({name:'Туннель',to:null,state:null}),expect.objectContaining({name:'Обратный путь',to:null,state:'blocked'})]));
 expect(exits.every(e=>e.beyond)).toBe(true);
});

it('does not turn hidden, hypothetical or negated passages into markers',()=>{
 for(const description of ['Выхода здесь нет.','Возможно, здесь есть проход.','За стеной скрытый туннель.','Ход закрыт тайной дверью.','Туннеля не существует.','Если открыть стену, появится проход.']){
  expect(orientationPlan({...base,here:{id:'here',name:'Зал',description}} as MapState)!.areas[0].sketch.exits).toEqual([]);
 }
});

it('does not normalize an unknown or blocked saved state into an open passage',()=>{
 for(const state of ['unknown','blocked']){
  const wire={...base,party:[],areas:[],scene_view:[],sketch:{...sketch,exits:[{name:'Дверь',kind:'door',side:'e',at:2,state}]}};
  expect(mapForDisplay(wire as never).sketch!.exits[0].state).toBe(state==='blocked'?'blocked':undefined);
 }
});

it('keeps multiple schematic exits on an irregular boundary separately clickable',()=>{
 const m={...base,exits:['a','b'].map(id=>({id,name:id,via:null,bearing:'n',visited:false}))} as MapState;
 const exits=orientationPlan(m)!.areas[0].sketch.exits;
 expect(new Set(exits.map(e=>JSON.stringify(e.cells))).size).toBe(2);
});

it('keeps distinct public directions alongside a structured entrance',()=>{
 const m={...base,here:{id:'here',name:'Зал',description:'Справа виден туннель. Слева виден вход. Пути назад нет.'},
  sketch:{...sketch,exits:[{name:'Арка',kind:'arch',side:'n',at:2,to:'next',state:'open'}]}} as unknown as MapState;
 const exits=orientationPlan(m)!.areas[0].sketch.exits;
 expect(exits.map(e=>e.name)).toEqual(expect.arrayContaining(['Арка','Туннель','Вход','Обратный путь']));
});
