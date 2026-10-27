import { FormEvent, useEffect, useRef, useState } from "react";
import { InstrumentHit, InstrumentSearchBox } from "./InstrumentSearchBox";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch } from "./writeApi";

type Provenance={instrument_id:string;evidence_id:string;content_hash:string;source:"MANUAL_MARKET";source_name:string;source_locator:string;currency:string;observed_at:string;effective_at:string;available_at:string;ingested_at:string;expires_at:string;independently_verified:false;trading_grade:false};
type Snapshot={instrument_id:string;source:string;source_name:string;as_of:string;base_currency:string;status:string;reason_code:string;quote:{price:string;provenance:Provenance}|null;provenance:Provenance|null};
type Saved={request_id:string;evidence_id:string;content_hash:string;ingested_at:string};
type Capabilities={status:string;supported_sources:string[];currency_boundary:string;fx_supported:boolean;universe_supported:boolean;historical_bars_supported:boolean;trading_grade:boolean;automatic_network_calls:boolean};
const labels:Record<string,string>={AVAILABLE:"参考价可读取（人工提供，未经独立核实）",MISSING:"该来源在此时点没有报价",EXPIRED:"报价已到期，参考价不可用",NOT_YET_AVAILABLE:"资料当时尚不可用，不借用旧价",INVALID:"已保存报价无法核对，请重新提供可核对资料",FX_REQUIRED:"缺少汇率，跨币种读取已阻止",UNSUPPORTED_SOURCE:"不支持该来源，不会自动换源"};
const errors:Record<string,string>={MARKET_REQUEST_CONFLICT:"保存标识已用于另一份内容，请核对后修改输入再保存。",FX_REQUIRED:"首版只支持人民币；该标的需要汇率数据，当前不能保存。",MARKET_DATA_UNAVAILABLE:"当前部署没有装配人工行情服务，请检查服务版本。",INSTRUMENT_NOT_FOUND:"标的不在本地目录，请先在组合或观察清单登记。",MARKET_INSTRUMENT_NOT_FOUND:"标的已不存在，请重新选择。"};

async function requestJson<T>(url:string,init:RequestInit={}):Promise<T>{
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  const limit=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error("请求超时。读取可重试；保存结果可能未知，请用同一内容再次保存以核对原请求。"));},15000);});
  try{return await Promise.race([(async()=>{
    const response=await apiFetch(url,{...init,signal:controller.signal});
    if(!response.ok){let code="";try{const body=await response.json();code=body?.detail?.code??"";}catch{/* 响应原文不展示 */}
      throw new Error(errors[code]??(response.status===401?"写入需要本机访问令牌，请在右上角配置后重试。":response.status===422?"输入未通过校验：检查正数价格、币种、带时区时间及先后顺序，内容已保留。":"服务请求失败，请检查后重试；未确认的保存使用相同内容核对原请求。"));}
    try{return await response.json() as T;}catch{throw new Error("响应格式异常。保存结果尚未确认，请用同一内容再次保存核对原请求。");}
  })(),limit]);}catch(reason){if(reason instanceof TypeError)throw new Error("无法连接服务。保存结果尚未确认，请保留输入并使用同一内容重试。");throw reason;}finally{clearTimeout(timer!);}
}
const utc=(value:string)=>new Date(value).toISOString();

