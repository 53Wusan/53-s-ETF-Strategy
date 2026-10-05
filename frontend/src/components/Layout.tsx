import { useEffect } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { api, staticDesk } from '../api'

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }) }, [location.pathname])
  async function logout() {
    await api('/auth/logout', { method: 'POST' })
    navigate('/login')
  }
  return (
    <div className="shell execution-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">L</span>
          <span><strong>杠杆策略台</strong><small>FEAR · GREED · DISCIPLINE</small></span>
        </NavLink>
        <nav>
          <NavLink to="/" end>看板</NavLink>
          <NavLink to="/research">保留方案</NavLink>
          <NavLink to="/method">计算说明</NavLink>{staticDesk && <NavLink to="/account">账户与对账</NavLink>}
          {!staticDesk && <NavLink to="/portfolio">组合</NavLink>}
          {!staticDesk && <NavLink to="/trades">实盘记录</NavLink>}
        </nav>
        <button className="ghost" onClick={staticDesk ? () => window.location.reload() : logout}>退出</button>
      </header>
      <main>{children}</main>
      <footer>数据与模型仅供研究，不构成投资建议，不会自动下单。</footer>
    </div>
  )
}

