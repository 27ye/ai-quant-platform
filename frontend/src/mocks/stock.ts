// 按 docs/API_SPEC.md 的数据格式造 mock，后端接口就绪后 VITE_USE_MOCK=false 即可切换
import type {
  ApiResponse,
  BacktestData,
  BacktestRequest,
  IndicatorsItem,
  KlineItem,
  ScoreData,
  StockBrief,
} from '../types/api'

const STOCK_LIST: StockBrief[] = [
  { stock_code: '600519', stock_name: '贵州茅台' },
  { stock_code: '000858', stock_name: '五粮液' },
  { stock_code: '000568', stock_name: '泸州老窖' },
  { stock_code: '600809', stock_name: '山西汾酒' },
  { stock_code: '600036', stock_name: '招商银行' },
  { stock_code: '601318', stock_name: '中国平安' },
  { stock_code: '300750', stock_name: '宁德时代' },
  { stock_code: '002594', stock_name: '比亚迪' },
  { stock_code: '300059', stock_name: '东方财富' },
  { stock_code: '601012', stock_name: '隆基绿能' },
]

export function mockSearch(keyword: string): ApiResponse<StockBrief[]> {
  const kw = keyword.trim()
  const data = kw
    ? STOCK_LIST.filter(
        (item) => item.stock_code.includes(kw) || item.stock_name.includes(kw),
      )
    : STOCK_LIST
  return { code: 0, message: 'success', data }
}

// 固定种子的伪随机数，保证每次刷新数据一致，方便演示和调试
function mulberry32(seed: number) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function buildDates(count: number, endDate = new Date('2026-09-02')): string[] {
  const dates: string[] = []
  const cursor = new Date(endDate)
  while (dates.length < count) {
    const day = cursor.getDay()
    if (day !== 0 && day !== 6) {
      dates.unshift(cursor.toISOString().slice(0, 10))
    }
    cursor.setDate(cursor.getDate() - 1)
  }
  return dates
}

function buildKline(days: number, seed: number, basePrice: number): KlineItem[] {
  const rand = mulberry32(seed)
  const dates = buildDates(days)
  let close = basePrice
  const rows: KlineItem[] = []
  for (const trade_date of dates) {
    const open = close * (1 + (rand() - 0.5) * 0.01)
    const changePct = (rand() - 0.48) * 0.045
    close = open * (1 + changePct)
    const high = Math.max(open, close) * (1 + rand() * 0.012)
    const low = Math.min(open, close) * (1 - rand() * 0.012)
    const volume = Math.round(30000 + rand() * 90000)
    rows.push({
      trade_date,
      open: round2(open),
      high: round2(high),
      low: round2(low),
      close: round2(close),
      volume,
      amount: round2(volume * close * 100),
      turnover_rate: Number((volume / 1_200_000_000).toFixed(4)),
      change_pct: Number(changePct.toFixed(4)),
    })
  }
  return rows
}

function round2(value: number): number {
  return Number(value.toFixed(2))
}

function average(values: number[], count: number): number {
  const slice = values.slice(-count)
  return slice.reduce((sum, value) => sum + value, 0) / slice.length
}

function stdDev(values: number[]): number {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length
  return Math.sqrt(variance)
}

export function mockKline(days = 180): ApiResponse<KlineItem[]> {
  return { code: 0, message: 'success', data: buildKline(days, 20260902, 1350) }
}

