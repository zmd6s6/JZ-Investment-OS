import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { WeeklyTaskHistory } from './WeeklyTaskHistory';
const a='10000000-0000-0000-0000-000000000001', b='b0000000-0000-0000-0000-000000000002';
const uuid='20000000-0000-0000-0000-000000000001';
const hash='a'.repeat(64), stamp='2026-11-01T00:00:00Z';
function task(id=a,protocol='1.0') { return {schema_version:'1.0',protocol,task_run_id:id,schedule_id:uuid,revision_id:uuid,week_start:'2026-10-26',scheduled_for:stamp,created_at:stamp,started_at:stamp,finished_at:stamp,task_status:'FAILED',attempt:3,reason_code:'SyntheticFailure',input_hash:hash,result_status:null,as_of:null,candidate_count:null,unknowns:['NO_COMMITTED_WEEKLY_RESULT'],auto_trade:false}; }
function detail(id=a,protocol='1.0',artifact=true) {return {...task(id,protocol),provenance:{name:'原冻结授权',venue:'SSE',revision_hash:hash,calendar_import_id:uuid,calendar_hash:hash,calendar_source:'原日历来源',calendar_version:'v1',template_run_id:uuid,source_name:'原范围',source_locator:'synthetic://old',quote_source_name:'原报价',fact_source_name:'原事实',snapshot_id:null,snapshot_hash:null,coverage_start:'2026-10-26',coverage_end:'2026-11-01',source_verification:'SOURCE_DECLARED_UNVERIFIED'},funnel_run_id:artifact?uuid:null,funnel_hash:artifact?hash:null,attempt_history:'NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY'};}
function page(items=[task()],cursor:string|null=null,protocol='1.0') { return {schema_version:'1.0',protocol,items,next_cursor:cursor,page_size:50,ordering:'created_at_desc_task_id_desc',auto_trade:false}; }
function response(value:unknown,status=200) {return new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});}
afterEach(()=>{cleanup();vi.restoreAllMocks();window.history.replaceState(null,'','/');sessionStorage.clear();});

test('authenticated exact URL outside loaded page reads original revision and refreshes its identity',async()=>{
 window.history.replaceState(null,'',`/opportunities?weekly_task_id=${b.toUpperCase()}`);sessionStorage.setItem('investment_os_write_token','synthetic-token');
 const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url,init)=>{
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer synthetic-token');
  expect(init?.method).toBeUndefined();
  return response(String(url).endsWith('/'+b)?detail(b):page());
 });
 render(<WeeklyTaskHistory version="1.0"/>);
 const panel=await screen.findByRole('region',{name:'原周任务审计详情'});
 expect(panel).toHaveTextContent(b);expect(panel).toHaveTextContent('原冻结授权');
 expect(within(panel).getByRole('link',{name:'查看原周筛选产物'})).toHaveAttribute('href',`/opportunities?run_id=${uuid}`);
 fireEvent.click(screen.getByRole('button',{name:'刷新所选周任务'}));
 await screen.findByRole('region',{name:'原周任务审计详情'});
 expect(fetch.mock.calls.filter(([url])=>String(url).endsWith('/'+b))).toHaveLength(2);
});

test('page failure preserves loaded rows and retry reaches the older failed task without artifact',async()=>{
 let fail=true;
 vi.spyOn(globalThis,'fetch').mockImplementation(async url=>{
  const value=String(url);
  if(value.includes('?cursor='))return fail?response({detail:{message:'合成分页失败'}},503):response(page([task(b)]));
  if(value.endsWith('/'+b))return response(detail(b,'1.0',false));
  return response(page([task()], 'next'));
 });
 render(<WeeklyTaskHistory version="1.0"/>);
 fireEvent.click(await screen.findByRole('button',{name:'加载更早周任务'}));
 await screen.findByRole('alert');expect(screen.getByRole('button',{name:`查看原周任务 ${a}`})).toBeVisible();
 fail=false;fireEvent.click(screen.getByRole('button',{name:'加载更早周任务'}));
 fireEvent.click(await screen.findByRole('button',{name:`查看原周任务 ${b}`}));
 const selected=await screen.findByRole('region',{name:'原周任务审计详情'});
 expect(selected).toHaveTextContent('本任务没有可核验的筛选产物');
 expect(within(selected).queryByRole('link')).not.toBeInTheDocument();
 expect(screen.getByText(/已加载2条/)).toBeVisible();
});

test('detail failure removes the previously selected artifact and recovery only rereads the same ID',async()=>{
 let fail=false;vi.spyOn(globalThis,'fetch').mockImplementation(async url=>response(String(url).endsWith('/'+a)?fail?{detail:{message:'原任务读取失败'}}:detail():page(),String(url).endsWith('/'+a)&&fail?404:200));
 render(<WeeklyTaskHistory version="1.0"/>);
 fireEvent.click(await screen.findByRole('button',{name:`查看原周任务 ${a}`}));
 await screen.findByRole('link',{name:'查看原周筛选产物'});
 fail=true;fireEvent.click(screen.getByRole('button',{name:'刷新所选周任务'}));
 await screen.findByText('原任务读取失败');
 expect(screen.queryByRole('region',{name:'原周任务审计详情'})).not.toBeInTheDocument();
 expect(screen.queryByRole('link',{name:'查看原周筛选产物'})).not.toBeInTheDocument();
 fail=false;fireEvent.click(screen.getByRole('button',{name:'刷新所选周任务'}));
 await screen.findByRole('link',{name:'查看原周筛选产物'});
});

test('late ignored-abort detail cannot replace a newer selection and protocol switch clears old content',async()=>{
 let finishA!:(value:Response)=>void;
 vi.spyOn(globalThis,'fetch').mockImplementation(async url=>{
  const value=String(url); if(value.endsWith('/'+a)) return new Promise(resolve=>{finishA=resolve;});
  if(value.endsWith('/'+b))return response(detail(b));
  return response(page([task(a,value.includes('complete-weekly')?'2.0':'1.0'),task(b,value.includes('complete-weekly')?'2.0':'1.0')],null,value.includes('complete-weekly')?'2.0':'1.0'));
 });
 const view=render(<WeeklyTaskHistory version="1.0"/>);
 fireEvent.click(await screen.findByRole('button',{name:`查看原周任务 ${a}`}));
 fireEvent.click(screen.getByRole('button',{name:`查看原周任务 ${b}`}));
 expect(await screen.findByRole('region',{name:'原周任务审计详情'})).toHaveTextContent(b);
 finishA(response(detail(a)));
 await waitFor(()=>expect(screen.getByRole('region',{name:'原周任务审计详情'})).toHaveTextContent(b));
 view.rerender(<WeeklyTaskHistory version="2.0"/>);
 await screen.findByRole('region',{name:'完整来源周任务审计'});
 expect(screen.queryByRole('region',{name:'原周任务审计详情'})).not.toBeInTheDocument();
});

test('malformed input and mismatched response identity never substitute an artifact',async()=>{
 vi.spyOn(globalThis,'fetch').mockImplementation(async url=>response(String(url).endsWith('/'+a)?detail(b):page()));
 render(<WeeklyTaskHistory version="1.0"/>);
 fireEvent.change(screen.getByLabelText('精确周任务ID'),{target:{value:'wrong'}});
 fireEvent.click(screen.getByRole('button',{name:'打开精确周任务'}));
 await screen.findByText(/周任务ID格式无效/);
 fireEvent.click(await screen.findByRole('button',{name:`查看原周任务 ${a}`}));
 await screen.findByText(/周任务详情与原ID不一致/);
 expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
