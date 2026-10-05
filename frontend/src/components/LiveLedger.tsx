import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, formatMoney } from '../api'
import type { Instrument, Portfolio, Trade } from '../types'
export type RecordIntent = { symbol: string; side: 'buy' | 'sell'; note: string; key: number }
function localTime() { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
export default function LiveLedger({ intent, expanded = false }: { intent?: RecordIntent; expanded?: boolean }) {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [open, setOpen] = useState(expanded || !!intent)
  const [version, setVersion] = useState(0)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false); const [page, setPage] = useState(0)
  const [form, setForm] = useState({ instrument_id: '', side: intent?.side ?? 'buy', quantity: '', price: '', fee: '', currency: 'USD', executed_at: localTime(), note: intent?.note ?? '' })
  useEffect(() => { let live = true
    Promise.all([api<Instrument[]>('/instruments'), api<Trade[]>('/trades?kind=live'), api<Portfolio>('/portfolio?kind=live')]).then(([i, t, p]) => { if (live) { setInstruments(i); setTrades(t); setPortfolio(p); if (intent && version === 0) { const instrument = i.find(x => x.symbol === intent.symbol); if (instrument) setForm(f => ({ ...f, instrument_id: String(instrument.id), currency: instrument.currency })) } } }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [version, intent])
  function selectInstrument(value: string) { const instrument = instruments.find(i => i.id === Number(value)); setForm(f => ({ ...f, instrument_id: value, currency: instrument?.currency ?? 'USD' })) }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (saving) return; setSaving(true); setError(''); setSuccess('')
    try { await api('/trades', { method: 'POST', body: JSON.stringify({ ...form, portfolio_kind: 'live', instrument_id: Number(form.instrument_id), quantity: Number(form.quantity), price: Number(form.price), fee: Number(form.fee || 0), executed_at: new Date(form.executed_at).toISOString() }) }); setSuccess('已保存实盘成交，组合持仓已更新。'); setForm(f => ({ ...f, quantity: '', price: '', fee: '', note: '' })); setVersion(v => v + 1); setOpen(false) }
    catch (e) { setError(e instanceof Error ? e.message : '保存失败') } finally { setSaving(false) }
  }
  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return; const body = new FormData(); body.append('file', file); setError(''); setSuccess(''); setSaving(true)
    try { const result = await api<{ imported: number }>('/trades/import', { method: 'POST', body }); setSuccess(`已导入 ${result.imported} 笔；实盘记录已刷新。`); setVersion(v => v + 1) } catch (e) { setError(e instanceof Error ? e.message : '导入失败') } finally { setSaving(false); event.target.value = '' }
  }
  const selected = instruments.find(i => i.id === Number(form.instrument_id))
  const positions = portfolio?.positions.filter(p => p.quantity > 0) ?? []
  const available = positions.find(p => p.instrument_id === Number(form.instrument_id))?.quantity ?? 0
  return <section className="desk-panel live-ledger" id="live-ledger">
    <div className="desk-section-heading"><div><h2>实盘成交与持仓</h2></div><button className="desk-button" onClick={() => { setOpen(!open); setSuccess('') }}>{open ? '收起录入' : '＋ 记录实盘成交'}</button></div>
    {error && <div className="desk-alert error" role="alert">{error}<button className="desk-link" onClick={() => { setError(''); setVersion(v => v + 1) }}>重新读取</button></div>}{success && <p className="positive" role="status">{success}</p>}
    {open && <form className="desk-record-form" onSubmit={submit}><div className="form-grid"><label>品种<select required value={form.instrument_id} onChange={e => selectInstrument(e.target.value)}><option value="">请选择品种</option>{instruments.map(i => <option value={i.id} key={i.id}>{i.symbol} · {i.name}</option>)}</select></label><label>方向<select value={form.side} onChange={e => setForm({ ...form, side: e.target.value as 'buy' | 'sell' })}><option value="buy">买入</option><option value="sell">卖出</option></select></label><label>实际股数<input required type="number" min="0.000001" step="any" value={form.quantity} onChange={e => setForm({ ...form, quantity: e.target.value })} /></label><label>实际成交价 · {selected?.currency ?? form.currency}<input required type="number" min="0.000001" step="any" value={form.price} onChange={e => setForm({ ...form, price: e.target.value })} /></label><label>实际费用 · {form.currency}<input type="number" min="0" step="any" placeholder="0" value={form.fee} onChange={e => setForm({ ...form, fee: e.target.value })} /></label><label>成交时间 · 本地时间<input type="datetime-local" required value={form.executed_at} onChange={e => setForm({ ...form, executed_at: e.target.value })} /></label><label className="wide">关联方案／备注<input maxLength={500} value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} placeholder="例如：主方案 · 首笔买入" /></label></div>{form.side === 'sell' && <p className="desk-footnote">可卖 {available.toFixed(4)} 股</p>}<button className="desk-primary" disabled={saving}>{saving ? '正在保存…' : '保存实际成交'}</button></form>}
    <div className="desk-position-chips">{!portfolio ? <span>正在读取实盘持仓…</span> : positions.length ? positions.map(p => <span key={p.instrument_id}><b>{p.symbol}</b> {p.quantity.toFixed(3)} 股 · 均价 {p.currency} {p.average_cost.toFixed(2)}<small>估值行情 {p.latest_price_date ?? '缺失'} · <Link to="/portfolio">查看组合</Link></small></span>) : <span>暂无实盘持仓</span>}</div>
    {!!trades.length && <div className="desk-table-scroll"><table className="desk-table"><thead><tr><th>成交时间</th><th>品种／方向</th><th>实际股数</th><th>成交价／费用</th><th>关联方案／备注</th></tr></thead><tbody>{trades.slice(expanded ? page * 30 : 0, expanded ? (page + 1) * 30 : 5).map(t => <tr key={t.id}><td>{new Date(t.executed_at).toLocaleString('zh-CN')}</td><td>{instruments.find(i => i.id === t.instrument_id)?.symbol} <span className={`desk-trade-badge ${t.side}`}>{t.side === 'buy' ? '买入' : '卖出'}</span></td><td>{Number(t.quantity).toFixed(3)}</td><td>{formatMoney(Number(t.price), t.currency)}<small>费用 {formatMoney(Number(t.fee), t.currency)}</small></td><td>{t.note || '—'}</td></tr>)}</tbody></table></div>}
    {expanded && trades.length > 30 && <div className="desk-pagination"><button className="desk-button" disabled={page===0} onClick={()=>setPage(page-1)}>上一页</button><span>{page+1}／{Math.ceil(trades.length/30)}</span><button className="desk-button" disabled={(page+1)*30>=trades.length} onClick={()=>setPage(page+1)}>下一页</button></div>}
    <div className="desk-ledger-links"><Link to="/portfolio" className="desk-link">查看实盘组合 →</Link>{!expanded && <Link to="/trades" className="desk-link">完整成交记录 →</Link>}{expanded && <label className="desk-button csv-import">导入成交 CSV<input disabled={saving} type="file" accept=".csv,text/csv" onChange={importCsv} /></label>}</div>
  </section>
}

