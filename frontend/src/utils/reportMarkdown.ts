import type { AIReportDetail } from '../types/api'

function text(value: unknown): string {
  if (value == null || value === '') return '未记录'
  return String(value).replace(/\\/g, '\\\\').replace(/([*_`[\]<>#|])/g, '\\$1')
}

function list(items: string[]): string {
  return items.length > 0 ? items.map((item) => `- ${text(item)}`).join('\n') : '- 未记录'
}

function actualMarketEnd(report: AIReportDetail): string {
  const snapshot = report.context_snapshot
  if (!snapshot) return '未记录'
  return text(snapshot.provenance.market_end_date)
}

function percent(value: number | null): string {
  if (value == null) return '未记录'
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

function customFacts(report: AIReportDetail): string[] {
  if (report.analysis_mode !== 'custom_backtest' || !report.context_snapshot) return []
  if (!('effective_parameters' in report.context_snapshot)) return []
  const context = report.context_snapshot
  const parameters = context.effective_parameters
  const metrics = context.metrics
  return [
    '## 保存的回测事实',
    '',
    '| 字段 | 保存值 |',
    '|---|---:|',
    `| 实际区间 | ${text(context.start_date)} ~ ${text(context.end_date)} |`,
    `| MA 参数 | ${parameters.ma_short_period} / ${parameters.ma_long_period} |`,
    `| 初始资金 | ${parameters.initial_cash} |`,
    `| 交易成本 / 滑点 | ${percent(parameters.transaction_cost)} / ${percent(parameters.slippage)} |`,
    `| 总收益 | ${percent(metrics.total_return)} |`,
    `| 年化收益 | ${percent(metrics.annual_return)} |`,
    `| 最大回撤 | ${percent(metrics.max_drawdown)} |`,
    `| 夏普率 | ${text(metrics.sharpe_ratio)} |`,
    `| 胜率 | ${percent(metrics.win_rate)} |`,
    `| 基准收益 | ${percent(metrics.benchmark_return)} |`,
    `| 成交笔数 / 往返次数 | ${metrics.order_count} / ${metrics.trade_count} |`,
    `| C 输入快照 SHA-256 | ${context.data_hash} |`,
    '',
  ]
}

export function buildReportMarkdown(report: AIReportDetail): string {
  const mode = report.analysis_mode === 'custom_backtest' ? '自定义回测解读' : '默认综合分析'
  const snapshotNote =
    report.snapshot_status === 'legacy_missing'
      ? '旧报告缺少上下文快照，未使用当前数据补写。'
      : '正文与元数据来自报告生成时保存的冻结快照。'

  return [
    `# AI 投研报告 ${text(report.stock_code)}`,
    '',
    '## 报告元数据',
    '',
    `- 报告 ID：${report.report_id}`,
    `- 分析模式：${mode}`,
    `- 关联回测 ID：${text(report.backtest_id)}`,
    `- 生成时间：${text(report.created_at)}`,
    `- 数据截至：${actualMarketEnd(report)}`,
    `- 上下文时间：${text(report.data_as_of)}`,
    `- 数据来源：${text(report.source_mode)}`,
    `- 模型：${text(report.model_name)}`,
    `- Prompt 版本：${text(report.prompt_version)}`,
    `- Context 版本：${text(report.context_schema_version)}`,
    `- Output 版本：${text(report.output_schema_version)}`,
    `- 上下文 SHA-256：${text(report.context_hash)}`,
    `- 快照状态：${text(report.snapshot_status)}`,
    '',
    `> ${snapshotNote}`,
    '',
    '## 摘要',
    '',
    text(report.summary),
    '',
    ...customFacts(report),
    `## ${report.analysis_mode === 'custom_backtest' ? '策略与参数' : '技术面'}`,
    '',
    text(report.technical_analysis),
    '',
    `## ${report.analysis_mode === 'custom_backtest' ? '回测表现' : '量化面'}`,
    '',
    text(report.quant_analysis),
    '',
    '## 新闻与信息边界',
    '',
    text(report.news_analysis),
    '',
    '## 优势',
    '',
    list(report.advantages),
    '',
    '## 风险',
    '',
    list(report.risks),
    '',
    '## 结论',
    '',
    text(report.conclusion),
    '',
    '> 风险提示：以上内容由 AI 基于保存的数据生成，不构成投资建议。',
    '',
  ].join('\n')
}

export function reportMarkdownFilename(report: AIReportDetail): string {
  const date = /^\d{4}-\d{2}-\d{2}/.exec(report.created_at)?.[0] ?? 'unknown-date'
  return `ai-report-${report.stock_code}-${report.report_id}-${date}.md`
}

export function downloadReportMarkdown(report: AIReportDetail): void {
  const blob = new Blob([buildReportMarkdown(report)], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = reportMarkdownFilename(report)
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
