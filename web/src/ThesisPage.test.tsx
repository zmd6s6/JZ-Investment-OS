import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThesisPage } from "./ThesisPage";

const instrument={instrument_id:"asset-a",market:"SSE",symbol:"629811",name:"合成逻辑标的",asset_type:"EQUITY",currency:"CNY",sector:""};
const evidence={evidence_id:"evidence-a",title:"合成支持资料",excerpt:"合成摘录",source_name:"合成来源",freshness_status:"FRESH"};
const content={state:"UNKNOWN",long_term_summary:"原合成逻辑",pillars:[{key:"P1",claim:{description:"原合成主张",evidence_ids:["evidence-a"]},status:"VALID"}],catalysts:[],risks:[],invalidation_conditions:[],monitoring_conditions:[],change_reason:"HUMAN_CORRECTION"};
const version={id:"version-a",version:1,parent_version_id:null,content_hash:"c".repeat(64),created_at:"2026-10-21",content,semantic_diff:null};
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{"content-type":"application/json"}});

beforeEach(()=>{window.history.replaceState({},"","/thesis?instrument_id=asset-a");sessionStorage.clear();});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

function mockFetch(post:(body:Record<string,unknown>)=>Promise<Response>, workspace=()=>({instrument_id:"asset-a",current_version_id:null as string|null,versions:[] as typeof version[]})) {
  return vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input);
    if(init?.method==="POST"){
      expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
      return post(JSON.parse(String(init.body)));
    }
    if(url.includes("/workspace"))return response(workspace());
    if(url.includes("/evidence?"))return response({items:[evidence]});
    if(url.includes("/api/v1/instruments/"))return response(instrument);
    return response([]);
  });
}

async function fillFirst() {
  const summary=await screen.findByLabelText("长期投资逻辑摘要");
  fireEvent.change(summary,{target:{value:"合成长期判断"}});
  fireEvent.change(screen.getByLabelText("逻辑支柱 1"),{target:{value:"合成需求稳定"}});
  fireEvent.click(screen.getByRole("checkbox",{name:"逻辑支柱 1引用 合成支持资料"}));
}

