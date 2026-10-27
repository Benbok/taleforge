/** Presentation only: these annotations never become stored exits or travel permission. */
import type {MapLocationPlan, MapState, Sketch, SketchExit} from './map';

function publicDirections(description:string):SketchExit[]{
 const result:SketchExit[]=[];
 const sentences=description.split(/(?<=[.!?;])\s+|[\n•]/u).map(s=>s.trim()).filter(Boolean);
 const uncertain=/тайн|скрыт|возмож|вероят|кажется|может|слух|говорят|(?:^|\s)если(?:\s|$)|будто|предполож/iu;
 const returnQuote=sentences.find(s=>/назад|обратн/iu.test(s)&&/(?:^|[^\p{L}])нет(?:[^\p{L}]|$)|отрезан|недоступ|завален|отвесн/iu.test(s));
 const negated=/(?:^|\s)нет(?:\s|$)|не\s+(?:вид|замет|обнаруж|существ|было|будет)|несуществ|(?:вход|выход|проход)[\p{L}]*\s+(?:здесь\s+)?нет/iu;
 const observed=/виден|видн[аоы]|видне|вед[её]т|ведут|уход|слыш|донос|располож|находится|открыт|темне|впереди|перед вами|появился|появилась/iu;
 const known=sentences.filter(s=>/(?:туннел|тоннел|проход|выход|вход)[\p{L}]*/iu.test(s)&&observed.test(s)&&!uncertain.test(s)&&!negated.test(s)&&s!==returnQuote);
 for(const quote of known){
  const name=/т[оу]ннел/iu.test(quote)?'Туннель':/вход/iu.test(quote)?'Вход':/выход/iu.test(quote)?'Выход':'Проход';
  const side=/вост|справа/iu.test(quote)?'e':/запад|слева/iu.test(quote)?'w':/юг|назад|позади/iu.test(quote)?'s':'n';
  if(result.some(e=>e.name===name&&e.side===side))continue;
  result.push({name,kind:'passage',side,at:0,to:null,state:null,beyond:quote,orientation:{quote,approximate:true}});
  if(result.length===7)break;
 }
 if(returnQuote&&!uncertain.test(returnQuote))result.push({name:'Обратный путь',kind:'passage',side:'s',at:0,to:null,state:'blocked',beyond:returnQuote,
  orientation:{quote:returnQuote,approximate:true}});
 return result;
}

function boundary(sketch:Sketch,side:SketchExit['side'],index:number,count:number):[number,number]{
 const walls=new Set(sketch.walls.map(([x,y])=>`${x},${y}`));
 const floor:[number,number][]=[];
 for(let y=0;y<sketch.rows;y++)for(let x=0;x<sketch.cols;x++)if((!sketch.mask||sketch.mask[y]?.[x]==='.')&&!walls.has(`${x},${y}`))floor.push([x,y]);
 if(!floor.length)return sketch.party;
 const vertical=side==='e'||side==='w';
 // Closest existing floor cell on the requested side; do not change the outline.
 const floorSet=new Set(floor.map(c=>`${c[0]},${c[1]}`));
 const [dx,dy]=side==='e'?[1,0]:side==='w'?[-1,0]:side==='n'?[0,-1]:[0,1];
 const outline=floor.filter(([x,y])=>!floorSet.has(`${x+dx},${y+dy}`));
 const unoccupied=outline.filter(([x,y])=>!sketch.exits.some(e=>e.side===side&&e.cells?.some(c=>c[0]===x&&c[1]===y)));
 const candidates=(unoccupied.length?unoccupied:outline).sort((a,b)=>vertical?a[1]-b[1]:a[0]-b[0]);
 return candidates[Math.min(candidates.length-1,Math.floor((index+1)*candidates.length/(count+1)))];
}

export function orientationPlan(map:MapState):MapLocationPlan|null{
 const source=map.location_map??(map.here&&map.sketch?{root_id:map.here.id,here_id:map.here.id,areas:[{id:map.here.id,name:map.here.name,offset:[0,0] as [number,number],level:0,status:'here' as const,revision:1,sketch:map.sketch}]}:null);
 if(!source)return null;
 return {...source,areas:source.areas.map(area=>{
  if(area.id!==source.here_id)return area;
  const original=map.sketch??area.sketch;
  const exits=original.exits.filter(e=>!e.hidden).map(e=>({...e}));
  const append:SketchExit[]=[];
  const destinations=new Set(exits.map(e=>e.to).filter(Boolean));
  for(const exit of map.exits){
   if(exit.id&&destinations.has(exit.id))continue;
   if(exit.id)destinations.add(exit.id);
   const state=['open','closed','locked','blocked'].includes(exit.state??'')?exit.state as SketchExit['state']:null;
   const side=exit.bearing?.includes('e')?'e':exit.bearing?.includes('w')?'w':exit.bearing?.includes('s')?'s':'n';
   append.push({name:exit.via&&exit.via!==exit.name?`${exit.via} → ${exit.name}`:exit.name,to:exit.id,room_ref:exit.room_ref,
    kind:'passage',state,side,at:0,orientation:{approximate:true,destination:exit.name}});
  }
  for(const exit of original.unplaced_exits??[]){
   if(exit.to&&destinations.has(exit.to)||exits.some(e=>e.name===exit.name)||append.some(e=>e.name===exit.name))continue;
   append.push({name:exit.name,to:exit.to,room_ref:exit.room_ref,kind:'passage',state:null,side:'n',at:0,orientation:{approximate:true}});
  }
  for(const direction of publicDirections(map.here?.description??'')){
   const existing=[...exits,...append];
   if(existing.some(e=>e.name.toLocaleLowerCase('ru').includes(direction.name.toLocaleLowerCase('ru'))
       ||e.beyond===direction.beyond))continue;
   append.push(direction);
  }
  const sketch={...original,exits};
  for(const exit of append){
   const sameSide=append.filter(e=>e.side===exit.side);
   const cell=boundary(sketch,exit.side,sameSide.indexOf(exit),sameSide.length);
   const identity=exit.to??exit.room_ref??exit.name;
   exits.push({...exit,at:exit.side==='n'||exit.side==='s'?cell[0]:cell[1],cells:[cell],passage_ref:`orientation:${area.id}:${identity}`});
  }
  return {...area,sketch};
 })};
}
