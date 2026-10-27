import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OpportunitiesPage } from './OpportunitiesPage';
const a={instrument_id:'11111111-1111-4111-8111-111111111111',market:'SSE',symbol:'629402',name:'合成A',asset_type:'EQUITY',currency:'CNY',sector:'Synthetic'};
const b={...a,instrument_id:'22222222-2222-4222-8222-222222222222',symbol:'629403',name:'合成B'};
vi.mock('./InstrumentSearchBox',()=>({InstrumentSearchBox:({onSelect}:{onSelect:(hit:typeof a)=>void})=><><button onClick={()=>onSelect(a)}>添加合成A</button><button onClick={()=>onSelect(b)}>添加合成B</button></>}));
const json=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data});
const eid='33333333-3333-4333-8333-333333333333';
function setup(handler:(url:string,init?:RequestInit)=>unknown=()=>json({})){
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{if(url.endsWith('/capabilities'))return json({status:'AVAILABLE'});if(url.endsWith('/runs')&&!init?.method)return json([]);return handler(url,init);});vi.stubGlobal('fetch',fetch);render(<OpportunitiesPage/>);return fetch;
}
async function facts(){
 fireEvent.click(screen.getByRole('button',{name:'添加合成A'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:'保存基础事实'})).toBeDisabled());
 fireEvent.change(screen.getByLabelText('基础事实来源名称'),{target:{value:'合成年报'}});
 fireEvent.change(screen.getByLabelText('事实出处'),{target:{value:'synthetic://facts'}});
 for(const label of ['事实观察时点','事实生效时点','事实可获取时点'])fireEvent.change(screen.getByLabelText(label),{target:{value:'2026-10-26T08:00:00'}});
 fireEvent.change(screen.getByLabelText('事实到期时点'),{target:{value:'2026-10-28T08:00:00'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'保存基础事实'})).toBeEnabled());
}
async function query(){
 await waitFor(()=>expect(screen.getByRole('button',{name:'运行本次确定性筛选'})).toBeDisabled());
 for(const [label,value] of [['范围名称','合成有限范围'],['范围出处','synthetic://scope'],['报价来源名称','合成行情'],['基础事实来源名称','合成年报'],['最低年度归属利润率','0.1'],['最低营收同比增幅','0.1'],['最高年报稀释PE（非TTM）','60'],['最低相对前收盘变化','0']])fireEvent.change(screen.getByLabelText(label),{target:{value}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'运行本次确定性筛选'})).toBeEnabled());
}
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();window.history.replaceState({},'','/');});

it('clears annual facts and share-basis confirmation when switching selected instruments',async()=>{
 setup();await facts();
 fireEvent.change(screen.getByLabelText('年度归属普通股股东利润'),{target:{value:'20'}});
 fireEvent.change(screen.getByLabelText('完整自然年年度'),{target:{value:'2025'}});
 fireEvent.change(screen.getByLabelText('报价与年度稀释EPS口径'),{target:{value:'true'}});
 fireEvent.click(screen.getByRole('button',{name:'添加合成B'}));
 expect(screen.getByLabelText('年度归属普通股股东利润')).toHaveValue('');
 expect(screen.getByLabelText('完整自然年年度')).toHaveValue(null);
 expect(screen.getByLabelText('报价与年度稀释EPS口径')).toHaveValue('');
 expect(screen.getByLabelText('事实出处')).toHaveValue('');
});

it('writes exact strings, keeps source/time, and retries unknown facts with the original id',async()=>{
 const commands:Record<string,unknown>[]=[];
 setup((_url,init)=>{const command=JSON.parse(init!.body as string);commands.push(command);if(commands.length===1)throw new TypeError('private raw');return json({request_id:command.request_id,evidence_id:eid,content_hash:'a'.repeat(64)});});
 await facts();fireEvent.change(screen.getByLabelText('年度归属普通股股东利润'),{target:{value:'20.000000000000000001'}});
 fireEvent.click(screen.getByRole('button',{name:'保存基础事实'}));await screen.findByText(/无法连接服务/);
 fireEvent.click(screen.getByRole('button',{name:'保存基础事实'}));await screen.findByText(/事实已保存/);
 expect(commands[0].request_id).toBe(commands[1].request_id);expect(commands[1].net_income).toBe('20.000000000000000001');expect(commands[1].available_at).toMatch(/Z$/);expect(commands[1].quote_evidence_id).toBeNull();expect(screen.queryByText('private raw')).not.toBeInTheDocument();
});

it('refuses a quote for another instrument and never binds that evidence',async()=>{
 setup(()=>json({instrument_id:b.instrument_id,source_name:'合成行情',source:'MANUAL_MARKET',base_currency:'CNY',status:'AVAILABLE',quote:{price:'10',provenance:{evidence_id:eid}}}));
 await facts();fireEvent.change(screen.getByLabelText('报价来源名称'),{target:{value:'合成行情'}});fireEvent.click(screen.getByRole('button',{name:'读取报价并绑定Evidence'}));await screen.findByText('报价与当前标的或来源不一致，未绑定。');expect(screen.queryByText(/人工参考价：/)).not.toBeInTheDocument();
});

it('reuses query as-of and request id after an unknown result, and shows empty scope honestly',async()=>{
 const requests:Record<string,unknown>[]=[];
 setup((_url,init)=>{const input=JSON.parse(init!.body as string);requests.push(input);if(requests.length===1)throw new TypeError('raw response');return json({run_id:input.request_id,query:input,formula_version:'manual-screen-v1',query_rule_hash:'b'.repeat(64),ingested_at:'2026-10-27T00:00:00Z',status:'EMPTY',rows:[],candidate_ids:[],auto_trade:false,independently_verified:false,deep_research:'NOT_PROVIDED',market_universe:'NOT_PROVIDED'});});
 await query();fireEvent.click(screen.getByRole('button',{name:'运行本次确定性筛选'}));await screen.findByText(/无法连接服务/);fireEvent.click(screen.getByRole('button',{name:'运行本次确定性筛选'}));await screen.findByText('本次没有手选标的，没有制造候选。');expect(requests[0].request_id).toBe(requests[1].request_id);expect(requests[0].as_of).toBe(requests[1].as_of);expect(screen.getByText(/全市场数据未提供；深研未提供/)).toBeInTheDocument();
});

it('malformed query result never renders a success or raw private fragments',async()=>{
 setup(()=>json({run_id:{private:'raw-private-fragment'}}));await query();fireEvent.click(screen.getByRole('button',{name:'运行本次确定性筛选'}));await screen.findByText('筛选结果格式异常，未采用。');expect(screen.queryByText('raw-private-fragment')).not.toBeInTheDocument();expect(screen.queryByRole('heading',{name:/本次筛选：/})).not.toBeInTheDocument();
});

it('bounded query timeout restores the button without clearing user inputs',async()=>{
 setup(()=>new Promise(()=>{}));await query();vi.useFakeTimers();fireEvent.click(screen.getByRole('button',{name:'运行本次确定性筛选'}));await act(async()=>{await vi.advanceTimersByTimeAsync(15001);});vi.useRealTimers();await screen.findByText(/请求超时/);expect(screen.getByRole('button',{name:'运行本次确定性筛选'})).toBeEnabled();expect(screen.getByLabelText('范围名称')).toHaveValue('合成有限范围');
});
