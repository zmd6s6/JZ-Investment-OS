import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { Panel, StatusBanner } from './ProductChrome';
import { apiFetch, readApiError } from './writeApi';
import './weekly-funnel.css';

type Template = {instrument_ids:string[];scope_name:string;scope_locator:string;quote_source_name:string;fact_source_name:string;candidate_limit:number;min_profit_margin:string;min_revenue_growth:string;max_pe:string;min_price_change:string;industry_filter:string|null};
type Configuration = {schema_version:string;schedule_id:string;revision_id:string;version:number;name:string;venue:string;enabled:boolean;calendar_import_id:string;calendar_source:string;calendar_version:string;calendar_hash:string;template_run_id:string;coverage_start:string;coverage_end:string;template:Template;blocker:string|null;scope:string;external_calls:0;model_calls:0;paid_calls:0;auto_trade:false};
type Run = {task_run_id:string;schedule_id:string;revision_id:string;week_start:string;scheduled_for:string;as_of:string|null;status:string;reason_code:string|null;attempt:number;funnel_run_id:string|null;candidate_count:number|null};
type Overview = {schema_version:string;configurations:Configuration[];recent_runs:Run[];auto_trade:false};
type Calendar = {venue:string;import_id:string;source_name:string;source_version:string;content_hash:string};
export type WeeklyTemplate = {run_id:string;query:Omit<Template,'instrument_ids'>;rows:{instrument_id:string;symbol:string}[]};
const reasons:Record<string,string>={UniverseScopeNotYetAvailable: '来源成员集合在该业务周尚未导入或可用；没有提交筛选产物。',WEEKLY_PAUSED:'已暂停；不会排入新筛选',WEEKLY_CALENDAR_CHANGED_OR_MISSING:'日历已变化或缺失；请重新保存版本，默认暂停',MARKET_CLOSED:'完整日历明确本周没有交易会话，已跳过',LOCAL_DATA_MISSING:'本地资料缺失、到期或在业务时点不可用；打开产物查看各层缺项',WeeklyConfigurationChanged:'排入后配置被暂停或替换；本次没有提交筛选产物'};
const statuses:Record<string,string>={COMPLETE:'筛选已完成',DEGRADED:'筛选已记录，资料不完整',EMPTY:'范围内没有候选',SKIPPED_CLOSED:'市场关闭，已跳过',FAILED:'任务失败',RUNNING:'任务运行中',PENDING:'任务等待中'};
const text=(value:unknown)=>typeof value==='string';
const uuid=(value:unknown)=>text(value)&&/^[0-9a-f-]{36}$/i.test(value as string);
const time=(value:unknown)=>text(value)&&Number.isFinite(Date.parse(value as string));
export function parseWeeklyConfiguration(raw:unknown):Configuration {
 const c=raw as Configuration;
 if(!c||c.schema_version!=='1.0'||!uuid(c.schedule_id)||!uuid(c.revision_id)||!Number.isInteger(c.version)||c.version<1||!text(c.name)||!['SSE','SZSE'].includes(c.venue)||typeof c.enabled!=='boolean'||!uuid(c.calendar_import_id)||!uuid(c.template_run_id)||!text(c.calendar_source)||!text(c.calendar_version)||!text(c.calendar_hash)||!/^[a-f0-9]{64}$/.test(c.calendar_hash)||!text(c.coverage_start)||!text(c.coverage_end)||!c.template||!Array.isArray(c.template.instrument_ids)||c.template.instrument_ids.length<1||c.template.instrument_ids.length>200||c.template.instrument_ids.some(i=>!uuid(i))||new Set(c.template.instrument_ids).size!==c.template.instrument_ids.length||!Number.isInteger(c.template.candidate_limit)||c.template.candidate_limit<1||c.template.candidate_limit>20||![c.template.scope_name,c.template.scope_locator,c.template.quote_source_name,c.template.fact_source_name,c.template.min_profit_margin,c.template.min_revenue_growth,c.template.max_pe,c.template.min_price_change].every(text)||!(c.template.industry_filter===null||text(c.template.industry_filter))||!(c.blocker===null||text(c.blocker))||c.scope!=='LOCAL_WEEKLY_DETERMINISTIC_ONLY'||c.external_calls!==0||c.model_calls!==0||c.paid_calls!==0||c.auto_trade!==false)throw new Error('周筛选配置格式异常，未确认保存或启用；请用同一内容重试核对。');
 return c;
}
export function parseWeeklyOverview(raw:unknown):Overview {
 const value=raw as Overview;
 if(!value||value.schema_version!=='1.0'||value.auto_trade!==false||!Array.isArray(value.configurations)||value.configurations.length>50||!Array.isArray(value.recent_runs)||value.recent_runs.length>50)throw new Error('周筛选响应格式异常，未采用。');
 value.configurations.forEach(parseWeeklyConfiguration);
 for(const r of value.recent_runs)if(!r||!uuid(r.task_run_id)||!uuid(r.schedule_id)||!uuid(r.revision_id)||!text(r.week_start)||!time(r.scheduled_for)||!(r.as_of===null||time(r.as_of))||!statuses[r.status]||!(r.reason_code===null||text(r.reason_code))||!Number.isInteger(r.attempt)||r.attempt<1||!(r.funnel_run_id===null||uuid(r.funnel_run_id))||!(r.candidate_count===null||(Number.isInteger(r.candidate_count)&&r.candidate_count>=0&&r.candidate_count<=20))||(['COMPLETE','DEGRADED','EMPTY'].includes(r.status)&&(!r.funnel_run_id||r.as_of===null||r.candidate_count===null)))throw new Error('周筛选运行记录格式异常，没有伪造成功。');
 return value;
}
async function json(url:string,body?:unknown):Promise<unknown>{
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
 try{const response=await apiFetch(url,body===undefined?{signal:controller.signal}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});if(!response.ok)throw new Error(await readApiError(response));return await response.json();}
 catch(e){if(e instanceof TypeError||e instanceof SyntaxError||(e instanceof DOMException&&e.name==='AbortError'))throw new Error('服务连接、超时或响应异常。结果未确认，输入已保留，请用同一内容重试核对。');throw e;}finally{clearTimeout(timeout);}
}
function Scope({template}:{template:Template|Omit<Template,'instrument_ids'>}){return <p>范围：{template.scope_name}；出处：{template.scope_locator}；报价来源：{template.quote_source_name}；事实来源：{template.fact_source_name}。条件：利润率 ≥ {template.min_profit_margin}，营收增长 ≥ {template.min_revenue_growth}，年报PE ≤ {template.max_pe}，价格变化 ≥ {template.min_price_change}；行业：{template.industry_filter||'不限'}；候选上限：{template.candidate_limit}。</p>;}

