import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ExecutionPage from '../src/pages/ExecutionPage'
import { api } from '../src/api'

vi.mock('../src/api', () => ({ api: vi.fn(), staticDesk: false, formatMoney: (n: number) => String(n) }))
vi.mock('../src/components/DeskChart', () => ({ default: () => <div>历史曲线</div> }))
const request = vi.mocked(api)
let stale = false
beforeEach(() => {
  stale = false
  request.mockReset()
  HTMLElement.prototype.scrollIntoView = vi.fn()
  request.mockImplementation(async (path: string) => {
    if (path.startsWith('/execution/catalog')) return {
      cutoff: '2026-10-02', last_completed_session: stale ? '2026-10-05' : '2026-10-02', stale,
      rule: { buy_score: 0, sell_score: 20, add_drop: .05, buy_gap_days: 3, profit_target: .5, exit_mode: 'trail', trailing_drop: .1, max_hold_days: 90 },
      items: [{ symbol: 'TQQQ', date: '2026-10-02', score: -30, raw_close: 81, adjusted_close: 40.5, price_change_pct: 1, phase: '恐惧', position: null }],
      next_open_plan: { signal_date: '2026-10-02', next_open_date: '2026-10-05', actions: [{ symbol: 'TQQQ', side: 'buy', reason: '首笔买入' }] },
    }
    if (path.startsWith('/execution/history')) return { observations: 0, points: [], distribution: [] }
    if (path.startsWith('/desk/observation')) return { latest: null, message: '观察尚未生成', data_date: null }
    if (path === '/instruments') return [{ id: 1, symbol: 'TQQQ', name: 'Test', currency: 'USD' }]
    if (path.startsWith('/portfolio')) return { positions: [] }
    if (path.startsWith('/trades')) return []
    throw Error(`Unexpected ${path}`)
  })
})
afterEach(cleanup)

describe('daily desk', () => {
  it('loads actions without full results and records actual inputs only after explicit save', async () => {
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>)
    await screen.findByText('一笔预算 HK$25,000')
    expect(request.mock.calls.some(([path]) => path.includes('/execution/results'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '记录已成交' }))
    await waitFor(() => expect((screen.getByLabelText('品种') as HTMLSelectElement).value).toBe('1'))
    expect((screen.getByLabelText('实际股数') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('实际成交价 · USD') as HTMLInputElement).value).toBe('')
    expect(request.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    fireEvent.change(screen.getByLabelText('实际股数'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('实际成交价 · USD'), { target: { value: '81' } })
    fireEvent.click(screen.getByRole('button', { name: '保存实际成交' }))
    await screen.findByText('已保存实盘成交，组合持仓已更新。')
    const write = request.mock.calls.find(([path, init]) => path === '/trades' && init?.method === 'POST')
    const body = JSON.parse(String(write?.[1]?.body))
    expect(body).toMatchObject({ instrument_id: 1, portfolio_kind: 'live', side: 'buy', quantity: 10, price: 81 })
    expect(body.note).toContain('主方案')
  })
  it('never shows stale cached orders as actionable daily recommendations', async () => {
    stale = true
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>)
    await screen.findByText('操作暂停：行情未更新')
    expect(screen.queryByText('一笔预算 HK$25,000')).toBeNull()
    expect(screen.queryByRole('button', { name: '记录已成交' })).toBeNull()
  })
})
