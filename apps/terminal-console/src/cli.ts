import { parseArgs } from 'node:util'
import { z } from 'zod'
import {
  ConsoleInputSchema,
  type ConsoleInput,
  type DashboardData,
} from './spec.js'

type ParseResult =
  | { kind: 'run'; input: ConsoleInput }
  | { kind: 'describe' }
  | { kind: 'help' }
  | {
      kind: 'error'
      error: {
        code: 'INVALID_INPUT'
        message: string
        suggestion: string
        recoverable: false
      }
    }

export function parseConsoleArgs(
  args: string[],
  environment: NodeJS.ProcessEnv = process.env,
): ParseResult {
  try {
    const { values } = parseArgs({
      args,
      allowPositionals: false,
      strict: true,
      options: {
        'api-url': { type: 'string' },
        role: { type: 'string' },
        output: { type: 'string' },
        fields: { type: 'string' },
        input: { type: 'string' },
        'dry-run': { type: 'boolean', default: false },
        describe: { type: 'boolean', default: false },
        help: { type: 'boolean', short: 'h', default: false },
      },
    })

    if (values.help) return { kind: 'help' }
    if (values.describe) return { kind: 'describe' }

    const rawInput = values.input
      ? parseJsonObject(values.input)
      : { success: true as const, data: {} as Record<string, unknown> }
    if (!rawInput.success) return rawInput.result

    const fields = values.fields
      ? values.fields.split(',').map((field) => field.trim()).filter(Boolean)
      : rawInput.data.fields
    const parsed = ConsoleInputSchema.safeParse({
      ...rawInput.data,
      apiUrl: values['api-url'] ?? rawInput.data.apiUrl ?? environment.SENTINEL_API_URL,
      role: values.role ?? rawInput.data.role ?? environment.SENTINEL_ROLE,
      output: values.output ?? rawInput.data.output,
      fields,
      dryRun: values['dry-run'] || rawInput.data.dryRun,
    })

    if (!parsed.success) {
      return invalidInput(parsed.error.issues.map((issue) => issue.message).join('; '))
    }
    return { kind: 'run', input: parsed.data }
  } catch (cause) {
    return invalidInput(cause instanceof Error ? cause.message : '无法解析命令参数')
  }
}

export function describeConsoleInput() {
  return z.toJSONSchema(ConsoleInputSchema)
}

export function selectDashboardFields(data: DashboardData, fields: ConsoleInput['fields']) {
  if (!fields.length) return data
  return Object.fromEntries(fields.map((field) => [field, data[field]]))
}

export const HELP_TEXT = `Sentinel-X Terminal Console

Usage:
  sentinel-x-terminal [options]

Options:
  --api-url <url>       Control API base URL (default: http://127.0.0.1:8000)
  --role <role>         viewer | approver | scenario_operator | planner | system
  --output <mode>       tui | json
  --fields <list>       health,incidents,approvals,scenarios
  --input <json>        Raw JSON payload matching --describe
  --dry-run             Validate and print the request without network access
  --describe            Print the runtime input schema as JSON
  -h, --help            Show this help
`

function parseJsonObject(value: string):
  | { success: true; data: Record<string, unknown> }
  | { success: false; result: Extract<ParseResult, { kind: 'error' }> } {
  try {
    const parsed: unknown = JSON.parse(value)
    if (!isRecord(parsed)) return { success: false, result: invalidInput('--input 必须是 JSON 对象') }
    return { success: true, data: parsed }
  } catch (cause) {
    return {
      success: false,
      result: invalidInput(cause instanceof Error ? cause.message : '--input 不是有效 JSON'),
    }
  }
}

function invalidInput(message: string): Extract<ParseResult, { kind: 'error' }> {
  return {
    kind: 'error',
    error: {
      code: 'INVALID_INPUT',
      message,
      suggestion: '运行 --describe 获取机器可读输入 schema。',
      recoverable: false,
    },
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
