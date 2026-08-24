import { describe, expect, it } from 'vitest'
import { parseConsoleArgs } from '../src/cli.js'

describe('parseConsoleArgs', () => {
  it('accepts a raw JSON payload and a convenience field mask', () => {
    const result = parseConsoleArgs([
      '--input',
      JSON.stringify({
        apiUrl: 'http://127.0.0.1:8000',
        role: 'viewer',
        output: 'json',
      }),
      '--fields',
      'health,incidents',
    ])

    expect(result).toMatchObject({
      kind: 'run',
      input: {
        apiUrl: 'http://127.0.0.1:8000',
        role: 'viewer',
        output: 'json',
        fields: ['health', 'incidents'],
        dryRun: false,
      },
    })
  })
})
