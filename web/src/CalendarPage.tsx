import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
import "./calendar.css";

type Venue="SSE"|"SZSE"|"US_EQUITIES";
type Draft={venue:Venue;source_name:string;source_version:string;csv_text:string;confirmed_source:boolean};
type Session={business_date:string;close_at_utc:string};
type Preview={schema_version:"1.0";venue:Venue;market_timezone:string;source_name:string;source_version:string;content_hash:string;sessions:Session[]};
type Configuration={venue:Venue;market_timezone:string;version:number;import_id:string;enabled:boolean;source_name:string;source_version:string;content_hash:string;imported_at:string;session_count:number;first_business_date:string;last_business_date:string;next_close_at:string|null};
type Report={report_kind:"CALENDAR_STATUS_ONLY";venue:Venue;business_date:string;as_of:string;calendar_import_id:string;calendar_hash:string;source_name:string;source_version:string;message:string;auto_trade:false;paid_calls:0};
type Run={task_run_id:string;task_name:string;as_of:string;status:string;attempt:number;started_at:string;finished_at:string|null;error_code:string|null;report:Report|null};
type Overview={schema_version:"1.0";scope:"CALENDAR_STATUS_ONLY_NO_PAID_CALLS";auto_trade:false;configurations:Configuration[];recent_runs:Run[]};
type FrozenPreview={value:Preview;input:Draft;expectedVersion:number};
const venues:Record<Venue,string>={SSE:"上海证券交易所",SZSE:"深圳证券交易所",US_EQUITIES:"美国股票市场"};
const timezone=(venue:Venue)=>venue==="US_EQUITIES"?"America/New_York":"Asia/Shanghai";
const validTime=(value:unknown)=>typeof value==="string"&&Number.isFinite(Date.parse(value));
const hash=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{64}$/.test(value);

export function parseCalendarOverview(raw:unknown):Overview {
  const value=raw as Overview;
  if(!value||value.schema_version!=="1.0"||value.scope!=="CALENDAR_STATUS_ONLY_NO_PAID_CALLS"||value.auto_trade!==false||!Array.isArray(value.configurations)||value.configurations.length>3||!Array.isArray(value.recent_runs)||value.recent_runs.length>30)throw new Error("日历状态响应格式异常，未采用，请重试或检查服务版本。");
  const ids=new Set<string>();
  for(const item of value.configurations){
    if(!item||!Object.hasOwn(venues,item.venue)||ids.has(item.venue)||item.market_timezone!==timezone(item.venue)||!Number.isInteger(item.version)||item.version<1||typeof item.import_id!=="string"||typeof item.enabled!=="boolean"||typeof item.source_name!=="string"||typeof item.source_version!=="string"||!hash(item.content_hash)||!validTime(item.imported_at)||!Number.isInteger(item.session_count)||item.session_count<1||item.session_count>1000||typeof item.first_business_date!=="string"||typeof item.last_business_date!=="string"||!(item.next_close_at===null||validTime(item.next_close_at)))throw new Error("日历配置无法核对，未改变当前输入。请刷新或检查服务版本。");
    ids.add(item.venue);
  }
  for(const run of value.recent_runs)if(!run||typeof run.task_run_id!=="string"||typeof run.task_name!=="string"||!validTime(run.as_of)||!["RUNNING","SUCCEEDED","FAILED"].includes(run.status)||!Number.isInteger(run.attempt)||run.attempt<1||!validTime(run.started_at)||!(run.finished_at===null||validTime(run.finished_at))||!(run.error_code===null||typeof run.error_code==="string")||(run.status==="SUCCEEDED"&&run.report===null)||!(run.report===null||(run.report.report_kind==="CALENDAR_STATUS_ONLY"&&Object.hasOwn(venues,run.report.venue)&&typeof run.report.business_date==="string"&&validTime(run.report.as_of)&&typeof run.report.calendar_import_id==="string"&&hash(run.report.calendar_hash)&&typeof run.report.source_name==="string"&&typeof run.report.source_version==="string"&&typeof run.report.message==="string"&&run.report.auto_trade===false&&run.report.paid_calls===0)))throw new Error("日历运行记录格式异常，未伪造成功状态。请刷新核对。");
  return value;
}

