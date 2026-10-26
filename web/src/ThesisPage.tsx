import { useEffect, useRef, useState } from "react";
import { InstrumentHit, InstrumentSearchBox } from "./InstrumentSearchBox";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { readAnalysisJson } from "./analysisReads";
import { apiFetch, readApiError } from "./writeApi";
import { TeamThesisDraft, TeamSource, TeamSuggestion, TeamImpact, impactRiskDescription } from "./TeamThesisDraft";
import { ThesisDraftChanges } from "./ThesisDraftChanges";

type Claim = { description: string; evidence_ids: string[] };
type Pillar = { key: string; claim: Claim; status: string };
type Condition = { condition: string; measurement: string; threshold: string; window: string };
type Content = { state: string; long_term_summary: string; pillars: Pillar[]; catalysts: Claim[]; risks: Claim[]; invalidation_conditions: Condition[]; monitoring_conditions: string[]; change_reason: string };
type Version = { id: string; version: number; parent_version_id: string | null; content_hash: string; created_at: string; content: Content; semantic_diff: unknown; review_sources?:{analysis_run_id:string;suggestion_ids:string[];impact_ids?:string[];input_hash:string;opinion_ids:string[]}[] };
type Workspace = { instrument_id: string; current_version_id: string | null; versions: Version[] };
type Evidence = { evidence_id: string; title: string; excerpt: string; source_name: string; freshness_status: string };
type Pending = { request_id: string; expected_version_id: string | null; content: Content; review_source?:TeamSource };
const stateNames: Record<string,string> = { UNKNOWN:"未知", VALID:"有效", STRENGTHENING:"增强", WEAKENING:"减弱", BROKEN:"已失效" };
const transitions: Record<string,string[]> = { UNKNOWN:["UNKNOWN","VALID"],VALID:["VALID","STRENGTHENING","WEAKENING"],STRENGTHENING:["STRENGTHENING","VALID","WEAKENING"],WEAKENING:["WEAKENING","BROKEN"],BROKEN:["BROKEN"] };
const blankClaim = (): Claim => ({ description:"",evidence_ids:[] });
const empty = (): Content => ({ state:"UNKNOWN",long_term_summary:"",pillars:[{ key:"P1",claim:blankClaim(),status:"VALID" }],catalysts:[],risks:[],invalidation_conditions:[],monitoring_conditions:[],change_reason:"HUMAN_CORRECTION" });

