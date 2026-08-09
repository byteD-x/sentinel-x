// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../lib/api'
import { IncidentDetailPage } from './IncidentDetailPage'

vi.mock('../hooks/useSSE', () => ({ useSSE: () => 'connected' }))
vi.mock('../lib/api', () => ({
  apiFetch: vi.fn(),
  currentRole: () => 'viewer',
}))

const overview = {
  id: 'incident-1',
  fingerprint: 'fixture-1',
  status: 'DETECTED',
  severity: 'warning',
  alert_name: 'Inventory API High Error Rate',
  description: '库存写入失败，结算流程受到影响。',
  created_at: '2026-08-09T10:00:00Z',
  updated_at: '2026-08-09T10:02:00Z',
  resolved_at: null,
  workflow_id: null,
  version: 1,
  environment: {
    profile: 'light',
    data_scope: 'exercise',
    source_mode: 'fixture',
  },
  impact: {
    summary: '库存写入失败，结算流程受到影响。',
    observed_at: '2026-08-09T10:01:00Z',
    source_mode: 'fixture',
  },
  top_hypothesis: {
    statement: '库存服务连接池耗尽。',
    confidence: 0.87,
    supporting_evidence_count: 3,
    opposing_evidence: null,
    source_mode: 'fixture',
  },
  next_decision: {
    kind: 'review_approval',
    title: '服务端指定的下一步',
    reason: '先核对错误日志与连接池指标。',
    target_href: '#approval-section',
  },
  active_approval: {
    id: 'approval-1',
    runbook_ref: 'restart_deployment@1',
    target: 'inventory-api',
    risk_level: 'R1',
    plan_hash: 'canonical-plan-hash',
    expires_at: '2026-08-09T10:30:00Z',
  },
  latest_verification: null,
  capabilities: {
    can_decide_approval: false,
    can_view_raw_evidence: true,
    denial_reason: '当前角色不能提交审批决定',
  },
  milestones: [
    {
      id: 'milestone-detect',
      phase: 'detect',
      state: 'current',
      occurred_at: '2026-08-09T10:00:00Z',
      summary: '服务端事故阶段',
      evidence_refs: [],
      source_kind: 'alert',
      source_mode: 'fixture',
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/incidents/incident-1']}>
      <Routes>
        <Route path="/incidents/:id" element={<IncidentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockImplementation(async input => {
    const path = String(input)
    const payload = path.endsWith('/timeline')
      ? { events: [] }
      : path.endsWith('/approvals')
        ? { items: [] }
        : overview
    return { json: async () => payload } as Response
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('IncidentDetailPage', () => {
  it('uses the server overview as the only source for the decision and evidence spine', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: '服务端指定的下一步' })).toBeInTheDocument()
    expect(screen.getByText('先核对错误日志与连接池指标。')).toBeInTheDocument()
    expect(screen.getByText('服务端事故阶段')).toBeInTheDocument()
    expect(screen.getAllByText('演练数据').length).toBeGreaterThan(0)
  })

  it('shows the server capability denial instead of deriving permissions from the local role', async () => {
    renderPage()

    expect(await screen.findByText('当前角色不能提交审批决定')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '批准恢复' })).not.toBeInTheDocument()
  })
})