function parsePreview(raw:unknown,input:Draft):Preview {
  const value=raw as Preview;
  if(!value||value.schema_version!=="1.0"||value.venue!==input.venue||value.market_timezone!==timezone(input.venue)||value.source_name!==input.source_name.trim()||value.source_version!==input.source_version.trim()||!hash(value.content_hash)||!Array.isArray(value.sessions)||!value.sessions.length||value.sessions.length>1000||value.sessions.some(s=>!s||typeof s.business_date!=="string"||!validTime(s.close_at_utc))||new Set(value.sessions.map(s=>s.business_date)).size!==value.sessions.length)throw new Error("日历预览响应不完整或来源不匹配，禁止确认导入，请重新预览。");
  return value;
}

async function requestJson<T>(url:string,body:unknown,operation:string):Promise<T> {
  const controller=new AbortController();
  let received=false;
  let timer:ReturnType<typeof setTimeout>;
  const deadline=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error(`${operation}结果尚未确认。输入已保留，请用同一内容重试核对；不会自动重复提交。`));},15000);});
  try {
    return await Promise.race([(async()=>{
      const response=await apiFetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:controller.signal});
      received=true;
      if(!response.ok)throw new Error(await readApiError(response));
      return await response.json() as T;
    })(),deadline]);
  } catch(reason) {
    if(!received||reason instanceof SyntaxError)throw new Error(`${operation}结果尚未确认。输入已保留，请用同一内容重试核对；不会自动重复提交。`);
    throw reason;
  } finally {clearTimeout(timer!);}
}

