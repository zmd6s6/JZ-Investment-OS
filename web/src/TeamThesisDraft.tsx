import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import { gateLabel } from "./analysisLabels";
import { Panel, StatusBanner } from "./ProductChrome";

export type TeamSource = {analysis_run_id:string;suggestion_ids:string[];impact_ids?:string[]};
export type TeamSuggestion = {id:string;opinion_id:string;role:string;stage:string;claim:string;evidence_ids:string[]};
export type TeamImpact = {id?:string;pillar_key:string;impact:"STRENGTHEN"|"WEAKEN"|"BREAK"|"NONE";reason:string;evidence_ids:string[];opinion_id:string;role:string;stage:string;baseline_status:"MATCHED"|"UNMATCHED"|"NO_BASELINE";baseline_claim:string|null;baseline_pillar_status:string|null};
type Review = {analysis_run_id:string;instrument_id:string;as_of:string;input_hash:string;base_version_id:string|null;suggestions:TeamSuggestion[];unknowns:string[];risk_gate:string;limitations:string[];impacts?:TeamImpact[]};
const impactNames = {STRENGTHEN:"加强判断",WEAKEN:"削弱判断",BREAK:"击穿判断",NONE:"未主张改变"};
const pillarNames:Record<string,string>={VALID:"成立",AT_RISK:"受挑战",INVALID:"不成立"};
const roles:Record<string,string>={MACRO:"宏观",INDUSTRY:"行业",FUNDAMENTAL:"基本面",MARKET_QUANT:"市场量化",EVENT:"事件",DEVILS_ADVOCATE:"反方审查",PORTFOLIO:"组合经理",RISK:"风险经理"};

export function impactRiskDescription(item:TeamImpact) {
  return `团队待核对 · 支柱 ${item.pillar_key} · ${impactNames[item.impact]}：${item.reason}`;
}

