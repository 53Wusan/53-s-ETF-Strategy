import { FormEvent, useState } from 'react'
import { api } from '../api'

export default function LoginPage() {
  const [username, setUsername] = useState('53')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      // Reload from the authenticated route so App can establish state from the HttpOnly cookie.
      window.location.assign('/')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="login-page">
      <section className="login-copy">
        <span className="eyebrow">PERSONAL STRATEGY SYSTEM</span>
        <h1>恐惧时准备，<br />贪婪时收获。</h1>
        <p>用可解释的四因子和经过样本外验证的纪律，追踪杠杆 ETF 的波动机会。</p>
      </section>
      <form className="login-card" onSubmit={submit}>
        <div className="brand-mark large">L</div>
        <h2>欢迎回来</h2>
        <p>这是你的私人投资研究台。</p>
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        {error && <div className="error-banner">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? '登录中…' : '进入看板'}</button>
      </form>
    </div>
  )
}
