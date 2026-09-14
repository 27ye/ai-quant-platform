// 按 docs/API_SPEC.md 的数据格式造 mock，后端接口就绪后 VITE_USE_MOCK_NEWS=false 即可切换
import type { ApiResponse, NewsItem } from '../types/api'

// 行业相关新闻模板池：按 stock_code 首位字符简单分桶，让不同行业显示不同样本
type Pool = { code: string; items: Omit<NewsItem, 'publish_time'>[] }

const POOLS: Pool[] = [
  {
    code: '6',
    items: [
      {
        title: '沪市白酒龙头批价持续稳健，渠道库存处于历史低位',
        summary: '行业跟踪显示，高端白酒终端动销环比改善，经销商信心指数回升至年内高位。',
        source: '财经联社',
        url: 'https://example.com/news/1',
      },
      {
        title: '银行板块息差企稳信号增强，零售业务贡献度提升',
        summary: '多家上市银行三季报显示净息差环比持平，财富管理手续费收入同比双位数增长。',
        source: '上证报',
        url: 'https://example.com/news/2',
      },
      {
        title: '险资权益配置上限上调，长期资金入市预期升温',
        summary: '监管近期表态鼓励险资作为长期资本入市，相关会计准则调整或减轻当期利润波动。',
        source: '证券时报',
        url: 'https://example.com/news/3',
      },
      {
        title: '光伏组件价格触底信号显现，行业产能出清进入下半场',
        summary: '一线厂商反馈 N 型电池片价格已逼近现金成本，二三线产能退出节奏加快。',
        source: '光伏行业协会',
        url: 'https://example.com/news/4',
      },
      {
        title: '央企市值管理考核细化，分红与回购预期持续强化',
        summary: '国资委明确将市值管理纳入负责人业绩考核，高分红央企估值修复逻辑延续。',
        source: '中证报',
        url: 'https://example.com/news/5',
      },
    ],
  },
  {
    code: '0',
    items: [
      {
        title: '深市消费龙头业绩超预期，高端化战略成效显现',
        summary: '公司在最新调研中透露，高端产品占比突破 40%，毛利率创近三年新高。',
        source: '深证资讯',
        url: 'https://example.com/news/6',
      },
      {
        title: '新能源车 9 月销量同环比双增，出口维持高景气',
        summary: '乘联会数据显示 9 月新能源乘用车零售预计同比增长 35%，欧洲出口份额持续提升。',
        source: '乘联会',
        url: 'https://example.com/news/7',
      },
      {
        title: '动力电池行业格局优化，二线厂商订单环比改善',
        summary: '碳酸锂价格企稳带动产业链补库，龙头与二线厂商开工率分化加剧。',
        source: '电池中国',
        url: 'https://example.com/news/8',
      },
      {
        title: '券商板块交投活跃度回升，两融余额重回万亿上方',
        summary: '市场风险偏好修复，9 月以来日均股基成交额同比放大，机构业务贡献边际提升。',
        source: '券商中国',
        url: 'https://example.com/news/9',
      },
      {
        title: '创新药出海案例增多，License-out 金额创历史新高',
        summary: '年内国产创新药对外授权交易金额突破 300 亿美元，BD 能力成为估值新锚。',
        source: '医药魔方',
        url: 'https://example.com/news/10',
      },
    ],
  },
  {
    code: '3',
    items: [
      {
        title: '创业板指领涨主要宽基，成长风格阶段性占优',
        summary: '资金面显示近期融资客加仓成长板块，外资对创业板龙头配置比例回升。',
        source: '创业板观察',
        url: 'https://example.com/news/11',
      },
      {
        title: '储能招标量价齐升，海外大储需求超预期',
        summary: '美国大储三季度装机有望创历史新高，国内厂商订单可见度延伸至 2027 年。',
        source: '储能头条',
        url: 'https://example.com/news/12',
      },
      {
        title: 'AI 应用商业化提速，国产算力链订单能见度提升',
        summary: '多家服务器厂商三季报指引上修，国产 AI 芯片在互联网客户份额持续扩大。',
        source: '半导体行业观察',
        url: 'https://example.com/news/13',
      },
      {
        title: '互联网龙头回购力度加码，股东回报逻辑强化',
        summary: '头部互联网公司年内累计回购金额同比增长，自由现金流持续改善。',
        source: '中概互联研究',
        url: 'https://example.com/news/14',
      },
      {
        title: '锂电材料价格筑底，产业链补库预期升温',
        summary: '碳酸锂期货主力合约连续走强，正极材料厂接货意愿明显改善。',
        source: 'SMM 锂电',
        url: 'https://example.com/news/15',
      },
    ],
  },
]

// 兜底池：未匹配到的 stock_code 走通用财经新闻
const FALLBACK_ITEMS: Omit<NewsItem, 'publish_time'>[] = [
  {
    title: 'A股三大指数集体收涨，北向资金净流入超 50 亿',
    summary: '沪指收复 3200 点关口，行业板块多数飘红，市场情绪显著回暖。',
    source: '新华财经',
    url: 'https://example.com/news/16',
  },
  {
    title: '央行公开市场净投放，资金面边际宽松',
    summary: 'DR007 加权均价回落至政策利率下方，银行间流动性整体充裕。',
    source: '中国货币网',
    url: 'https://example.com/news/17',
  },
  {
    title: '统计局公布 8 月经济数据，工业增加值同比回升',
    summary: '8 月规模以上工业增加值同比增长 4.5%，高于市场预期。',
    source: '国家统计局',
    url: 'https://example.com/news/18',
  },
  {
    title: '证监会研究深化退市改革，强化优胜劣汰机制',
    summary: '监管层强调将持续巩固常态化退市机制，提升上市公司整体质量。',
    source: '证监会发布',
    url: 'https://example.com/news/19',
  },
  {
    title: '国务院常务会议研究稳增长举措，扩大有效投资',
    summary: '会议部署加快专项债发行使用，重点支持基础设施与民生领域。',
    source: '中国政府网',
    url: 'https://example.com/news/20',
  },
]

// 生成最近 N 天的 ISO 时间字符串（毫秒级），保证 mock 刷新数据一致
function buildPublishTimes(count: number, base = new Date('2026-09-11T09:30:00')): string[] {
  const times: string[] = []
  const cursor = new Date(base)
  let step = 0
  while (times.length < count) {
    // 每条间隔几小时到一天，最新一条为 base 时间
    cursor.setHours(cursor.getHours() - step * 7 - 3)
    times.unshift(cursor.toISOString())
    step++
  }
  return times
}

export function mockNews(stockCode: string, limit = 20): ApiResponse<NewsItem[]> {
  const head = stockCode.charAt(0)
  const pool = POOLS.find((item) => item.code === head)?.items ?? FALLBACK_ITEMS
  // 重复池内条目凑到 limit 条上限，让 mock 数据有列表滚动效果
  const raw: Omit<NewsItem, 'publish_time'>[] = []
  let i = 0
  while (raw.length < limit) {
    raw.push(pool[i % pool.length])
    i++
  }
  const times = buildPublishTimes(raw.length)
  const data: NewsItem[] = raw.map((item, idx) => ({
    ...item,
    publish_time: times[idx],
  }))
  return { code: 0, message: 'success', data }
}