describe("人工投资逻辑工作台",()=>{
  it("团队来源只显式加入草稿，保留人工摘要与状态，最后保存来源关联",async()=>{
    window.history.replaceState({},"","/thesis?instrument_id=asset-a&analysis_run_id=run-a");
    const posts:Record<string,unknown>[]=[];
    let saved=false;
    vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
      const url=String(input);
      if(init?.method==="POST"){posts.push(JSON.parse(String(init.body)));saved=true;return response({version_id:"version-b",version:2,created:true});}
      if(url.includes("thesis-review"))return response({analysis_run_id:"run-a",instrument_id:"asset-a",base_version_id:"version-a",as_of:"2026-10-22",input_hash:"a".repeat(64),unknowns:[],risk_gate:"UNKNOWN",limitations:[],suggestions:[{id:"opinion-a:0",opinion_id:"opinion-a",role:"FUNDAMENTAL",stage:"ROUND_1",claim:"团队新增合成观察",evidence_ids:["evidence-a"]}]});
      if(url.includes("/workspace"))return response({instrument_id:"asset-a",current_version_id:saved?"version-b":"version-a",versions:[saved?{...version,id:"version-b",version:2,content:posts[0].content,review_sources:[{analysis_run_id:"run-a",suggestion_ids:["opinion-a:0"],opinion_ids:["opinion-a"],input_hash:"a".repeat(64)}]}:version]});
      if(url.includes("/evidence?"))return response({items:[evidence]});
      return response(instrument);
    });
    render(<ThesisPage/>);
    fireEvent.change(await screen.findByLabelText("长期投资逻辑摘要"),{target:{value:"保留人工整理的长期判断"}});
    expect(posts).toHaveLength(0);
    fireEvent.click(await screen.findByRole("checkbox",{name:"带入团队观点 1 · 基本面"}));
    fireEvent.click(screen.getByRole("button",{name:"将勾选观点加入编辑草稿"}));
    expect(screen.getByLabelText("长期投资逻辑摘要")).toHaveValue("保留人工整理的长期判断");
    expect(screen.getByLabelText("逻辑状态")).toHaveValue("UNKNOWN");
    expect(screen.getByLabelText("逻辑支柱 2")).toHaveValue("团队新增合成观察");
    expect(screen.getByLabelText("支柱 2 状态")).toHaveValue("AT_RISK");
    expect(posts).toHaveLength(0);
    fireEvent.click(screen.getByRole("button",{name:"保存投资逻辑新版本"}));
    await screen.findByText("已保存投资逻辑版本 2，历史未被覆盖。");
    expect(posts[0].review_source).toEqual({analysis_run_id:"run-a",suggestion_ids:["opinion-a:0"]});
    expect(await screen.findByRole("heading",{name:"4 · 人工核对的团队来源"})).toBeVisible();
    expect(screen.getByRole("link",{name:"查看来源分析报告"})).toHaveAttribute("href","/analysis?run_id=run-a");
  });
  it("无记录不自动创建，通过表单明确保存并展示历史",async()=>{
    let saved=false;
    const posts:Record<string,unknown>[]=[];
    const fetch=mockFetch(async body=>{posts.push(body);saved=true;return response({version_id:"version-a",version:1,created:true});},()=>({instrument_id:"asset-a",current_version_id:saved?"version-a":null,versions:saved?[version]:[]}));
    render(<ThesisPage/>);
    await fillFirst();
    expect(posts).toHaveLength(0);
    fireEvent.click(screen.getByRole("button",{name:"保存投资逻辑新版本"}));
    await screen.findByText("已保存投资逻辑版本 1，历史未被覆盖。");
    expect(posts).toHaveLength(1);
    expect(posts[0].expected_version_id).toBeNull();
    expect((posts[0].content as typeof content).pillars[0].claim.evidence_ids).toEqual(["evidence-a"]);
    await screen.findByText(/版本 1 · 未知 · 原合成逻辑/);
    expect(fetch.mock.calls.some(([url])=>String(url).includes("analysis-jobs"))).toBe(false);
  });
  it("并发冲突保留草稿，不自动覆盖或重新提交",async()=>{
    const fetch=mockFetch(async()=>response({detail:{code:"THESIS_EDIT_CONFLICT"}},409),()=>({instrument_id:"asset-a",current_version_id:"version-a",versions:[version]}));
    render(<ThesisPage/>);
    const input=await screen.findByLabelText("长期投资逻辑摘要");
    fireEvent.change(input,{target:{value:"保留我的未保存草稿"}});
    fireEvent.click(screen.getByRole("button",{name:"保存投资逻辑新版本"}));
    await screen.findByText(/本次没有覆盖。输入已保留/);
    expect(input).toHaveValue("保留我的未保存草稿");
    expect(fetch.mock.calls.filter(([,init])=>init?.method==="POST")).toHaveLength(1);
  });
  it("网络结果未知时相同内容复用保存标识",async()=>{
    const ids:unknown[]=[];
    mockFetch(async body=>{ids.push(body.request_id);throw new TypeError("synthetic network failure");});
    render(<ThesisPage/>);await fillFirst();
    const button=screen.getByRole("button",{name:"保存投资逻辑新版本"});
    fireEvent.click(button);await screen.findByText(/保存结果尚未确认，输入已保留/);
    fireEvent.click(button);await waitFor(()=>expect(ids).toHaveLength(2));
    expect(ids[0]).toBe(ids[1]);
    expect(screen.getByLabelText("长期投资逻辑摘要")).toHaveValue("合成长期判断");
  });
  it("缺少逐条证据时不发送保存请求",async()=>{
    const fetch=mockFetch(async()=>response({}));
    render(<ThesisPage/>);
    fireEvent.change(await screen.findByLabelText("长期投资逻辑摘要"),{target:{value:"合成长期判断"}});
    fireEvent.change(screen.getByLabelText("逻辑支柱 1"),{target:{value:"没有引用的主张"}});
    fireEvent.click(screen.getByRole("button",{name:"保存投资逻辑新版本"}));
    await screen.findByText(/每个逻辑支柱、催化剂和风险主张都需要至少一条支持资料/);
    expect(fetch.mock.calls.filter(([,init])=>init?.method==="POST")).toHaveLength(0);
  });
});
