import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import { StatusBanner } from "./ProductChrome";
import { gateLabel, stanceLabel } from "./analysisLabels";

type Agent = {stage:string;role:string;agent_run_id:string;opinion_id:string;status:string;error_code:string|null;model_name:string;prompt_version:string;prompt_hash:string;content_hash:string;started_at:string;ended_at:string;stance:string;confidence:string;observations:{claim:string;evidence_ids:string[]}[];unknowns:string[]};
type Risk = {id:string;gate:string;content_hash:string;as_of:string;expires_at:string;veto:boolean;veto_codes:string[];hard_flags:unknown[];soft_flags:unknown[];evidence_ids:string[]};
type Records = {run_id:string;status:"RECORDED"|"NOT_RECORDED";committee_session_id:string|null;input_hash:string|null;agents:Agent[];risk:Risk|null;decision_status:"NOT_REGISTERED"};
const roles:Record<string,string>={MACRO:"宏观研究",INDUSTRY:"行业研究",FUNDAMENTAL:"基本面研究",MARKET_QUANT:"市场与量化",EVENT:"事件研究",DEVILS_ADVOCATE:"反方审查",PORTFOLIO:"组合经理",RISK:"风险经理"};
const stages:Record<string,string>={ROUND_1:"第一轮",ROUND_2:"第二轮",PORTFOLIO:"委员会后 · 组合评估",RISK:"委员会后 · 风险评估"};

export function AnalysisResearch({runId}:{runId:string}) {
  const [data,setData]=useState<Records|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(false);
  const generation=useRef(0);
  const controller=useRef<AbortController|null>(null);
  useEffect(()=>{++generation.current;controller.current?.abort();controller.current=null;setData(null);setError(null);setLoading(false);return()=>{++generation.current;controller.current?.abort();controller.current=null;};},[runId]);
  async function load() {
    if(controller.current)return;
    const attempt=++generation.current;
    const next=new AbortController();controller.current=next;setLoading(true);setError(null);
    try {
      const value=await readAnalysisJson<Records>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/research-records`,next.signal,"读取研究主表记录");
      if(next.signal.aborted||attempt!==generation.current)return;
      if(value.run_id!==runId||!Array.isArray(value.agents)||!["RECORDED","NOT_RECORDED"].includes(value.status)||(value.status==="RECORDED"&&(!value.committee_session_id||!value.risk)))throw new Error("研究记录响应不完整，未采用。请只读重试。");
      setData(value);
    } catch(reason) {if(!next.signal.aborted&&attempt===generation.current)setError(reason instanceof Error?reason.message:"研究记录读取失败，请重试。");}
    finally {if(controller.current===next)controller.current=null;if(attempt===generation.current)setLoading(false);}
  }
  return <section className="frozen-inputs"><h3>研究主表与决策关联</h3>
    <p className="hint-text">只读核对实际委员会、观点与风险记录，不重跑模型，也不补写旧报告。历史风控结果不是当前交易授权。</p>
    <button type="button" className="btn" disabled={loading} onClick={()=>void load()}>{loading?"正在读取研究记录…":data?"重新读取研究记录":"查看研究主表记录"}</button>
    <StatusBanner kind="error" text={error}/>
    {data?.status==="NOT_RECORDED"?<p>此运行尚无本版研究主表关联记录；不从报告摘要补造。</p>:null}
    {data?.status==="RECORDED"?<>
      <p>已保存委员会与风险主表 · {data.agents.length} 项角色运行</p>
      <p className="hint-text">委员会 ID：{data.committee_session_id} · 固定输入摘要：{data.input_hash}</p>
      {data.risk?<article className="evidence-card"><h4>已保存的风险评估 · {gateLabel(data.risk.gate)}</h4>
        <p>评估时点：{data.risk.as_of} · 历史有效期至：{data.risk.expires_at}</p>
        <p className="hint-text">Risk ID：{data.risk.id} · 内容摘要：{data.risk.content_hash}</p>
        <p>证据引用：{data.risk.evidence_ids.join("、")||"无；不视为通过"}</p>
        <details><summary>查看风险旗与解除条件</summary><pre>{JSON.stringify({硬风险:data.risk.hard_flags,软风险:data.risk.soft_flags},null,2)}</pre></details>
      </article>:null}
      <p className="banner banner-info">正式 Decision 尚未创建：已批准政策／策略及完整估值、仓位版本链仍待收口。测试工件登记不是批准。当前是影子建议，不是待审批、获批或已成交记录。</p>
      {data.agents.map(agent=><details key={agent.opinion_id}><summary>{stages[agent.stage]??agent.stage} · {roles[agent.role]??agent.role} · {agent.error_code?"资料不足／运行失败":stanceLabel(agent.stance)}</summary>
        <p>{agent.model_name} · {agent.prompt_version} · 置信度 {agent.confidence}</p>
        <p className="hint-text">实际运行：{agent.started_at} → {agent.ended_at}<br/>AgentRun：{agent.agent_run_id}<br/>Opinion：{agent.opinion_id}<br/>内容摘要：{agent.content_hash}<br/>Prompt 摘要：{agent.prompt_hash}</p>
        {agent.observations.map((claim,i)=><p key={i}>{claim.claim}<span className="hint-text"> · 证据 {claim.evidence_ids.join("、")}</span></p>)}
        {agent.unknowns.length?<p>未知项：{agent.unknowns.join("；")}</p>:null}
      </details>)}
    </>:null}
  </section>;
}