export function TeamThesisDraft({runId,instrumentId,baseVersionId,evidence,disabled,adopted,onApply,onApplyRisks}:{runId:string;instrumentId:string;baseVersionId:string|null;evidence:{evidence_id:string;freshness_status:string}[];disabled:boolean;adopted:boolean;onApply:(source:TeamSource,suggestions:TeamSuggestion[])=>void;onApplyRisks?:(source:TeamSource,impacts:TeamImpact[])=>void}) {
  const [review,setReview]=useState<Review|null>(null);
  const [chosen,setChosen]=useState<string[]>([]);
  const [chosenImpacts,setChosenImpacts]=useState<string[]>([]);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  const [attempt,setAttempt]=useState(0);
  const generation=useRef(0);
  useEffect(()=>{
    const current=++generation.current;
    const controller=new AbortController();
    setLoading(true);setError(null);setReview(null);setChosen([]);setChosenImpacts([]);
    void readAnalysisJson<Review>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/thesis-review`,controller.signal,"读取团队草稿来源").then(value=>{
      if(controller.signal.aborted||current!==generation.current)return;
      if(value.analysis_run_id!==runId||value.instrument_id!==instrumentId||!Array.isArray(value.suggestions)||!Array.isArray(value.unknowns)||!Array.isArray(value.limitations)||!(value.base_version_id===null||typeof value.base_version_id==="string")||new Set(value.suggestions.map(s=>s.id)).size!==value.suggestions.length||value.suggestions.some(s=>!s.id||typeof s.claim!=="string"||!Array.isArray(s.evidence_ids)||!s.evidence_ids.length))throw new Error("团队草稿来源响应不完整或标的不匹配，未采用。");
      if(value.impacts!==undefined&&(!Array.isArray(value.impacts)||value.impacts.length>100||value.impacts.some(item=>!item||typeof item.pillar_key!=="string"||!item.pillar_key||!Object.hasOwn(impactNames,item.impact)||typeof item.reason!=="string"||!item.reason||typeof item.opinion_id!=="string"||typeof item.role!=="string"||!["ROUND_1","ROUND_2","PORTFOLIO","RISK"].includes(item.stage)||!Array.isArray(item.evidence_ids)||!item.evidence_ids.length||item.evidence_ids.some(id=>typeof id!=="string")||!["MATCHED","UNMATCHED","NO_BASELINE"].includes(item.baseline_status)||(item.baseline_status==="MATCHED"&&(typeof item.baseline_claim!=="string"||typeof item.baseline_pillar_status!=="string")))))throw new Error("团队支柱影响记录格式异常，未采用，也未改变草稿。");
      const identified=value.impacts?.filter(i=>i.id!==undefined)??[];
      if(identified.some(i=>typeof i.id!=="string"||!i.id)||new Set(identified.map(i=>i.id)).size!==identified.length)throw new Error("团队影响选择标识异常，未采用，也未改变草稿。");
      setReview(value);
    }).catch(reason=>{if(!controller.signal.aborted&&current===generation.current)setError(reason instanceof Error?reason.message:"读取失败，请只读重试。");}).finally(()=>{if(!controller.signal.aborted&&current===generation.current)setLoading(false);});
    return()=>controller.abort();
  },[runId,instrumentId,attempt]);
  const stale=Boolean(review&&review.base_version_id!==baseVersionId);
  const available=(suggestion:{evidence_ids:string[]})=>suggestion.evidence_ids.every(id=>evidence.some(e=>e.evidence_id===id&&e.freshness_status==="FRESH"));
  const riskEligible=(item:TeamImpact)=>Boolean(item.id&&item.baseline_status==="MATCHED"&&["WEAKEN","BREAK"].includes(item.impact)&&available(item)&&impactRiskDescription(item).length<=3000);
  return <Panel title="团队观点 → 待核对草稿" description="只读取已保存的结构化观点，不调用模型。勾选并加入仅改变当前编辑草稿，最后明确保存才生成版本。">
    <p className="context-note">模型观点不等于已核实事实。不会自动增强／恢复逻辑状态，也不会改动原摘要或批准交易；加入的支柱默认“受挑战”，请逐条核对。</p>
    <a className="btn ghost" href={`/analysis?run_id=${encodeURIComponent(runId)}`}>返回来源分析报告</a>
    <StatusBanner kind="error" text={error}/><StatusBanner kind="info" text={loading?"正在读取团队草稿来源…":null}/>
    {error?<button type="button" className="btn" disabled={loading||disabled} onClick={()=>setAttempt(v=>v+1)}>重试读取团队观点</button>:null}
    {review?<>
      <p>来源时点：{review.as_of} · 当时风险门：{gateLabel(review.risk_gate)}（不是当前授权）</p>
      <p className="hint-text" style={{overflowWrap:"anywhere"}}>输入摘要：{review.input_hash} · 基准版本：{review.base_version_id??"尚无版本"}</p>
      {stale?<p className="banner banner-error">当前投资逻辑已不同于本次分析基准，禁止直接带入。请核对最新版本后明确新建分析；不会覆盖新版本。</p>:null}
      {review.unknowns.length?<details open><summary>团队尚未解决的未知项（{review.unknowns.length}）</summary><ul>{review.unknowns.map((item,i)=><li key={i}>{item}</li>)}</ul></details>:null}
      {onApplyRisks&&review.impacts?.length?<details open><summary>把支柱挑战整理为风险草稿</summary>
        <p>只把你勾选的削弱／击穿理由加入风险清单，不改原支柱、摘要或状态。相反观点仍在下方保留；请先对照，再选择。与下方观察带入二选一，本次最多20条。</p>
        {review.impacts.map((item,index)=><label className="check-row evidence-card" key={item.id??index} style={{overflowWrap:"anywhere"}}>
          <input type="checkbox" aria-label={`带入风险判断 ${index+1} · ${roles[item.role]??item.role}`} checked={Boolean(item.id&&chosenImpacts.includes(item.id))} disabled={disabled||loading||stale||adopted||!riskEligible(item)||(!chosenImpacts.includes(item.id??"")&&chosenImpacts.length>=20)} onChange={event=>setChosenImpacts(values=>event.target.checked?[...values,item.id!]:values.filter(id=>id!==item.id))}/>
          <span>{roles[item.role]??item.role} · 支柱 {item.pillar_key} · {impactNames[item.impact]}（理由和原支柱见下方影响判断）{!riskEligible(item)?<small>仅供核对：需匹配原支柱、有效资料、可追溯选择ID及长度合规的完整风险文字；加强或无改变判断不作为风险带入。</small>:null}</span>
        </label>)}
        <button type="button" className="btn" disabled={disabled||loading||stale||adopted||!chosenImpacts.length||chosenImpacts.some(id=>!review.impacts?.some(i=>i.id===id&&riskEligible(i)))} onClick={()=>onApplyRisks({analysis_run_id:runId,suggestion_ids:[],impact_ids:chosenImpacts},review.impacts!.filter(i=>i.id&&chosenImpacts.includes(i.id)))}>{adopted?"已加入编辑草稿，尚未代表保存":"将勾选影响加入风险草稿"}</button>
      </details>:null}
      <details><summary>团队对逻辑支柱的影响判断（{review.impacts?.length??0}）</summary><p className="hint-text">这是当次模型观点，不是已核实的逻辑变更。不同角色的矛盾保留，不自动投票、采纳或改变状态。</p>{review.limitations.some(v=>v.startsWith("ADDITIONAL_IMPACTS_NOT_SHOWN:")&&!v.endsWith(":0"))?<p>最多展示100条影响判断，另有记录未展示，请回来源报告核对。</p>:null}{review.impacts?.length?review.impacts.map((item,index)=><article className="evidence-card" key={index} style={{overflowWrap:"anywhere"}}><h4>{roles[item.role]??item.role} · {impactNames[item.impact]} · 支柱键 {item.pillar_key}</h4><p>{item.baseline_status==="MATCHED"?`当次基准支柱：${item.baseline_claim}（原状态：${pillarNames[item.baseline_pillar_status??""]??item.baseline_pillar_status}）`:item.baseline_status==="NO_BASELINE"?"当次分析没有已保存的逻辑基准，不能视为修改了现有支柱。":"未匹配当次基准支柱，不自动套用到其他支柱。"}</p><p className="evidence-excerpt">{item.reason}</p><p className="hint-text">{item.stage==="ROUND_2"?"第二轮":"已保存观点"} · 证据：{item.evidence_ids.join("、")} · 观点：{item.opinion_id}</p>{!available(item)?<p>支持资料当前不可用；这里只保留历史判断，不授权新分析或状态变更。</p>:null}</article>):<p>{review.impacts===undefined?"旧响应未提供支柱影响字段，未补造历史。":"本次没有保存可展示的支柱影响判断，不从观察或自由文字推断。"}</p>}</details>
      {review.limitations.filter(v=>v.startsWith("ADDITIONAL_OBSERVATIONS_NOT_SHOWN:")&&!v.endsWith(":0")).length?<p className="hint-text">本页最多展示100条团队观察，其余请回来源报告核对，不代表已形成共识。</p>:null}
      {!review.suggestions.length?<p>没有可带入的有效结构化观察，不从自由文字编造逻辑。</p>:null}
      {review.suggestions.map((s,i)=><label className="evidence-card check-row" key={s.id}><input type="checkbox" aria-label={`带入团队观点 ${i+1} · ${roles[s.role]??s.role}`} checked={chosen.includes(s.id)} disabled={disabled||loading||stale||adopted||!available(s)||(!chosen.includes(s.id)&&chosen.length>=20)} onChange={event=>setChosen(values=>event.target.checked?[...values,s.id]:values.filter(id=>id!==s.id))}/><span><strong>{roles[s.role]??s.role} · {s.stage==="ROUND_2"?"第二轮":"已保存观点"}</strong><p>{s.claim}</p><small style={{overflowWrap:"anywhere"}}>观点 ID：{s.opinion_id} · 证据：{s.evidence_ids.join("、")}</small>{!available(s)?<small style={{display:"block"}}>支持资料已不新鲜或不在当前列表，不能直接带入；请先核对资料。</small>:null}</span></label>)}
      <button type="button" className="btn" disabled={disabled||loading||stale||adopted||!chosen.length||chosen.some(id=>!review.suggestions.some(s=>s.id===id&&available(s)))} onClick={()=>onApply({analysis_run_id:runId,suggestion_ids:chosen},review.suggestions.filter(s=>chosen.includes(s.id)))}>{adopted?"已加入编辑草稿，尚未代表保存":"将勾选观点加入编辑草稿"}</button>
    </>:null}
  </Panel>;
}
