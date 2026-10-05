import { useState } from 'react'
import { unlockDesk } from '../api'

export default function UnlockPage({ onUnlock }: { onUnlock: () => void }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <div className="login-page"><div className="login-copy"><span className="brand-mark large">L</span><h1>每天，做好一笔。</h1></div><form className="login-card" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(''); try { await unlockDesk(password); onUnlock() } catch (e) { setError(e instanceof Error ? e.message : '暂时无法打开') } finally { setBusy(false) } }}><h2>杠杆策略台</h2><p>输入密码查看账户与每日计划</p><label>访问密码<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label>{error && <div className="error" role="alert">{error}</div>}<button className="desk-button" disabled={busy}>{busy ? '正在打开…' : '进入策略台'}</button></form></div>
}
