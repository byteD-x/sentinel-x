import {
  DashboardDataSchema,
  type ConsoleDataSpec,
  type ConsoleInput,
  type ConsoleResult,
} from './spec.js'

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

type ReadResult =
  | { success: true; data: unknown }
  | Extract<ConsoleResult, { success: false }>

export class ConsoleDataHandler implements ConsoleDataSpec {
  constructor(private readonly fetcher: Fetcher = fetch) {}

  async execute(input: ConsoleInput): Promise<ConsoleResult> {
    const headers = {
      Accept: 'application/json',
      'X-Sentinel-Role': input.role,
    }

    const health = await this.read('/health', input, headers)
    if (!health.success) return health
    const incidents = await this.read('/api/incidents?limit=20', input, headers)
    if (!incidents.success) return incidents
    const approvals = await this.read('/api/approvals?status=pending', input, headers)
    if (!approvals.success) return approvals
    const scenarios = await this.read('/api/scenarios', input, headers)
    if (!scenarios.success) return scenarios

    const parsed = DashboardDataSchema.safeParse({
      health: health.data,
      incidents: isRecord(incidents.data) ? incidents.data.items : undefined,
      approvals: isRecord(approvals.data) ? approvals.data.items : undefined,
      scenarios: isRecord(scenarios.data) ? scenarios.data.items : undefined,
    })
    if (!parsed.success) {
      return {
        success: false,
        error: {
          code: 'INVALID_RESPONSE',
          message: '控制面返回的数据不符合终端契约',
          suggestion: '检查控制面版本与终端控制台版本是否匹配。',
          recoverable: false,
        },
      }
    }

    return { success: true, data: parsed.data }
  }

  private async read(
    path: string,
    input: ConsoleInput,
    headers: Record<string, string>,
  ): Promise<ReadResult> {
    try {
      const response = await this.fetcher(new URL(path, `${input.apiUrl}/`), { headers })
      if (!response.ok) {
        return {
          success: false,
          error: {
            code: 'HTTP_ERROR',
            message: `控制面请求失败（HTTP ${response.status}）`,
            suggestion: response.status === 403 ? '使用具有对应权限的角色重试。' : '确认控制面在线后重试。',
            recoverable: response.status >= 500,
          },
        }
      }
      return { success: true, data: await response.json() }
    } catch (cause) {
      return {
        success: false,
        error: {
          code: 'API_UNAVAILABLE',
          message: cause instanceof Error ? cause.message : '无法连接控制面',
          suggestion: '启动 local-demo 控制面，或通过 --api-url 指定地址。',
          recoverable: true,
        },
      }
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
