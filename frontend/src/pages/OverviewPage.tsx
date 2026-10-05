import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import ScoreGauge from '../components/ScoreGauge'
import type { LatestSignal } from '../types'

const actionText: Record<string, string> = { hold: '观察', buy: '买入 1/3', add: '继续加仓', reduce: '减仓 1/3', exit: '清仓', data_blocked: '数据阻断' }

export default function OverviewPage() {
  const [items, setItems] = useState<LatestSignal[]>([])
  const [filter, setFilter] = useState<'ALL' | 'US' | 'HK'>('ALL')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  useEffect(() => {
    api<LatestSignal[]>('/signals/latest').then(setItems).catch((reason) => setError(reason.message)).finally(() => setLoading(false))
  }, [])
  const visible = useMemo(() => items.filter((item) => filter === 'ALL' || item.instrument.market === filter), [items, filter])
  const active = items.filter((item) => item.signal && item.signal.action !== 'hold').length
  const fear = items.filter((item) => (item.signal?.score || 0) <= -60).length
  const greed = items.filter((item) => (item.signal?.score || 0) >= 60).length
  async function recompute() {
    setRefreshing(true)
    try { await api('/jobs/recompute', { method: 'POST' }) } finally { setRefreshing(false) }
  }
  return (
    <>
      <section className="hero-row">
        <div><span className="eyebrow">DAILY SIGNALS</span><h1>今天，市场在说什么？</h1><p>收盘后更新 · 交易信号在次一交易日开盘模拟执行</p></div>
        <button className="secondary" onClick={recompute} disabled={refreshing}>{refreshing ? '更新已启动' : '手动更新'}</button>
      </section>
      <section className="metric-strip">
        <article><span>追踪标的</span><strong>{items.length || '—'}</strong><small>美股与港股</small></article>
        <article><span>今日动作</span><strong>{active}</strong><small>非重复提醒</small></article>
        <article><span>恐惧区</span><strong className="fear">{fear}</strong><small>指数 ≤ -60</small></article>
        <article><span>贪婪区</span><strong className="greed">{greed}</strong><small>指数 ≥ 60</small></article>
      </section>
      <section className="section-head">
        <div><h2>信号雷达</h2><p>优先关注距离下一档阈值最近的标的。</p></div>
        <div className="segmented">{(['ALL', 'US', 'HK'] as const).map((value) => <button className={filter === value ? 'active' : ''} onClick={() => setFilter(value)} key={value}>{value === 'ALL' ? '全部' : value}</button>)}</div>
      </section>
      {error && <div className="error-banner">{error}</div>}
      {loading ? <div className="empty">正在读取信号…</div> : visible.every((item) => !item.signal) ? <div className="empty"><strong>等待第一次行情计算</strong><span>点击“手动更新”，或等待收盘后的自动任务。</span></div> : (
        <div className="signal-grid">
          {visible.map((item) => (
            <Link className={`signal-card ${item.signal?.action || 'empty'}`} to={`/instruments/${item.instrument.symbol}`} key={item.instrument.symbol}>
              <div className="card-top"><div><span className="symbol">{item.instrument.symbol}</span><small>{item.instrument.market} · {item.instrument.leverage}×</small></div><span className={`action-pill ${item.signal?.action || ''}`}>{item.signal ? actionText[item.signal.action] || item.signal.action : '待计算'}</span></div>
              <h3>{item.instrument.name}</h3>
              {item.signal ? <>
                <ScoreGauge score={item.signal.score} compact />
                <div className="card-stats"><span><small>收盘价</small><strong>{item.instrument.currency} {item.signal.price.toFixed(2)}</strong></span><span><small>距下一阈值</small><strong>{item.signal.distance_to_threshold.toFixed(1)}</strong></span><span><small>模拟仓位</small><strong>{item.position_steps}/3</strong></span></div>
                <div className="card-foot"><span>{item.signal.date}</span><span className={`confidence ${item.thresholds.confidence}`}>{item.thresholds.confidence} confidence</span></div>
              </> : <div className="card-empty">尚无信号</div>}
            </Link>
          ))}
        </div>
      )}
    </>
  )
}

