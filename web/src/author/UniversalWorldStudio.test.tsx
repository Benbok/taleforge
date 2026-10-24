import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import UniversalWorldStudio from './UniversalWorldStudio';
import { mockApi, renderWithClient } from './testkit';

const fields = {title:'Стеклянные острова',premise:'Исследовать гавань',world:'Острова',laws:'Никто не летает',
 inhabitants:'Моряки',powers:'Ветер',history:'PRIVATE HISTORY',start:'У ворот гавани',style:'Исследование',
 difficulty:'normal',excluded_themes:[],public_text:'Гавань ждёт.',secret_text:'PRIVATE SECRET'};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('saves authored laws, asks a question, accepts the reviewed revision and displays its launch', async () => {
 let revision = 3;
 let saved = {...fields};
 let review: object | null = null;
 let published: object[] = [];
 const mock = mockApi(c => {
  if (c.url.endsWith('/studio') && c.method === 'PUT') { saved = (c.body as {fields:typeof fields}).fields; revision++; review=null; }
  if (c.url.endsWith('/studio')) return {body:{project_id:'ap_1',draft_revision:revision,fields:saved,review}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:revision},preparation:{stages:[]},published}};
  if (c.url.endsWith('/review')) { review={project_id:'ap_1',source_revision:revision,status:(c.body as {answer?:string}).answer?'ready':'questions',question:(c.body as {answer?:string}).answer?null:'Как моряки путешествуют?',notes:[]}; return {body:review}; }
  if (c.url.endsWith('/accept')) { published=[{id:'av_1',version:1,source_revision:revision,published_at:'2026-10-24'}]; return {status:201,body:published[0]}; }
  return undefined;
 });
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByDisplayValue(fields.laws);
 expect(screen.getByRole('button',{name:'Принять версию'}).hasAttribute('disabled')).toBe(true);
 fireEvent.change(screen.getByLabelText('Законы мира'),{target:{value:'Летать нельзя. Можно плавать.'}});
 expect(screen.getByRole('button',{name:'Проверить мир с мастером'}).hasAttribute('disabled')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Сохранить мир'}));
 await waitFor(()=>expect(mock.calls.some(c=>c.method==='PUT')).toBe(true));
 await waitFor(()=>expect(screen.getByRole('button',{name:'Проверить мир с мастером'}).hasAttribute('disabled')).toBe(false));
 fireEvent.click(screen.getByRole('button',{name:'Проверить мир с мастером'}));
 await screen.findByText('Как моряки путешествуют?');
 fireEvent.change(screen.getByLabelText('Ответ мастеру'),{target:{value:'Они плавают.'}});
 fireEvent.click(screen.getByRole('button',{name:'Ответить мастеру'}));
 await screen.findByText('Мастер готов принять эту редакцию.');
 fireEvent.click(screen.getByRole('button',{name:'Принять версию'}));
 await screen.findByText(/Версия 1 · редакция 4/);
 expect(screen.getByRole('button',{name:'Запустить версию 1'})).toBeTruthy();
 const sent = mock.calls.find(c=>c.method==='PUT')!.body as {fields:typeof fields};
 expect(sent.fields.laws).toBe('Летать нельзя. Можно плавать.');
 expect(sent.fields.secret_text).toBe('PRIVATE SECRET');
});
