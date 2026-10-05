import { useEffect, useState } from 'react'
import { api, formatMoney } from '../api'
import type { Portfolio } from '../types'

export default function PortfolioPage() {
  const [data, setData] = useState<Portfolio | null>(null)
  const [kind, setKind] = useState<'all' | 'paper' | 'live'>('live')
  const [error, setError] = useState('')
  useEffect(() => {
    const suffix = kind === 'all' ? '' : `?kind=${kind}`
    api<Portfolio>(`/portfolio${suffix}`).then(setData).catch((reason) => setError(reason.message))
  }, [kind])
  return (
    <div className="execution-dashboard">
      <section className="desk-heading"><div><span className="desk-eyebrow">账户组合</span><h1>策略和实盘，分开看清。</h1><p>所有原币成交保留原值，汇总按最新可用汇率折算。</p></div><div className="segmented">{(['all', 'paper', 'live'] as const).map((value) => <button key={value} aria-pressed={kind === value} className={kind === value ? 'active' : ''} onClick={() => setKind(value)}>{value === 'all' ? '合并' : value === 'paper' ? '模拟' : '实盘'}</button>)}</div></section>
      {error && <div className="error-banner">{error}</div>}
      {!data ? <div className="empty">正在计算组合…</div> : <>
        {data.missing_fx.length > 0 && <div className="notice">缺少 {data.missing_fx.join('、')} → {data.base_currency} 汇率，对应持仓未计入汇总。</div>}
        <section className="metric-strip portfolio-metrics">
          <article><span>持仓市值</span><strong>{formatMoney(data.totals.market_value, data.base_currency)}</strong></article>
          <article><span>持仓成本</span><strong>{formatMoney(data.totals.cost, data.base_currency)}</strong></article>
          <article><span>未实现盈亏</span><strong className={data.totals.unrealized < 0 ? 'fear' : 'greed'}>{formatMoney(data.totals.unrealized, data.base_currency)}</strong></article>
          <article><span>已实现盈亏</span><strong className={data.totals.realized < 0 ? 'fear' : 'greed'}>{formatMoney(data.totals.realized, data.base_currency)}</strong></article>
        </section>
        <section className="desk-panel table-panel"><div className="desk-section-heading"><div><h2>当前持仓</h2><p>价格日期和币种始终可见，避免把不同市场数据混在一起。</p></div></div>
          {data.positions.length === 0 ? <div className="empty small">暂无成交记录</div> : <div className="table-scroll"><table><thead><tr><th>账本</th><th>标的</th><th>数量</th><th>均价</th><th>最新价</th><th>市值</th><th>未实现</th><th>数据日</th></tr></thead><tbody>{data.positions.map((position) => <tr key={`${position.portfolio_kind}-${position.instrument_id}`}><td><span className={`book ${position.portfolio_kind}`}>{position.portfolio_kind === 'paper' ? '模拟' : '实盘'}</span></td><td><strong>{position.symbol}</strong><small>{position.name}</small></td><td>{position.quantity.toFixed(4)}</td><td>{position.currency} {position.average_cost.toFixed(2)}</td><td>{position.last_price.toFixed(2)}</td><td>{position.market_value.toFixed(2)}</td><td className={position.unrealized_pnl < 0 ? 'fear' : 'greed'}>{position.unrealized_pnl.toFixed(2)}</td><td>{position.latest_price_date || '—'}</td></tr>)}</tbody></table></div>}
        </section>
      </>}
    </div>
  )
}

