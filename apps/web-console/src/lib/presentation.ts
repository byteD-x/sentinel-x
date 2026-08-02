export const INCIDENT_STATUS_LABELS: Record<string, string> = {
  DETECTED: '已发现',
  TRIAGING: '分诊中',
  DIAGNOSING: '调查中',
  PLAN_PROPOSED: '方案待审批',
  AWAITING_APPROVAL: '待审批',
  EXECUTING: '执行中',
  VERIFYING: '验证中',
  RESOLVED: '已恢复',
  ESCALATED: '已升级',
  FAILED: '失败',
}

export const SEVERITY_LABELS: Record<string, string> = {
  critical: '严重',
  warning: '警告',
  info: '提示',
}

export const ROLE_LABELS: Record<string, string> = {
  viewer: '只读',
  approver: '审批人',
  scenario_operator: '演练操作员',
  planner: '方案制定者',
  system: '系统服务',
}

export const RISK_LABELS: Record<string, string> = {
  R0: '只读',
  R1: '可回滚 · 需审批',
  R2: '高风险 · 已禁用',
  R3: '禁止执行',
}

export const CATEGORY_LABELS: Record<string, string> = {
  network: '网络连接',
  application: '应用服务',
  database: '数据存储',
  kubernetes: '容器平台',
  resource: '资源不足',
}

const SERVICE_LABELS: Record<string, string> = {
  'payment-api': '支付服务',
  'inventory-api': '库存服务',
  'order-api': '订单服务',
  payment: '支付服务',
  inventory: '库存服务',
  order: '订单服务',
}

const SCENARIO_LABELS: Record<string, string> = {
  'payment-latency@1': '支付服务变慢',
  'order-db-errors@1': '订单服务报错',
  'inventory-split-brain@1': '库存数据不一致',
  'payment-pod-crash@1': '支付服务崩溃',
  'inventory-cpu-saturation@1': '库存服务太忙',
  'order-bad-deployment@1': '订单服务版本有问题',
}

export function serviceLabel(value: unknown) {
  const text = String(value || '').trim()
  const normalized = text.toLowerCase()
  if (SERVICE_LABELS[text]) return SERVICE_LABELS[text]
  if (normalized.includes('redis') || normalized.includes('postgres') || normalized.includes('database')) return '数据服务'
  if (normalized.includes('kubernetes') || normalized.includes('cluster') || normalized.includes('deployment')) return '服务运行环境'
  return text.replace(/-api$/, '服务') || '相关服务'
}

export function incidentDescription(value: unknown) {
  const text = String(value || '暂时没有更多说明')
  const titles: Record<string, string> = {
    'Payment API High Latency': '支付服务响应变慢',
    'Order Service 5xx Error Rate': '订单服务频繁报错',
    'Inventory Stock Sync Lag': '库存同步变慢',
    'Inventory CPU Saturation': '库存服务太忙',
    'Payment API High Latency 指标异常': '支付服务响应时间异常',
    'payment-api 日志出现连续超时或错误': '支付服务日志持续出现超时和错误',
    '跨服务 Trace 将慢点收敛到同一依赖调用': '多条调用链指向同一依赖服务',
    'payment-api 的依赖调用异常是当前事故的主要根因': '支付服务依赖的另一个服务响应变慢，疑似为主要原因',
    '其他业务服务基线正常': '其他服务目前未发现异常',
  }
  if (titles[text]) return titles[text]
  return text
    .replace(/payment-api 的依赖调用异常是当前事故的主要根因/g, '支付服务依赖的另一个服务响应变慢，疑似为主要原因')
    .replace(/payment-api/g, '支付服务')
    .replace(/inventory-api/g, '库存服务')
    .replace(/order-api/g, '订单服务')
    .replace(/Payment API/g, '支付服务')
    .replace(/Order Service/g, '订单服务')
    .replace(/Inventory/g, '库存服务')
    .replace(/High Latency/g, '响应变慢')
    .replace(/\bTrace\b/g, '调用链')
    .replace(/\bp99\s*延迟/gi, '响应时间')
    .replace(/\bp99\b/gi, '响应时间')
    .replace(/\b5xx\s*错误率/gi, '报错比例')
    .replace(/\b5xx\b/gi, '报错')
    .replace(/CPU 使用率持续 >95%/g, '资源使用率持续很高')
    .replace(/\bCPU\b/g, '资源使用情况')
    .replace(/依赖调用/g, '依赖服务')
    .replace(/库存同步延迟/g, '库存同步时间')
}

export function scenarioLabel(value: string) {
  return SCENARIO_LABELS[value] || value.replace(/@\d+$/, '').replace(/-/g, ' ')
}

export function scenarioDescription(id: string, fallback: string) {
  const descriptions: Record<string, string> = {
    'payment-latency@1': '支付服务响应延迟升高，依赖库存服务连接超时。',
    'order-db-errors@1': '订单服务错误率升高，数据库连接不足。',
    'inventory-split-brain@1': '库存数据出现分叉，读请求返回不一致结果。',
    'payment-pod-crash@1': '支付服务实例崩溃，将自动重启。',
    'inventory-cpu-saturation@1': '库存服务资源耗尽，需要扩容。',
    'order-bad-deployment@1': '订单服务版本异常，需要回滚。',
  }
  return descriptions[id] || incidentDescription(fallback)
}

export function actionLabel(runbookRef: unknown) {
  const value = String(runbookRef || '')
  if (value.includes('scale')) return '扩容服务'
  if (value.includes('rollback')) return '回滚版本'
  if (value === 'no_op') return '自动恢复'
  if (value.includes('restart')) return '重启服务'
  return '恢复服务'
}

export function riskLabel(value: unknown) {
  const text = String(value || '')
  return RISK_LABELS[text] || text || '未标注'
}

export function evidenceSourceLabel(source: unknown) {
  const value = String(source || '').toLowerCase()
  if (value.includes('prom')) return '监控指标'
  if (value.includes('loki') || value.includes('log')) return '日志'
  if (value.includes('tempo') || value.includes('trace')) return '调用链'
  return '调查记录'
}

export function actorLabel(actor: unknown) {
  const value = String(actor || '')
  if (value.includes('system') || value.includes('alert')) return '系统'
  if (value.includes('scenario')) return '演练程序'
  if (value.includes('diagnostic') || value.includes('investigator')) return '调查服务'
  return '处理系统'
}

export function countEvidence(value: unknown) {
  if (typeof value === 'number') return String(value)
  const text = String(value || '').trim()
  if (!text) return '0'
  return String(text.split(',').filter(Boolean).length)
}
