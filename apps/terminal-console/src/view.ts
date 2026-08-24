import type { Spec, UIElement } from '@json-render/core'
import type { DashboardData } from './spec.js'

export type ConsoleView = 'overview' | 'approvals' | 'scenarios' | 'system'

const TERMINAL_STATES = new Set(['RESOLVED', 'ESCALATED', 'FAILED'])
const VIEW_TABS = [
  { label: '总览', value: 'overview' },
  { label: '审批', value: 'approvals' },
  { label: '演练', value: 'scenarios' },
  { label: '系统', value: 'system' },
]

export function createConsoleSpec(data: DashboardData, view: ConsoleView): Spec {
  const elements: Record<string, UIElement> = {
    root: element('Box', { flexDirection: 'column', paddingX: 1, gap: 1 }, [
      'header',
      'context',
      'divider',
      'tabs',
      `view-${view}`,
      'footer-divider',
      'footer',
    ]),
    header: element('Box', { flexDirection: 'row', justifyContent: 'space-between' }, [
      'brand',
      'environment',
    ]),
    brand: element('Heading', { text: 'SENTINEL-X // INCIDENT COMMAND', level: 'h1', color: 'cyan' }),
    environment: element('Badge', {
      label: `${data.health.environment.toUpperCase()} / ${data.health.status.toUpperCase()}`,
      variant: data.health.status === 'ok' ? 'success' : 'error',
    }),
    context: element('Text', {
      text: `Control API ${data.health.version}  ·  恢复动作 ${data.health.actions_enabled ? '审批后启用' : '关闭'}  ·  仅限隔离演练环境`,
      dimColor: true,
    }),
    divider: element('Divider', { character: '─', color: 'gray' }),
    tabs: element('Tabs', { tabs: VIEW_TABS, value: view, color: 'cyan' }),
    'footer-divider': element('Divider', { character: '─', color: 'gray', dimColor: true }),
    footer: element('Text', {
      text: '[←/→] 切换视图   [r] 刷新   [q] 退出   机器输出: --output json --fields health,incidents',
      dimColor: true,
    }),
  }

  if (view === 'overview') addOverview(elements, data)
  if (view === 'approvals') addApprovals(elements, data)
  if (view === 'scenarios') addScenarios(elements, data)
  if (view === 'system') addSystem(elements, data)

  return { root: 'root', elements }
}

export function createErrorSpec(code: string, message: string, suggestion?: string): Spec {
  return {
    root: 'error-root',
    elements: {
      'error-root': element('Box', { flexDirection: 'column', padding: 1, gap: 1 }, [
        'error-title',
        'error-status',
        'error-suggestion',
        'error-footer',
      ]),
      'error-title': element('Heading', { text: 'SENTINEL-X // CONNECTION FAILED', level: 'h1', color: 'red' }),
      'error-status': element('StatusLine', { text: `${code}: ${message}`, status: 'error' }),
      'error-suggestion': element('Callout', {
        type: 'warning',
        title: '恢复建议',
        content: suggestion || '确认控制面在线后重试。',
      }),
      'error-footer': element('Text', { text: '[r] 重试   [q] 退出', dimColor: true }),
    },
  }
}

function addOverview(elements: Record<string, UIElement>, data: DashboardData) {
  const active = data.incidents.filter((incident) => !TERMINAL_STATES.has(incident.status))
  const resolved = data.incidents.filter((incident) => incident.status === 'RESOLVED')
  const critical = data.incidents.filter((incident) => incident.severity === 'critical')
  const priority = findPriorityIncident(active)

  elements['view-overview'] = element('Box', { flexDirection: 'column', gap: 1 }, [
    'metrics',
    'priority',
    'queue-title',
    'incident-table',
    'safety-line',
  ])
  elements.metrics = element('Box', { flexDirection: 'row', gap: 3, flexWrap: 'wrap' }, [
    'metric-active',
    'metric-approval',
    'metric-critical',
    'metric-resolved',
  ])
  elements['metric-active'] = element('Metric', { label: '处理中', value: String(active.length), detail: '需持续调查', trend: 'neutral' })
  elements['metric-approval'] = element('Metric', { label: '待审批', value: String(data.approvals.length), detail: 'R1 人工门禁', trend: data.approvals.length ? 'up' : 'neutral' })
  elements['metric-critical'] = element('Metric', { label: '严重故障', value: String(critical.length), detail: 'critical', trend: critical.length ? 'up' : 'neutral' })
  elements['metric-resolved'] = element('Metric', { label: '已恢复', value: String(resolved.length), detail: '已验证', trend: resolved.length ? 'down' : 'neutral' })
  elements.priority = element('Callout', {
    type: priority?.status === 'AWAITING_APPROVAL' ? 'important' : 'info',
    title: '优先处理',
    content: priority
      ? `${priority.alert_name} · ${priority.description}`
      : '当前没有活动事故。',
  })
  elements['queue-title'] = element('Heading', { text: '事故队列', level: 'h2' })
  elements['incident-table'] = element('Table', {
    columns: [
      { header: '状态', key: 'status', width: 20 },
      { header: '级别', key: 'severity', width: 10 },
      { header: '故障', key: 'incident', width: 34 },
      { header: '更新时间', key: 'updated', width: 16 },
    ],
    rows: data.incidents.slice(0, 8).map((incident) => ({
      status: incident.status,
      severity: incident.severity,
      incident: incident.alert_name,
      updated: compactTime(incident.updated_at),
    })),
    borderStyle: 'single',
    headerColor: 'cyan',
  })
  elements['safety-line'] = element('StatusLine', {
    text: 'R2 数据库/跨服务动作禁用，R3 动作永久禁止。',
    status: 'warning',
  })
}

