const steps = [
  { title: "授权保存", href: null, detail: "输入本系统的访问令牌，验证后可保存。不是模型 API Key，也不能随便编一个。" },
  { title: "配置研究团队", href: "/settings#models", detail: "保存并启用模型 → 分配默认模型 → 填写定价与预算。连接测试会调用供应商，可能计费。" },
  { title: "记录研究对象", href: "/portfolio", detail: "已有持仓：新建组合、填现金和分仓；未持有：加入观察清单。不需要 Tushare Token。" },
  { title: "发起一次分析", href: "/portfolio#holdings", detail: "在持仓或观察清单点「立即分析」，核对组合与调用说明再启动。本轮使用已入库证据，启用来源不等于已有证据。" },
  { title: "阅读报告", href: "/analysis", detail: "先看完成状态与数据缺口，再看各角色观点、分歧、风险和建议。缺行情不生成虚构估值或买入数量。" },
] as const;

export function UsageGuide({ onAccess, expanded = false }: { onAccess: () => void; expanded?: boolean }) {
  return (
    <details className="usage-guide" open={expanded}>
      <summary><span>使用指南</span><span className="guide-summary">从授权到报告 · 随时展开查看</span></summary>
      <ol className="journey-steps">
        {steps.map((step, index) => (
          <li key={step.title}>
            <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
            <div>
              {step.href ? <a href={step.href}>{step.title} →</a> : <button type="button" onClick={onAccess}>{step.title} →</button>}
              <p>{step.detail}</p>
              {index === 2 ? <a className="guide-secondary" href="/watchlist">没有持仓？先添加观察标的 →</a> : null}
            </div>
          </li>
        ))}
      </ol>
      <p className="guide-footnote">这是操作顺序，不代表配置已通过验收。行情源可后补；审批与手工执行（P7）、定期选股（P8）、完整复盘尚未交付。</p>
    </details>
  );
}

export function requestAccessSetup() {
  window.dispatchEvent(new Event("investment-os:configure-access"));
}
