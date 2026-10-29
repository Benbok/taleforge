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

const sparse = {...fields, world:'', laws:'', start:'', inhabitants:'', powers:'', history:'', style:'', public_text:'', secret_text:''};

it('fills only the empty fields from an idea and never overwrites the author text', async () => {
 const mock = mockApi(c => {
  if (c.url.endsWith('/studio') && c.method !== 'POST') return {body:{project_id:'ap_1',draft_revision:3,fields:sparse,review:null}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:3},preparation:{stages:[]},published:[]}};
  if (c.url.endsWith('/studio/draft')) return {body:{premise:'DRAFT PREMISE',world:'Средиземье, Третья эпоха',laws:'Кольцо искажает носителя',inhabitants:'',powers:'',history:'',start:'Шир, 3018 год',style:'',public_text:''}};
  return undefined;
 });
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByDisplayValue(fields.premise);
 const fill = screen.getByRole('button',{name:'Заполнить из идеи'});
 expect(fill.hasAttribute('disabled')).toBe(true);
 fireEvent.change(screen.getByLabelText('Идея мира'),{target:{value:'Властелин колец, 3018 год'}});
 fireEvent.click(fill);
 await screen.findByDisplayValue('Средиземье, Третья эпоха');
 expect((screen.getByLabelText('Законы мира') as HTMLTextAreaElement).value).toBe('Кольцо искажает носителя');
 expect((screen.getByLabelText('Начало приключения') as HTMLTextAreaElement).value).toBe('Шир, 3018 год');
 expect((screen.getByLabelText('Замысел') as HTMLTextAreaElement).value).toBe(fields.premise); // the author's text stays
 expect(mock.calls.some(c=>c.method==='PUT')).toBe(false); // a proposal only: nothing saved
 expect(screen.getByRole('button',{name:'Сохранить мир'}).hasAttribute('disabled')).toBe(false);
 expect(mock.calls.find(c=>c.url.endsWith('/studio/draft'))!.body).toEqual({idea:'Властелин колец, 3018 год'});
});

it('applies a master suggestion to the field only when the author asks', async () => {
 const review = {project_id:'ap_1',source_revision:3,status:'questions',question:'Как освещена гавань?',notes:[],suggestions:[{field:'style',text:'Тихо и жутковато'}]};
 mockApi(c => {
  if (c.url.endsWith('/studio')) return {body:{project_id:'ap_1',draft_revision:3,fields,review}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:3},preparation:{stages:[]},published:[]}};
  return undefined;
 });
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByText('Тихо и жутковато');
 expect((screen.getByLabelText('Стиль') as HTMLTextAreaElement).value).toBe('Исследование');
 fireEvent.click(screen.getByRole('button',{name:'Применить предложение: Стиль'}));
 expect((screen.getByLabelText('Стиль') as HTMLTextAreaElement).value).toBe('Тихо и жутковато');
 expect(screen.getByRole('button',{name:'Сохранить мир'}).hasAttribute('disabled')).toBe(false);
});

it('keeps the extra fields in a collapsed section that opens by itself when they are filled', async () => {
 mockApi(c => {
  if (c.url.endsWith('/studio')) return {body:{project_id:'ap_1',draft_revision:3,fields:sparse,review:null}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:3},preparation:{stages:[]},published:[]}};
  return undefined;
 });
 const { container } = renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByDisplayValue(fields.premise);
 const extra = container.querySelector('details[data-testid="extra-fields"]') as HTMLDetailsElement;
 expect(extra.open).toBe(false);
 expect(screen.getByText('Дополнительно')).toBeTruthy();
});

function filledStudio() {
 return mockApi(c => {
  if (c.url.endsWith('/studio') && c.method !== 'POST') return {body:{project_id:'ap_1',draft_revision:3,fields,review:null}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:3},preparation:{stages:[]},published:[]}};
  if (c.url.endsWith('/studio/draft')) return {body:{premise:'НОВЫЙ ЗАМЫСЕЛ',world:'',laws:'',inhabitants:'',powers:'Как действует магия',history:'',start:'',style:'',public_text:''}};
  return undefined;
 });
}

