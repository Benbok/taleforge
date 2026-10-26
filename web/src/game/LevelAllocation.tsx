import {useRef,useState} from 'react';
import {api} from '../lib/api';
import {abilityKeys,abilityNames,type AbilityKey,type HeroCard} from '../lib/universal';

export default function LevelAllocation({campaignId,card,onUpdated}:{campaignId:string;card:HeroCard;onUpdated:(card:unknown)=>void}) {
 const [choice,setChoice]=useState<Partial<Record<AbilityKey,string>>>({});
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const request=useRef<{fingerprint:string;key:string}|null>(null);
 const available=BigInt(card.sheet.unspent_points ?? '0');
 const spent=Object.values(choice).reduce((sum,v)=>sum+BigInt(v ?? '0'),0n);
 const left=available-spent;
 const admissionPending=!!(card as HeroCard & {progression?:{admission_pending?:boolean}}).progression?.admission_pending;
 async function resume(){
  setBusy(true);setError('');
  try{onUpdated(await api(`/api/campaigns/${campaignId}/characters/${card.id}/resume-admission`,{method:'POST'}));}
  catch(e){setError(e instanceof Error?e.message:'Не удалось завершить вступление. Повторите запрос.');}
  finally{setBusy(false);}
 }
 if(admissionPending)return <section aria-label='Вступление героя' className='space-y-2 rounded-xl border border-accent/40 p-3 text-xs'>
  <h3 className='font-semibold'>Завершите вступление в группу</h3>
  <p className='text-muted'>Герой создан на первом уровне. Отдельное событие повысит копию до уровня группы и выдаст очки развития.</p>
  {error&&<p role='alert'>{error}</p>}
  <button disabled={busy} className='btn-primary px-3 py-2' onClick={resume}>Завершить вступление</button>
 </section>;
 if(available===0n)return null;
 function change(key:AbilityKey,delta:bigint){
  setChoice(old=>{const next={...old};const value=BigInt(old[key]??'0')+delta;if(value===0n)delete next[key];else next[key]=String(value);return next;});
 }
 async function confirm(){
  if(busy||spent===0n||left<0n)return;
  const fingerprint=JSON.stringify({revision:card.revision,choice});
  if(request.current?.fingerprint!==fingerprint)request.current={fingerprint,key:crypto.randomUUID()};
  setBusy(true);setError('');
  try{
   const updated=await api(`/api/campaigns/${campaignId}/characters/${card.id}/allocate-points`,{method:'POST',body:JSON.stringify({expected_revision:card.revision,allocations:choice,request_key:request.current!.key})});
   setChoice({});request.current=null;onUpdated(updated);
  }catch(e){setError(e instanceof Error?e.message:'Не удалось сохранить распределение. Повторите подтверждение.');}
  finally{setBusy(false);}
 }
 return <section aria-label='Развитие героя' className='space-y-3 rounded-xl border border-accent/40 bg-accent/5 p-3 text-xs'>
  <h3 className='font-heading font-semibold text-ink'>Новые возможности героя</h3>
  <p className='text-muted'>Вы заработали {String(available)} очк. Можно вложить оба очка уровня в одну характеристику.</p>
  <p className='font-mono text-accent'>Осталось распределить: {String(left)}</p>
  <div className='space-y-2'>{abilityKeys.map(key=><div key={key} className='flex items-center justify-between gap-2'>
   <label>{abilityNames[key]} <span className='font-mono'>{card.sheet.abilities[key]} → {String(BigInt(card.sheet.abilities[key])+BigInt(choice[key]??'0'))}</span></label>
   <span className='flex gap-2'>
    <button className='btn-ghost px-2 py-1' aria-label={`Убрать ${abilityNames[key]}`} disabled={busy||!choice[key]} onClick={()=>change(key,-1n)}>−</button>
    <button className='btn-ghost px-2 py-1' aria-label={`Добавить ${abilityNames[key]}`} disabled={busy||left<=0n} onClick={()=>change(key,1n)}>+</button>
   </span>
  </div>)}</div>
  <p className='leading-relaxed text-muted'>Очки тратятся после подтверждения. Рост максимума сохраняет уже потраченные ресурсы; погибшего героя он не воскрешает.</p>
  {error&&<p role='alert' className='text-bad'>{error}</p>}
  <button className='btn-primary w-full px-3 py-2' disabled={busy||spent===0n||left<0n} onClick={confirm}>{busy?'Сохраняем…':'Подтвердить распределение'}</button>
 </section>;
}
