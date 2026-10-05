import { useEffect, useMemo, useState } from 'react'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import ReactEChartsCore from 'echarts-for-react/esm/core'
import { Link, useParams } from 'react-router-dom'
import { api, formatPct } from '../api'
import ScoreGauge from '../components/ScoreGauge'
import type { Backtest, SignalHistory } from '../types'

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  CanvasRenderer,
])

export default function InstrumentPage() {
  const { symbol = '' } = useParams()
  const [history, setHistory] = useState<SignalHistory | null>(null)
  const [backtest, setBacktest] = useState<Backtest | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([
      api<SignalHistory>(`/signals/${symbol}/history`),
      api<Backtest>(`/backtests/${symbol}`).catch(() => null),
    ]).then(([signals, run]) => { setHistory(signals); setBacktest(run) }).catch((reason) => setError(reason.message))
  }, [symbol])
  const latest = history?.points.at(-1)
  const signalOption = useMemo(() => {
    if (!history) return {}
    const dates = history.points.map((point) => point.date)
    const markLines = [...history.thresholds.buys, ...history.thresholds.sells].map((yAxis) => ({ yAxis, lineStyle: { color: yAxis < 0 ? '#24c68b' : '#ff6a6a', opacity: 0.45, type: 'dashed' } }))
    return {
      animation: false,
      tooltip: { trigger: 'axis', backgroundColor: '#101c2f', borderColor: '#2d3c55', textStyle: { color: '#eef4ff' } },
      legend: { data: ['贪恐指数', '复权价格'], textStyle: { color: '#8fa2bd' }, right: 0 },
      grid: { left: 44, right: 55, top: 40, bottom: 55 },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 10, borderColor: 'transparent', backgroundColor: '#101c2f', fillerColor: 'rgba(92, 110, 255, .18)' }],
      xAxis: { type: 'category', data: dates, boundaryGap: false, axisLine: { lineStyle: { color: '#33435d' } }, axisLabel: { color: '#72849e' } },
      yAxis: [
        { type: 'value', min: -100, max: 100, name: '贪恐', nameTextStyle: { color: '#72849e' }, axisLabel: { color: '#72849e' }, splitLine: { lineStyle: { color: '#1a2940' } } },
        { type: 'value', scale: true, name: history.instrument.currency, nameTextStyle: { color: '#72849e' }, axisLabel: { color: '#72849e' }, splitLine: { show: false } },
      ],
      series: [
        { name: '贪恐指数', type: 'line', symbol: 'none', data: history.points.map((point) => point.score), lineStyle: { width: 2.5, color: '#8b68ff' }, areaStyle: { color: 'rgba(120, 92, 255, .08)' }, markLine: { symbol: 'none', label: { show: false }, data: markLines } },
        { name: '复权价格', type: 'line', yAxisIndex: 1, symbol: 'none', data: history.points.map((point) => point.price), lineStyle: { width: 1.5, color: '#3ea6ff' } },
      ],
    }
  }, [history])
  const equityOption = useMemo(() => {
    if (!backtest) return {}
    return {
      animation: false,
      tooltip: { trigger: 'axis', backgroundColor: '#101c2f', borderColor: '#2d3c55', textStyle: { color: '#eef4ff' } },
      legend: { data: ['策略', 'ETF 买入持有', '基础指数买入持有', '现金'], textStyle: { color: '#8fa2bd' }, right: 0 },
      grid: { left: 48, right: 25, top: 38, bottom: 38 },
      xAxis: { type: 'category', data: backtest.equity_curve.map((row) => row.date), boundaryGap: false, axisLine: { lineStyle: { color: '#33435d' } }, axisLabel: { color: '#72849e' } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#72849e', formatter: (value: number) => `${value.toFixed(1)}×` }, splitLine: { lineStyle: { color: '#1a2940' } } },
      series: [
        { name: '策略', type: 'line', symbol: 'none', data: backtest.equity_curve.map((row) => row.equity), lineStyle: { color: '#5de0a5', width: 2.5 } },
        { name: 'ETF 买入持有', type: 'line', symbol: 'none', data: backtest.equity_curve.map((row) => row.buy_hold), lineStyle: { color: '#677a96', width: 1.5 } },
        { name: '基础指数买入持有', type: 'line', symbol: 'none', data: backtest.equity_curve.map((row) => row.underlying_buy_hold), lineStyle: { color: '#3ea6ff', width: 1.5 } },
        { name: '现金', type: 'line', symbol: 'none', data: backtest.equity_curve.map((row) => row.cash), lineStyle: { color: '#f1b74c', width: 1, type: 'dashed' } },
      ],
    }
  }, [backtest])
  if (error) return <div className="error-banner">{error}</div>
  if (!history) return <div className="empty">正在读取 {symbol}…</div>
  return (
    <>
      <div className="breadcrumb"><Link to="/">信号</Link><span>/</span><span>{history.instrument.symbol}</span></div>
      <section className="instrument-hero">
        <div><span className="eyebrow">{history.instrument.symbol}</span><h1>{history.instrument.name}</h1><p>指标日期 {latest?.date || '—'} · 阈值方法 {history.thresholds.method}</p></div>
        {latest && <ScoreGauge score={latest.score} />}
      </section>
      {latest ? <>
        <section className="factor-grid">
          {[['大盘点位', latest.market_position], ['ETF 点位', latest.etf_position], ['波动', latest.volatility], ['趋势', latest.trend]].map(([label, value]) => <article key={String(label)}><span>{label}</span><strong className={Number(value) < 0 ? 'fear' : 'greed'}>{Number(value).toFixed(1)}</strong><div className="factor-bar"><i style={{ width: `${Math.abs(Number(value)) / 2}%`, marginLeft: Number(value) < 0 ? `${50 - Math.abs(Number(value)) / 2}%` : '50%' }} /></div></article>)}
        </section>
        <section className="panel"><div className="panel-head"><div><h2>价格与贪恐指数</h2><p>双轴仅用于同步观察，两条曲线单位不同；阈值以虚线标示。</p></div><div className="threshold-chips">{history.thresholds.buys.map((value) => <span className="buy" key={value}>{value}</span>)}{history.thresholds.sells.map((value) => <span className="sell" key={value}>+{value}</span>)}</div></div><ReactEChartsCore echarts={echarts} option={signalOption} style={{ height: 430 }} /></section>
      </> : <div className="empty"><strong>尚无信号历史</strong><span>运行一次收盘任务后这里会显示四因子与价格曲线。</span></div>}
      {backtest ? <>
        <section className="section-head"><div><h2>样本外策略验证</h2><p>{backtest.start_date} 至 {backtest.end_date} · 次日开盘成交 · 每边 {backtest.friction_bps} bp</p></div></section>
        <section className="metric-strip backtest-metrics">
          <article><span>累计收益</span><strong>{formatPct(backtest.metrics.total_return)}</strong></article>
          <article><span>年化收益</span><strong>{formatPct(backtest.metrics.cagr)}</strong></article>
          <article><span>最大回撤</span><strong className="fear">{formatPct(backtest.metrics.max_drawdown)}</strong></article>
          <article><span>Calmar</span><strong>{backtest.metrics.calmar?.toFixed(2) || '—'}</strong></article>
          <article><span>Sharpe</span><strong>{backtest.metrics.sharpe?.toFixed(2) || '—'}</strong></article>
          <article><span>卖出胜率</span><strong>{formatPct(backtest.metrics.win_rate)}</strong></article>
          <article><span>成交次数</span><strong>{backtest.metrics.trades || 0}</strong></article>
        </section>
        <section className="panel"><ReactEChartsCore echarts={echarts} option={equityOption} style={{ height: 360 }} /></section>
      </> : <div className="notice">尚未生成回测。至少需要 100 个有效指标日，504 日以上才会尝试个性化阈值。</div>}
    </>
  )
}
