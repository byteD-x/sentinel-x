import { z } from 'zod'

export const SentinelRoleSchema = z.enum([
  'viewer',
  'approver',
  'scenario_operator',
  'planner',
  'system',
])

export const OutputModeSchema = z.enum(['tui', 'json'])
export const ConsoleFieldSchema = z.enum(['health', 'incidents', 'approvals', 'scenarios'])

const ApiBaseUrlSchema = z.string().url().superRefine((value, context) => {
  if (/\p{Cc}/u.test(value)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址不能包含控制字符' })
    return
  }

  if (/%[0-9a-f]{2}/i.test(value)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址不能包含百分号编码片段' })
  }
  if (!/^https?:\/\/(?:\[[0-9a-f:.]+\]|[^/?#\s]+)\/?$/i.test(value)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址必须是无路径和查询参数的基址' })
  }

  let url: URL
  try {
    url = new URL(value)
  } catch {
    return
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址仅支持 http 或 https' })
  }
  if (url.username || url.password) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址不能内嵌凭据' })
  }
  if ((url.pathname && url.pathname !== '/') || url.search || url.hash) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'API 地址必须是无路径和查询参数的基址' })
  }
})

export const ConsoleInputSchema = z.object({
  apiUrl: ApiBaseUrlSchema.default('http://127.0.0.1:8000'),
  role: SentinelRoleSchema.default('viewer'),
  output: OutputModeSchema.default('tui'),
  fields: z.array(ConsoleFieldSchema).default([]),
  dryRun: z.boolean().default(false),
})

export type ConsoleInput = z.infer<typeof ConsoleInputSchema>

const IsoDateSchema = z.string().min(1)

export const HealthSchema = z.object({
  status: z.string(),
  version: z.string(),
  environment: z.string(),
  actions_enabled: z.boolean(),
})

export const IncidentSchema = z.object({
  id: z.string().min(1),
  fingerprint: z.string().nullable().optional(),
  status: z.string().min(1),
  severity: z.string().min(1),
  alert_name: z.string(),
  description: z.string(),
  created_at: IsoDateSchema,
  updated_at: IsoDateSchema,
  resolved_at: IsoDateSchema.nullable().optional(),
  workflow_id: z.string().nullable().optional(),
  version: z.number().int(),
})

export const ApprovalSchema = z.object({
  id: z.string().min(1),
  incident_id: z.string().min(1),
  plan_id: z.string().min(1),
  runbook_ref: z.string().min(1),
  target: z.string().min(1),
  parameters: z.record(z.string(), z.unknown()),
  risk_level: z.string().min(1),
  plan_hash: z.string().min(1),
  status: z.string().min(1),
  created_at: IsoDateSchema,
  expires_at: IsoDateSchema,
  decided_at: IsoDateSchema.nullable().optional(),
  decided_by: z.string().nullable().optional(),
  decision_reason: z.string().nullable().optional(),
  incident: z.object({
    id: z.string().min(1),
    status: z.string().min(1),
    severity: z.string().min(1),
    alert_name: z.string(),
    description: z.string(),
    updated_at: IsoDateSchema,
  }).optional(),
})

export const ScenarioSchema = z.object({
  id: z.string().min(1),
  name: z.string(),
  version: z.number().int(),
  description: z.string(),
  category: z.string(),
  allowlisted_runbooks: z.array(z.string()).optional(),
})

export const DashboardDataSchema = z.object({
  health: HealthSchema,
  incidents: z.array(IncidentSchema),
  approvals: z.array(ApprovalSchema),
  scenarios: z.array(ScenarioSchema),
})

export type DashboardData = z.infer<typeof DashboardDataSchema>

export const ConsoleErrorCodeSchema = z.enum([
  'API_UNAVAILABLE',
  'HTTP_ERROR',
  'INVALID_RESPONSE',
])

export const ConsoleFailureSchema = z.object({
  success: z.literal(false),
  error: z.object({
    code: ConsoleErrorCodeSchema,
    message: z.string(),
    suggestion: z.string().optional(),
    recoverable: z.boolean(),
  }),
})

export const ConsoleSuccessSchema = z.object({
  success: z.literal(true),
  data: DashboardDataSchema,
})

export type ConsoleResult = z.infer<typeof ConsoleSuccessSchema> | z.infer<typeof ConsoleFailureSchema>

export interface ConsoleDataSpec {
  execute(input: ConsoleInput): Promise<ConsoleResult>
}
