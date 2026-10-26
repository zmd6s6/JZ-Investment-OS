import { useEffect, useState } from "react";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";

type Capability = {key:string;label:string;work_item:string;engineering:"IMPLEMENTED"|"PARTIAL"|"NOT_IMPLEMENTED";integration:"INTEGRATED"|"BASELINE_ONLY"|"NOT_IMPLEMENTED";human_acceptance:"PENDING";service:"ASSEMBLED"|"UNAVAILABLE"|"NOT_APPLICABLE";route:string|null;detail:string;steps:string[];failure:string};
type Snapshot = {schema_version:"1.0";release:"MVP-BETA";evidence_basis:"BUILD_MANIFEST_AND_SERVICE_ASSEMBLY";auto_trade:false;capabilities:Capability[]};
const engineering={IMPLEMENTED:"已实现",PARTIAL:"部分实现",NOT_IMPLEMENTED:"尚未实现"};
const integration={INTEGRATED:"已有接通证据",BASELINE_ONLY:"仅底层基础",NOT_IMPLEMENTED:"未接通产品"};
const routes=new Set(["/acceptance","/portfolio","/watchlist","/settings","/#policy"]);

export function parseAcceptance(raw:unknown):Snapshot {
  const value=raw as Snapshot;
  if(!value||value.schema_version!=="1.0"||value.release!=="MVP-BETA"||value.auto_trade!==false||value.evidence_basis!=="BUILD_MANIFEST_AND_SERVICE_ASSEMBLY"||!Array.isArray(value.capabilities)||!value.capabilities.length||value.capabilities.length>50)throw new Error("产品进度响应不完整，未采用。请重试或检查服务版本。");
  const ids=new Set<string>();
  for(const item of value.capabilities){
    if(!item||typeof item.key!=="string"||!item.key||ids.has(item.key)||typeof item.label!=="string"||typeof item.work_item!=="string"||!Object.hasOwn(engineering,item.engineering)||!Object.hasOwn(integration,item.integration)||item.human_acceptance!=="PENDING"||!["ASSEMBLED","UNAVAILABLE","NOT_APPLICABLE"].includes(item.service)||!(item.route===null||routes.has(item.route))||typeof item.detail!=="string"||typeof item.failure!=="string"||!Array.isArray(item.steps)||item.steps.some(step=>typeof step!=="string")||(item.route!==null&&(item.integration!=="INTEGRATED"||item.service!=="ASSEMBLED")))throw new Error("产品能力记录格式异常，未显示成功状态。请重试或检查服务版本。");
    ids.add(item.key);
  }
  return value;
}

export function AcceptancePage(){
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    let live=true;
    const deadline=setTimeout(()=>{controller.abort();if(live){setError("读取产品进度超时，请重试。未发起写入或模型调用。");setLoading(false);}},15000);
    setSnapshot(null);setError(null);setLoading(true);
    void fetch("/api/v1/product-acceptance",{signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error("无法读取产品进度，请重试。不会将服务故障解释为功能可用。");
      return parseAcceptance(await response.json());
    }).then(value=>{if(live&&!controller.signal.aborted)setSnapshot(value);}).catch(reason=>{if(live&&!controller.signal.aborted)setError(reason instanceof SyntaxError?"产品进度响应格式异常，请重试或检查服务版本。":reason instanceof TypeError?"无法连接产品服务，请检查服务后重试。":reason instanceof Error?reason.message:"读取失败，请重试。");}).finally(()=>{if(live&&!controller.signal.aborted){clearTimeout(deadline);setLoading(false);}});
    return()=>{live=false;clearTimeout(deadline);controller.abort();};
  },[attempt]);
  return <ProductChrome eyebrow="MVP-BETA · 产品交付" title="产品进度与验收" subtitle="先看哪些入口可用，再按步骤体验；工程通过、服务装配和你的实际验收分别记录。">
    <Panel title="如何理解本页" actions={<button type="button" className="btn" disabled={loading} onClick={()=>setAttempt(n=>n+1)}>{loading?"正在读取…":"刷新产品进度"}</button>}>
      <p>本页由当前服务构建的交付清单与用例装配信息提供，不实时检测数据库、供应商连接或运行任务，也不读取你的持仓或凭据。服务已装配不等于配置就绪或运行健康。</p>
      <p>人工验收仍为待验收；阅读本页、点击入口或测试通过都不会替你接受Checkpoint。自动交易始终关闭。</p>
      <StatusBanner kind="info" text={loading?"正在读取当前构建的产品进度…":null}/>
      <StatusBanner kind="error" text={error}/>
    </Panel>
    {snapshot?<div className="capability-grid acceptance-grid">{snapshot.capabilities.map(item=><article key={item.key} className="capability-card" aria-label={`${item.label}能力状态`}>
      <h2>{item.label}</h2><p className="muted">工作项：{item.work_item}</p>
      <dl className="acceptance-states"><dt>工程交付</dt><dd>{engineering[item.engineering]}</dd><dt>集成证据</dt><dd>{integration[item.integration]}</dd><dt>人工验收</dt><dd>待所有者验收</dd><dt>服务装配</dt><dd>{item.service==="ASSEMBLED"?"已装配（非健康检测）":item.service==="UNAVAILABLE"?"当前部署未装配，入口暂不可用":"尚无产品用例"}</dd></dl>
      <p>{item.detail}</p>
      {item.route?<a className="btn" href={item.route}>进入{item.label}</a>:<p className="banner banner-info">暂不可进入：{item.service==="UNAVAILABLE"?"当前服务配置不完整":"等待工作项接通产品"}</p>}
      <details><summary>操作指引与失败提示</summary>{item.steps.length?<ol>{item.steps.map((step,index)=><li key={index}>{step}</li>)}</ol>:<p>当前没有完整产品操作路径。</p>}<p>失败时应看到：{item.failure}</p></details>
    </article>)}</div>:null}
  </ProductChrome>;
}
