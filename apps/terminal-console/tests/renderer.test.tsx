import { JSONUIProvider, Renderer } from '@json-render/ink'
import { render } from 'ink-testing-library'
import { describe, expect, it } from 'vitest'
import { DashboardDataSchema } from '../src/spec.js'
import { createConsoleSpec } from '../src/view.js'

describe('terminal renderer', () => {
  it('renders the overview spec through @json-render/ink', () => {
    const data = DashboardDataSchema.parse({
      health: {
        status: 'ok',
        version: '0.1.0',
        environment: 'local-demo',
        actions_enabled: false,
      },
      incidents: [],
      approvals: [],
      scenarios: [],
    })
    const spec = createConsoleSpec(data, 'overview')

    const { lastFrame, unmount } = render(
      <JSONUIProvider initialState={{}}>
        <Renderer spec={spec} />
      </JSONUIProvider>,
    )

    const frame = lastFrame()
    expect(frame).toContain('SENTINEL-X // INCIDENT COMMAND')
    expect(frame).toContain('LOCAL-DEMO / OK')
    expect(frame).toContain('事故队列')
    unmount()
  })
})
