import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { UniverseSnapshotPanel, parseUniverseSummary } from './UniverseSnapshotPanel';

const id='11111111-1111-4111-8111-111111111111';
const now='2026-10-29T00:00:00Z';
const source={schema_version:'1.0',source_name:'合成来源',source_version:'v1',source_locator:'synthetic://scope.csv',market:'SSE',coverage_definition:'明确合成集合',observed_at:'2026-10-27T00:00:00.000Z',effective_at:'2026-10-27T00:00:00.000Z',available_at:'2026-10-27T00:00:00.000Z',declared_total:1,completeness:'UNKNOWN'};
const flags={schema_version:'1.0',origin:'SOURCE_DECLARED',verification:'UNVERIFIED',market_universe:'NOT_PROVIDED',external_calls:0,model_calls:0,paid_calls:0,auto_trade:false};
const member={schema_version:'1.0',instrument_id:id,market:'SSE',symbol:'SYN',name:'合成成员',currency:'CNY',asset_type:'EQUITY'};
const csv='market,symbol\nSSE,SYN';
const fileHash='f77339999b516f8fe745f6e4bfee0531dd24ff1597a2d633911b32ba186c7d1a'; // SHA-256 of the synthetic CSV fixture, not a credential. pragma: allowlist secret
const snapshot={...flags,snapshot_id:id,source,ingested_at:now,evidence_id:id,file_hash:fileHash,members_hash:'b'.repeat(64),content_hash:'c'.repeat(64),member_count:1,members:[member]};
const filters={quote_source_name:'合成报价',fact_source_name:'合成年报',candidate_limit:'1',industry_filter:'',as_of:'',min_profit_margin:'0.1',min_revenue_growth:'0.1',max_pe:'60',min_price_change:'0'};
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function props(){return {filters,activeRunId:null,disabled:false,onBusyChange:vi.fn(),onBound:vi.fn(async()=>{})};}
async function fill(){fireEvent.change(screen.getByLabelText('来源集合名称'),{target:{value:source.source_name}});fireEvent.change(screen.getByLabelText('来源集合版本'),{target:{value:'v1'}});fireEvent.change(screen.getByLabelText('来源集合出处'),{target:{value:source.source_locator}});fireEvent.change(screen.getByLabelText('覆盖定义（来源声明）'),{target:{value:source.coverage_definition}});fireEvent.change(screen.getByLabelText('来源市场'),{target:{value:'SSE'}});fireEvent.change(screen.getByLabelText('来源声明总数'),{target:{value:'1'}});fireEvent.change(screen.getByLabelText('完整性声明'),{target:{value:'UNKNOWN'}});for(const label of ['来源观察时点','来源生效时点','来源可获取时点'])fireEvent.change(screen.getByLabelText(label),{target:{value:'2026-10-27T00:00'}});fireEvent.change(screen.getByLabelText('集合CSV内容'),{target:{value:csv}});fireEvent.click(screen.getByRole('button',{name:'预览来源集合（不保存）'}));await screen.findByText('待确认预览 · 1 项');}

test('explicit preview/ack import with unknown response preserves exact request on retry',async()=>{
 vi.stubGlobal('crypto',{randomUUID:()=> '22222222-2222-4222-8222-222222222222',subtle:{digest:async()=>Uint8Array.from(fileHash.match(/../g)!,h=>parseInt(h,16)).buffer}});let attempts=0;const writes:unknown[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(!init?.method)return new Response('[]');const body=JSON.parse(String(init.body));if(url.endsWith('/preview'))return new Response(JSON.stringify({...flags,source:{schema_version:'1.0',...body.source},members:[member],file_hash:fileHash,members_hash:'b'.repeat(64),preview_hash:'d'.repeat(64),full_scan_supported:true}));writes.push(body);if(attempts++===0)throw new TypeError('offline');return new Response(JSON.stringify({...snapshot,source:{schema_version:'1.0',...body.source},snapshot_id:body.request_id}));}));
 render(<UniverseSnapshotPanel {...props()}/>);await fill();const button=screen.getByRole('button',{name:'确认保存来源快照'});expect(button).toBeDisabled();fireEvent.click(screen.getByLabelText(/我有权在本机/));expect(button).toBeDisabled();fireEvent.click(screen.getByLabelText(/我已核对来源、版本/));fireEvent.click(button);await screen.findByText(/连接、超时或响应异常/);await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);await screen.findByText(/来源快照已保存/);expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);expect(screen.getByText(/冻结成员 1 项/)).toBeVisible();
});

test('bound command never accepts a member subset and validates exact origin before callback',async()=>{
 const p=props();const bodies:Record<string,unknown>[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method){const body=JSON.parse(String(init.body));bodies.push(body);return new Response(JSON.stringify({origin:{schema_version:'1.0',run_id:body.request_id,source:snapshot},run:{run_id:body.request_id,query:{instrument_ids:[id]}}}));}return new Response(JSON.stringify(url=== '/api/v1/opportunities/universes'?[snapshot]:snapshot));}));
 render(<UniverseSnapshotPanel {...p}/>);await screen.findByRole('button',{name:/读取来源 合成来源/});fireEvent.click(screen.getByRole('button',{name:/读取来源 合成来源/}));await screen.findByText(/当前来源快照：合成来源/);fireEvent.click(screen.getByRole('button',{name:'按此快照全部成员筛选'}));await waitFor(()=>expect(p.onBound).toHaveBeenCalledOnce());expect(bodies[0]).toMatchObject({snapshot_hash:snapshot.content_hash,as_of:null,candidate_limit:1});expect(bodies[0]).not.toHaveProperty('instrument_ids');
});

test('201 members remain visible but full scan is disabled and malformed authority is rejected',async()=>{
 const members=Array.from({length:201},(_,n)=>({...member,instrument_id:`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`,symbol:'SYN'+n}));const large={...snapshot,source:{...source,declared_total:201},member_count:201,members};
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/v1/opportunities/universes'?[large]:large))));render(<UniverseSnapshotPanel {...props()}/>);fireEvent.click(await screen.findByRole('button',{name:/读取来源 合成来源/}));await screen.findByText(/冻结成员 201 项/);expect(screen.getByRole('button',{name:'按此快照全部成员筛选'})).toBeDisabled();expect(screen.getByText(/没有截断、抽样或拼接每批候选/)).toBeVisible();expect(()=>parseUniverseSummary({...snapshot,verification:'VERIFIED'})).toThrow();expect(()=>parseUniverseSummary({...snapshot,source:{...source,available_at:null}})).toThrow();
});
