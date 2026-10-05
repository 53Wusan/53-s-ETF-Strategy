import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { IndicatorScale, Strategy, StrategyList } from '../deskTypes'

type Model = { indicator_scale: IndicatorScale }
const factors = [
  ['价格位置', '30%', '21／60／252日高低区间位置，加上价格自身分位'],
  ['动量共识', '20%', 'RSI6／14／21，加上MACD相对波动的强弱'],
  ['量价资金流', '25%', '5／20日涨跌成交量平衡，加上20日Chaikin量价资金流'],
  ['波动状态', '10%', 'ATR波动率自身分位取反：波动越高，越偏恐惧'],
  ['近期紧迫度', '15%', '短期涨跌、距近期高点的回撤，以及开盘跳空'],
]
function RuleCard({ strategy }: { strategy: Strategy }) {
  const r = strategy.rule
  return <article className="desk-panel method-rule"><h3>{strategy.label}</h3><dl>
    <div><dt>首笔</dt><dd>指数≤{r.buy_score}，每笔初始本金的{strategy.capital.lot_fraction * 100}%。</dd></div>
    <div><dt>加仓</dt><dd>指数仍≤{r.buy_score}，相对上一笔成交价再跌{r.add_drop * 100}%，且距上一笔买入至少{r.buy_gap_days}自然日；三个条件同时满足。</dd></div>
    <div><dt>卖出</dt><dd>{r.exit_mode === 'trail' ? <>指数≥{r.sell_score}或持仓盈利≥{r.profit_target * 100}%时启动保护；收盘价较本轮持仓参考高点回撤{r.trailing_drop * 100}%才卖一笔，触及门槛当天不一定卖。</> : <>指数≥{r.sell_score}或持仓盈利≥{r.profit_target * 100}%先卖一笔；之后每再多盈利10个百分点，或较本轮持仓参考高点回撤{r.trailing_drop * 100}%，再卖一笔。</>}</dd></div>
    <div><dt>期限</dt><dd>距本轮第一笔买入{r.max_hold_days}自然日后开始逐笔退出；正常卖出至少间隔{r.sell_gap_days}自然日，清仓后至少{r.reentry_days}自然日才再入场。{r.idle_exit_days ? `无操作满${r.idle_exit_days}自然日且持仓收益在±5%内，也会退出一笔。` : ''}</dd></div>
    <div><dt>仓位</dt><dd>单只累计投入本金最多{strategy.capital.max_lots * strategy.capital.lot_fraction * 100}%，组合最多5只，预留HK$120,000；现金不足就跳过。每笔比例按初始HK$500,000计算，不随净值复利放大。</dd></div>
  </dl></article>
}
export default function MethodPage() {
  const [model, setModel] = useState<Model | null>(null)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [error, setError] = useState('')
  useEffect(() => { const controller = new AbortController()
    Promise.all([api<Model>('/execution/catalog?profile=rank2', { signal: controller.signal }), api<StrategyList>('/desk/strategies', { signal: controller.signal })]).then(([m, s]) => { if (!controller.signal.aborted) { setModel(m); setStrategies(s.items.filter(x => x.daily_enabled)) } }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [])
  const scale = model?.indicator_scale
  const p = scale?.parameters
  return <div className="execution-dashboard method-page">
    <div className="desk-heading"><div><span className="desk-eyebrow">读懂指数，再看操作</span><h1>计算说明</h1><p>交易指数 → 策略条件 → 次日计划；五项量价观察是独立的辅助模型。</p></div><Link className="desk-link" to="/">返回看板 →</Link></div>
    {error && <div className="desk-alert error" role="alert">{error}</div>}
    <section className="desk-panel"><h2>首页指数是怎么来的？</h2><p>它是每只ETF自己的价格与动量指标，使用日线收盘数据，不是盘中实时行情，也没有读取新闻或宏观风险。</p>
    <div className="method-inputs"><article><b>① 21日价格位置 · X</b><p>把复权收盘价放在最近21个交易日的复权最高／最低价之间：靠近低点为负，靠近高点为正，统一到−100～+100。</p></article><article><b>② RSI14自身分位 · R</b><p>计算14日RSI，再比较它在自身近252个交易日里的位置：越靠近历史低位越负，越靠近高位越正，统一到−100～+100。</p></article></div>
    {p ? <div className="method-formula"><span>当前冻结参数 · 来自实际运行配置</span><code>当日输入 D = {p[0].toFixed(6)} + {p[1].toFixed(6)} × X/100 + {p[3].toFixed(6)} × R/100</code><code>平滑值 L = {(1 - p[4]).toFixed(6)} × D + {p[4].toFixed(6)} × 昨日L</code><code>交易指数 = 100 × tanh(L)，最后限制在−99～+99</code><small>tanh将数值平滑压缩。递推初值为0；另有252日价格位置项，但当前权重为0。两项有效系数没有归一化到总和1。</small></div> : <p className="desk-footnote">{error ? '参数未读取成功，暂不展示数值。' : '正在读取计算参数…'}</p>}
    <p>平滑用昨天的状态减少来回跳动；最终分数来自已发生的价格变化，不等于未来涨跌概率，也不直接等于历史百分位。</p></section>
    <section className="desk-panel"><h2>为什么显示−50～+50？</h2><p>{scale ? `当前参数的理论可达范围约为${scale.attainable_min.toFixed(2)}～+${scale.attainable_max.toFixed(2)}。` : '当前参数可达范围比±99窄。'}两项输入系数合计约0.493，平滑不会扩大这个范围，tanh又进一步压缩，所以当前模型不会触及±99。首页图表使用−50～+50刻度，原始分数和策略门槛保持一致。</p>
    <div className="desk-table-scroll"><table className="desk-table"><thead><tr><th>方式</th><th>含义与影响</th></tr></thead><tbody><tr><td>保留±50显示 · 当前采用</td><td>贴近实际波动范围，旧回测、0／20买卖门槛都可直接对照。</td></tr><tr><td>只放大显示到±99</td><td>正负两侧分别按理论上限缩放，可映射到±99；排序与信息量不变。当前原始+20约显示为+{scale ? (20 * 99 / scale.attainable_max).toFixed(1) : '44.2'}，阈值也必须同步换算。</td></tr><tr><td>改变权重或非线性强度</td><td>改变模型本身，需要重新验证策略，不能把旧收益直接移过来。</td></tr></tbody></table></div>
    <p className="desk-footnote">只放大显示不会更准确；为避免两套分数混淆，目前没有启用±99显示转换。</p></section>
    <section className="desk-panel"><h2>指数区间、历史分位，有什么区别？</h2><p>区间回答“现在分数在哪里”，例如+30落在20～40。分布卡片显示所选历史窗口中，每个区间出现的天数比例，当前区间只有一张高亮。</p><p>历史分位回答“相对自己过去有多高”：当前值≥多少比例的历史有效分数。比如分位90%表示处于这段历史的顶部约10%，并不表示股价会下跌90%。切换100日／1年／600日，分位与区间占比会改变，当前指数不变。</p><p>主方案与短周期目前按原始指数0／20判断；GDXU十分位研究方案按自身600日历史分位进出，两者不能混用。历史分布包含所选窗口的最新有效日，仅用于展示。</p></section>
    <section className="desk-panel"><h2>五项量价观察与它有什么关联？</h2><p>两者都来自同一只ETF的复权OHLCV日线，会共享部分价格位置和RSI信息，但公式、权重与平滑方式不同。五项观察不是首页交易指数的拆解，也不参与每日买卖。</p><div className="desk-table-scroll"><table className="desk-table"><thead><tr><th>辅助分项</th><th>权重</th><th>观察什么</th></tr></thead><tbody>{factors.map(([name, weight, detail]) => <tr key={name}><td>{name}</td><td>{weight}</td><td>{detail}</td></tr>)}</tbody></table></div><p>五项先加权，经过100 × tanh(加权值／50)压缩，再平滑：向恐惧变化时采用55%新值，向恢复变化时采用25%新值。因此，同一天辅助指数与交易指数可能差很多。</p></section>
    <section className="method-rules"><h2>每日计划怎样由指数变成买卖？</h2><p>下方读取网页保留方案的实际参数。参考高点取首笔开盘价与持仓期间历次收盘价的最高值。收盘后检查条件，生成下一交易日开盘的模拟计划；过期行情暂停展示操作。实盘记录独立录入。</p>{strategies.map(strategy => <RuleCard key={strategy.id} strategy={strategy} />)}<p className="desk-footnote">回测假设：复权开盘价、可用零碎股、单边成本0.1%、固定汇率7.8、现金利息0。实盘以实际成交、费用和可用现金为准。指数模型的冻结参数文件与执行方案不同，执行规则以下方方案为准。</p><Link className="desk-link" to="/research">查看各方案回测 →</Link></section>
  </div>
}
