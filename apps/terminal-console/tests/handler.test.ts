import { describe, expect, it, vi } from 'vitest'
import { ConsoleDataHandler } from '../src/handler.js'
import { ConsoleInputSchema } from '../src/spec.js'

describe('ConsoleDataHandler', () => {
  it('loads a typed dashboard snapshot from the control API', async () => {
    const responses: Record<string, unknown> = {
      '/health': {
        status: 'ok',
        version: '0.1.0',
        environment: 'local-demo',
        actions_enabled: false,
      },
      '/api/incidents?limit=20': {
        items: [
          {
            id: 'inc-1',
            fingerprint: 'fixture-1',
            status: 'AWAITING_APPROVAL',
            severity: 'critical',
            alert_name: 'payment-api latency',
            description: '支付延迟升高',
            created_at: '2026-08-09T07:00:00Z',
            updated_at: '2026-08-09T07:02:00Z',
            resolved_at: null,
            workflow_id: null,
            version: 2,
          },
        ],
        total: 1,
        next_cursor: null,
      },
      '/api/approvals?status=pending': {
        items: [
          {
            id: 'approval-1',
            incident_id: 'inc-1',
            plan_id: 'plan-1',
            runbook_ref: 'restart_deployment@1',
            target: 'payment-api',
            parameters: { reason: '演练' },
            risk_level: 'R1',
            plan_hash: 'abc123',
            status: 'pending',
            created_at: '2026-08-09T07:02:00Z',
            expires_at: '2026-08-09T07:32:00Z',
            incident: {
              id: 'inc-1',
              status: 'AWAITING_APPROVAL',
              severity: 'critical',
              alert_name: 'payment-api latency',
              description: '支付延迟升高',
              updated_at: '2026-08-09T07:02:00Z',
            },
          },
        ],
        total: 1,
      },
      '/api/scenarios': {
        items: [
          {
            id: 'payment-latency@1',
            name: 'payment-latency@1',
            version: 1,
            description: 'Payment API 高延迟',
            category: 'network',
          },
        ],
      },
    }
    const fetcher = vi.fn(async (input: string | URL | Request) => {
      const body = responses[new URL(String(input)).pathname + (new URL(String(input)).search || '')]
      return new Response(JSON.stringify(body), { status: 200 })
    })

    const input = ConsoleInputSchema.parse({ apiUrl: 'http://127.0.0.1:8000' })
    const result = await new ConsoleDataHandler(fetcher).execute(input)

    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.incidents[0].id).toBe('inc-1')
      expect(result.data.approvals[0].target).toBe('payment-api')
      expect(result.data.scenarios).toHaveLength(1)
    }
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('returns a recoverable error when the control API is unavailable', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED'))
    const input = ConsoleInputSchema.parse({ apiUrl: 'http://127.0.0.1:8000' })

    const result = await new ConsoleDataHandler(fetcher).execute(input)

    expect(result).toEqual({
      success: false,
      error: {
        code: 'API_UNAVAILABLE',
        message: 'connect ECONNREFUSED',
        suggestion: '启动 local-demo 控制面，或通过 --api-url 指定地址。',
        recoverable: true,
      },
    })
  })
})
