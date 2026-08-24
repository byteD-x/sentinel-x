import { describe, expect, it } from 'vitest'
import { DashboardDataSchema } from '../src/spec.js'
import { createConsoleSpec } from '../src/view.js'

describe('createConsoleSpec', () => {
  it('builds an overview with stable metrics and a priority incident', () => {
    const data = DashboardDataSchema.parse({
      health: {
        status: 'ok',
        version: '0.1.0',
        environment: 'local-demo',
        actions_enabled: false,
      },
      incidents: [
        {
          id: 'inc-priority',
          status: 'AWAITING_APPROVAL',
          severity: 'critical',
          alert_name: 'payment-api latency',
          description: '支付延迟升高',
          created_at: '2026-08-09T07:00:00Z',
          updated_at: '2026-08-09T07:02:00Z',
          resolved_at: null,
          version: 2,
        },
      ],
      approvals: [],
      scenarios: [],
    })

    const spec = createConsoleSpec(data, 'overview')

    expect(spec.root).toBe('root')
    expect(spec.elements['metrics']?.children).toHaveLength(4)
    expect(spec.elements['priority']?.props).toMatchObject({
      title: '优先处理',
      content: 'payment-api latency · 支付延迟升高',
    })
    expect(spec.elements['incident-table']?.type).toBe('Table')
  })
})
