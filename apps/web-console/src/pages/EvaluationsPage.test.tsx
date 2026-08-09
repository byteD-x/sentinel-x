// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EvaluationsPage } from './EvaluationsPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(route = '/evaluations') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/evaluations" element={<EvaluationsPage />} />
        <Route path="/evaluations/:reportId" element={<EvaluationsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const validSummary = {
  report_id: 'eval-20260809-101500-a1b2c3',
  created_at: '2026-08-09T10:15:00Z',
  archive_status: 'valid',
  metadata: {
    commit_sha: 'a'.repeat(40),
    profile: 'light',
    environment_ref: 'local-isolated',
    hardware_ref: null,
    dataset_ref: 'holdout@1',
    model_ref: 'investigator-v1',
    policy_ref: 'policy@1',
    prompt_ref: 'investigator@1',
    random_seed: 42,
    runs_per_scenario: 1,
    timeout_seconds: 600,
  },
  comparability: {
    comparable: false,
    baseline_ref: null,
    reasons: ['尚未建立同口径 baseline。'],
  },
  aggregate: {
    attempted_runs: 1,
    completed_runs: 1,
    failed_runs: 0,
    metrics: [],
  },
  artifact: {
    sha256: `sha256:${'b'.repeat(64)}`,
    size_bytes: 2048,
    media_type: 'application/json',
  },
} as const

const validDetail = {
  report: {
    schema_version: '1.0',
    report_id: validSummary.report_id,
    created_at: validSummary.created_at,
    metadata: validSummary.metadata,
    comparability: validSummary.comparability,
    aggregate: {
      attempted_runs: 2,
      completed_runs: 1,
      failed_runs: 1,
      metrics: [{
        name: 'top1_accuracy',
        category: 'diagnosis',
        value: 75,
        unit: '%',
        target: 60,
        direction: 'higher_is_better',
        passed: true,
        sample_count: 1,
      }],
    },
    runs: [{
      run_id: 'run-001',
      scenario_ref: 'inventory-latched-5xx@1',
      run_index: 0,
      incident_id: 'incident-001',
      model_ref: 'investigator-v1',
      config: { seed: 42 },
      metrics: [],
    }],
    failures: [{
      scenario_ref: 'inventory-latched-5xx@1',
      run_index: 1,
      category: 'system',
      code: 'SCENARIO_EXECUTION_FAILED',
      message: '场景执行失败；详见受限执行日志。',
    }],
  },
  artifact: validSummary.artifact,
} as const

describe('EvaluationsPage', () => {
  it('loads archived evaluations and exposes each valid report as a selectable control', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ available: true, items: [validSummary] }))
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('button', { name: '打开评测报告 eval-20260809-101500-a1b2c3' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/evaluations', expect.any(Object))
  })

  it('shows only the summary facts supplied by a valid archive', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ available: true, items: [validSummary] })))

    renderPage()

    const report = await screen.findByRole('button', { name: '打开评测报告 eval-20260809-101500-a1b2c3' })
    expect(report).toHaveTextContent('holdout@1')
    expect(report).toHaveTextContent('investigator-v1')
    expect(report).toHaveTextContent('完成 1')
    expect(report).toHaveTextContent('失败 0')
    expect(report).toHaveTextContent('不可比较')
    expect(report).toHaveTextContent(`sha256:${'b'.repeat(12)}`)
  })

  it('shows the server reason when no evaluation archive exists', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      available: false,
      unavailable_reason: '尚无已归档的评测报告',
      items: [],
    })))

    renderPage()

    expect(await screen.findByText('尚无已归档的评测报告')).toHaveAttribute('role', 'status')
    expect(screen.queryByRole('button', { name: /打开评测报告/ })).not.toBeInTheDocument()
  })

  it('shows an invalid archive as a non-selectable error record', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      available: false,
      unavailable_reason: '没有可读取的评测报告',
      items: [{
        report_id: 'eval-corrupted',
        archive_status: 'invalid',
        error: {
          code: 'EVALUATION_ARCHIVE_INVALID',
          message: '评测归档无效',
        },
      }],
    })))

    renderPage()

    expect(await screen.findByText('eval-corrupted')).toBeInTheDocument()
    expect(screen.getByText('评测归档无效')).toBeInTheDocument()
    expect(screen.getByText('EVALUATION_ARCHIVE_INVALID')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /eval-corrupted/ })).not.toBeInTheDocument()
  })

  it('loads the selected report from its detail endpoint', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === `/api/evaluations/${validSummary.report_id}`) return Promise.resolve(jsonResponse(validDetail))
      return Promise.resolve(jsonResponse({ available: true, items: [validSummary] }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage(`/evaluations/${validSummary.report_id}`)

    expect(await screen.findByRole('heading', { name: validSummary.report_id })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`/api/evaluations/${validSummary.report_id}`, expect.any(Object))
  })

  it('renders metrics, comparability, failures and SHA-256 only from the selected report', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === `/api/evaluations/${validSummary.report_id}`) return Promise.resolve(jsonResponse(validDetail))
      return Promise.resolve(jsonResponse({ available: true, items: [validSummary] }))
    }))

    renderPage(`/evaluations/${validSummary.report_id}`)

    const detail = await screen.findByRole('region', { name: '评测报告详情' })
    expect(within(detail).getByText('Top-1 根因命中率')).toBeInTheDocument()
    expect(within(detail).getByText('75%')).toBeInTheDocument()
    expect(within(detail).getByText('目标 60%')).toBeInTheDocument()
    expect(within(detail).getByText('样本 1')).toBeInTheDocument()
    expect(within(detail).getByText('不可比较')).toBeInTheDocument()
    expect(within(detail).getByText('尚未建立同口径 baseline。')).toBeInTheDocument()
    expect(within(detail).getByText('SCENARIO_EXECUTION_FAILED')).toBeInTheDocument()
    expect(within(detail).getByText('场景执行失败；详见受限执行日志。')).toBeInTheDocument()
    expect(within(detail).getByText(validSummary.artifact.sha256)).toBeInTheDocument()
    expect(within(detail).queryByText(/提升/)).not.toBeInTheDocument()
  })

  it('keeps the archive list and scopes a detail loading failure to the report region', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === `/api/evaluations/${validSummary.report_id}`) {
        return Promise.resolve(jsonResponse({ detail: '评测归档不可读取' }, 503))
      }
      return Promise.resolve(jsonResponse({ available: true, items: [validSummary] }))
    }))

    renderPage(`/evaluations/${validSummary.report_id}`)

    const detail = await screen.findByRole('region', { name: '评测报告详情' })
    expect(await within(detail).findByRole('alert')).toHaveTextContent('无法读取这份评测报告：评测归档不可读取')
    expect(screen.getByRole('button', { name: `打开评测报告 ${validSummary.report_id}` })).toBeInTheDocument()
  })

  it('keeps loaded archive data visible while a refresh is pending', async () => {
    const user = userEvent.setup()
    let finishRefresh: ((response: Response) => void) | undefined
    const pendingRefresh = new Promise<Response>(resolve => { finishRefresh = resolve })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ available: true, items: [validSummary] }))
      .mockReturnValueOnce(pendingRefresh)
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const report = await screen.findByRole('button', { name: `打开评测报告 ${validSummary.report_id}` })

    await user.click(screen.getByRole('button', { name: '刷新' }))

    expect(report).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('正在更新评测归档')

    finishRefresh?.(jsonResponse({ available: true, items: [validSummary] }))
  })

  it('navigates to the report route and loads detail when a report is selected', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === `/api/evaluations/${validSummary.report_id}`) return Promise.resolve(jsonResponse(validDetail))
      return Promise.resolve(jsonResponse({ available: true, items: [validSummary] }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: `打开评测报告 ${validSummary.report_id}` }))

    expect(await screen.findByRole('heading', { name: validSummary.report_id })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`/api/evaluations/${validSummary.report_id}`, expect.any(Object))
  })

  it('announces detail loading without blocking the archive list', async () => {
    const pendingDetail = new Promise<Response>(() => undefined)
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === `/api/evaluations/${validSummary.report_id}`) return pendingDetail
      return Promise.resolve(jsonResponse({ available: true, items: [validSummary] }))
    }))

    renderPage(`/evaluations/${validSummary.report_id}`)

    expect(await screen.findByText('正在读取报告…')).toHaveAttribute('aria-live', 'polite')
    expect(await screen.findByRole('button', { name: `打开评测报告 ${validSummary.report_id}` })).toBeInTheDocument()
  })
})