it('regenerates over the filled fields only after the author confirms, and saves nothing', async () => {
 const mock = filledStudio();
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByDisplayValue(fields.premise);
 fireEvent.change(screen.getByLabelText('Идея мира'),{target:{value:'Властелин колец'}});
 fireEvent.click(screen.getByRole('button',{name:'Перегенерировать с заменой'}));
 await screen.findByDisplayValue('НОВЫЙ ЗАМЫСЕЛ');
 expect((screen.getByLabelText('Силы и возможности') as HTMLTextAreaElement).value).toBe('Как действует магия');
 expect((screen.getByLabelText('Законы мира') as HTMLTextAreaElement).value).toBe(fields.laws); // not offered: stays
 expect(mock.calls.some(c=>c.method==='PUT')).toBe(false);
 expect(screen.getByRole('button',{name:'Сохранить мир'}).hasAttribute('disabled')).toBe(false);
});

it('does not regenerate when the author declines the confirmation', async () => {
 const mock = filledStudio();
 vi.spyOn(window, 'confirm').mockReturnValue(false);
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 await screen.findByDisplayValue(fields.premise);
 fireEvent.change(screen.getByLabelText('Идея мира'),{target:{value:'Властелин колец'}});
 fireEvent.click(screen.getByRole('button',{name:'Перегенерировать с заменой'}));
 expect(mock.calls.some(c=>c.url.endsWith('/studio/draft'))).toBe(false);
 expect((screen.getByLabelText('Замысел') as HTMLTextAreaElement).value).toBe(fields.premise);
});

function publishedStudio(listed: boolean) {
 let isListed = listed;
 const mock = mockApi(c => {
  if (c.url.endsWith('/studio') && c.method !== 'POST') return {body:{project_id:'ap_1',draft_revision:3,fields,review:null}};
  if (c.url.endsWith('?view=summary')) return {body:{project:{id:'ap_1',title:fields.title,draft_revision:3,listed:isListed},preparation:{stages:[]},published:[{id:'av_1',version:1,source_revision:3,published_at:'2026-10-29'}]}};
  if (c.url.endsWith('/catalog')) { isListed = (c.body as {listed:boolean}).listed; return {body:{id:'ap_1',title:fields.title,draft_revision:3,listed:isListed}}; }
  if (c.url.endsWith('/archive')) return {status:204,body:null};
  return undefined;
 });
 return mock;
}

it('hides an accepted world from the catalog and brings it back', async () => {
 const mock = publishedStudio(true);
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 fireEvent.click(await screen.findByRole('button',{name:'Скрыть из каталога'}));
 await screen.findByRole('button',{name:'Вернуть в каталог'});
 expect(mock.calls.find(c=>c.url.endsWith('/catalog'))!.method).toBe('PUT');
 expect(mock.calls.find(c=>c.url.endsWith('/catalog'))!.body).toEqual({listed:false});
 fireEvent.click(screen.getByRole('button',{name:'Вернуть в каталог'}));
 await screen.findByRole('button',{name:'Скрыть из каталога'});
 expect(mock.calls.filter(c=>c.url.endsWith('/catalog')).pop()!.body).toEqual({listed:true});
});

it('archives the project only after the author confirms', async () => {
 const mock = publishedStudio(true);
 const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
 renderWithClient(<UniversalWorldStudio projectId='ap_1' />);
 const button = await screen.findByRole('button',{name:'Архивировать проект'});
 fireEvent.click(button);
 expect(mock.calls.some(c=>c.url.endsWith('/archive'))).toBe(false);
 confirm.mockReturnValue(true);
 fireEvent.click(button);
 await waitFor(()=>expect(mock.calls.some(c=>c.url.endsWith('/archive')&&c.method==='POST')).toBe(true));
});
