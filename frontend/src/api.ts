export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const staticDesk = import.meta.env.VITE_STATIC_DESK === 'true'
const snapshots = new Map<string, Promise<Record<string, unknown>>>()
function staticSnapshot(file: string): Promise<Record<string, unknown>> {
  if (!snapshots.has(file)) {
    const request = fetch(`${import.meta.env.BASE_URL}data/${file}`, { cache: 'no-cache' }).then(async response => {
      if (!response.ok) throw new ApiError(response.status, '每日快照暂未就绪')
      return response.json() as Promise<Record<string, unknown>>
    }).catch(error => { snapshots.delete(file); throw error })
    snapshots.set(file, request)
  }
  return snapshots.get(file)!
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (staticDesk) {
    if (path === '/auth/me') return {} as T
    if (init?.method && init.method !== 'GET') throw new ApiError(405, '每日数据由自动任务更新')
    const url = new URL(path, 'https://desk.invalid')
    let file: string | undefined
    if (url.pathname === '/account') file = 'account.json'
    if (url.pathname === '/execution/catalog') file = `catalog-${url.searchParams.get('profile') || 'rank2'}.json`
    else if (url.pathname.startsWith('/execution/history/')) file = `history-${url.pathname.split('/').pop()}.json`
    else if (url.pathname === '/desk/strategies') file = 'strategies.json'
    else if (url.pathname.startsWith('/desk/strategies/')) file = `strategy-${url.pathname.split('/').pop()}.json`
    else if (url.pathname.startsWith('/desk/observation/')) file = `observation-${url.pathname.split('/').pop()}.json`
    if (!file) throw new ApiError(404, '该账户功能未在公开页面提供')
    const value = structuredClone(await staticSnapshot(file))
    if (url.pathname === '/execution/catalog' && value.valid_until && Date.now() > Date.parse(String(value.valid_until))) {
      value.stale = true
      value.next_open_plan = null
      value.last_completed_session = '等待自动更新'
    }
    if (url.pathname === '/execution/catalog' && url.searchParams.get('profile') === 'rank2') {
      const account = await staticSnapshot('account.json') as { next_open_plan: unknown; buy_budget_usd: number; positions: Record<string, unknown>; cash_usd: number; data_date: string }
      if (url.searchParams.get('profile') === 'rank2') {
        if (!value.stale) value.next_open_plan = account.next_open_plan
        value.buy_budget_usd = account.buy_budget_usd
        value.simulation_account = { cash_hkd: account.cash_usd * 7.8, position_count: Object.keys(account.positions).length }
        value.items = (value.items as Array<Record<string, unknown>>).map(item => ({ ...item, position: account.positions[String(item.symbol)] || null }))
      }
    }
    if (url.pathname.startsWith('/execution/history/')) {
      const limit = Number(url.searchParams.get('limit') || 600)
      if (limit > 0) value.points = (value.points as unknown[]).slice(-limit)
    }
    return value as T
  }
  const headers = init?.body instanceof FormData
    ? init.headers
    : { 'Content-Type': 'application/json', ...(init?.headers || {}) }
  const response = await fetch(`/api${path}`, {
    credentials: 'include',
    headers,
    ...init,
  })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : body.detail?.message || message
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export function formatMoney(value: number, currency = 'CNY') {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value || 0)
}

export function formatPct(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}
