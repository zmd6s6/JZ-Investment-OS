import { expect, it } from "vitest";
import { parseAcceptance } from "./AcceptancePage";
const item={key:"valuation",label:"参考估值与持仓对账",work_item:"MVP-202",engineering:"IMPLEMENTED",integration:"INTEGRATED",human_acceptance:"PENDING",service:"ASSEMBLED",route:"/valuation",detail:"参考估值，非完整Sizing。",steps:["选择组合和来源。"],failure:"缺价或FX不计算完整NAV。"};
const snapshot={schema_version:"1.0",release:"MVP-BETA",auto_trade:false,evidence_basis:"BUILD_MANIFEST_AND_SERVICE_ASSEMBLY",capabilities:[item]};
it("accepts the exact shipped valuation route without accepting Owner checkpoint",()=>{
 const result=parseAcceptance(snapshot);
 expect(result.capabilities[0].route).toBe("/valuation");
 expect(result.capabilities[0].human_acceptance).toBe("PENDING");
});
it.each(["https://external.example.test/valuation","//external.example.test/valuation","/valuation-unshipped"])("still rejects unsupported target %s",route=>{
 expect(()=>parseAcceptance({...snapshot,capabilities:[{...item,route}]})).toThrow();
});
