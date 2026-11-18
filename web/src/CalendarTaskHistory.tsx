import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, getWriteToken, readApiError } from './writeApi';

type Task = {schema_version:'1.0';task_run_id:string;task_name:string;task_status:string;attempt:number;created_at:string;scheduled_for:string;started_at:string|null;finished_at:string|null;reason_code:string|null;input_hash:string;auto_trade:false};
type Source = {venue:string;market_timezone:string;business_date:string;close_at_utc:string;calendar_import_id:string;calendar_session_id:string;imported_at:string;source_name:string;source_version:string;calendar_hash:string;source_verification:'SOURCE_DECLARED_UNVERIFIED'};
type Detail = Task & {idempotency_key:string;source:Source|null;report_event_id:string|null;report_recorded_at:string|null;report_json:Record<string,unknown>|null;report_hash:string|null;unknowns:string[];attempt_history:'NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY'};
type Page = {schema_version:'1.0';items:Task[];next_cursor:string|null;page_size:50;ordering:'created_at_desc_task_id_desc';auto_trade:false};
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const text=(v:unknown):v is string=>typeof v==='string';
const time=(v:unknown)=>text(v)&&Number.isFinite(Date.parse(v));
const hash=(v:unknown)=>text(v)&&/^[a-f0-9]{64}$/.test(v);
const optional=(v:unknown,valid:(x:unknown)=>boolean)=>v===null||valid(v);
const status:Record<string,string>={FAILED:'状态任务失败',SUCCEEDED:'状态任务已完成',RUNNING:'状态任务运行中'};
const unknown:Record<string,string>={ATTEMPT_TIMELINE_NOT_RECORDED:'未记录逐次尝试时间线，仅显示当前保存的尝试与状态。',ORIGINAL_SOURCE_MISSING_OR_UNVERIFIED:'原日历导入、会话或输入无法核验（UNKNOWN），未使用当前来源替代。',REPORT_MISSING_OR_UNVERIFIED:'原状态报告缺失或无法核验（UNKNOWN），未展示其他报告。',NO_COMMITTED_STATUS_REPORT:'本任务未生成状态报告；旧失败保留，更正来源后产生的是独立任务。',UNSUPPORTED_RECORDED_STATUS:'保存的状态不属于本日历运行协议，含义未知。'};
export function parseCalendarTask(raw:unknown):Task{
 const v=raw as Task;
 if(!v||v.schema_version!=='1.0'||!uuid(v.task_run_id)||!text(v.task_name)||!v.task_name.startsWith('calendar_status_')||!text(v.task_status)||!Number.isInteger(v.attempt)||v.attempt<1||!time(v.created_at)||!time(v.scheduled_for)||!optional(v.started_at,time)||!optional(v.finished_at,time)||!optional(v.reason_code,text)||!hash(v.input_hash)||v.auto_trade!==false)throw new Error('日历任务响应格式异常，未采用其他记录。');
 return v;
}
export function parseCalendarTaskPage(raw:unknown):Page{
 const v=raw as Page;
 if(!v||v.schema_version!=='1.0'||v.page_size!==50||v.ordering!=='created_at_desc_task_id_desc'||v.auto_trade!==false||!Array.isArray(v.items)||v.items.length>50||!optional(v.next_cursor,text))throw new Error('日历任务分页格式异常，请刷新重试。');
 v.items.forEach(parseCalendarTask);
 if(new Set(v.items.map(x=>x.task_run_id)).size!==v.items.length)throw new Error('日历任务分页包含重复记录，请刷新核对。');
 return v;
}
export function parseCalendarTaskDetail(raw:unknown,id:string):Detail{
 const v=raw as Detail;parseCalendarTask(v);
 if(v.task_run_id!==id||!text(v.idempotency_key)||v.attempt_history!=='NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY'||!optional(v.report_event_id,uuid)||!optional(v.report_hash,hash)||!optional(v.report_recorded_at,time)||!Array.isArray(v.unknowns)||!v.unknowns.every(text)||v.source===undefined||v.report_json===undefined)throw new Error('日历任务详情与原ID不一致，旧详情已清除。');
 const p=v.source,r=v.report_json;
 if(p&&(!['SSE','SZSE','US_EQUITIES'].includes(p.venue)||p.market_timezone!==(p.venue==='US_EQUITIES'?'America/New_York':'Asia/Shanghai')||![p.business_date,p.source_name,p.source_version].every(text)||!time(p.close_at_utc)||!time(p.imported_at)||!uuid(p.calendar_import_id)||!uuid(p.calendar_session_id)||!hash(p.calendar_hash)||p.source_verification!=='SOURCE_DECLARED_UNVERIFIED'))throw new Error('原日历来源无法核对。');
 if(Boolean(r)!==Boolean(v.report_event_id)||Boolean(r)!==Boolean(v.report_hash)||Boolean(r)!==Boolean(v.report_recorded_at))throw new Error('原状态报告关联不完整。');
 if(r&&(!p||v.task_status!=='SUCCEEDED'||r.report_kind!=='CALENDAR_STATUS_ONLY'||r.calendar_import_id!==p.calendar_import_id||r.calendar_hash!==p.calendar_hash||r.venue!==p.venue||r.business_date!==p.business_date||!time(r.as_of)||Date.parse(String(r.as_of))!==Date.parse(v.scheduled_for)||r.source_name!==p.source_name||r.source_version!==p.source_version||!text(r.message)||r.auto_trade!==false||r.paid_calls!==0))throw new Error('原状态报告来源不匹配，未展示。');
 return v;
}
async function read(url:string,signal:AbortSignal){
 const response=await apiFetch(url,{signal,headers:{Authorization:`Bearer ${getWriteToken()}`}});
 if(response.status===401)throw new Error('日历任务审计需要有效令牌，请核对右上角令牌后重试。');
 if(!response.ok)throw new Error(await readApiError(response));
 return response.json() as Promise<unknown>;
}
const missing=(v:string|number|null)=>v??'未提供';
export function CalendarTaskHistory(){
 const [rows,setRows]=useState<Task[]>([]),[cursor,setCursor]=useState<string|null>(null);
 const [id,setId]=useState(()=>new URLSearchParams(window.location.search).get('calendar_task_id')??'');
 const [detail,setDetail]=useState<Detail|null>(null),[pageError,setPageError]=useState(''),[detailError,setDetailError]=useState('');
 const [pageBusy,setPageBusy]=useState(false),[detailBusy,setDetailBusy]=useState(false);
 const pageRequest=useRef(0),detailRequest=useRef(0),pageController=useRef<AbortController|null>(null),detailController=useRef<AbortController|null>(null);
 const load=useCallback(async(after:string|null=null)=>{
  const generation=++pageRequest.current;pageController.current?.abort();const controller=new AbortController();pageController.current=controller;setPageBusy(true);setPageError('');
  const timeout=setTimeout(()=>controller.abort(),15000);
  try{const value=parseCalendarTaskPage(await read(`/api/v1/calendar/tasks${after?`?cursor=${encodeURIComponent(after)}`:''}`,controller.signal));if(generation!==pageRequest.current||controller.signal.aborted)return;setRows(old=>after?[...old,...value.items.filter(x=>!old.some(y=>y.task_run_id===x.task_run_id))]:value.items);setCursor(value.next_cursor);}
  catch(error){if(generation===pageRequest.current)setPageError(error instanceof Error&&error.name!=='AbortError'?error.message:'日历历史连接失败或超时，已加载记录保留，请重试。');}
  finally{clearTimeout(timeout);if(generation===pageRequest.current)setPageBusy(false);}
 },[]);
 const open=useCallback(async(selected:string)=>{
  selected=selected.trim().toLowerCase();const generation=++detailRequest.current;detailController.current?.abort();setId(selected);setDetail(null);setDetailError('');setDetailBusy(false);
  const url=new URL(window.location.href);url.searchParams.set('calendar_task_id',selected);window.history.replaceState(null,'',url);
  if(!uuid(selected)){setDetailError('日历任务ID格式无效，请核对原任务链接。');return;}
  const controller=new AbortController();detailController.current=controller;setDetailBusy(true);const timeout=setTimeout(()=>controller.abort(),15000);
  try{const value=parseCalendarTaskDetail(await read(`/api/v1/calendar/tasks/${encodeURIComponent(selected)}`,controller.signal),selected);if(generation===detailRequest.current&&!controller.signal.aborted)setDetail(value);}
  catch(error){if(generation===detailRequest.current)setDetailError(error instanceof Error&&error.name!=='AbortError'?error.message:'日历任务详情连接失败或超时，旧详情已清除，请重试。');}
  finally{clearTimeout(timeout);if(generation===detailRequest.current)setDetailBusy(false);}
 },[]);
 useEffect(()=>{void load();const selected=new URLSearchParams(window.location.search).get('calendar_task_id');if(selected)void open(selected);return()=>{++pageRequest.current;++detailRequest.current;pageController.current?.abort();detailController.current?.abort();};},[load,open]);
 function submit(event:FormEvent){event.preventDefault();void open(id);}
 const p=detail?.source;
 return <section aria-label="日历状态任务历史" style={{overflowWrap:'anywhere',minWidth:0}}>
  <h2>4 · 日历状态任务历史</h2><p>已加载{rows.length}条，每页最多50条。按首次记录时间与任务ID倒序；最近30条摘要仍独立保留。新增任务请刷新读取。这里只读，不重试或生成任务。</p>
  <button type="button" className="btn" disabled={pageBusy} onClick={()=>void load()}>刷新日历任务历史</button>
  {pageError&&<p role="alert">{pageError}</p>}{pageBusy&&<p role="status">正在读取日历任务历史…</p>}
  {!pageBusy&&!pageError&&!rows.length&&<p>尚无日历状态任务。</p>}
  {rows.map(row=><article className="evidence-card" key={row.task_run_id}><h3>{row.task_name} · {status[row.task_status]??'原记录状态未知'}</h3><p>任务 {row.task_run_id} · 首次记录 {row.created_at} · 当前保存尝试{row.attempt}</p><button type="button" className="btn" onClick={()=>void open(row.task_run_id)}>查看原日历任务 {row.task_run_id}</button></article>)}
  {cursor?<button type="button" className="btn" disabled={pageBusy} onClick={()=>void load(cursor)}>加载更早日历任务</button>:rows.length>0&&!pageError&&<p>已到当前历史末尾；此范围不是全部任务总数。</p>}
  <form className="calendar-fields" onSubmit={submit}><label>精确日历任务ID<input value={id} onChange={e=>{++detailRequest.current;detailController.current?.abort();setId(e.target.value);setDetail(null);setDetailError('');setDetailBusy(false);}}/></label><button type="submit" className="btn" disabled={detailBusy}>打开精确日历任务</button></form>
  <button type="button" className="btn" disabled={detailBusy||!id} onClick={()=>void open(id)}>刷新所选日历任务</button>
  {detailBusy&&<p role="status">正在读取原日历任务…</p>}{detailError&&<p role="alert">{detailError}</p>}
  {detail&&<section aria-label="原日历任务详情"><h3>原任务 {detail.task_run_id}</h3><p>{status[detail.task_status]??'状态含义未知'} · 当前保存尝试{detail.attempt} · 原因 {missing(detail.reason_code)}</p><p>首次记录 {detail.created_at} · 业务收盘 {detail.scheduled_for} · 当前尝试开始 {missing(detail.started_at)} · 完成 {missing(detail.finished_at)}</p><p>原任务键 {detail.idempotency_key} · 输入hash {detail.input_hash}</p>
   {p?<><p>原来源 {p.source_name} · 版本 {p.source_version} · {p.venue} / {p.market_timezone} · 业务日期 {p.business_date}</p><p>原导入 {p.calendar_import_id} · 原会话 {p.calendar_session_id} · 导入时点 {p.imported_at} · 来源hash {p.calendar_hash}</p><p>来源为人工声明，未推断官方核验（SOURCE_DECLARED / UNVERIFIED）。</p></>:<p>原来源未知，未使用当前日历指针替代。</p>}
   {detail.report_json?<><h4>原日历状态报告</h4><p>{String(detail.report_json.message)}</p><p>原报告事件 {detail.report_event_id} · 记录时间 {detail.report_recorded_at} · 原持久审计hash {detail.report_hash}</p><p>仅状态报告，无付费调用，自动交易关闭。</p></>:<p>本任务没有可核验的状态报告。</p>}
   {detail.unknowns.map(value=><p key={value}>{unknown[value]??`未提供的审计信息 ${value}`}</p>)}
  </section>}
 </section>;
}
