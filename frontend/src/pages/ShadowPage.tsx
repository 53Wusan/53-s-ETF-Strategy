import { useEffect, useState } from 'react'
import { api, invalidateStaticSnapshots, staticDesk } from '../api'

type Trade = { date: string; symbol: string; side: string; quantity: number; price: number; fee_hkd: number }
type Position = { quantity: number; cost_hkd: number; market_value_hkd: number; pnl_hkd: number; profit_pct: number }
type Account = { activation_date: string; initial_usd: number; cash_usd: number; equity_usd: number; data_date: string; trades: Trade[]; positions: Record<string, Position> }
const fx = 7.8 // The existing ledger stores position amounts in HKD at this fixed conversion.
const money = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const signedMoney = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${money(Math.abs(n))}`
const signedPercent = (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
export default function ShadowPage() {
  const [account, setAccount] = useState<Account | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => { api<Account>('/account').then(setAccount).catch(e => setError(e.message)) }, [revision])
  useEffect(() => {
    if (!staticDesk) return
    const check = () => {
      if (document.visibilityState !== 'visible') return
      invalidateStaticSnapshots()
      setRevision(value => value + 1)
    }
    const timer = window.setInterval(check, 5 * 60 * 1000)
    document.addEventListener('visibilitychange', check)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', check) }
  }, [])
  const positions = Object.entries(account?.positions ?? {}).filter(([, p]) => p.quantity > 0)
  const profit = account ? account.equity_usd - account.initial_usd : 0
  const returnPct = account && account.initial_usd > 0 ? profit / account.initial_usd * 100 : 0
  const marketValue = positions.reduce((sum, [, p]) => sum + p.market_value_hkd / fx, 0)
  return <div className="execution-dashboard">
    <div className="desk-heading"><h1>账户与对账</h1></div>
    {error && <div className="desk-alert">{error}</div>}
    {account && <section className="desk-panel">
      <h2>方案② · 自动模拟账本</h2>
      <p>启用 {account.activation_date} · 截至 {account.data_date} 美股收盘 · 金额均为美元</p>
      <div className="desk-summary">
        <article><span>当前现金</span><strong>{money(account.cash_usd)}</strong><small>可用模拟资金</small></article>
        <article><span>持仓市值</span><strong>{money(marketValue)}</strong><small>{positions.length} 只 ETF · 仓位 {account.equity_usd > 0 ? (marketValue / account.equity_usd * 100).toFixed(1) : '0.0'}%</small></article>
        <article><span>账户总资产</span><strong>{money(account.equity_usd)}</strong><small>初始本金 {money(account.initial_usd)}</small></article>
        <article><span>累计盈亏</span><strong className={profit >= 0 ? 'positive' : 'negative'}>{signedMoney(profit)}</strong><small>收益率 {signedPercent(returnPct)} · 已计模拟交易费用</small></article>
      </div>
      <h3>当前持仓</h3>
      <div className="desk-table-scroll"><table className="desk-table">
        <thead><tr><th>品种</th><th>模拟份额</th><th>持仓成本</th><th>当前市值</th><th>浮动盈亏</th><th>盈亏比例</th></tr></thead>
        <tbody>{positions.map(([symbol, p]) => <tr key={symbol}>
          <td>{symbol}</td><td>{p.quantity.toFixed(3)}</td><td>{money(p.cost_hkd / fx)}</td><td>{money(p.market_value_hkd / fx)}</td>
          <td className={p.pnl_hkd >= 0 ? 'positive' : 'negative'}>{signedMoney(p.pnl_hkd / fx)}</td>
          <td className={p.pnl_hkd >= 0 ? 'positive' : 'negative'}>{signedPercent(p.profit_pct)}</td>
        </tr>)}</tbody>
      </table>{!positions.length && <p>当前空仓，资金全部为现金。</p>}</div>
      <p className="desk-footnote">市值按上述日期收盘行情计算。累计盈亏为总资产减初始本金，包含已实现和持仓浮动盈亏；模拟使用复权份额，暂按单边 0.1% 费用。富途实际股数、成交价与费用在对账时确认。</p>
      <h3>成交记录</h3>
      <div className="desk-table-scroll"><table className="desk-table"><thead><tr><th>日期</th><th>品种</th><th>方向</th><th>复权价格</th><th>模拟份额</th><th>费用</th></tr></thead><tbody>{account.trades.slice().reverse().map((t,i)=><tr key={i}><td>{t.date}</td><td>{t.symbol}</td><td>{t.side==='buy'?'买入':'卖出'}</td><td>{money(t.price)}</td><td>{t.quantity.toFixed(3)}</td><td>{money(t.fee_hkd/fx)}</td></tr>)}</tbody></table>{!account.trades.length && <p>账户已准备，尚无模拟成交。</p>}</div>
    </section>}
  </div>
}
