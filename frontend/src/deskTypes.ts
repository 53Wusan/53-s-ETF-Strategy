export type Rule = { buy_score: number; add_drop: number; buy_gap_days: number; sell_score: number; profit_target: number; max_hold_days: number; sell_gap_days: number; reentry_days: number; exit_mode: string; trailing_drop: number; idle_exit_days?: number | null }
export type Metrics = { return_pct: number; max_drawdown_pct: number; ending_equity_hkd: number; trade_count: number; median_lot_hold_days: number | null }
export type Annual = { year: number; return_pct: number; max_drawdown_pct: number; buys: number; sells: number; through: string }
export type Strategy = { id: string; label: string; tags: string[]; description: string; metrics: Metrics; start: string; end: string; capital: { lot_fraction: number; max_lots: number; reserve_hkd: number }; symbols: string[]; rule: Rule; stress2022: Metrics | null; daily_enabled: boolean }
export type StrategyList = { items: Strategy[]; start: string; end: string; default: string; note: string; stale: boolean }
export type StrategyDetail = Strategy & { annual: Annual[]; curve: { date: string; equity_hkd: number }[]; trades: { date: string; symbol: string; side: string; reason: string; price: number; quantity: number; realized_pnl_hkd: number }[] }
export const names: Record<string, string> = { TQQQ: '三倍纳斯达克', FAS: '三倍金融', GDXU: '三倍金矿 ETN', CURE: '三倍医疗', DFEN: '三倍国防航空', TECL: '三倍科技', UPRO: '三倍标普500', EDC: '三倍新兴市场', UGL: '两倍黄金', SOXL: '三倍半导体', CONL: '两倍Coinbase', LABU: '三倍生物科技', NAIL: '三倍房屋建筑', YINN: '三倍中国大盘' }
export const pct = (n: number | null | undefined) => n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
export const hkd = (n: number) => `HK$${n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
export const tone = (n: number) => n < 0 ? 'negative' : 'positive'

export type IndicatorScale = { attainable_min: number; attainable_max: number; smoothing_memory: number; parameters: number[]; display_min: number; display_max: number }
export const scoreBands = [
  { lower: -50, upper: -40, label: '−50～−40' },
  { lower: -40, upper: -20, label: '−40～−20' },
  { lower: -20, upper: 0, label: '−20～0' },
  { lower: 0, upper: 20, label: '0～20' },
  { lower: 20, upper: 40, label: '20～40' },
  { lower: 40, upper: 50, label: '40～50' },
]
export function scoreBandIndex(score: number | null | undefined) {
  if (score == null || !Number.isFinite(score)) return -1
  return scoreBands.findIndex((b, i) => score >= b.lower && (score < b.upper || (i === scoreBands.length - 1 && score === b.upper)))
}
