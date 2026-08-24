import { describe, expect, it } from 'vitest'
import { ConsoleInputSchema } from '../src/spec.js'

describe('ConsoleInputSchema', () => {
  it('rejects a resource URL with embedded query parameters', () => {
    const result = ConsoleInputSchema.safeParse({
      apiUrl: 'http://127.0.0.1:8000/api/incidents?status=all',
      role: 'viewer',
      output: 'tui',
      fields: [],
      dryRun: false,
    })

    expect(result.success).toBe(false)
  })

  it('rejects a percent-encoded path segment before URL normalization', () => {
    const result = ConsoleInputSchema.safeParse({
      apiUrl: 'http://127.0.0.1:8000/%2e%2e',
    })

    expect(result.success).toBe(false)
  })
})
