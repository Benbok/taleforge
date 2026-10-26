import {LocationMap} from './LocationMap';
import type {MapState,MapLocationPlan} from './map';
import {useInspector} from './inspector';

export default function OrientationMap({map}:{map:MapState}){
 const inspect=useInspector(s=>s.open);
 const visual:MapLocationPlan|null=map.location_map ?? (map.here && map.sketch ? {
  root_id:map.here.id,here_id:map.here.id,areas:[{id:map.here.id,name:map.here.name,offset:[0,0],level:0,status:'here',revision:1,sketch:map.sketch}],
 }:null);
 return <section className='space-y-4' aria-label='Ориентирующая карта'>
  <p className='rounded-lg border border-line-soft bg-raised p-3 text-sm text-muted'>Карта показывает известное окружение. Осмотр и масштаб не расходуют время. Действия и перемещения описывайте в чате.</p>
  {visual ? <LocationMap map={visual} m={map} orientationOnly /> : <p className='text-sm text-muted'>Точная схема ещё не известна. Для игры достаточно описания и известных ориентиров.</p>}
  {map.here?.description&&<p className='whitespace-pre-line leading-relaxed text-ink-2'>{map.here.description}</p>}
  {map.around.length>0&&<div className='space-y-2'>
   <h3 className='font-semibold'>Известное окружение</h3>
   <ul className='grid gap-2 sm:grid-cols-2'>{map.around.map(item=><li key={item.id}>
    <button className='w-full rounded-lg border border-line px-3 py-2 text-left hover:border-accent' onClick={event=>inspect(item.id,item.name,event.currentTarget)}>{item.name}{item.condition&&<span className='ml-2 text-xs text-muted'>{item.condition}</span>}</button>
   </li>)}</ul>
  </div>}
  {map.exits.length>0&&<div className='space-y-2'>
   <h3 className='font-semibold'>Известные направления</h3>
   <ul className='space-y-2'>{map.exits.map((exit,index)=><li key={exit.id??exit.room_ref??index} className='rounded-lg border border-line-soft px-3 py-2'>
    {exit.id?<button className='underline decoration-dotted underline-offset-4' onClick={event=>inspect(exit.id!,exit.name,event.currentTarget)}>{exit.name}</button>:<span>{exit.name}</span>}
    {exit.via&&<span className='ml-2 text-xs text-muted'>{exit.via}</span>}
   </li>)}</ul>
  </div>}
 </section>;
}
