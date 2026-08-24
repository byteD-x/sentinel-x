// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../lib/api'
import { ScenariosPage } from './ScenariosPage'

vi.mock('../lib/api', () => ({
  apiFetch: vi.fn(),
  currentRole: () => 'scenario_operator',
}))

const scenarioProjection = {
  items: [
    {
      id: 'payment-pod-crash@1',
      name: '投影优先场景',
      version: 1,
      description: '由 Control API 返回的目标说明',
      category: 'application',
      target_service: 'catalog-cache',
      target_namespace: 'sandbox-team-a',
      allowlisted_runbooks: [],
    },
    {
      id: 'opaque-recovery@1',
      name: '受控恢复场景',
      version: 1,
      description: '仅展示公开的受控恢复信息',
      category: 'application',
      target_service: 'checkout-api',
      target_namespace: 'sandbox-team-b',
      allowlisted_runbooks: ['restart_deployment@1'],
    },
    {
      id: 'opaque-verification@1',
      name: '恢复验证场景',
      version: 1,
      description: '公开投影说明恢复动作无需执行',
      category: 'kubernetes',
      target_service: 'payment-api',
      target_namespace: 'sandbox-team-c',
      allowlisted_runbooks: ['no_op'],
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ScenariosPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
  vi.mocked(apiFetch).mockResolvedValue({
    json: async () => scenarioProjection,
  } as Response)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('ScenariosPage', () => {
  it('uses the Control API projection instead of inferring the target or recovery path from a scenario ID', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /投影优先场景/ }))
    const preflight = screen.getByLabelText('演练启动条件')

    expect(within(preflight).getByText('由 Control API 返回的目标说明')).toBeInTheDocument()
    expect(within(preflight).getByText('catalog-cache')).toBeInTheDocument()
    expect(within(preflight).getByText('sandbox-team-a')).toBeInTheDocument()
    expect(within(preflight).getByText('无允许的恢复操作，升级人工')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /受控恢复场景/ }))

    expect(within(preflight).getByText('restart_deployment@1')).toBeInTheDocument()
    expect(within(preflight).getByText('由策略决定审批或人工升级')).toBeInTheDocument()
  })

  it('keeps a no-op recovery path understandable without exposing its internal marker', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /恢复验证场景/ }))
    const preflight = screen.getByLabelText('演练启动条件')

    expect(within(preflight).getByText('无需执行恢复动作，进入验证')).toBeInTheDocument()
    expect(within(preflight).queryByText('no_op')).not.toBeInTheDocument()
  })

  it('shows the loading error when the public scenario projection is unavailable', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('场景目录不可用'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('场景目录不可用')
  })
})
