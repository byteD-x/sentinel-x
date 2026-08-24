import { JSONUIProvider, Renderer } from '@json-render/ink'
import type { Spec } from '@json-render/core'
import { useApp, useInput } from 'ink'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ConsoleDataSpec, ConsoleInput, ConsoleResult } from './spec.js'
import { createConsoleSpec, createErrorSpec, type ConsoleView } from './view.js'

const VIEWS: ConsoleView[] = ['overview', 'approvals', 'scenarios', 'system']

interface TerminalAppProps {
  input: ConsoleInput
  service: ConsoleDataSpec
}

export function TerminalApp({ input, service }: TerminalAppProps) {
  const { exit } = useApp()
  const [view, setView] = useState<ConsoleView>('overview')
  const [result, setResult] = useState<ConsoleResult | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setResult(await service.execute(input))
    setLoading(false)
  }, [input, service])

  useEffect(() => {
    void load()
  }, [load])

  useInput((value, key) => {
    if (value === 'q') exit()
    if (value === 'r') void load()

    const currentIndex = VIEWS.indexOf(view)
    if (key.leftArrow) setView(VIEWS[(currentIndex - 1 + VIEWS.length) % VIEWS.length])
    if (key.rightArrow) setView(VIEWS[(currentIndex + 1) % VIEWS.length])
    if (/^[1-4]$/.test(value)) setView(VIEWS[Number(value) - 1])
  })

  const spec = useMemo(() => resolveSpec(result, view, loading), [loading, result, view])

  return (
    <JSONUIProvider initialState={{}}>
      <Renderer spec={spec} />
    </JSONUIProvider>
  )
}

function resolveSpec(result: ConsoleResult | null, view: ConsoleView, loading: boolean): Spec {
  if (loading || !result) {
    return {
      root: 'loading-root',
      elements: {
        'loading-root': {
          type: 'Box',
          props: { flexDirection: 'column', padding: 1, gap: 1 },
          children: ['loading-title', 'loading-spinner'],
        },
        'loading-title': {
          type: 'Heading',
          props: { text: 'SENTINEL-X // INCIDENT COMMAND', level: 'h1', color: 'cyan' },
          children: [],
        },
        'loading-spinner': {
          type: 'Spinner',
          props: { label: '正在读取控制面快照', color: 'cyan' },
          children: [],
        },
      },
    }
  }
  if (!result.success) {
    return createErrorSpec(result.error.code, result.error.message, result.error.suggestion)
  }
  return createConsoleSpec(result.data, view)
}
