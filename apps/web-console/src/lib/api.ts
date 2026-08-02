export type SentinelRole = 'viewer' | 'approver' | 'scenario_operator' | 'planner' | 'system'

export class ApiError extends Error {
  status: number
  detail?: string

  constructor(status: number, detail?: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function currentRole(): SentinelRole {
  const configured = import.meta.env.VITE_SENTINEL_ROLE as SentinelRole | undefined
  return configured || 'viewer'
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (!headers.has('X-Sentinel-Role')) headers.set('X-Sentinel-Role', currentRole())
  const token = import.meta.env.VITE_SENTINEL_TOKEN as string | undefined
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(input, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new ApiError(response.status, body.detail || `请求失败（HTTP ${response.status}）`)
  }
  return response
}

