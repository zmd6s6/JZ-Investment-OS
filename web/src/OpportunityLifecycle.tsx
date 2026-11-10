export type Lifecycle={schema_version:string;instrument_id:string;as_of:string;status:string;reason:string;state:string|null;source_record_id:string|null;source_version:number|null;effective_at:string|null;recorded_at:string|null;thesis_version_id:string|null;decision_id:string|null;source_hash:string|null};
const reasons:Record<string,string>={STATE_NOT_PROVIDED:'未提供状态记录',STATE_NOT_YET_AVAILABLE:'该时点尚不可用',STATE_HISTORY_UNAVAILABLE:'当前记录已修订，无法证明该时点的历史状态',STATE_INVALID:'状态或来源引用无法核对',LIFECYCLE_PORT_NOT_PROVIDED:'状态读取服务未提供'};
export function OpportunityLifecycle({snapshot,next}:{snapshot?:Lifecycle|null;next?:string}){
 return <div><p>生命周期：{snapshot?.status==='AVAILABLE'?snapshot.state:'UNKNOWN／未提供'}。只读记录，不由本次筛选推断，不代表可买入或批准。</p>{snapshot?.status==='AVAILABLE'?<p>状态来源：instrument_state / {snapshot.source_record_id}；版本 {snapshot.source_version}<br/>生效 {snapshot.effective_at}；记录 {snapshot.recorded_at}；筛选时点 {snapshot.as_of}<br/>来源摘要 {snapshot.source_hash}<br/>Thesis版本 {snapshot.thesis_version_id||'未提供'}；Decision {snapshot.decision_id||'未提供'}</p>:<p>{snapshot?(reasons[snapshot.reason]||'状态来源无法核对'):'历史运行未冻结生命周期；不使用当前状态回填。'}</p>}<p>后续条件：{next==='EXPLICIT_RESEARCH_CONSENT_REQUIRED'?'核对资料时效、模型和预算，逐个明确同意后研究；不会自动运行。':next==='DEEP_RESEARCH_NOT_PROVIDED'?'本历史运行当时未提供深研；保留原记录。':next==='OUTSIDE_CURRENT_RESEARCH_LIMIT'?'超出本次研究上限；调整条件后新建查询，不改旧结果。':'核对各层缺项或不满足条件；补资料后新建查询，不改旧结果。'}</p></div>;
}

export function checkLifecycle(snapshot:Lifecycle|undefined|null,instrument:string,asOf:string){
 if(snapshot==null)return;
 const states=['DISCOVER','WATCH','SETUP','BUYABLE','HOLD','ADD','REDUCE','EXIT','COOLDOWN','ARCHIVED'];
 if(snapshot.schema_version!=='1.0'||snapshot.instrument_id!==instrument||Date.parse(snapshot.as_of)!==Date.parse(asOf)||!['AVAILABLE','UNKNOWN'].includes(snapshot.status))throw new Error('生命周期来源或时点无法核对。');
 if(snapshot.status==='AVAILABLE'&&(!states.includes(snapshot.state||'')||snapshot.source_version!==1||!snapshot.source_record_id||!snapshot.effective_at||!snapshot.recorded_at||Date.parse(snapshot.effective_at)>Date.parse(asOf)||Date.parse(snapshot.recorded_at)>Date.parse(asOf)||!snapshot.source_hash||! /^[0-9a-f]{64}$/.test(snapshot.source_hash)))throw new Error('生命周期快照无法核对。');
 if(snapshot.status==='UNKNOWN'&&snapshot.state!==null)throw new Error('未知生命周期不可显示确定状态。');
}
