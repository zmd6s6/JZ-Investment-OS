import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MarketDataPage } from './MarketDataPage';

const instrument={instrument_id:'11111111-1111-4111-8111-111111111111',market:'SSE',symbol:'629201',name:'合成行情',currency:'CNY',asset_type:'EQUITY',sector:'Synthetic'};
const capabilities={status:'AVAILABLE',supported_sources:['MANUAL_MARKET'],currency_boundary:'CNY_ONLY',fx_supported:false,universe_supported:false,historical_bars_supported:false,trading_grade:false,automatic_network_calls:false};
const json=(body:unknown, status=200)=>({ok:status<400,status,json:async()=>body});
const provenance={instrument_id:instrument.instrument_id,evidence_id:'22222222-2222-4222-8222-222222222222',content_hash:'a'.repeat(64),source:'MANUAL_MARKET',source_name:'合成来源',source_locator:'synthetic://manual',currency:'CNY',observed_at:'2026-10-26T00:00:00Z',effective_at:'2026-10-26T00:00:00Z',available_at:'2026-10-26T00:00:00Z',ingested_at:'2026-10-27T00:00:00Z',expires_at:'2026-10-28T00:00:00Z',independently_verified:false,trading_grade:false};
const snapshot=(status='AVAILABLE')=>({instrument_id:instrument.instrument_id,source:'MANUAL_MARKET',source_name:'合成来源',as_of:'2026-10-27T00:00:00Z',base_currency:'CNY',status,reason_code:'synthetic',quote:status==='AVAILABLE'?{price:'15.250000000000000001',provenance}:null,provenance:status==='FX_REQUIRED'?null:provenance});
function setup(handler:(url:string,init?:RequestInit)=>unknown=()=>json({})){
  window.history.replaceState({},'',`/market-data?instrument_id=${instrument.instrument_id}&source_name=${encodeURIComponent('合成来源')}`);
  const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
    if(url.endsWith('/capabilities'))return json(capabilities);
    if(url.endsWith('/portfolios'))return json([]);
    if(url.includes('/instruments/'))return json(instrument);
    return handler(url,init);
  });
  vi.stubGlobal('fetch',fetch);
  render(<MarketDataPage/>);
  return fetch;
}
async function fillQuote(){
  await waitFor(()=>expect(screen.getByRole('button',{name:'明确保存人工报价'})).toBeEnabled());
  fireEvent.change(screen.getByLabelText('参考价格（人民币）'),{target:{value:'15.250000000000000001'}});
  fireEvent.change(screen.getByLabelText('来源出处'),{target:{value:'synthetic://manual'}});
  for(const label of ['观察时点','生效时点','可获取时点'])fireEvent.change(screen.getByLabelText(label),{target:{value:'2026-10-26T08:00:00'}});
  fireEvent.change(screen.getByLabelText('到期时点'),{target:{value:'2026-10-28T08:00:00'}});
}
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();sessionStorage.clear();});

it('saves exact strings with UTC times and retains request id after unknown result',async()=>{
  const commands:Record<string,string>[]=[];
  setup((_url,init)=>{
    const command=JSON.parse(init!.body as string);commands.push(command);
    if(commands.length===1)throw new TypeError('private raw fragment');
    return json({request_id:command.request_id,evidence_id:provenance.evidence_id,content_hash:provenance.content_hash,ingested_at:provenance.ingested_at});
  });
  await fillQuote();
  fireEvent.click(screen.getByRole('button',{name:'明确保存人工报价'}));
  await screen.findByText(/无法连接服务/);
  expect(screen.queryByText('private raw fragment')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'明确保存人工报价'}));
  await screen.findByText(/人工报价已记录/);
  expect(commands[0].request_id).toEqual(commands[1].request_id);
  expect(commands[1].price).toBe('15.250000000000000001');
  expect(commands[1].available_at).toMatch(/Z$/);
  expect(commands[1].source).toBe('MANUAL_MARKET');
  fireEvent.change(screen.getByLabelText('参考价格（人民币）'),{target:{value:'16'}});
  fireEvent.click(screen.getByRole('button',{name:'明确保存人工报价'}));
  await waitFor(()=>expect(commands).toHaveLength(3));
  expect(commands[2].request_id).not.toBe(commands[1].request_id);
});

it.each(['MISSING','EXPIRED','NOT_YET_AVAILABLE','INVALID','FX_REQUIRED'])('shows %s without fabricating a price',async(status)=>{
  setup(()=>json(snapshot(status)));
  await waitFor(()=>expect(screen.getByRole('button',{name:'读取指定来源报价'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'读取指定来源报价'}));
  await screen.findByText('没有可用参考价格，不默认零、不补造汇率。');
  expect(screen.queryByText(/参考价格：/)).not.toBeInTheDocument();
});

it('reads exact source and clears the previous price after a failed refresh',async()=>{
  let calls=0;
  const fetch=setup(url=>{expect(url).toContain('source=MANUAL_MARKET');calls++;return calls===1?json(snapshot()):json({detail:'private raw error'},500);});
  await waitFor(()=>expect(screen.getByRole('button',{name:'读取指定来源报价'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'读取指定来源报价'}));
  await screen.findByText('参考价格：15.250000000000000001 CNY');
  fireEvent.click(screen.getByRole('button',{name:'读取指定来源报价'}));
  await screen.findByText(/服务请求失败/);
  expect(screen.queryByText(/参考价格：/)).not.toBeInTheDocument();
  expect(fetch.mock.calls.every(([url])=>url.startsWith('/api/'))).toBe(true);
});

it('rejects malformed successful data and mismatched targets',async()=>{
  setup(()=>json({...snapshot(),instrument_id:'wrong'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'读取指定来源报价'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'读取指定来源报价'}));
  await screen.findByText(/报价响应与本次目标不一致/);
  expect(screen.queryByText(/参考价格：/)).not.toBeInTheDocument();
});

it('has bounded save feedback even if fetch never settles',async()=>{
  setup(()=>new Promise(()=>{}));
  await fillQuote();
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button',{name:'明确保存人工报价'}));
  await vi.advanceTimersByTimeAsync(15001);
  vi.useRealTimers();
  await screen.findByText(/请求超时/);
  expect(screen.getByRole('button',{name:'明确保存人工报价'})).toBeEnabled();
});
