import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CalendarTaskHistory, parseCalendarTaskDetail, parseCalendarTaskPage } from './CalendarTaskHistory';
const id=(n:number)=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
const row=(n:number)=>({schema_version:'1.0',task_run_id:id(n),task_name:'calendar_status_SSE',task_status:'FAILED',attempt:3,created_at:'2025-01-01T00:00:00Z',scheduled_for:'2025-01-01T07:00:00Z',started_at:null,finished_at:null,reason_code:'SyntheticFailure',input_hash:'a'.repeat(64),auto_trade:false});
const page=(items=[row(1)],next_cursor:string|null=null)=>({schema_version:'1.0',items,next_cursor,page_size:50,ordering:'created_at_desc_task_id_desc',auto_trade:false});
const detail=(n:number)=>({...row(n),idempotency_key:'calendar-status:SSE:2025-01-01:'+id(800),source:{venue:'SSE',market_timezone:'Asia/Shanghai',business_date:'2025-01-01',close_at_utc:'2025-01-01T07:00:00Z',calendar_import_id:id(800),calendar_session_id:id(801),imported_at:'2025-01-01T00:00:00Z',source_name:'原来源A',source_version:'原版本',calendar_hash:'b'.repeat(64),source_verification:'SOURCE_DECLARED_UNVERIFIED'},report_event_id:null,report_recorded_at:null,report_json:null,report_hash:null,unknowns:['NO_COMMITTED_STATUS_REPORT','ATTEMPT_TIMELINE_NOT_RECORDED'],attempt_history:'NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY'});
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
afterEach(()=>{cleanup();vi.restoreAllMocks();window.history.replaceState(null,'','/calendar');});
it('opens an exact older URL outside the page and refreshes the original failed source without writes',async()=>{
 window.history.replaceState(null,'',`/calendar?calendar_task_id=${id(99)}`);
 const calls=vi.spyOn(globalThis,'fetch').mockImplementation(async input=>String(input).includes('/tasks/')?response(detail(99)):response(page()));
 render(<CalendarTaskHistory/>);
 await screen.findByRole('region',{name:'原日历任务详情'});
 expect(screen.getByText(/原来源A/)).toBeTruthy();expect(screen.getByText(/本任务未生成状态报告/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'刷新所选日历任务'}));await screen.findByRole('region',{name:'原日历任务详情'});
 expect(window.location.search).toContain(id(99));expect(calls.mock.calls.every(([,init])=>!init?.method)).toBe(true);
});
it('retains loaded rows on page failure and retries the same cursor before reaching the end',async()=>{
 let fail=true;
 vi.spyOn(globalThis,'fetch').mockImplementation(async input=>String(input).includes('?cursor=')?(fail?response({detail:'offline'},503):response(page([row(2)]))):response(page([row(1)],'next')));
 render(<CalendarTaskHistory/>);fireEvent.click(await screen.findByRole('button',{name:'加载更早日历任务'}));
 await screen.findByRole('alert');expect(screen.getByRole('button',{name:`查看原日历任务 ${id(1)}`})).toBeTruthy();
 fail=false;fireEvent.click(screen.getByRole('button',{name:'加载更早日历任务'}));await screen.findByRole('button',{name:`查看原日历任务 ${id(2)}`});
 expect(screen.getByText(/已加载2条/)).toBeTruthy();expect(screen.queryByRole('button',{name:'加载更早日历任务'})).toBeNull();
});
it('clears old detail on failed selection and ignores a late earlier response',async()=>{
 let resolve!:(r:Response)=>void;
 vi.spyOn(globalThis,'fetch').mockImplementation(async input=>String(input).endsWith('/'+id(1))?new Promise<Response>(r=>{resolve=r;}):String(input).endsWith('/'+id(2))?response(detail(2)):String(input).includes('/tasks/')?response({detail:'missing'},422):response(page([row(1),row(2)])));
 render(<CalendarTaskHistory/>);fireEvent.click(await screen.findByRole('button',{name:`查看原日历任务 ${id(1)}`}));
 fireEvent.click(screen.getByRole('button',{name:`查看原日历任务 ${id(2)}`}));await screen.findByRole('region',{name:'原日历任务详情'});
 await act(async()=>resolve(response(detail(1))));expect(screen.getByRole('region',{name:'原日历任务详情'}).textContent).toContain(id(2));
 fireEvent.change(screen.getByLabelText('精确日历任务ID'),{target:{value:id(99)}});expect(screen.queryByRole('region',{name:'原日历任务详情'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'打开精确日历任务'}));await screen.findByRole('alert');expect(screen.queryByText('原日历状态报告')).toBeNull();
});
it('rejects malformed ID locally and unauthorized reads visibly',async()=>{
 const calls=vi.spyOn(globalThis,'fetch').mockResolvedValue(response({detail:'unauthorized'},401));
 render(<CalendarTaskHistory/>);await screen.findByRole('alert');fireEvent.change(screen.getByLabelText('精确日历任务ID'),{target:{value:'bad'}});fireEvent.click(screen.getByRole('button',{name:'打开精确日历任务'}));
 await screen.findByText(/日历任务ID格式无效/);expect(calls).toHaveBeenCalledTimes(1);
});
it.each([page(Array.from({length:51},(_,n)=>row(n))),page([row(1),row(1)]),{...page(),page_size:100},{...page(),auto_trade:true}])('rejects malformed or excessive pages',value=>expect(()=>parseCalendarTaskPage(value)).toThrow());
it('rejects mismatched exact response and fabricated report linkage',()=>{
 expect(()=>parseCalendarTaskDetail(detail(1),id(2))).toThrow();
 expect(()=>parseCalendarTaskDetail({...detail(1),report_hash:'a'.repeat(64)},id(1))).toThrow();
});
