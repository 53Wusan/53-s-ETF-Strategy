import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ApiError, api, staticDesk } from './api'
import UnlockPage from './pages/UnlockPage'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'

const PortfolioPage = lazy(() => import('./pages/PortfolioPage'))
const TradesPage = lazy(() => import('./pages/TradesPage'))
const ResearchPage = lazy(() => import('./pages/ResearchPage'))
const MethodPage = lazy(() => import('./pages/MethodPage'))
const ExecutionPage = lazy(() => import('./pages/ExecutionPage'))
const ShadowPage = lazy(() => import('./pages/ShadowPage'))

export default function App() {
  const location = useLocation()
  const [unlocked, setUnlocked] = useState(false)
  if (staticDesk && !unlocked) return <UnlockPage onUnlock={() => setUnlocked(true)} />
  if (!staticDesk && location.pathname === '/login') return <Routes><Route path="/login" element={<LoginPage />} /></Routes>
  return <AuthenticatedApp />
}

function AuthenticatedApp() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  useEffect(() => {
    api('/auth/me').then(() => setAuthenticated(true)).catch((error) => setAuthenticated(!(error instanceof ApiError && error.status === 401)))
  }, [])
  if (authenticated === null) return <div className="app-loading"><span className="brand-mark large">L</span><p>正在打开策略台…</p></div>
  if (!authenticated) return <Navigate to="/login" replace />
  return <Layout><Suspense fallback={<div className="empty">正在加载页面…</div>}><Routes><Route path="/" element={<ExecutionPage />} /><Route path="/research" element={<ResearchPage />} /><Route path="/method" element={<MethodPage />} /><Route path="/account" element={<ShadowPage />} /><Route path="/portfolio" element={staticDesk ? <Navigate to="/account" replace /> : <PortfolioPage />} /><Route path="/trades" element={staticDesk ? <Navigate to="/account" replace /> : <TradesPage />} /><Route path="/sentiment" element={<Navigate to="/#index-history" replace />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></Suspense></Layout>
}
