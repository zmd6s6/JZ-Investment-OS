import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OpportunityResearchPanel } from './OpportunityResearchPanel';

const candidate={funnelRunId:'11111111-1111-4111-8111-111111111111',instrumentId:'22222222-2222-4222-8222-222222222222',name:'合成候选',marketSource:'合成行情',evidenceIds:['33333333-3333-4333-8333-333333333333','44444444-4444-4444-8444-444444444444']};
const book='55555555-5555-4555-8555-555555555555',profile='66666666-6666-4666-8666-666666666666';
const choices={roles:['MACRO','CIO'],models:[{profile_id:profile,name:'合成模型',model_name:'synthetic',pricing_configured:true}],data_profiles:[{profile_id:'source',name:'合成研究源'}],budget_configured:true,budget_version:'test',remaining_tokens:100,remaining_cost:'1',max_model_calls:27};
const response=(value:unknown,status=200)=>({ok:status<400,status,json:async()=>value});
function setup(post:(body:any)=>unknown=()=>response({}),override={},initialHistory:unknown[]=[]){const fetch=vi.fn(async(url:string,init?:RequestInit)=>{if(url==='/api/v1/portfolios')return response([{portfolio_id:book,name:'合成组合'}]);if(url.includes('/choices'))return response({...choices,...override});if(url.includes('/research')&&init?.method==='POST')return post(JSON.parse(String(init.body)));if(url.endsWith('/research'))return response(initialHistory);throw new Error('unexpected URL');});vi.stubGlobal('fetch',fetch);render(<OpportunityResearchPanel candidate={candidate}/>);return fetch;}
async function choose(){await screen.findByRole('option',{name:'合成模型 / synthetic'});fireEvent.change(screen.getByLabelText('研究组合'),{target:{value:book}});fireEvent.change(screen.getByLabelText('候选研究模型'),{target:{value:profile}});}
function consent(){fireEvent.click(screen.getByLabelText(/我确认上述候选Evidence及组合选择/));}
function linked(command:any){return {command,status:'ANALYSIS_RECORDED',auto_trade:false,analysis_run:{run_id:'77777777-7777-4777-8777-777777777777',request_id:command.analysis.request_id,instrument_id:candidate.instrumentId,portfolio_id:book,status:'DEGRADED',error_code:null,steps:[],shadow_decision:{action:'AVOID',risk_gate:'UNKNOWN',sizing_status:'BLOCKED',auto_trade:false,execution_allowed:false,target_quantity:null}}};}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});

it('never starts on mount or selection; only a single explicit candidate carries proven evidence',async()=>{const commands:any[]=[];const fetch=setup(body=>{commands.push(body);return response(linked(body));});await choose();expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0);expect(screen.getByRole('button',{name:'明确发起这一候选研究'})).toBeDisabled();consent();fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await screen.findByText(/已保存这一个候选/);expect(commands).toHaveLength(1);expect(commands[0].funnel_run_id).toBe(candidate.funnelRunId);expect(commands[0].analysis.evidence_ids).toEqual(candidate.evidenceIds);expect(commands[0].analysis.data_profile_ids).toEqual([]);expect(screen.getByText(/只读影子结论 AVOID；Risk UNKNOWN/)).toBeVisible();expect(screen.getByLabelText(/我确认上述候选Evidence/)).not.toBeChecked();});

it('unknown response retry preserves original request id and does not auto submit',async()=>{const commands:any[]=[];setup(body=>{commands.push(body);if(commands.length===1)throw new TypeError('private-detail');return response(linked(body));});await choose();consent();fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await screen.findByRole('alert');expect(commands).toHaveLength(1);fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await screen.findByText(/已保存这一个候选/);expect(commands[0]).toEqual(commands[1]);expect(screen.queryByText('private-detail')).not.toBeInTheDocument();});

it('new research source requires separate query and consent and resets approval on edits',async()=>{const commands:any[]=[];setup(body=>{commands.push(body);return response(linked(body));});await choose();fireEvent.click(screen.getByText('本候选获取新资料（可选）'));fireEvent.click(screen.getByLabelText('研究源 合成研究源'));consent();fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await screen.findByText('选择研究源后必须填写查询词并单独同意资料调用。');expect(commands).toHaveLength(0);fireEvent.change(screen.getByLabelText('候选资料查询词'),{target:{value:'合成候选公告'}});expect(screen.getByLabelText(/我确认上述候选Evidence/)).not.toBeChecked();fireEvent.click(screen.getByLabelText(/我同意仅为这一候选/));consent();fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await screen.findByText(/已保存这一个候选/);expect(commands[0].analysis.allow_data_calls).toBe(true);expect(commands[0].analysis.query).toBe('合成候选公告');});

it('missing budget disables dispatch and mismatched analysis result is rejected',async()=>{setup(()=>response({}),{budget_configured:false});await choose();consent();expect(screen.getByRole('button',{name:'明确发起这一候选研究'})).toBeDisabled();});

it('refuses a linked response from another instrument',async()=>{setup(body=>response({...linked(body),analysis_run:{...linked(body).analysis_run,instrument_id:'wrong'}}));await choose();consent();fireEvent.click(screen.getByRole('button',{name:'明确发起这一候选研究'}));await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('研究关联响应无法核对'));expect(screen.queryByText(/只读影子结论 AVOID/)).not.toBeInTheDocument();});

it('persisted unqueued intent requires its own renewed model and data consent before exact replay',async()=>{
 const commands:any[]=[];
 const original={schema_version:'1.0',funnel_run_id:candidate.funnelRunId,analysis:{request_id:'88888888-8888-4888-8888-888888888888',portfolio_id:book,instrument_id:candidate.instrumentId,model_profiles:{MACRO:profile,CIO:profile},evidence_ids:candidate.evidenceIds,data_profile_ids:['source'],query:'原查询',market_source_name:candidate.marketSource,allow_model_calls:true,allow_data_calls:true}};
 setup(body=>{commands.push(body);return response(linked(body));},{},[{command:original,status:'AWAITING_EXPLICIT_RETRY',analysis_run:null,auto_trade:false}]);
 await choose();consent();
 expect(screen.getByRole('button',{name:'明确重试这条原排队请求'})).toBeDisabled();
 fireEvent.click(screen.getByLabelText(/我已核对上列原请求，重新同意原模型/));
 expect(screen.getByRole('button',{name:'明确重试这条原排队请求'})).toBeDisabled();
 fireEvent.click(screen.getByLabelText(/我重新同意上列原研究源及原查询/));
 fireEvent.click(screen.getByRole('button',{name:'明确重试这条原排队请求'}));
 await screen.findByText(/已保存这一个候选/);
 expect(commands).toEqual([original]);
});
