import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import { gateLabel } from "./analysisLabels";
import { Panel, StatusBanner } from "./ProductChrome";

export type TeamSource = {analysis_run_id:string;suggestion_ids:string[]};
export type TeamSuggestion = {id:string;opinion_id:string;role:string;stage:string;claim:string;evidence_ids:string[]};
type Review = {analysis_run_id:string;instrument_id:string;as_of:string;input_hash:string;base_version_id:string|null;suggestions:TeamSuggestion[];unknowns:string[];risk_gate:string;limitations:string[]};
const roles:Record<string,string>={MACRO:"宏观",INDUSTRY:"行业",FUNDAMENTAL:"基本面",MARKET_QUANT:"市场量化",EVENT:"事件",DEVILS_ADVOCATE:"反方审查",PORTFOLIO:"组合经理",RISK:"风险经理"};

export function TeamThesisDraft({runId,instrumentId,baseVersionId,evidence,disabled,adopted,onApply}:{runId:string;instrumentId:string;baseVersionId:string|null;evidence:{evidence_id:string;freshness_status:string}[];disabled:boolean;adopted:boolean;onApply:(source:TeamSource,suggestions:TeamSuggestion[])=>void}) {
  const [review,setReview]=useState<Review|null>(null);
  const [chosen,setChosen]=useState<string[]>([]);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  const [attempt,setAttempt]=useState(0);
  const generation=useRef(0);
  useEffect(()=>{
    const current=++generation.current;
    const controller=new AbortController();
    setLoading(true);setError(null);setReview(null);setChosen([]);
    void readAnalysisJson<Review>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/thesis-review`,controller.signal,"读取团队草稿来源").then(value=>{
      if(controller.signal.aborted||current!==generation.current)return;
      if(value.analysis_run_id!==runId||value.instrument_id!==instrumentId||!Array.isArray(value.suggestions)||!Array.isArray(value.unknowns)||!Array.isArray(value.limitations)||!(value.base_version_id===null||typeof value.base_version_id==="string")||new Set(value.suggestions.map(s=>s.id)).size!==value.suggestions.length||value.suggestions.some(s=>!s.id||typeof s.claim!=="string"||!Array.isArray(s.evidence_ids)||!s.evidence_ids.length))throw new Error("团队草稿来源响应不完整或标的不匹配，未采用。");
      setReview(value);
    }).catch(reason=>{if(!controller.signal.aborted&&current===generation.current)setError(reason instanceof Error?reason.message:"读取失败，请只读重试。");}).finally(()=>{if(!controller.signal.aborted&&current===generation.current)setLoading(false);});
    return()=>controller.abort();
  },[runId,instrumentId,attempt]);
  const stale=Boolean(review&&review.base_version_id!==baseVersionId);
  const available=(suggestion:TeamSuggestion)=>suggestion.evidence_ids.every(id=>evidence.some(e=>e.evidence_id===id&&e.freshness_status==="FRESH"));
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
      {review.limitations.filter(v=>v.startsWith("ADDITIONAL_OBSERVATIONS_NOT_SHOWN:")&&!v.endsWith(":0")).length?<p className="hint-text">本页最多展示100条团队观察，其余请回来源报告核对，不代表已形成共识。</p>:null}
      {!review.suggestions.length?<p>没有可带入的有效结构化观察，不从自由文字编造逻辑。</p>:null}
      {review.suggestions.map((s,i)=><label className="evidence-card check-row" key={s.id}><input type="checkbox" aria-label={`带入团队观点 ${i+1} · ${roles[s.role]??s.role}`} checked={chosen.includes(s.id)} disabled={disabled||loading||stale||adopted||!available(s)||(!chosen.includes(s.id)&&chosen.length>=20)} onChange={event=>setChosen(values=>event.target.checked?[...values,s.id]:values.filter(id=>id!==s.id))}/><span><strong>{roles[s.role]??s.role} · {s.stage==="ROUND_2"?"第二轮":"已保存观点"}</strong><p>{s.claim}</p><small style={{overflowWrap:"anywhere"}}>观点 ID：{s.opinion_id} · 证据：{s.evidence_ids.join("、")}</small>{!available(s)?<small style={{display:"block"}}>支持资料已不新鲜或不在当前列表，不能直接带入；请先核对资料。</small>:null}</span></label>)}
      <button type="button" className="btn" disabled={disabled||loading||stale||adopted||!chosen.length||chosen.some(id=>!review.suggestions.some(s=>s.id===id&&available(s)))} onClick={()=>onApply({analysis_run_id:runId,suggestion_ids:chosen},review.suggestions.filter(s=>chosen.includes(s.id)))}>{adopted?"已加入编辑草稿，尚未代表保存":"将勾选观点加入编辑草稿"}</button>
    </>:null}
  </Panel>;
}