async function save(url: string, body: Pending) {
  const controller=new AbortController();
  let responseReceived=false;
  let timer: ReturnType<typeof setTimeout>;
  const deadline=new Promise<never>((_,reject)=>{ timer=setTimeout(()=>{ controller.abort(); reject(new Error("保存结果尚未确认。输入已保留，可用同一内容再次保存以核对原请求；不会重复创建版本。")); },15000); });
  try {
    return await Promise.race([(async()=>{
      const response=await apiFetch(url,{method:"POST",signal:controller.signal,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      responseReceived=true;
      if (!response.ok) throw new Error(await readApiError(response));
      return await response.json() as {version_id:string;version:number;created:boolean};
    })(),deadline]);
  } catch(reason) {
    if(!responseReceived || reason instanceof SyntaxError) throw new Error("保存结果尚未确认，输入已保留。请用同一内容再次保存以核对原请求，不会重复创建版本。");
    throw reason;
  } finally { clearTimeout(timer!); }
}

function ClaimEditor({ label, value, evidence, disabled, onChange }: { label:string;value:Claim;evidence:Evidence[];disabled:boolean;onChange:(value:Claim)=>void }) {
  const missing=value.evidence_ids.filter(id=>!evidence.some(e=>e.evidence_id===id));
  return <div className="evidence-card">
    <label>{label}<textarea required maxLength={3000} value={value.description} onChange={e=>onChange({...value,description:e.target.value})} /></label>
    <details open><summary>{label}的支持资料（{value.evidence_ids.length}）</summary>
      {[...evidence,...missing.map(id=>({evidence_id:id,title:"未在当前资料列表中，请核对或移除",excerpt:"",source_name:"旧引用",freshness_status:"UNAVAILABLE"}))].map(item=><label className="check-row" key={item.evidence_id}>
        <input type="checkbox" aria-label={`${label}引用 ${item.title}`} disabled={disabled || (item.freshness_status!=="FRESH"&&!value.evidence_ids.includes(item.evidence_id))} checked={value.evidence_ids.includes(item.evidence_id)} onChange={e=>onChange({...value,evidence_ids:e.target.checked?[...value.evidence_ids,item.evidence_id]:value.evidence_ids.filter(id=>id!==item.evidence_id)})} />
        <span>{item.title} · {item.source_name} · {item.freshness_status==="FRESH"?"期限内可引用（不代表已核实）":"当前不可用，可移除旧引用"}{item.excerpt?<small style={{display:"block"}}>{item.excerpt}</small>:null}</span>
      </label>)}
      {!evidence.length ? <p>暂无已入库资料，请先到「研究资料」准备有效证据。不自动查询供应商。</p>:null}
    </details>
  </div>;
}

export function ThesisPage() {
  const [instrument,setInstrument]=useState<InstrumentHit|null>(null);
  const [reviewRun,setReviewRun]=useState(()=>new URLSearchParams(window.location.search).get("analysis_run_id"));
  const [reviewSource,setReviewSource]=useState<TeamSource|null>(null);
  const [workspace,setWorkspace]=useState<Workspace|null>(null);
  const [evidence,setEvidence]=useState<Evidence[]>([]);
  const [draft,setDraft]=useState<Content>(empty);
  const [dirty,setDirty]=useState(false);
  const [loading,setLoading]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [message,setMessage]=useState<string|null>(null);
  const [refresh,setRefresh]=useState(0);
  const sequence=useRef(0);
  const initialChoice=useRef(0);
  const busy=useRef(false);
  const pending=useRef<Pending|null>(null);
  const id=instrument?.instrument_id;
  useEffect(()=>{
    const controller=new AbortController();
    const initial=new URLSearchParams(window.location.search).get("instrument_id");
    const generation=initialChoice.current;
    if(initial) void readAnalysisJson<InstrumentHit>(`/api/v1/instruments/${encodeURIComponent(initial)}`,controller.signal,"读取标的").then(value=>{ if(!controller.signal.aborted&&initialChoice.current===generation)setInstrument(value); }).catch(reason=>{if(!controller.signal.aborted&&initialChoice.current===generation)setError(String(reason.message??reason));});
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{
    const generation=++sequence.current;
    const controller=new AbortController();
    setWorkspace(null);setEvidence([]);setError(null);setLoading(Boolean(id));
    if(id) void Promise.all([
      readAnalysisJson<Workspace>(`/api/v1/theses/${encodeURIComponent(id)}/workspace`,controller.signal,"读取投资逻辑"),
      readAnalysisJson<{items:Evidence[]}>(`/api/v1/instruments/${encodeURIComponent(id)}/evidence?limit=100`,controller.signal,"读取支持资料"),
    ]).then(([next,library])=>{
      if(controller.signal.aborted||generation!==sequence.current)return;
      if(next.instrument_id!==id || !Array.isArray(next.versions) || !Array.isArray(library.items)) throw new Error("投资逻辑或资料响应不完整，未采用。");
      const current=next.versions.find(v=>v.id===next.current_version_id);
      if(next.current_version_id&&!current)throw new Error("未找到当前逻辑版本，未采用响应。");
      setWorkspace(next);setEvidence(library.items);setDraft(current?structuredClone(current.content):empty());setDirty(false);setReviewSource(null);pending.current=null;
    }).catch(reason=>{if(!controller.signal.aborted&&generation===sequence.current)setError(reason instanceof Error?reason.message:"读取失败，请重试。");}).finally(()=>{if(!controller.signal.aborted&&generation===sequence.current)setLoading(false);});
    return ()=>controller.abort();
  },[id,refresh]);
  function change(next: Content) { setDraft(next);setDirty(true);setMessage(null); }
  function select(hit: InstrumentHit) {
    if(hit.instrument_id===id)return;
    if(busy.current || (dirty&&!window.confirm("切换标的会放弃尚未保存的内容，是否继续？")))return;
    ++initialChoice.current;++sequence.current;setWorkspace(null);setEvidence([]);setDraft(empty());setInstrument(hit);setDirty(false);setMessage(null);setReviewRun(null);setReviewSource(null);
  }
  function adopt(source:TeamSource,suggestions:TeamSuggestion[]) {
    if(busy.current||loading||!workspace||reviewSource)return;
    const base=draft.pillars.filter(p=>p.claim.description.trim()||p.claim.evidence_ids.length);
    const unique:TeamSuggestion[]=[];
    const signature=(description:string,ids:string[])=>JSON.stringify([description.trim(),[...ids].sort()]);
    const known=new Set(base.map(p=>signature(p.claim.description,p.claim.evidence_ids)));
    for(const candidate of suggestions){const key=signature(candidate.claim,candidate.evidence_ids);if(!known.has(key)){known.add(key);unique.push(candidate);}}
    if(!unique.length){setMessage("所选观点已在草稿中，没有重复加入，也未保存。");return;}
    if(base.length+unique.length>20){setError("加入后将超过20个逻辑支柱，请减少勾选或先整理现有草稿；当前内容未改变。");return;}
    change({...draft,pillars:[...base,...unique.map(s=>({key:`T-${crypto.randomUUID()}`,claim:{description:s.claim,evidence_ids:s.evidence_ids},status:"AT_RISK"}))],change_reason:"NEW_EVIDENCE"});
    setReviewSource(source);setError(null);setMessage(`已加入 ${unique.length} 条团队观点到编辑草稿，尚未保存；逻辑状态未自动改变。`);
  }
  function adoptRisks(source:TeamSource,impacts:TeamImpact[]) {
    if(busy.current||loading||!workspace||reviewSource)return;
    const signature=(claim:Claim)=>JSON.stringify([claim.description.trim(),[...claim.evidence_ids].sort()]);
    const known=new Set(draft.risks.map(signature));
    const added:Claim[]=[];
    for(const item of impacts){const claim={description:impactRiskDescription(item),evidence_ids:[...item.evidence_ids]};if(!known.has(signature(claim))){known.add(signature(claim));added.push(claim);}}
    if(!added.length){setMessage("所选风险已在草稿中，没有重复加入，也未保存。");return;}
    if(draft.risks.length+added.length>20){setError("加入后将超过20条风险，请减少勾选或先整理草稿；当前内容未改变。");return;}
    change({...draft,risks:[...draft.risks,...added],change_reason:"NEW_EVIDENCE"});
    setReviewSource(source);setError(null);setMessage(`已加入 ${added.length} 条待核对风险，尚未保存；原支柱、摘要和逻辑状态均保留。`);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if(busy.current||!id||!workspace)return;
    if([...draft.pillars.map(p=>p.claim),...draft.catalysts,...draft.risks].some(c=>!c.evidence_ids.length)){setError("每个逻辑支柱、催化剂和风险主张都需要至少一条支持资料，输入已保留。");return;}
    const candidate={expected_version_id:workspace.current_version_id,content:{...structuredClone(draft),monitoring_conditions:draft.monitoring_conditions.map(item=>item.trim()).filter(Boolean)},...(reviewSource?{review_source:reviewSource}:{})};
    if(!pending.current || JSON.stringify({...pending.current,request_id:undefined})!==JSON.stringify(candidate)) pending.current={request_id:crypto.randomUUID(),...candidate};
    busy.current=true;setSaving(true);setError(null);setMessage(null);
    try {
      const result=await save(`/api/v1/theses/${encodeURIComponent(id)}/versions`,pending.current);
      if(!result.version_id||!Number.isInteger(result.version))throw new Error("保存响应不完整，输入已保留，请核对后重试同一请求。");
      setMessage(result.created?`已保存投资逻辑版本 ${result.version}，历史未被覆盖。`:`没有实质变化，继续使用版本 ${result.version}，未创建空版本。`);
      setDirty(false);setRefresh(v=>v+1);
    } catch(reason) { setError(reason instanceof Error?reason.message:"保存失败，输入已保留。"); }
    finally { busy.current=false;setSaving(false); }
  }
  const current=workspace?.versions.find(v=>v.id===workspace.current_version_id);
  return <ProductChrome eyebrow="长期投资记忆" title="投资逻辑工作台" subtitle="记录为何持有、何时失效。明确保存才生成版本，不调用模型，不批准交易。">
    <StatusBanner kind="error" text={error}/><StatusBanner kind="ok" text={message}/><StatusBanner kind="info" text={loading?"正在读取投资逻辑与支持资料…":saving?"正在保存，请勿重复提交…":null}/>
    <Panel title="1 · 选择研究标的" description="先准备资料，再写逻辑；保存后可从研究页单独确认费用并启动分析。">
      {!saving?<InstrumentSearchBox onSelect={select}/>:null}
      {instrument?<p>当前标的：{instrument.market} · {instrument.symbol} {instrument.name}</p>:<p>搜索已有持仓或观察标的，或从「研究资料」进入。</p>}
      {id?<div className="btn-row"><a className="btn" href={`/research?instrument_id=${encodeURIComponent(id)}`}>准备资料／继续分析</a><button type="button" className="btn ghost" disabled={loading||saving} onClick={()=>{if(!dirty||window.confirm("重新读取会放弃尚未保存的内容，是否继续？"))setRefresh(v=>v+1);}}>重新读取当前版本</button></div>:null}
    </Panel>
    {workspace?<Panel title="2 · 明确保存投资逻辑" description={`基准：${current?`版本 ${current.version}`:"尚无版本"}。冲突会阻止保存，不会覆盖他人的更新。`}>
      <p className="context-note">这里是你维护的研究判断，不是政策批准或交易授权。资料必须可用且有出处；新建默认“未知”。已失效逻辑的重新生效须完整复核，本页不提供快捷恢复。</p>
      {reviewRun&&id?<TeamThesisDraft key={`${id}-${refresh}`} runId={reviewRun} instrumentId={id} baseVersionId={workspace.current_version_id} evidence={evidence} disabled={saving||loading} adopted={Boolean(reviewSource)} onApply={adopt} onApplyRisks={adoptRisks}/>:null}
      {reviewSource?<p className="context-note">本次保存将记录人工核对的分析／观点来源。<button type="button" className="btn ghost" disabled={saving} onClick={()=>{setReviewSource(null);setDirty(true);setMessage("已解除团队来源关联，编辑文字仍保留；后续按人工草稿保存。");}}>解除团队来源关联</button></p>:null}
      <form className="thesis-editor" onSubmit={e=>void submit(e)}><fieldset disabled={loading||saving} style={{border:0,padding:0,minWidth:0}}>
        <label>长期投资逻辑摘要<textarea required maxLength={3000} value={draft.long_term_summary} onChange={e=>change({...draft,long_term_summary:e.target.value})}/></label>
        <div className="form-grid"><label>逻辑状态<select aria-label="逻辑状态" value={draft.state} onChange={e=>change({...draft,state:e.target.value})}>{(current?transitions[current.content.state]??[current.content.state]:["UNKNOWN","VALID"]).map(state=><option key={state} value={state}>{stateNames[state]??state}</option>)}</select></label>
        <label>修订原因<select value={draft.change_reason} onChange={e=>change({...draft,change_reason:e.target.value})}><option value="HUMAN_CORRECTION">人工整理／修正</option><option value="NEW_EVIDENCE">新增证据</option><option value="SCHEDULED_REVIEW">定期复核</option><option value="EVENT">事件变化</option></select></label></div>
        <h3>逻辑支柱</h3>{draft.pillars.map((p,index)=><div key={p.key}>
          <ClaimEditor label={`逻辑支柱 ${index+1}`} value={p.claim} evidence={evidence} disabled={saving} onChange={claim=>change({...draft,pillars:draft.pillars.map((v,i)=>i===index?{...v,claim}:v)})}/>
          <label>支柱 {index+1} 状态<select value={p.status} onChange={e=>change({...draft,pillars:draft.pillars.map((v,i)=>i===index?{...v,status:e.target.value}:v)})}><option value="VALID">成立</option><option value="AT_RISK">受挑战</option><option value="INVALID">不成立</option></select></label>
          <button type="button" className="btn ghost" disabled={draft.pillars.length===1} onClick={()=>change({...draft,pillars:draft.pillars.filter((_,i)=>i!==index)})}>移除支柱 {index+1}</button>
        </div>)}<button type="button" className="btn" disabled={draft.pillars.length>=20} onClick={()=>change({...draft,pillars:[...draft.pillars,{key:`P${Math.max(0,...draft.pillars.map(p=>Number(p.key.replace(/^P/,""))||0))+1}`,claim:blankClaim(),status:"VALID"}]})}>添加逻辑支柱</button>
        {(["catalysts","risks"] as const).map(kind=><section key={kind}><h3>{kind==="catalysts"?"催化剂（可选）":"风险主张（可选）"}</h3>{draft[kind].map((claim,index)=><div key={index}><ClaimEditor label={`${kind==="catalysts"?"催化剂":"风险主张"} ${index+1}`} value={claim} evidence={evidence} disabled={saving} onChange={next=>change({...draft,[kind]:draft[kind].map((c,i)=>i===index?next:c)})}/><button type="button" className="btn ghost" onClick={()=>change({...draft,[kind]:draft[kind].filter((_,i)=>i!==index)})}>移除{kind==="catalysts"?"催化剂":"风险主张"} {index+1}</button></div>)}<button type="button" className="btn" disabled={draft[kind].length>=20} onClick={()=>change({...draft,[kind]:[...draft[kind],blankClaim()]})}>添加{kind==="catalysts"?"催化剂":"风险主张"}</button></section>)}
        <h3>失效条件</h3>{draft.invalidation_conditions.map((condition,index)=><div className="evidence-card" key={index}>{(["condition","measurement","threshold","window"] as const).map((field,i)=><label key={field}>{["失效条件","观察指标","失效阈值","观察窗口"][i]} {index+1}<input required maxLength={3000} value={condition[field]} onChange={e=>change({...draft,invalidation_conditions:draft.invalidation_conditions.map((c,n)=>n===index?{...c,[field]:e.target.value}:c)})}/></label>)}<button type="button" className="btn ghost" onClick={()=>change({...draft,invalidation_conditions:draft.invalidation_conditions.filter((_,i)=>i!==index)})}>移除失效条件 {index+1}</button></div>)}
        <button type="button" className="btn" disabled={draft.invalidation_conditions.length>=20} onClick={()=>change({...draft,invalidation_conditions:[...draft.invalidation_conditions,{condition:"",measurement:"",threshold:"",window:""}]})}>添加失效条件</button>
        <label>持续观察事项（每行一项，最多20项）<textarea value={draft.monitoring_conditions.join("\n")} onChange={e=>change({...draft,monitoring_conditions:e.target.value.split("\n")})}/></label>
        <p className="hint-text">摘要是人工判断；每个事实主张单独关联证据。保存只更新逻辑版本，不会重新运行已有分析。</p>
        <ThesisDraftChanges before={current?.content??null} after={draft}/>
        <button type="submit" className="btn primary">{saving?"正在保存…":"保存投资逻辑新版本"}</button>
      </fieldset></form>
    </Panel>:null}
    {workspace?<Panel title="3 · 历史版本与变更" description="所有旧版只读保留；当前分析使用启动时固定的版本。">{!workspace.versions.length?<p>尚无正式版本，未自动创建占位记录。</p>:workspace.versions.map(v=><details key={v.id}><summary>版本 {v.version} · {stateNames[v.content.state]??v.content.state} · {v.content.long_term_summary}</summary><p style={{overflowWrap:"anywhere"}}>版本 ID：{v.id} · 前版：{v.parent_version_id??"无"} · 内容摘要：{v.content_hash}</p><p>保存时间：{v.created_at}</p><pre className="hint-text">{JSON.stringify({内容:v.content,语义变更:v.semantic_diff},null,2)}</pre></details>)}</Panel>:null}
    {workspace?.versions.some(v=>v.review_sources?.length)?<Panel title="4 · 人工核对的团队来源" description="这是人工整理时核对的来源，不表示模型自动更新或投资批准。">{workspace.versions.flatMap(v=>(v.review_sources??[]).map((source,index)=><article className="evidence-card" key={`${v.id}-${index}`}><p>投资逻辑版本 {v.version} · 核对 {source.suggestion_ids.length} 条团队观点{source.impact_ids?.length?` / ${source.impact_ids.length} 条支柱影响`:""}</p><a className="btn ghost" href={`/analysis?run_id=${encodeURIComponent(source.analysis_run_id)}`}>查看来源分析报告</a><p className="hint-text" style={{overflowWrap:"anywhere"}}>分析 ID：{source.analysis_run_id} · 输入摘要：{source.input_hash}<br/>观点 ID：{source.opinion_ids.join("、")}{source.impact_ids?.length?<><br/>影响 ID：{source.impact_ids.join("、")}</>:null}</p></article>))}</Panel>:null}
  </ProductChrome>;
}
