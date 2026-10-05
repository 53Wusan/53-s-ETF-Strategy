export type Thresholds = {
  buys: number[]
  sells: number[]
  confidence: 'low' | 'medium' | 'high'
  method: string
  validation_metrics?: Record<string, number | string>
}

export type LatestSignal = {
  instrument: {
    id: number
    symbol: string
    name: string
    market: 'US' | 'HK'
    currency: string
    leverage: number
  }
  signal: null | {
    date: string
    price: number
    score: number
    market_position: number
    etf_position: number
    volatility: number
    trend: number
    action: string
    reason: string
    quality_status: string
    next_threshold: number
    distance_to_threshold: number
  }
  thresholds: Thresholds
  position_steps: number
  pending_delta: number
}

export type SignalHistory = {
  instrument: { id: number; symbol: string; name: string; currency: string }
  thresholds: Thresholds
  points: Array<{
    date: string
    price: number
    score: number
    market_position: number
    etf_position: number
    volatility: number
    trend: number
    action: string
    reason: string
  }>
}

export type Backtest = {
  symbol: string
  start_date: string
  end_date: string
  friction_bps: number
  parameters: Record<string, unknown>
  metrics: Record<string, number>
  equity_curve: Array<{ date: string; equity: number; buy_hold: number; underlying_buy_hold: number; cash: number; position: number }>
  completed_at: string
}

export type Instrument = {
  id: number
  symbol: string
  name: string
  market: string
  currency: string
  leverage: number
  latest_bar_date: string | null
  data_status: string
}

export type Trade = {
  id: number
  instrument_id: number
  portfolio_kind: 'paper' | 'live'
  side: 'buy' | 'sell'
  quantity: number
  price: number
  fee: number
  currency: string
  executed_at: string
  note: string
  source: string
}

export type Portfolio = {
  base_currency: string
  totals: Record<'market_value' | 'cost' | 'realized' | 'unrealized' | 'fees', number>
  positions: Array<{
    portfolio_kind: string
    instrument_id: number
    symbol: string
    name: string
    currency: string
    quantity: number
    average_cost: number
    last_price: number
    market_value: number
    realized_pnl: number
    unrealized_pnl: number
    fees: number
    latest_price_date: string | null
  }>
  missing_fx: string[]
}