export function mockIndicators(): ApiResponse<IndicatorsItem[]> {
  const kline = buildKline(180, 20260902, 1350)
  const data: IndicatorsItem[] = kline.map((row, index) => {
    const closes = kline.slice(0, index + 1).map((item) => item.close)
    const n = closes.length
    const ready = (window: number) => n >= window
    // 模拟预热期：窗口未满时指标为 null，与 C 的真实实现一致
    const ma20 = ready(20) ? average(closes, 20) : null
    const std = ready(20) ? stdDev(closes.slice(-20)) || 1 : null
    return {
      trade_date: row.trade_date,
      ma5: ready(5) ? round2(average(closes, 5)) : null,
      ma10: ready(10) ? round2(average(closes, 10)) : null,
      ma20: ma20 != null ? round2(ma20) : null,
      ma60: ready(60) ? round2(average(closes, 60)) : null,
      // MACD 实际预热约 33 天（EMA12 + EMA26 + DEA9），mock 用 34 天近似
      macd: ready(34) && ma20 != null ? Number(((row.close - ma20) / 8).toFixed(3)) : null,
      macd_signal:
        ready(34) && ma20 != null ? Number(((row.close - ma20) / 10).toFixed(3)) : null,
      macd_hist:
        ready(34) && ma20 != null ? Number(((row.close - ma20) / 40).toFixed(3)) : null,
      rsi14: ready(15) ? Number((35 + (std ?? 1) * 2).toFixed(2)) : null,
      boll_upper: ma20 != null && std != null ? round2(ma20 + 2 * std) : null,
      boll_middle: ma20 != null ? round2(ma20) : null,
      boll_lower: ma20 != null && std != null ? round2(ma20 - 2 * std) : null,
    }
  })
  return { code: 0, message: 'success', data }
}

export function mockScore(stockCode: string): ApiResponse<ScoreData> {
  return {
    code: 0,
    message: 'success',
    data: {
      stock_code: stockCode,
      score: 72,
      trend_score: 30,
      momentum_score: 18,
      volume_score: 12,
      risk_score: 12,
      level: '技术面偏强',
      reasons: [
        '价格站上 MA20，短期趋势偏多',
        'RSI14 处于中性区间，未超买',
        '成交量温和放大，量价配合',
        '近期回撤可控，风险得分中等',
      ],
    },
  }
}

export function mockBacktest(payload: BacktestRequest): ApiResponse<BacktestData> {
  // V3 F5：strategy=macd 用不同种子模拟另一策略的权益路径（后端接线前的契约演示）
  const isMacd = payload.strategy === 'macd'
  const kline = buildKline(180, isMacd ? 20260903 : 20260902, isMacd ? 1280 : 1350)
  const initialCash = payload.parameters?.initial_cash ?? 100000
  // 模拟简单策略：价格涨跌驱动权益，initial_cash 起步的绝对权益
  let equity = initialCash
  const equityCurve = kline.map((row, index) => {
    const prevClose = index > 0 ? kline[index - 1].close : row.close
    equity *= row.close / prevClose
    return {
      trade_date: row.trade_date,
      equity: Number(equity.toFixed(2)),
    }
  })
  const finalEquity = equityCurve[equityCurve.length - 1].equity
  const data: BacktestData = {
    stock_code: payload.stock_code,
    initial_cash: initialCash,
    final_equity: finalEquity,
    total_return: Number((finalEquity / initialCash - 1).toFixed(4)),
    annual_return: 0.21,
    max_drawdown: -0.12,
    sharpe_ratio: 1.36,
    win_rate: 0.54,
    trade_count: 23,
    equity_curve: equityCurve,
  }
  // V2 语义（显式传 parameters）：附记录 ID、语义版本、基准/回撤曲线与成交记录
  if (payload.parameters) {
    const firstClose = kline[0].close
    let peak = -Infinity
    data.backtest_id = isMacd ? 13 : 12
    data.semantics_version = 'v2_windowed'
    data.benchmark_curve = kline.map((row) => ({
      trade_date: row.trade_date,
      benchmark_equity: Number(((row.close / firstClose) * initialCash).toFixed(2)),
    }))
    data.drawdown_curve = equityCurve.map((point) => {
      peak = Math.max(peak, point.equity)
      return {
        trade_date: point.trade_date,
        drawdown: Number((point.equity / peak - 1).toFixed(4)),
      }
    })
    data.trades = [
      {
        order_id: 1,
        signal_date: kline[0].trade_date,
        execution_date: kline[1].trade_date,
        side: 'buy',
        execution_price: kline[1].open,
        shares: Number((initialCash / kline[1].open).toFixed(2)),
        gross_amount: initialCash,
        fee: Number((initialCash * 0.001).toFixed(2)),
        cash_after: 0,
        position_after: 1,
        round_trip_pnl: null,
        round_trip_return: null,
      },
    ]
    data.order_count = 1
  }
  return { code: 0, message: 'success', data }
}
