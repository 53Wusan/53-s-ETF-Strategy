import LiveLedger from '../components/LiveLedger'
export default function TradesPage() {
  return <div className="execution-dashboard"><div className="desk-heading"><div><span className="desk-eyebrow">实盘交易账本</span><h1>把实际成交记清楚。</h1><p>与首页共享同一本实盘账，保存后自动更新组合持仓。</p></div></div><LiveLedger expanded /></div>
}
