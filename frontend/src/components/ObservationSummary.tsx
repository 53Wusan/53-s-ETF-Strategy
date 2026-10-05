import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
type Observation = { status: string; message: string; data_date: string | null; latest: { score: number; components: { key: string; weight: number; value: number; contribution: number }[] } | null }
const labels: Record<string, string> = { price_position: '价格位置', momentum: '动量共识', volume_flow: '量价资金流', volatility_state: '波动状态', urgency: '近期紧迫度' }
export default function ObservationSummary({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Observation | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { const controller = new AbortController(); api<Observation>(`/desk/observation/${symbol}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setData(value) }).catch(e => { if (!controller.signal.aborted) setError(e.message) }); return () => controller.abort() }, [symbol])
  return <details className="desk-observation"><summary>五项量价观察 · 辅助模型 <span>价格位置 · 动量 · 资金流 · 波动 · 紧迫度</span></summary><p className="desk-footnote">独立于上方交易指数，不参与买卖规则。 <Link className="desk-link" to="/method">查看关系 →</Link></p>{error ? <p role="alert">{error}</p> : !data ? <p>正在读取五项观察…</p> : data.latest ? <><div className="desk-five-factors">{data.latest.components.map(c => <div key={c.key}><span>{labels[c.key]} · {Math.round(c.weight * 100)}%</span><strong className={c.contribution < 0 ? 'negative' : 'positive'}>{c.contribution > 0 ? '+' : ''}{c.contribution.toFixed(1)}</strong><small>分项 {c.value.toFixed(1)}</small></div>)}</div><p className="desk-footnote">{data.data_date} · 五项观察指数 {data.latest.score.toFixed(1)} · {data.status === 'stale' ? '历史数据，非当前信号' : '辅助观察'}</p></> : <p>{data.message}</p>}</details>
}


