import { useEffect, useState } from 'react'
import { api, invalidateStaticSnapshots, staticDesk } from '../api'

type Trade = { date: string; symbol: string; side: string; quantity: number; price: number; fee_hkd: number }
type Account = { activation_date: string; initial_usd: number; cash_usd: number; equity_usd: number; data_date: string; trades: Trade[] }
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
  const money = (n: number) => `$${n.toLocaleString('en-US', {maximumFractionDigits: 2})}`
  return <div className="execution-dashboard"><div className="desk-heading"><h1>账户与对账</h1></div>{error && <div className="desk-alert">{error}</div>}{account && <section className="desk-panel"><h2>方案② · 自动模拟账本</h2><p>启用 {account.activation_date} · 行情 {account.data_date}</p><div className="desk-daily-grid"><div>本金 <strong>{money(account.initial_usd)}</strong></div><div>净值 <strong>{money(account.equity_usd)}</strong></div><div>模拟现金 <strong>{money(account.cash_usd)}</strong></div></div><p className="desk-footnote">模拟使用复权份额、暂按单边0.1%费用。富途实际股数、成交价与费用在对账时确认。</p><div className="desk-table-scroll"><table className="desk-table"><thead><tr><th>日期</th><th>品种</th><th>方向</th><th>复权价格</th><th>模拟份额</th><th>费用</th></tr></thead><tbody>{account.trades.slice().reverse().map((t,i)=><tr key={i}><td>{t.date}</td><td>{t.symbol}</td><td>{t.side==='buy'?'买入':'卖出'}</td><td>{money(t.price)}</td><td>{t.quantity.toFixed(3)}</td><td>{money(t.fee_hkd/7.8)}</td></tr>)}</tbody></table>{!account.trades.length && <p>账户已准备，尚无模拟成交。</p>}</div></section>}</div>
}
