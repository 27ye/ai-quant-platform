// AI 分析 mock：字段对齐 docs/API_SPEC.md 第 9 节
import type {
  AIAnalysisData,
  AIReportDetail,
  AIReportSummary,
  ApiResponse,
  PaginatedAIReports,
} from '../types/api'

export function mockAIAnalysis(stockCode: string): ApiResponse<AIAnalysisData> {
  return {
    code: 0,
    message: 'success',
    data: {
      stock_code: stockCode,
      quant_score: 72,
      trend: 'bullish',
      summary: `综合来看，${stockCode} 当前处于短期趋势偏强、中期震荡上行阶段。技术面动能延续，量化评分中等偏上，消息面无明显利空。整体维持谨慎乐观判断。`,
      technical_analysis:
        '价格站上 MA20 且 MA5 上穿 MA10，短期均线呈多头排列；MACD 柱状图在零轴上方温和放大；RSI14 约 62，处于强势区间但尚未超买。布林带上轨附近有压力，需关注放量突破情况。',
      quant_analysis:
        '量化综合评分 72 分（满分 100），其中趋势分 30/40、动量分 18/25、量能分 12/20、风险分 12/15。趋势与动量贡献主要得分，量能略有不足。',
      news_analysis:
        '近期无重大负面公告，行业景气度中性偏暖，市场情绪稳定。未检测到可能引发剧烈波动的突发事件。',
      advantages: [
        '短期均线多头排列，趋势结构清晰',
        'RSI 强势区间运行且未超买，上行仍有空间',
        '回撤控制良好，风险分项得分较高',
      ],
      risks: [
        '接近布林带上轨，存在技术性回调压力',
        '量能未能同步放大，突破需要成交量确认',
        '估值处于历史偏高分位，注意情绪波动',
      ],
      conclusion:
        '建议以中性偏多思路对待：持仓者可继续持有并关注 MA20 支撑，空仓者等待回调至均线附近再考虑介入，突破布林带上轨且放量时可视为趋势加强信号。',
      model_name: 'mock-model',
    },
  }
}

// ============ V2 AI 报告历史 mock（契约：D 的 V2_AI_REPORT_HISTORY_CONTRACT.md）============
// 覆盖两种记录形态：id=101 完整快照（complete）+ id=100 旧记录（legacy_missing）

const MOCK_REPORT_SUMMARIES: AIReportSummary[] = [
  {
    report_id: 101,
    stock_code: '600519',
    quant_score: 82,
    trend: 'bullish',
    summary:
      '趋势得分较高，均线多头排列延续，量能配合尚可，综合评分处于强势区间，维持谨慎乐观。',
    model_name: 'deepseek-v4-flash',
    data_as_of: '2026-09-14T15:00:00Z',
    created_at: '2026-09-15T08:30:00Z',
    source_mode: 'live',
    snapshot_status: 'complete',
  },
  {
    report_id: 100,
    stock_code: '600519',
    quant_score: 33,
    trend: 'bearish',
    summary: '早期冻结演示报告：趋势偏弱，成交低迷，评分处于较弱区间，建议观望。',
    model_name: 'deepseek-v4-flash',
    data_as_of: null,
    created_at: '2026-09-10T02:12:00Z',
    source_mode: 'unknown',
    snapshot_status: 'legacy_missing',
  },
]

export function mockAIReports(params: {
  stock_code?: string
  page?: number
  page_size?: number
}): ApiResponse<PaginatedAIReports> {
  const page = params.page ?? 1
  const pageSize = params.page_size ?? 20
  const filtered = params.stock_code
    ? MOCK_REPORT_SUMMARIES.filter((item) => item.stock_code === params.stock_code)
    : MOCK_REPORT_SUMMARIES
  const start = (page - 1) * pageSize
  return {
    code: 0,
    message: 'success',
    data: {
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
    },
  }
}

export function mockAIReportDetail(reportId: number): ApiResponse<AIReportDetail> {
  const base = mockAIAnalysis('600519').data
  if (reportId === 100) {
    // V1 旧记录：无上下文快照、无版本字段，来源未知
    return {
      code: 0,
      message: 'success',
      data: {
        ...base,
        quant_score: 33,
        trend: 'bearish',
        report_id: 100,
        created_at: '2026-09-10T02:12:00Z',
        data_as_of: null,
        source_mode: 'unknown',
        prompt_version: null,
        context_schema_version: null,
        output_schema_version: null,
        context_hash: null,
        snapshot_status: 'legacy_missing',
        context_snapshot: null,
      },
    }
  }
  return {
    code: 0,
    message: 'success',
    data: {
      ...base,
      quant_score: 82,
      report_id: reportId,
      created_at: '2026-09-15T08:30:00Z',
      data_as_of: '2026-09-14T15:00:00Z',
      source_mode: 'live',
      prompt_version: 'v2.0',
      context_schema_version: 'v2.0',
      output_schema_version: 'v2.0',
      context_hash:
        '9af45d325e7cced7fc420da9f502e3abcf72ede1b7ad95070b264f8b0c4052f4',
      snapshot_status: 'complete',
      context_snapshot: {
        stock: { stock_code: '600519', stock_name: '贵州茅台', industry: '白酒' },
        market_snapshot: {
          trade_date: '2026-09-14',
          close: 1450.5,
          change_pct: 0.012,
          turnover_rate: 0.002,
        },
        technical_indicators: null,
        quant_score: { score: 82, level: 'strong', reasons: ['趋势得分较高'] },
        backtest_metrics: null,
        news: [],
        data_as_of: '2026-09-14T15:00:00Z',
        provenance: {
          source_mode: 'live',
          provider: 'akshare',
          market_start_date: '2025-09-14',
          market_end_date: '2026-09-14',
          market_rows: 243,
          news_status: 'empty',
          news_count: 0,
          retrieved_at: '2026-09-14T15:00:00Z',
        },
      },
    },
  }
}