export function CalendarPage(){
  const [overview,setOverview]=useState<Overview|null>(null);
  const [healthy,setHealthy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [working,setWorking]=useState(false);
  const [readingFile,setReadingFile]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [message,setMessage]=useState<string|null>(null);
  const [draft,setDraft]=useState<Draft>({venue:"SSE",source_name:"",source_version:"",csv_text:"",confirmed_source:false});
  const [preview,setPreview]=useState<FrozenPreview|null>(null);
  const [confirmImport,setConfirmImport]=useState(false);
  const [acknowledged,setAcknowledged]=useState<string[]>([]);
  const busy=useRef(false);
  const generation=useRef(0);
  const readController=useRef<AbortController|null>(null);
  const fileGeneration=useRef(0);
  const importRequest=useRef<{fingerprint:string;body:unknown}|null>(null);
  const modeRequests=useRef(new Map<Venue,{fingerprint:string;body:unknown}>());
  const load=useCallback(async(manual=true)=>{
    const id=++generation.current;
    readController.current?.abort();
    const controller=new AbortController();readController.current=controller;
    if(manual){setLoading(true);setError(null);}
    const deadline=setTimeout(()=>{controller.abort();if(id===generation.current){setHealthy(false);setLoading(false);setError("读取日历与运行记录超时，请刷新重试；原输入保留。");}},15000);
    try {
      const response=await fetch("/api/v1/calendar",{signal:controller.signal});
      if(!response.ok)throw new Error("无法读取日历服务，请检查应用与数据库后刷新重试。");
      const value=parseCalendarOverview(await response.json());
      if(!controller.signal.aborted&&id===generation.current){setOverview(value);setHealthy(true);setError(null);}
    }catch(reason){if(!controller.signal.aborted&&id===generation.current){setHealthy(false);setError(reason instanceof SyntaxError?"日历响应格式异常，请刷新重试。":reason instanceof TypeError?"无法连接日历服务，请检查本地服务后刷新重试。":reason instanceof Error?reason.message:"读取失败，请刷新重试。");}}
    finally{clearTimeout(deadline);if(id===generation.current&&!controller.signal.aborted)setLoading(false);}
  },[]);
  useEffect(()=>{void load();return()=>{++generation.current;readController.current?.abort();};},[load]);
  const enabled=Boolean(overview?.configurations.some(c=>c.enabled));
  useEffect(()=>{if(!enabled)return;const timer=setInterval(()=>{if(!busy.current&&document.visibilityState!=="hidden")void load(false);},5000);return()=>clearInterval(timer);},[enabled,load]);
  const currentVersion=overview?.configurations.find(c=>c.venue===draft.venue)?.version??0;
  const stale=Boolean(preview&&preview.expectedVersion!==currentVersion);
  function change(patch:Partial<Draft>){++fileGeneration.current;setDraft(value=>({...value,...patch,confirmed_source:false}));setPreview(null);setConfirmImport(false);importRequest.current=null;setMessage(null);}
  async function file(file:File|undefined){if(!file)return;const id=++fileGeneration.current;setDraft(value=>({...value,confirmed_source:false}));setPreview(null);setConfirmImport(false);importRequest.current=null;setReadingFile(false);if(file.size>400000){setError("日历CSV文件过大，请限制为1000条以内、10万字符以内。未导入。");return;}setReadingFile(true);try{const value=await file.text();if(id!==fileGeneration.current)return;if(value.length>100000){setError("日历CSV超过10万字符，未导入。");return;}setReadingFile(false);change({csv_text:value});setError(null);}catch{if(id===fileGeneration.current)setError("无法读取日历文件，请重新选择或粘贴CSV；未导入。");}finally{if(id===fileGeneration.current)setReadingFile(false);}}
  async function run(action:()=>Promise<void>){if(busy.current)return;busy.current=true;setWorking(true);setError(null);setMessage(null);++generation.current;readController.current?.abort();try{await action();}catch(reason){setError(reason instanceof Error?reason.message:"操作失败，输入已保留。");}finally{busy.current=false;setWorking(false);}}
  async function makePreview(){await run(async()=>{const input=structuredClone(draft);const version=currentVersion;const value=parsePreview(await requestJson("/api/v1/calendar/preview",input,"日历预览"),input);setPreview({input,value,expectedVersion:version});setConfirmImport(false);setMessage("预览完成，尚未导入。请核对来源、业务日期与UTC收盘时间后明确确认。");});}
  async function save(){if(!preview||stale||!confirmImport)return;await run(async()=>{const candidate={...preview.input,expected_version:preview.expectedVersion};const fingerprint=JSON.stringify(candidate);if(importRequest.current?.fingerprint!==fingerprint)importRequest.current={fingerprint,body:{...candidate,request_id:crypto.randomUUID()}};const result=await requestJson<Configuration>("/api/v1/calendar/imports",importRequest.current.body,"日历保存");if(result.venue!==preview.input.venue||result.content_hash!==preview.value.content_hash||typeof result.enabled!=="boolean"||!Number.isInteger(result.version)||result.version<1)throw new Error("保存回执无法核对，请保留原内容重试核对；不会自动创建新请求。");setMessage(`已保存并核对日历。当前${result.enabled?"已启用无付费状态报告（相同内容未新建版本，保留原状态）":"已暂停，不会自动开始研究或模型调用"}。`);setPreview(null);setConfirmImport(false);importRequest.current=null;await load();});}
  async function mode(config:Configuration){await run(async()=>{const candidate={expected_version:config.version,enabled:!config.enabled,status_only_acknowledgement:true};const fingerprint=JSON.stringify(candidate);if(modeRequests.current.get(config.venue)?.fingerprint!==fingerprint)modeRequests.current.set(config.venue,{fingerprint,body:{...candidate,request_id:crypto.randomUUID()}});const result=await requestJson<Configuration>(`/api/v1/calendar/${config.venue}/mode`,modeRequests.current.get(config.venue)!.body,config.enabled?"暂停状态报告":"启用状态报告");if(result.venue!==config.venue||result.enabled!==!config.enabled||result.import_id!==config.import_id||result.content_hash!==config.content_hash||result.version!==config.version+1)throw new Error("启停回执无法核对，请刷新确认或用原操作重试；不会自动重放。");modeRequests.current.delete(config.venue);setMessage(result.enabled?"仅日历状态报告已启用。Worker按已导入收盘时段有界检查，本页每5秒只读刷新；不调用模型或数据源。":"日历状态报告已暂停。已生成的历史保留，不会删除。");await load();});}
  const disabled=loading||working||readingFile||!healthy;
  return <ProductChrome eyebrow="MVP-401 · 无付费运行" title="市场日历与运行状态" subtitle="导入明确交易时段，观察Worker实际状态报告；这里不会运行团队研究或下单。">
    <StatusBanner kind="error" text={error}/><StatusBanner kind="ok" text={message}/>
    <StatusBanner kind="info" text={working?"正在处理日历操作，请勿重复提交…":readingFile?"正在读取日历文件…":loading?"正在读取日历与运行记录…":null}/>
    <Panel title="先了解范围" actions={<button type="button" className="btn" disabled={working||loading} onClick={()=>void load()}>{loading?"正在读取…":"刷新日历与运行记录"}</button>}>
      <p>1. 填写市场与有权使用的来源 → 2. 上传或粘贴CSV并预览 → 3. 明确导入（新版本默认暂停） → 4. 单独确认启用无付费状态报告。</p>
      <p>目前只提供日历状态报告；团队研究、完整分析、周月复核与真实定时费用授权尚未接通，不会被本开关启用。自动交易始终关闭。</p>
      <p>没有运行记录不代表Worker健康：可能尚无到期会话、已暂停或Worker未运行。启用后的可见页面每5秒只读刷新；失败时仍可手动刷新，输入不会丢失。</p>
      {!healthy&&!loading&&overview?<p className="banner banner-info">下方为上次读取状态，当前未确认；恢复读取前禁止新的保存或启停。</p>:null}
    </Panel>
    <Panel title="1 · 导入明确日历" description="最多1000条；不推断工作日、节假日或真实数据授权。来源文字只作为不可信说明保存。">
      <fieldset disabled={disabled} className="calendar-fields" style={{border:0,padding:0,minWidth:0}}>
        <label>日历市场<select value={draft.venue} onChange={e=>change({venue:e.target.value as Venue})}>{Object.entries(venues).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <p>市场时区：{timezone(draft.venue)}；当前已保存配置版本：{currentVersion||"尚无版本"}</p>
        <label>日历来源名称<input maxLength={200} value={draft.source_name} placeholder="填写你已核对的实际来源名称，勿填凭据" onChange={e=>change({source_name:e.target.value})}/></label>
        <label>来源版本<input maxLength={200} value={draft.source_version} placeholder="例如文件发布日期或来源版本号" onChange={e=>change({source_version:e.target.value})}/></label>
        <label>上传日历CSV<input type="file" accept=".csv,text/csv" onChange={e=>void file(e.target.files?.[0])}/></label>
        <label>日历CSV内容<textarea rows={7} maxLength={100000} value={draft.csv_text} placeholder={"business_date,close_at\nYYYY-MM-DD,HH:MM"} onChange={e=>change({csv_text:e.target.value})}/></label>
        <p className="hint-text">第一行必须为 business_date,close_at；每行一个明确业务日期与本地收盘时间。时区由市场固定，重复 / 错误行、DST歧义时刻会整批拒绝。示例格式不代表真实交易日历。</p>
        <label className="calendar-check"><input type="checkbox" checked={draft.confirmed_source} onChange={e=>{setDraft(value=>({...value,confirmed_source:e.target.checked}));setPreview(null);setConfirmImport(false);importRequest.current=null;}}/><span>我已核对来源与时段，确认有权导入这些日历数据。</span></label>
        <button type="button" className="btn" disabled={!draft.confirmed_source||!draft.source_name.trim()||!draft.source_version.trim()||!draft.csv_text.trim()} onClick={()=>void makePreview()}>{working?"正在处理…":"预览日历（不保存）"}</button>
      </fieldset>
      {preview?<section className="calendar-preview"><h3>待确认预览 · {preview.value.sessions.length}条时段</h3><p>{preview.value.source_name} · {preview.value.source_version} · {preview.value.market_timezone}</p><p style={{overflowWrap:"anywhere"}}>内容摘要：{preview.value.content_hash}</p>
        <details open><summary>核对规范化时段（{preview.value.sessions.length}）</summary><div style={{maxHeight:320,overflow:"auto"}}>{preview.value.sessions.map(session=><p key={session.business_date}>业务日期 {session.business_date} · UTC收盘 {session.close_at_utc}</p>)}</div></details>
        {stale?<p className="banner banner-error">当前配置已变化，旧预览不能保存。请保留输入并重新预览，不会覆盖新版本。</p>:null}
        <label className="calendar-check"><input type="checkbox" checked={confirmImport} disabled={disabled||stale} onChange={e=>setConfirmImport(e.target.checked)}/><span>我确认按此预览导入；新版本默认暂停，相同内容保持原启用状态。</span></label>
        <button type="button" className="btn primary" disabled={disabled||stale||!confirmImport} onClick={()=>void save()}>确认导入日历</button>
      </section>:null}
    </Panel>
    <Panel title="2 · 已保存日历与启停" description="导入不会自动启用；启用只允许无付费的日历状态报告。">
      {!overview?.configurations.length?<p>{loading?"正在读取已保存日历…":!healthy?"当前日历状态未确认，请恢复读取后核对；不能据此断言没有配置。":"尚无已保存日历，不会调度任何产品状态任务。"}</p>:overview.configurations.map(config=><article className="evidence-card calendar-config" key={config.venue} aria-label={`${venues[config.venue]}日历配置`}>
        <h3>{venues[config.venue]} · {config.enabled?"已启用无付费状态报告":"已暂停"}</h3><p>{config.source_name} · 版本 {config.source_version} · 配置版本 {config.version}</p>
        <p>时区 {config.market_timezone} · {config.session_count}条会话 · {config.first_business_date} 至 {config.last_business_date}</p><p>导入时间：{config.imported_at} · {config.next_close_at?`下一未来收盘（UTC）：${config.next_close_at}`:"无未来时段；已到期时段将由Worker有界检查，不代表已完成。"}</p><p style={{overflowWrap:"anywhere"}}>来源摘要：{config.content_hash}</p>
        {!config.enabled?<label className="calendar-check"><input type="checkbox" checked={acknowledged.includes(`${config.venue}:${config.version}`)} disabled={disabled} onChange={e=>setAcknowledged(values=>e.target.checked?[...values,`${config.venue}:${config.version}`]:values.filter(v=>v!==`${config.venue}:${config.version}`))}/><span>我仅启用该市场已导入时段的状态报告；不调用付费模型、研究来源或交易。</span></label>:null}
        <button type="button" className="btn" disabled={disabled||(!config.enabled&&!acknowledged.includes(`${config.venue}:${config.version}`))} onClick={()=>void mode(config)}>{config.enabled?"暂停状态报告":"启用无付费状态报告"}</button>
      </article>)}
    </Panel>
    <Panel title="3 · Worker实际运行记录" description="最近30次日历状态任务；完成仅表示状态报告写入，不表示团队分析或投资批准。">
      {!overview?.recent_runs.length?<p>尚无日历状态运行记录。请核对是否导入并启用、收盘时刻是否已到，以及Worker服务是否运行。</p>:overview.recent_runs.map(run=><article key={run.task_run_id} className="evidence-card" style={{overflowWrap:"anywhere"}}>
        <h3>{run.task_name} · {run.status==="SUCCEEDED"?"状态报告已完成":run.status==="FAILED"?"状态任务失败":"状态任务运行中"}</h3><p>业务时点 {run.as_of} · 第{run.attempt}次尝试 · 实际开始 {run.started_at} · 完成 {run.finished_at??"未完成"}</p>
        {run.report?<><p>{run.report.message}</p><p>来源：{run.report.source_name} · 版本 {run.report.source_version} · 市场 {run.report.venue}</p><p>来源摘要：{run.report.calendar_hash}</p></>:<p>{run.status==="FAILED"?"未生成状态报告。请核对并导入更正后的来源版本，再明确启用以恢复；旧失败记录保留，已成功业务日期不会重复报告。":"尚未保存状态报告。"}</p>}
        {run.error_code?<p>失败代码：{run.error_code}{run.attempt>=3?"（已达自动重试上限）":"；Worker可在上限内重试，暂停可停止后续调度。"}</p>:null}
      </article>)}
    </Panel>
  </ProductChrome>;
}
