import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { api } from '../api'

type Observation = {
  symbol: string; name: string; version: string; status: string; message: string
  data_date: string | null; expected_date: string | null; weights: Record<string, number>
  latest: { score: number; components: Record<string, number>; contributions: Record<string, number> } | null
  points: { date: string; score: number | null }[]
}
const labels: Record<string, string> = { price_position: '价格位置', momentum: '动量共识', volume_flow: '成交量资金流', volatility_state: '波动状态', urgency: '近期紧迫度' }
const states: Record<string, string> = { ok: '已更新', stale: '行情过期', warning: '质量警告', blocked: '暂停计算', missing: '暂无行情', insufficient: '历史不足' }

export default function SentimentPage() {
  const [instruments, setInstruments] = useState<{ symbol: string; name: string }[]>([])
  const [symbol, setSymbol] = useState('TQQQ')
  const [data, setData] = useState<Observation | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    api<{ symbol: string; name: string }[]>('/instruments').then(value => { if (active) setInstruments(value) }).catch(reason => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [retry])
  useEffect(() => {
    let active = true
    api<Observation>(`/sentiment/${encodeURIComponent(symbol)}`).then(value => { if (active) setData(value) }).catch(reason => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [symbol, retry])
  function reload() { setData(null); setError(''); setRetry(value => value + 1) }
  return <>
    <div className="hero-row"><div><span className="eyebrow">情绪观察 · 研究版</span><h1>看见市场情绪</h1><p>以 ETF 自身量价观察恐惧与贪婪；本页不生成买卖指令。</p></div>
      <div className="sentiment-controls"><label>观察标的<select value={symbol} onChange={event => { setData(null); setError(''); setSymbol(event.target.value) }}>
        {!instruments.length && <option value="TQQQ">TQQQ</option>}
        {instruments.map(item => <option key={item.symbol} value={item.symbol}>{item.symbol} · {item.name}</option>)}
      </select></label><button className="secondary" onClick={reload}>重新读取</button></div>
    </div>
    {error && <div role="alert" className="empty">{error}<button className="secondary" onClick={reload}>重试</button></div>}
    {!data && !error && <div className="empty" role="status">正在计算情绪指数…</div>}
    {data && <>
      <div className={`sentiment-status ${data.status === 'ok' ? '' : 'fear'}`} role="status"><strong>{states[data.status]}</strong> · {data.message}</div>
      <div className="metric-strip">
        <article><span>{data.status === 'stale' ? '历史情绪指数' : '情绪指数'}</span><strong className={data.latest && data.latest.score < 0 ? 'fear' : 'greed'}>{data.latest?.score.toFixed(1) ?? '—'}</strong><small>−100 恐惧 / +100 贪婪</small></article>
        <article><span>行情日期</span><strong className="sentiment-date">{data.data_date ?? '—'}</strong><small>最近收盘日 {data.expected_date ?? '—'}</small></article>
        <article><span>观察标的</span><strong>{data.symbol}</strong><small>{data.name}</small></article>
        <article><span>公式版本</span><strong className="sentiment-version">{data.version}</strong><small>五项固定权重 · 仅供观察</small></article>
      </div>
      {data.points.length > 0 && <section className="sentiment-panel"><h2>情绪历史</h2><p>最近最多 756 个交易日；拖动下方时间条查看，空缺分数不连线。</p><ReactECharts style={{ height: 340 }} option={{ animation: false, tooltip: { trigger: 'axis' }, grid: { left: 45, right: 20, top: 25, bottom: 65 }, xAxis: { type: 'category', data: data.points.map(point => point.date), axisLabel: { color: '#8091aa' } }, yAxis: { type: 'value', min: -100, max: 100, axisLabel: { color: '#8091aa' }, splitLine: { lineStyle: { color: '#203149' } } }, dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 5 }], series: [{ name: '情绪指数', type: 'line', showSymbol: false, connectNulls: false, data: data.points.map(point => point.score), lineStyle: { color: '#9a83ff', width: 2 } }] }} /></section>}
      {data.latest && <section className="sentiment-panel"><h2>五项贡献</h2><p>贡献为分项分数 × 权重；最终指数还经过非线性变换和快降慢升平滑，因此不等于下表贡献之和。</p><div className="sentiment-table"><table><thead><tr><th>分项</th><th>权重</th><th>分数</th><th>线性贡献</th></tr></thead><tbody>{Object.entries(labels).map(([key, label]) => <tr key={key}><td>{label}</td><td>{(data.weights[key] * 100).toFixed(0)}%</td><td>{data.latest!.components[key].toFixed(1)}</td><td className={data.latest!.contributions[key] < 0 ? 'fear' : 'greed'}>{data.latest!.contributions[key].toFixed(1)}</td></tr>)}</tbody></table></div></section>}
    </>}
  </>
}
