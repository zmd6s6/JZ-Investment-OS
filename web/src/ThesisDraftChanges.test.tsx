import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ThesisDraftChanges } from "./ThesisDraftChanges";
const base = { state:"UNKNOWN",long_term_summary:"原摘要",pillars:[],catalysts:[],risks:[],invalidation_conditions:[],monitoring_conditions:[],change_reason:"HUMAN_CORRECTION" };
afterEach(cleanup);
it("仅展示实际改变字段，证据变动可见且输入不变",()=>{
  const before=structuredClone(base);
  const after={...base,pillars:[{key:"P1",claim:{description:"合成主张",evidence_ids:["synthetic-evidence"]},status:"AT_RISK"}]};
  render(<ThesisDraftChanges before={before} after={after}/>);
  fireEvent.click(screen.getByText("保存前核对修改（1 项）"));
  expect(screen.getByRole("heading",{name:"逻辑支柱及支持证据"})).toBeVisible();
  expect(screen.getByText(/synthetic-evidence/)).toBeVisible();
  expect(screen.queryByRole("heading",{name:"长期投资逻辑摘要"})).not.toBeInTheDocument();
  expect(before).toEqual(base);
  expect(after.pillars[0].status).toBe("AT_RISK");
});
it("新建与无修改明确区分，外部文字不执行",()=>{
  const view=render(<ThesisDraftChanges before={base} after={base}/>);
  expect(screen.getByText(/当前草稿与载入版本一致/)).toBeInTheDocument();
  view.rerender(<ThesisDraftChanges before={null} after={{...base,long_term_summary:"<script>not-an-instruction</script>"}}/>);
  expect(screen.getAllByText("尚无已保存内容")).toHaveLength(8);
  expect(view.container.querySelector("script")).toBeNull();
});