export function MarketDataPage(){
  const initial=new URLSearchParams(window.location.search);
  const [instrument,setInstrument]=useState<InstrumentHit|null>(null);
  const [sourceName,setSourceName]=useState(initial.get("source_name")??"");
  const [locator,setLocator]=useState("");const [price,setPrice]=useState("");
  const [observed,setObserved]=useState("");const [effective,setEffective]=useState("");const [available,setAvailable]=useState("");const [expires,setExpires]=useState("");
  const [asOf,setAsOf]=useState("");const [baseCurrency,setBaseCurrency]=useState("CNY");const [portfolio,setPortfolio]=useState("");
  const [portfolios,setPortfolios]=useState<{portfolio_id:string;name:string}[]>([]);
  const [capabilities,setCapabilities]=useState<Capabilities|null>(null);const [snapshot,setSnapshot]=useState<Snapshot|null>(null);const [saved,setSaved]=useState<Saved|null>(null);
  const [working,setWorking]=useState(false);const [error,setError]=useState<string|null>(null);const [message,setMessage]=useState<string|null>(null);
  const busy=useRef(false);const generation=useRef(0);const pending=useRef<{fingerprint:string;id:string}|null>(null);
  useEffect(()=>{let live=true;const id=initial.get("instrument_id");
    void requestJson<Capabilities>("/api/v1/market-data/capabilities").then(value=>{if(live)setCapabilities(value);}).catch(reason=>{if(live)setError(reason.message);});
    void requestJson<typeof portfolios>("/api/v1/portfolios").then(value=>{if(live&&Array.isArray(value))setPortfolios(value);}).catch(()=>{/* 组合仅为可选边界核对，无法读取时不默认选择 */});
    if(id)void requestJson<InstrumentHit>(`/api/v1/instruments/${encodeURIComponent(id)}`).then(value=>{if(live&&value.instrument_id===id)setInstrument(value);}).catch(reason=>{if(live)setError(reason.message);});
    return()=>{live=false;generation.current++;};
  },[]);
  const changeSelection=()=>{generation.current++;setSnapshot(null);setSaved(null);setMessage(null);};
  async function readQuote(){
    if(busy.current||!instrument||!sourceName.trim())return;
    busy.current=true;setWorking(true);setError(null);setSnapshot(null);
    const current=++generation.current;
    const query=new URLSearchParams({instrument_id:instrument.instrument_id,source:"MANUAL_MARKET",source_name:sourceName.trim(),base_currency:baseCurrency});
    if(asOf)query.set("as_of",utc(asOf));if(portfolio)query.set("portfolio_id",portfolio);
    try{const value=await requestJson<Snapshot>(`/api/v1/market-data/reference-quote?${query}`);
      if(current!==generation.current)return;
      if(value.instrument_id!==instrument.instrument_id||value.source_name!==sourceName.trim()||value.source!=="MANUAL_MARKET"||value.base_currency!==baseCurrency||!Object.hasOwn(labels,value.status)||(value.status==="AVAILABLE"&&(!value.quote||typeof value.quote.price!=="string"||!/^\d+(\.\d+)?$/.test(value.quote.price)))||(value.status!=="AVAILABLE"&&value.quote!==null))throw new Error("报价响应与本次目标不一致或字段异常，未采用。");
      setSnapshot(value);window.history.replaceState({},"",`/market-data?${new URLSearchParams({instrument_id:instrument.instrument_id,source_name:sourceName.trim()})}`);
    }catch(reason){if(current===generation.current)setError(reason instanceof Error?reason.message:"读取失败，请重试。");}finally{busy.current=false;setWorking(false);}
  }
  async function saveQuote(event:FormEvent){
    event.preventDefault();if(busy.current||!instrument)return;
    busy.current=true;setWorking(true);setError(null);setMessage(null);setSnapshot(null);setSaved(null);
    try{const content={instrument_id:instrument.instrument_id,source:"MANUAL_MARKET",source_name:sourceName.trim(),source_locator:locator.trim(),currency:instrument.currency,price,observed_at:utc(observed),effective_at:utc(effective),available_at:utc(available),expires_at:utc(expires)};
      const fingerprint=JSON.stringify(content);if(pending.current?.fingerprint!==fingerprint)pending.current={fingerprint,id:crypto.randomUUID()};
      const value=await requestJson<Saved>("/api/v1/market-data/manual-quotes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...content,request_id:pending.current.id})});
      if(value.request_id!==pending.current.id||!value.evidence_id||!/^([0-9a-f]{64})$/.test(value.content_hash))throw new Error("保存回执格式异常，结果未确认；请使用同一内容再次保存核对原请求。");
      setSaved(value);setMessage("人工报价已记录，尚未核实为市场事实；可点击读取核对当前可用状态。不会启动模型或交易。");
      window.history.replaceState({},"",`/market-data?${new URLSearchParams({instrument_id:instrument.instrument_id,source_name:sourceName.trim()})}`);
    }catch(reason){setError(reason instanceof Error?reason.message:"保存未确认，输入已保留。");}finally{busy.current=false;setWorking(false);}
  }
  return <ProductChrome eyebrow="结构化数据 · CNY单币种" title="人工行情与汇率边界" subtitle="没有Tushare凭据也可记录自己有权使用的报价。人工输入不等于已核实或可用于交易的数据。">
    <Panel title="1 · 能力与使用方式"><p>先在组合或观察清单登记标的，在这里选择标的并填写来源、精确价格与时间，明确保存后再读取核对。资料仅作不可信参考；不会连接网页、调用模型或生成订单。</p><p>当前只支持人工人民币参考价。没有FX、全市场证券全集、历史日线 / 波动率 / 流动性，也没有完整仓位计算；博查新闻不会被当作行情。</p><p>数据服务：{capabilities?.status==="AVAILABLE"?"已装配人工行情记录（不是市场连接健康检测）":capabilities?"当前部署未装配":"正在读取能力…"}</p><p>时间输入按当前浏览器时区 {Intl.DateTimeFormat().resolvedOptions().timeZone}，提交转换为UTC；读取结果保留完整UTC时点。</p></Panel>
    <StatusBanner kind="error" text={error}/><StatusBanner kind="ok" text={message}/><StatusBanner kind="info" text={working?"正在处理，请等待结果…":null}/>
    <Panel title="2 · 选择标的与来源"><InstrumentSearchBox onSelect={hit=>{if(!busy.current){changeSelection();setInstrument(hit);}}}/><p>{instrument?`当前标的：${instrument.market} ${instrument.symbol} ${instrument.name} · ${instrument.currency}`:"尚未选择标的；没有目录数据时请先录入持仓或观察标的。"}</p><label className="field">来源名称<input maxLength={255} value={sourceName} disabled={working} onChange={e=>{changeSelection();setSourceName(e.target.value);}} placeholder="例如：自己核对的公开收盘价"/></label>{instrument&&instrument.currency!=="CNY"?<p className="banner banner-error">该标的不是人民币报价，缺少FX，不能在首版保存或据此估值。</p>:null}</Panel>
    <Panel title="3 · 记录有出处的人工报价" description="不填写真实供应商密钥。保存生成只追加Evidence与审计，不修改旧资料。"><form onSubmit={event=>void saveQuote(event)}><fieldset disabled={working||!instrument||instrument.currency!=="CNY"||capabilities?.status!=="AVAILABLE"} style={{border:0,padding:0,minWidth:0}}><div className="form-grid">
      <label className="field">参考价格（人民币）<input required inputMode="decimal" value={price} onChange={e=>setPrice(e.target.value)} placeholder="例如 15.25，不使用逗号或科学计数法"/></label>
      <label className="field">来源出处<input required maxLength={2000} value={locator} onChange={e=>setLocator(e.target.value)} placeholder="原始网页地址、文件名或可核对资料定位；不会访问该地址"/></label>
      <label className="field">观察时点<input required type="datetime-local" step="1" value={observed} onChange={e=>setObserved(e.target.value)}/></label>
      <label className="field">生效时点<input required type="datetime-local" step="1" value={effective} onChange={e=>setEffective(e.target.value)}/></label>
      <label className="field">可获取时点<input required type="datetime-local" step="1" value={available} onChange={e=>setAvailable(e.target.value)}/></label>
      <label className="field">到期时点<input required type="datetime-local" step="1" value={expires} onChange={e=>setExpires(e.target.value)}/></label>
    </div><p>可获取时点不能早于观察 / 生效，到期必须更晚；系统另记实际入库时点，不能回填为历史上已知。过期或未来资料不会变成可用报价。</p><button className="btn primary" type="submit" disabled={!sourceName.trim()}>明确保存人工报价</button></fieldset></form>{saved?<p className="hint-text" style={{overflowWrap:"anywhere"}}>Evidence：{saved.evidence_id} · 摘要：{saved.content_hash} · 入库：{saved.ingested_at}</p>:null}</Panel>
    <Panel title="4 · 只读核对参考输入" description="每次只读取你明确指定的来源，不静默换源或借用旧报价。刷新后按地址中的标的 / 来源再明确读取。"><div className="form-grid"><label className="field">读取时点（留空使用服务端当前UTC）<input type="datetime-local" step="1" disabled={working} value={asOf} onChange={e=>{changeSelection();setAsOf(e.target.value);}}/></label><label className="field">估值基准币种<select disabled={working} value={baseCurrency} onChange={e=>{changeSelection();setBaseCurrency(e.target.value);}}><option value="CNY">人民币 CNY</option><option value="USD">美元 USD（缺FX会阻止）</option></select></label><label className="field">组合币种边界（可选）<select disabled={working} value={portfolio} onChange={e=>{changeSelection();setPortfolio(e.target.value);}}><option value="">只核对标的</option>{portfolios.map(p=><option key={p.portfolio_id} value={p.portfolio_id}>{p.name}</option>)}</select></label></div><button type="button" className="btn" disabled={working||!instrument||!sourceName.trim()} onClick={()=>void readQuote()}>读取指定来源报价</button>
      {snapshot?<article className="evidence-card" style={{overflowWrap:"anywhere"}}><h3>{labels[snapshot.status]}</h3><p>读取时点：{snapshot.as_of} · 来源：{snapshot.source_name} · 基准币种：{snapshot.base_currency}</p>{snapshot.quote?<p>参考价格：{snapshot.quote.price} {snapshot.quote.provenance.currency}</p>:<p>没有可用参考价格，不默认零、不补造汇率。</p>}{snapshot.provenance?<details open><summary>来源与业务时间</summary><p>出处：{snapshot.provenance.source_locator}</p><p>观察：{snapshot.provenance.observed_at}<br/>生效：{snapshot.provenance.effective_at}<br/>可获取：{snapshot.provenance.available_at}<br/>入库：{snapshot.provenance.ingested_at}<br/>到期：{snapshot.provenance.expires_at}</p><p>Evidence：{snapshot.provenance.evidence_id}<br/>内容摘要：{snapshot.provenance.content_hash}</p></details>:null}<p>人工提供、未经独立核实、非交易级数据；本页不解除Risk或Approval闸门。</p></article>:null}
    </Panel>
  </ProductChrome>;
}