export function WeeklyFunnelPanel({template}:{template:WeeklyTemplate|null}){
 const [overview,setOverview]=useState<Overview|null>(null);const [calendars,setCalendars]=useState<Calendar[]>([]);const [healthy,setHealthy]=useState(false);const [working,setWorking]=useState(false);const [error,setError]=useState<string|null>(null);const [message,setMessage]=useState<string|null>(null);
 const [edit,setEdit]=useState('');const [name,setName]=useState('');const [venue,setVenue]=useState('');const [start,setStart]=useState('');const [end,setEnd]=useState('');const [complete,setComplete]=useState(false);const [local,setLocal]=useState(false);const [modeAck,setModeAck]=useState(false);
 const feedback=useRef<HTMLDivElement>(null);
 useEffect(()=>{if((error||message)&&typeof feedback.current?.scrollIntoView==='function')feedback.current.scrollIntoView({behavior:'smooth',block:'center'});},[error,message]);
 const busy=useRef(false);const alive=useRef(true);const generation=useRef(0);const pending=useRef<{key:string;id:string;scheduleId:string}|null>(null);
 const load=useCallback(async()=>{const id=++generation.current;try{const [raw,calendarRaw]=await Promise.all([json('/api/v1/opportunities/weekly'),json('/api/v1/calendar')]);const data=parseWeeklyOverview(raw);const c=calendarRaw as {schema_version:string;configurations:Calendar[]};if(!c||c.schema_version!=='1.0'||!Array.isArray(c.configurations)||c.configurations.some(x=>!x||!text(x.venue)||!uuid(x.import_id)||!text(x.source_name)||!text(x.source_version)||!text(x.content_hash)))throw new Error('日历状态无法核对，请到日历页面检查。');if(alive.current&&id===generation.current){setOverview(data);setCalendars(c.configurations);setHealthy(true);}}catch(e){if(alive.current&&id===generation.current){setHealthy(false);setError(e instanceof Error?e.message:'读取周筛选失败。');}}},[]);
 useEffect(()=>{alive.current=true;void load();return()=>{alive.current=false;++generation.current;};},[load]);
 const active=overview?.configurations.some(c=>c.enabled);
 useEffect(()=>{if(!active)return;const timer=setInterval(()=>{if(!busy.current&&document.visibilityState!=='hidden')void load();},5000);return()=>clearInterval(timer);},[active,load]);
 useEffect(()=>{setComplete(false);setLocal(false);pending.current=null;},[template?.run_id]);
 const selected=overview?.configurations.find(c=>c.schedule_id===edit);const calendar=calendars.find(c=>c.venue===venue);
 useEffect(()=>{setComplete(false);setLocal(false);pending.current=null;},[calendar?.import_id,selected?.version]);
 const modeVersions=JSON.stringify(overview?.configurations.map(c=>[c.schedule_id,c.version,c.calendar_import_id,c.blocker]));
 useEffect(()=>setModeAck(false),[modeVersions]);
 function changed(){setComplete(false);setLocal(false);setMessage(null);pending.current=null;}
 async function operate(action:()=>Promise<void>){if(busy.current)return;busy.current=true;setWorking(true);setError(null);setMessage(null);++generation.current;try{await action();}catch(e){if(alive.current)setError(e instanceof Error?e.message:'周筛选操作失败，输入已保留。');}finally{busy.current=false;if(alive.current)setWorking(false);}}
 async function save(event:FormEvent){event.preventDefault();if(!template||!calendar||!complete||!local)return;await operate(async()=>{const scheduleId=edit||pending.current?.scheduleId||crypto.randomUUID();const content={schedule_id:scheduleId,expected_version:selected?.version??0,name:name.trim(),venue,funnel_run_id:template.run_id,calendar_import_id:calendar.import_id,coverage_start:start,coverage_end:end,complete_calendar_acknowledgement:true,local_only_acknowledgement:true};const key=JSON.stringify(content);if(pending.current?.key!==key)pending.current={key,id:crypto.randomUUID(),scheduleId};const result=parseWeeklyConfiguration(await json('/api/v1/opportunities/weekly',{...content,request_id:pending.current.id}));if(result.schedule_id!==scheduleId||result.enabled||result.calendar_import_id!==calendar.import_id)throw new Error('保存回执与本次配置不一致，尚未确认。请刷新核对。');setEdit(result.schedule_id);pending.current=null;setComplete(false);setLocal(false);setMessage('周筛选新版本已保存，默认暂停。核对范围和日历后可单独启用本地筛选。');await load();});}
 const modePending=useRef(new Map<string,{key:string;id:string}>());
 async function mode(c:Configuration){if(!c.enabled&&!modeAck)return;await operate(async()=>{const content={expected_version:c.version,enabled:!c.enabled,local_only_acknowledgement:true};const key=JSON.stringify(content);let request=modePending.current.get(c.schedule_id);if(request?.key!==key){request={key,id:crypto.randomUUID()};modePending.current.set(c.schedule_id,request);}const result=parseWeeklyConfiguration(await json(`/api/v1/opportunities/weekly/${c.schedule_id}/mode`,{...content,request_id:request!.id}));if(result.schedule_id!==c.schedule_id||result.enabled!==!c.enabled)throw new Error('启停回执不一致，请刷新核对，尚未确认。');setModeAck(false);setMessage(result.enabled?'已显式启用本地周筛选；每个配置版本、业务周仅提交一次。':'暂停已确认。此前已提交的历史保留，不再排入新的筛选。');await load();});}
 return <div className="weekly-funnel"><Panel title="6 · 每周本地确定性筛选" description="默认暂停；不访问外网、不调用模型、零费用。不是全市场任务，也不自动研究候选。">
 <p>先从上方展示的历史漏斗冻结手选范围（最多200项）、来源、条件和候选上限（最多20项）。仅支持同一沪市或深市人民币标的。日历状态任务的启用不授权本任务。<a href="/calendar">去日历导入明确来源的完整交易日期</a>。</p>
 <div ref={feedback} style={{scrollMarginTop:160}}/>
 {error?<StatusBanner kind="error" text={error}/>:null}{message?<StatusBanner kind="ok" text={message}/>:null}
 <button className="btn" type="button" disabled={working} onClick={()=>{setError(null);void load();}}>刷新周筛选与日历</button>
 <form onSubmit={e=>void save(e)}><fieldset disabled={working||!healthy} style={{border:0,padding:0}}><div className="form-grid">
 <label className="field">周配置<select value={edit} onChange={e=>{changed();setEdit(e.target.value);const c=overview?.configurations.find(x=>x.schedule_id===e.target.value);setName(c?.name??'');setVenue(c?.venue??'');setStart(c?.coverage_start??'');setEnd(c?.coverage_end??'');}}><option value="">新建（默认暂停）</option>{overview?.configurations.map(c=><option key={c.schedule_id} value={c.schedule_id}>{c.name} · v{c.version}</option>)}</select></label>
 <label className="field">周配置名称<input required value={name} onChange={e=>{changed();setName(e.target.value);}}/></label><label className="field">周筛选市场<select required value={venue} onChange={e=>{changed();setVenue(e.target.value);}}><option value="">请明确选择</option><option value="SSE">沪市 · Asia/Shanghai</option><option value="SZSE">深市 · Asia/Shanghai</option></select></label>
 <label className="field">完整覆盖开始（周一）<input required type="date" value={start} onChange={e=>{changed();setStart(e.target.value);}}/></label><label className="field">完整覆盖结束（周日）<input required type="date" value={end} onChange={e=>{changed();setEnd(e.target.value);}}/></label></div>
 {template?<><p>将冻结当前展示漏斗：{template.run_id}；{template.rows.length} 项：{template.rows.map(r=>r.symbol).join('、')}。</p><Scope template={template.query}/></>:<p>先在上方运行或选择一条历史漏斗，才能保存配置。</p>}
 {calendar?<p>绑定当前日历：{calendar.source_name} / {calendar.source_version}；摘要 {calendar.content_hash}。更换导入后旧配置停止排入，必须保存新版本。</p>:<p>所选市场没有可核对日历，不能保存或启用。</p>}
 <p>每周频率固定：完整自然周结束后的周一00:00（上海时间）才到期；使用该周最后一个明确会话的收盘时点。覆盖1–52周。缺资料或过期会显示缺项；只有下列完整性声明才能把无会话的周解释为关闭。没有声明就不能推断交易日。</p>
 <label><input type="checkbox" checked={complete} onChange={e=>setComplete(e.target.checked)}/>我已核对来源，绑定日历包含上述每个完整周的全部交易日期；未列日期明确为休市，非未知或漏导入</label><br/>
 <label><input type="checkbox" checked={local} onChange={e=>setLocal(e.target.checked)}/>仅授权读取本地已保存事实与行情，固定零外网／零模型／零费用，不授权候选研究或交易</label><br/>
 <button className="btn primary" type="submit" disabled={!template||!calendar||!complete||!local||template.rows.length===0}>保存周配置（暂停）</button></fieldset></form>
 <label><input type="checkbox" checked={modeAck} disabled={working||!healthy} onChange={e=>setModeAck(e.target.checked)}/>我已核对下方保存版本的范围、来源、完整周和日历；确认仅启用本地周筛选</label>
 {overview?.configurations.map(c=><article className="evidence-card" key={c.schedule_id}><h3>{c.name} · v{c.version} · {c.enabled?'已启用本地筛选':'已暂停'}</h3><p>{c.venue}，{c.coverage_start} 至 {c.coverage_end}；版本 {c.revision_id}；固定零外网／零模型／零费用。</p><Scope template={c.template}/><a href={`/opportunities?run_id=${encodeURIComponent(c.template_run_id)}`}>核对冻结范围的原始漏斗与标的名称</a><p>冻结标的 {c.template.instrument_ids.length} 项：{c.template.instrument_ids.join('、')}</p><p>日历 {c.calendar_source} / {c.calendar_version}；{c.calendar_hash}</p>{c.blocker?<p>{reasons[c.blocker]??'配置状态需要重新核对'}</p>:null}<button className="btn" type="button" disabled={working||!healthy||(!c.enabled&&(!modeAck||Boolean(c.blocker&&c.blocker!=='WEEKLY_PAUSED')))} onClick={()=>void mode(c)}>{c.enabled?'暂停':'启用本地周筛选'} {c.name}</button></article>)}
 <h3>周筛选运行历史</h3><p>最近50个任务；每个版本、业务周唯一。失败最多重试3次；无产物时不伪造业务快照。暂停与修订保留旧历史。覆盖到期后需显式保存新覆盖版本，不自动延长。</p>
 {overview?.recent_runs.length===0?<p>尚无周筛选任务；默认暂停或完整业务周尚未结束时不会制造运行。</p>:null}
 {overview?.recent_runs.map(r=><article className="evidence-card" key={r.task_run_id}><h4>{r.week_start} 周 · {statuses[r.status]} · 第{r.attempt}次</h4><p>任务 {r.task_run_id}；版本 {r.revision_id}；到期 {r.scheduled_for}；业务快照 {r.as_of??'未提交'}；候选 {r.candidate_count??'未产生'}。</p>{r.reason_code?<p>{reasons[r.reason_code]??'任务未完成，请核对服务日志和本地资料；没有自动扩大范围。'}</p>:null}{r.funnel_run_id?<a href={`/opportunities?run_id=${encodeURIComponent(r.funnel_run_id)}`}>查看本周候选与各层缺项</a>:<p>本任务没有筛选产物。</p>}</article>)}
 </Panel></div>;
}
