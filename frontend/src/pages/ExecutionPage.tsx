import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, invalidateStaticSnapshots, staticDesk } from '../api'
import LiveLedger from '../components/LiveLedger'
import type { RecordIntent } from '../components/LiveLedger'
import ObservationSummary from '../components/ObservationSummary'
import { names, pct, tone, scoreBands, scoreBandIndex } from '../deskTypes'
import type { Rule } from '../deskTypes'
const DeskChart = lazy(() => import('../components/DeskChart'))
type Item = { symbol: string; date: string; score: number | null; raw_close: number | null; adjusted_close: number; price_change_pct: number; phase: string; position: { lots: number } | null }
type Order = { symbol: string; side: 'buy' | 'sell'; reason: string }
type Catalog = { buy_budget_usd?: number; cutoff: string; last_completed_session: string; stale: boolean; items: Item[]; rule: Rule; simulation_account?: { cash_hkd: number; position_count: number } | null; next_open_plan: { signal_date: string; next_open_date: string; actions: Order[] } | null }
type History = { observations: number; distribution: { threshold: number; operator: string; count: number; pct: number | null }[]; points: { date: string; price: number; score: number | null }[] }
const pool = ['TQQQ','FAS','GDXU','CURE','DFEN','TECL','UPRO','EDC','UGL']
export default function ExecutionPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [profile, setProfile] = useState('rank2')
  const [focus, setFocus] = useState('TQQQ')
  const [windowDays, setWindowDays] = useState(600)
  const [history, setHistory] = useState<History | null>(null)
  const [all, setAll] = useState(false)
  const [error, setError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [revision, setRevision] = useState(0)
  const [intent, setIntent] = useState<RecordIntent>(); const intentCounter = useRef(0)
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
  useEffect(() => {
    const controller = new AbortController()
    api<Catalog>(`/execution/catalog?profile=${profile}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setCatalog(value) }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [profile, revision])
  useEffect(() => {
    const controller = new AbortController()
    api<History>(`/execution/history/${focus}?limit=${windowDays}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setHistory(value) }).catch(e => { if (!controller.signal.aborted) setHistoryError(e.message) })
    return () => controller.abort()
  }, [focus, windowDays, revision])
  async function refresh() {
    setRefreshing(true); setError('')
    try { if (staticDesk) { window.location.reload(); return } await api('/execution/refresh', { method: 'POST' }); setRevision(v => v + 1) }
    catch (e) { setError(e instanceof Error ? e.message : '行情更新未完成') } finally { setRefreshing(false) }
  }
  function record(symbol: string, side: 'buy' | 'sell') {
    setIntent({ symbol, side, note: `${profile === 'rank2' ? '主方案 · 恐惧分批／回撤保护' : '短周期 · 分档兑现'} · 手工核对实际成交`, key: ++intentCounter.current })
    document.getElementById('live-ledger')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const item = catalog?.items.find(i => i.symbol === focus)
  const currentBand = scoreBandIndex(item?.score)
  const validScores = history?.points.map(p => p.score).filter((score): score is number => score != null && Number.isFinite(score)) ?? []
  const bandCounts = scoreBands.map((_, index) => validScores.filter(score => scoreBandIndex(score) === index).length)
  const currentRank = item?.score != null && validScores.length ? 100 * validScores.filter(score => score <= item.score!).length / validScores.length : null
  const plan = catalog && !catalog.stale ? catalog.next_open_plan : null
  const orders = plan?.actions ?? []
  const chart = useMemo(() => history ? {
    animation: false, color: ['#2875ed','#8d46ec'], tooltip: { trigger: 'axis' }, legend: { top: 0, data: ['复权股价 · USD','交易贪恐指数'] },
    grid: { left: 56, right: 46, top: 44, bottom: 62 }, xAxis: { type: 'category', boundaryGap: false, data: history.points.map(p => p.date), axisLabel: { hideOverlap: true } },
    yAxis: [{ type: 'value', scale: true, splitLine: { show: false } },{ type: 'value', min: -50, max: 50, splitLine: { lineStyle: { color: '#edf0f6' } } }], dataZoom: [{ type: 'inside' },{ type: 'slider', height: 20, bottom: 5 }],
    series: [{ name: '复权股价 · USD', type: 'line', showSymbol: false, lineStyle: { width: 2.2 }, data: history.points.map(p => p.price) },{ name: '交易贪恐指数', type: 'line', yAxisIndex: 1, showSymbol: false, connectNulls: false, data: history.points.map(p => p.score), lineStyle: { width: 2 }, markArea: { silent: true, data: [[{ yAxis: -50, itemStyle: { color: 'rgba(30,150,107,.12)' } },{ yAxis: -20 }],[{ yAxis: 20, itemStyle: { color: 'rgba(228,83,99,.12)' } },{ yAxis: 50 }]] }, markLine: { silent: true, symbol: 'none', data: [catalog?.rule.buy_score ?? 0,catalog?.rule.sell_score ?? 20].map(yAxis => ({ yAxis })) } }],
  } : null, [history,catalog?.rule])
  return <div className="execution-dashboard">
    <div className="desk-heading"><div><span className="desk-eyebrow">53 · 每日策略台</span><h1>今天，做哪一笔？</h1></div><button className="desk-button" disabled={refreshing} onClick={refresh}>{refreshing ? '正在更新…' : '↻ 检查最新行情'}</button></div>
    {error && <div className="desk-alert error" role="alert">{error}<button className="desk-link" onClick={() => setRevision(v => v + 1)}>重试读取</button></div>}
    <section className="desk-panel daily-operations"><div className="desk-section-heading"><div><h2>每日操作 <small className="desk-plan-badge">模拟计划</small></h2><p>{catalog ? `收盘 ${catalog.cutoff} · ${plan ? `执行 ${plan.next_open_date}` : '等待核对'}` : '正在读取最新完整收盘…'}</p></div><label className="desk-profile"><select aria-label="每日参考方案" value={profile} onChange={e => { setCatalog(null); setError(''); setProfile(e.target.value) }}><option value="rank2">主方案 · 恐惧分批／回撤保护</option>{!staticDesk && <option value="short">短周期 · 分档兑现／30日</option>}</select></label></div>
    {catalog?.stale ? <div className="desk-alert"><strong>操作暂停：行情未更新</strong><span>本地 {catalog.cutoff}，最近完整交易日 {catalog.last_completed_session}。</span></div> : catalog && !plan ? <div className="desk-alert"><strong>操作暂停：方案与行情日期尚未对齐</strong></div> : catalog && plan && !orders.length ? <div className="desk-no-orders"><strong>今日暂无买卖计划</strong><span>买入 0 · 卖出 0</span></div> : <div className="desk-daily-grid">{(['buy','sell'] as const).map(side => { const rows = orders.filter(o => o.side === side); return <div className={`desk-action-box ${side}`} key={side}><h3>{side === 'buy' ? '买入／加仓' : '卖出／减仓'} <small>{rows.length} 笔</small></h3>{!catalog ? <p>正在核对…</p> : !rows.length ? <p>暂无计划</p> : rows.map(o => <div className="desk-order" key={o.symbol}><div><b>{o.symbol}</b><span>{o.reason}</span><small>{side === 'buy' ? catalog?.buy_budget_usd ? `一笔预算 $${catalog.buy_budget_usd.toLocaleString('en-US')}` : '一笔预算 HK$25,000' : '卖出一笔持仓'}</small></div>{!staticDesk && <button className="desk-button" onClick={() => record(o.symbol, side)}>记录已成交</button>}</div>)}</div> })}</div>}
    {catalog && <Link className="desk-link desk-plan-link" to={`/research?strategy=${profile}`}>方案规则与回测 →</Link>}
    </section>
    <div className="desk-section-heading compact-heading"><h2>指数看板 <small>收盘 {catalog?.cutoff ?? '—'}</small></h2><button className="desk-link" onClick={() => setAll(!all)}>{all ? '只看9只关注品种' : '展开其他品种'}</button></div>
    {!catalog && !error && <div className="desk-empty">正在读取品种看板…</div>}
    <div className="desk-watch-grid">{catalog?.items.filter(i => all || pool.includes(i.symbol)).map(i => <button key={i.symbol} className={`desk-watch-tile ${focus === i.symbol ? 'selected' : ''}`} onClick={() => { if (focus !== i.symbol) { setHistory(null); setHistoryError(''); setFocus(i.symbol) } }} aria-pressed={focus === i.symbol}><div><b>{i.symbol}</b><small>{names[i.symbol]}</small></div><strong className="violet">{i.score == null ? '—' : i.score.toFixed(1)}</strong><div><span>${(i.raw_close ?? i.adjusted_close).toFixed(2)}</span><small className={tone(i.price_change_pct)}>{pct(i.price_change_pct)}</small></div></button>)}</div>
    {!staticDesk && <LiveLedger key={intent?.key ?? 0} intent={intent} />}
    {item && <section className="desk-panel" id="index-history"><div className="desk-section-heading"><div><span className="desk-eyebrow">{focus} · {names[focus]}</span><h2>历史指数与价格</h2><p>交易指数 {item.score?.toFixed(1) ?? '—'} · {item.phase} · {item.position ? `${item.position.lots}笔模拟持仓` : '模拟空仓'}</p></div><div className="desk-range-buttons">{[{ n: 100, text: '100日' },{ n: 252, text: '1年' },{ n: 600, text: '600日' },{ n: 0, text: '全部' }].map(w => <button key={w.n} className={windowDays === w.n ? 'active' : ''} onClick={() => { if (windowDays !== w.n) { setHistory(null); setHistoryError(''); setWindowDays(w.n) } }}>{w.text}</button>)}</div></div>
    {historyError ? <div className="desk-alert error" role="alert">{historyError}<button className="desk-link" onClick={() => setRevision(v => v + 1)}>重试</button></div> : chart ? <Suspense fallback={<div className="desk-empty">正在绘制历史曲线…</div>}><DeskChart option={chart} /></Suspense> : <div className="desk-empty">正在读取 {focus} 历史…</div>}
    <details open className="desk-rule-details"><summary>查看指数分布 · {validScores.length}个有效交易日</summary>
    <div className="desk-current-score"><strong>{focus} · {item.score == null ? '指数缺失' : `最新收盘 ${item.score.toFixed(1)}`}</strong><span>{item.date}{catalog?.stale ? ' · 行情待更新' : ''}{currentRank != null ? ` · 历史分位 ${currentRank.toFixed(1)}%` : ''}</span></div>
    <div className="desk-distribution">{scoreBands.map((band, index) => <div className={`desk-bin ${index < 3 ? 'fear-band' : 'greed-band'} ${index === currentBand ? 'current' : ''}`} key={band.lower} aria-current={index === currentBand ? 'true' : undefined}><span>{band.label}{index === currentBand && <b className="desk-current-label">当前</b>}</span><strong>{validScores.length ? (100 * bandCounts[index] / validScores.length).toFixed(1) : '—'}%</strong><small>{bandCounts[index]}天</small></div>)}</div><div className="desk-distribution-footer"><span>各区间独立统计 · 左含右不含，最后一档含50</span><Link className="desk-link" to="/method">指数怎么计算？ →</Link></div></details>
    <ObservationSummary key={`${focus}-${revision}`} symbol={focus} />
    {!staticDesk && <div className="desk-ledger-links"><button className="desk-link" onClick={() => record(focus, 'buy')}>记录 {focus} 实际买入</button><button className="desk-link" onClick={() => record(focus, 'sell')}>记录 {focus} 实际卖出</button><Link to="/research" className="desk-link">保留方案与回测 →</Link></div>}
    </section>}
  </div>
}



