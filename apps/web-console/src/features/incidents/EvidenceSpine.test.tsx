// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { EvidenceSpine } from './EvidenceSpine'

afterEach(cleanup)

describe('EvidenceSpine', () => {
  it('renders milestones in the order supplied by the server', () => {
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-detect',
            phase: 'detect',
            state: 'complete',
            occurred_at: '2026-08-09T10:00:00Z',
            summary: '库存服务错误率超过阈值',
            evidence_refs: ['evidence-metrics'],
            source_kind: 'alert',
            source_mode: 'fixture',
          },
          {
            id: 'milestone-investigate',
            phase: 'investigate',
            state: 'current',
            occurred_at: '2026-08-09T10:01:00Z',
            summary: '日志与调用链指向同一异常实例',
            evidence_refs: ['evidence-logs', 'evidence-trace'],
            source_kind: 'evidence',
            source_mode: 'observed',
          },
        ]}
      />,
    )

    const milestones = screen.getAllByRole('listitem')
    expect(milestones).toHaveLength(2)
    expect(milestones[0]).toHaveTextContent('库存服务错误率超过阈值')
    expect(milestones[1]).toHaveTextContent('日志与调用链指向同一异常实例')
  })

  it('shows a useful empty state when the server returns no milestones', () => {
    render(<EvidenceSpine milestones={[]} />)

    expect(screen.getByRole('status')).toHaveTextContent('暂无处置证据')
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('exposes the server-marked current milestone without deriving it from phase', () => {
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-verify',
            phase: 'verify',
            state: 'current',
            occurred_at: '2026-08-09T10:08:00Z',
            summary: '正在观察恢复窗口',
            evidence_refs: [],
            source_kind: 'verification',
            source_mode: 'observed',
          },
        ]}
      />,
    )

    expect(screen.getByRole('listitem')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('当前阶段')).toBeInTheDocument()
  })

  it('labels a failed milestone with text as well as visual state', () => {
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-action',
            phase: 'execute',
            state: 'failed',
            occurred_at: '2026-08-09T10:06:00Z',
            summary: '恢复操作未完成',
            evidence_refs: [],
            source_kind: 'action',
            source_mode: 'observed',
          },
        ]}
      />,
    )

    expect(screen.getByRole('listitem')).toHaveAttribute('data-state', 'failed')
    expect(screen.getByText('阶段失败')).toBeInTheDocument()
  })

  it('labels fixture provenance only when the server marks the milestone as fixture data', () => {
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-evidence',
            phase: 'investigate',
            state: 'complete',
            occurred_at: '2026-08-09T10:02:00Z',
            summary: '指标超过演练阈值',
            evidence_refs: ['evidence-metrics'],
            source_kind: 'evidence',
            source_mode: 'fixture',
          },
        ]}
      />,
    )

    expect(screen.getByText('调查证据')).toBeInTheDocument()
    expect(screen.getByText('演练数据')).toBeInTheDocument()
  })

  it('expands server-provided details and evidence references on request', async () => {
    const user = userEvent.setup()
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-logs',
            phase: 'investigate',
            state: 'complete',
            occurred_at: '2026-08-09T10:03:00Z',
            summary: '日志显示连接超时',
            evidence_refs: ['evidence-logs'],
            source_kind: 'evidence',
            source_mode: 'observed',
          },
        ]}
      />,
    )

    const toggle = screen.getByRole('button', { name: '查看详情：日志显示连接超时' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('evidence-logs')).not.toBeInTheDocument()

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('evidence-logs')).toBeInTheDocument()
  })

  it('keeps every milestone toggle at least 44px high for touch input', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/features/incidents/EvidenceSpine.module.css'), 'utf8')

    expect(css).toMatch(/\.toggle\s*\{[^}]*min-height:\s*44px/s)
  })

  it('can focus and expand a milestone using only the keyboard', async () => {
    const user = userEvent.setup()
    render(
      <EvidenceSpine
        milestones={[
          {
            id: 'milestone-keyboard',
            phase: 'approve',
            state: 'current',
            occurred_at: '2026-08-09T10:05:00Z',
            summary: '等待值班人员审批',
            evidence_refs: ['evidence-plan'],
            source_kind: 'approval',
            source_mode: 'observed',
          },
        ]}
      />,
    )

    await user.tab()
    const toggle = screen.getByRole('button', { name: '查看详情：等待值班人员审批' })
    expect(toggle).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('evidence-plan')).toBeInTheDocument()
  })
})