function addApprovals(elements: Record<string, UIElement>, data: DashboardData) {
  elements['view-approvals'] = element('Box', { flexDirection: 'column', gap: 1 }, [
    'approval-heading',
    'approval-summary',
    'approval-table',
  ])
  elements['approval-heading'] = element('Heading', { text: '待审批队列', level: 'h2' })
  elements['approval-summary'] = element('Callout', {
    type: data.approvals.length ? 'important' : 'info',
    title: data.approvals.length ? `${data.approvals.length} 项等待人工决策` : '没有待审批项',
    content: data.approvals.length
      ? '审批前核对事故、目标、runbook、风险等级、计划哈希与过期时间。'
      : '当前控制面没有需要人工决策的 R1 动作。',
  })
  elements['approval-table'] = element('Table', {
    columns: [
      { header: '事故', key: 'incident', width: 28 },
      { header: '动作', key: 'action', width: 24 },
      { header: '目标', key: 'target', width: 18 },
      { header: '风险', key: 'risk', width: 8 },
      { header: '过期', key: 'expires', width: 16 },
    ],
    rows: data.approvals.slice(0, 8).map((approval) => ({
      incident: approval.incident?.alert_name || approval.incident_id,
      action: approval.runbook_ref,
      target: approval.target,
      risk: approval.risk_level,
      expires: compactTime(approval.expires_at),
    })),
    borderStyle: 'single',
    headerColor: 'yellow',
  })
}

function addScenarios(elements: Record<string, UIElement>, data: DashboardData) {
  elements['view-scenarios'] = element('Box', { flexDirection: 'column', gap: 1 }, [
    'scenario-heading',
    'scenario-boundary',
    'scenario-table',
  ])
  elements['scenario-heading'] = element('Heading', { text: '演练场景', level: 'h2' })
  elements['scenario-boundary'] = element('StatusLine', {
    text: '场景只作用于 local-demo；启动能力仅开放给 scenario_operator。',
    status: 'info',
  })
  elements['scenario-table'] = element('Table', {
    columns: [
      { header: '场景', key: 'scenario', width: 30 },
      { header: '类别', key: 'category', width: 14 },
      { header: 'Runbook', key: 'runbook', width: 26 },
      { header: '说明', key: 'description', width: 42 },
    ],
    rows: data.scenarios.slice(0, 8).map((scenario) => ({
      scenario: scenario.id,
      category: scenario.category,
      runbook: scenario.allowlisted_runbooks?.join(', ') || '未声明',
      description: scenario.description,
    })),
    borderStyle: 'single',
    headerColor: 'cyan',
  })
}

function addSystem(elements: Record<string, UIElement>, data: DashboardData) {
  elements['view-system'] = element('Box', { flexDirection: 'column', gap: 1 }, [
    'system-heading',
    'system-grid',
    'system-safety',
  ])
  elements['system-heading'] = element('Heading', { text: '系统边界', level: 'h2' })
  elements['system-grid'] = element('Box', { flexDirection: 'column', gap: 0 }, [
    'system-api',
    'system-version',
    'system-environment',
    'system-actions',
  ])
  elements['system-api'] = element('KeyValue', { label: 'Control API', value: data.health.status, labelColor: 'cyan' })
  elements['system-version'] = element('KeyValue', { label: '版本', value: data.health.version, labelColor: 'cyan' })
  elements['system-environment'] = element('KeyValue', { label: '环境', value: data.health.environment, labelColor: 'cyan' })
  elements['system-actions'] = element('KeyValue', { label: '恢复动作', value: data.health.actions_enabled ? '审批后启用' : '关闭', labelColor: 'cyan' })
  elements['system-safety'] = element('Callout', {
    type: 'important',
    title: '安全红线',
    content: '不连接真实生产集群；不暴露任意 Shell、kubectl、Secrets、pods/exec 或集群级写权限。',
  })
}

function findPriorityIncident(incidents: DashboardData['incidents']) {
  const awaitingApproval = incidents.find((incident) => incident.status === 'AWAITING_APPROVAL')
  if (awaitingApproval) return awaitingApproval
  const rank: Record<string, number> = { critical: 0, warning: 1, info: 2 }
  return [...incidents].sort((left, right) => (rank[left.severity] ?? 9) - (rank[right.severity] ?? 9))[0]
}

function compactTime(value: string) {
  return value.replace('T', ' ').replace(/(\.\d+)?Z$/, '').slice(0, 16)
}

function element(type: string, props: Record<string, unknown>, children: string[] = []): UIElement {
  return { type, props, children }
}
