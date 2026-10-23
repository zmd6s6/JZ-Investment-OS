import { explainFailure, tokenPriceLabel } from "./analysisLabels";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue => value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const rows = (value: unknown): RecordValue[] => Array.isArray(value) ? value.map(record) : [];
function amount(value: unknown): string {
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value)) return "未知";
  const normalized = tokenPriceLabel(value);
  const [whole, fraction = ""] = normalized.split(".");
  return fraction.length > 8 ? `${whole}.${fraction.slice(0, 8)}…` : normalized;
}
function percent(value: unknown): string {
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value)) return "未知";
  const sign = value.startsWith("-") ? "-" : "";
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  const padded = fraction.padEnd(2, "0");
  const integer = `${whole}${padded.slice(0, 2)}`.replace(/^0+(?=\d)/, "");
  return `${sign}${amount(`${integer}.${padded.slice(2) || "0"}`)}%`;
}

function DailyMarketObservations({ features }: { features: unknown }) {
  const value = record(features), bar = record(value.bar);
  if (value.calculation_version !== "daily-observations-v1") return <p className="hint-text">本报告未记录单日行情观察，不根据当前行情补算；有参考价不代表已取得成交或波动率数据。</p>;
  const labels: Record<string, string> = { open: "开盘价", high: "最高价", low: "最低价", previous_close: "昨收价", volume_shares: "成交量", turnover: "成交额" };
  const missing = Array.isArray(value.missing_fields) ? value.missing_fields.map(String) : [];
  return <section aria-label="单日行情观察">
    <h4>单日行情观察（程序计算）</h4>
    <p className="hint-text">只描述本次参考日线，不是实时行情或交易指令。日内振幅不等于历史 / 年化波动率，成交额不等于可交易容量，仍不生成建议数量。</p>
    <dl className="valuation-summary">
      <div><dt>单日涨跌幅</dt><dd>{percent(value.daily_return)}</dd></div>
      <div><dt>日内振幅</dt><dd>{percent(value.intraday_range)}</dd></div>
      <div><dt>成交量（股）</dt><dd>{amount(value.volume_shares)}</dd></div>
      <div><dt>成交额（{String(value.currency)}）</dt><dd>{amount(value.turnover)}</dd></div>
    </dl>
    <p>开 / 高 / 低 / 收：{amount(bar.open)} / {amount(bar.high)} / {amount(bar.low)} / {amount(bar.close)}；昨收：{amount(bar.previous_close)}（{bar.previous_close_basis === "EX_RIGHTS" ? "除权昨收口径" : "提供方口径"}）。涨跌幅 = (收盘 − 昨收) / 昨收；振幅 = (最高 − 最低) / 昨收。</p>
    <p className="muted">来源：{String(value.source ?? "未知")}{value.degraded === true ? "（降级源）" : ""} · 参考时点：{String(bar.as_of ?? "未知")}；未证明真实发布时间或交易级新鲜度。</p>
    {missing.length > 0 && <p role="note">单日数据不完整，未补零：{missing.map(name => labels[name] ?? name).join("、")}。</p>}
    <p className="muted" style={{ overflowWrap: "anywhere" }}>单日输入摘要：{String(value.input_hash ?? "未记录")}</p>
  </section>;
}

export function AnalysisValuation({ valuation, sizing }: { valuation: unknown; sizing: unknown }) {
  const value = record(valuation), size = record(sizing);
  if (value.calculation_version !== "portfolio-valuation-v1") return <p className="hint-text">此历史报告未记录本版估值对账，不按当前持仓补算；旧数值仅保留在技术数据中，不作为完整仓位依据。</p>;
  const missing = Array.isArray(size.reason_codes) ? size.reason_codes.map(String) : [];
  return <section aria-label="估值对账与仓位缺口">
    <p className="hint-text">基于本次冻结的持仓、现金及实际返回报价，不是实时资产。金额单位：{String(value.base_currency)}；权重以本次净值为分母。长小数以 … 截显，完整精确值保留在技术数据中。</p>
    <dl className="valuation-summary">
      <div><dt>现金余额</dt><dd>{amount(value.cash_balance)}</dd></div>
      <div><dt>持仓总市值</dt><dd>{amount(value.holdings_value)}</dd></div>
      <div><dt>组合净值</dt><dd>{amount(value.nav)}</dd></div>
      <div><dt>现金占比</dt><dd>{percent(value.cash_weight)}</dd></div>
      <div><dt>总持仓暴露</dt><dd>{percent(value.gross_exposure)}</dd></div>
      <div><dt>标的 Core / Tactical 权重</dt><dd>{percent(value.target_core_weight)} / {percent(value.target_tactical_weight)}</dd></div>
    </dl>
    <p>对账状态：{value.status === "OK" ? "净值与持仓对账完整，仓位输入仍须单独检查" : value.status === "PARTIAL" ? "部分价格缺失，不以零补齐" : "估值校验未通过，不合并异币种或无效输入"}</p>
    <p className="muted">分析时点：{String(value.as_of ?? "未知")} · 行情仅提供参考时点，尚未验证交易级新鲜度与真实可用时间。</p>
    <DailyMarketObservations features={value.target_market_features} />
    {rows(value.position_values).length ? <details open><summary>逐项核对持仓与分仓</summary>
      <div style={{ overflowX: "auto" }}><table aria-label="冻结持仓估值明细"><thead><tr><th>标的 / 行业</th><th>Core / Tactical 数量</th><th>参考价 / 币种</th><th>Core / Tactical 市值</th><th>Core / Tactical 权重</th><th>来源 / 时间</th></tr></thead><tbody>
        {rows(value.position_values).map((row, i) => <tr key={`${row.instrument_id}-${i}`}>
          <td>{String(row.symbol)} · {String(row.name)}<div className="muted">{String(row.sector ?? "行业未知")}（持仓录入分类）</div></td>
          <td>{amount(row.core_quantity)} / {amount(row.tactical_quantity)}</td>
          <td>{amount(row.price)} {String(row.currency)}</td>
          <td>{amount(row.core_value)} / {amount(row.tactical_value)}</td>
          <td>{percent(row.core_weight)} / {percent(row.tactical_weight)}</td>
          <td>{String(row.source ?? "缺报价")}{row.degraded === true ? "（降级源）" : ""}<div className="muted">{String(row.quote_as_of ?? "未知")}</div></td>
        </tr>)}
      </tbody></table></div>
    </details> : <p>本次冻结组合没有持仓；现金与观察标的价格分别核对。</p>}
    <details><summary>行业分布（按持仓录入分类，不冒充供应商已核实）</summary>
      {rows(value.sector_values).map(row => <p key={String(row.sector)}>{String(row.sector)}：{amount(row.market_value)} {String(value.base_currency)} · {percent(row.weight)}</p>)}
      <p>未分类市值：{amount(value.unclassified_value)}；未知分类不当作零行业暴露。</p>
    </details>
    <div className="banner banner-info" role="note"><strong>暂不生成建议数量</strong><p>参考价格齐全不代表仓位输入齐全。可继续阅读团队分析、风险与投资逻辑；以下缺口需工程接入，不需要再填写本机访问令牌。</p>
      <ul>{missing.map(code => <li key={code}>{explainFailure(code)}</li>)}</ul>
      <p>测试公式未获投资授权；本报告不批准、下单或改变持仓。</p>
    </div>
    <p className="muted" style={{ overflowWrap: "anywhere" }}>估值输入摘要：{String(value.input_hash ?? "未记录")}</p>
  </section>;
}
