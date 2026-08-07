import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Clock3, ClipboardCheck, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
import { INCIDENT_STATUS_LABELS, ROLE_LABELS, SEVERITY_LABELS, actionLabel, incidentDescription, riskLabel, serviceLabel } from '../lib/presentation'
import styles from './ApprovalsPage.module.css'

interface ApprovalIncident {
  id: string
  status: string
  severity: string
  alert_name: string
  description: string
  updated_at: string
}

interface ApprovalItem {
  id: string
  incident_id: string
  runbook_ref: string
  target: string
  parameters: Record<string, unknown>
  risk_level: string
  plan_hash: string
  status: string
  created_at: string
  expires_at: string
  incident: ApprovalIncident
}

const FILTERS = [
  { value: 'pending', label: '待审批' },
  { value: 'all', label: '全部记录' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'expired', label: '已过期' },
]

const STATUS_LABELS: Record<string, string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
}

const STATUS_CLASS: Record<string, string> = {
  pending: styles.pending,
  approved: styles.approved,
  rejected: styles.rejected,
  expired: styles.expired,
}

const SEVERITY_CLASS: Record<string, string> = {
  critical: styles.critical,
  warning: styles.warning,
  info: styles.info,
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ApprovalsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const statusFilter = searchParams.get('status') || 'pending'
  const [items, setItems] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const role = currentRole()

  const fetchApprovals = useCallback(async () => {
    setLoading(true)
    try {
      const response = await apiFetch(`/api/approvals?status=${encodeURIComponent(statusFilter)}`)
      const data = await response.json()
      setItems(data.items || [])
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载审批队列失败')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { fetchApprovals() }, [fetchApprovals])

  const handleFilterChange = (value: string) => {
    setSearchParams(value === 'pending' ? {} : { status: value })
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}><ClipboardCheck size={14} aria-hidden="true" /> 恢复审批</div>
          <h1 className={styles.title}>恢复操作审批</h1>
          <p className={styles.subtitle}>先核对目标服务、影响范围和风险级别，再提交审批决定。当前角色：{ROLE_LABELS[role] || '只读'}。</p>
        </div>
        <button className={styles.refreshButton} type="button" onClick={fetchApprovals} disabled={loading} title="刷新审批队列">
          <RefreshCw size={15} className={loading ? styles.spin : ''} aria-hidden="true" />
          刷新
        </button>
      </header>

      <section className={styles.queueSummary} aria-label="审批队列摘要">
        <div className={styles.summaryLead}>
          <span className={styles.summaryIcon}><ShieldCheck size={17} aria-hidden="true" /></span>
          <div>
            <strong>{statusFilter === 'pending' ? `${items.length} 项待审批` : `${items.length} 条审批记录`}</strong>
          <span>{statusFilter === 'pending' ? '通过后才会执行恢复操作' : '已提交的审批决定'}</span>
          </div>
        </div>
        <div className={styles.filters} aria-label="审批状态筛选">
          {FILTERS.map(filter => (
            <button
              key={filter.value}
              className={filter.value === statusFilter ? styles.filterActive : styles.filterButton}
              type="button"
              aria-pressed={filter.value === statusFilter}
              onClick={() => handleFilterChange(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </section>

      {error && (
        <div className={styles.error} role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>暂时无法读取审批队列：{error}。请稍后重试。</span>
        </div>
      )}

      {loading ? (
        <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} />加载审批队列</div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>
          <ClipboardCheck size={24} aria-hidden="true" />
          <strong>{statusFilter === 'pending' ? '当前没有待审批的恢复操作' : '没有符合条件的审批记录'}</strong>
          <span>{statusFilter === 'pending' ? '新的恢复方案会出现在这里。' : '切换上方筛选查看其他记录。'}</span>
        </div>
      ) : (
        <section className={styles.queue} aria-label="审批记录" role="list">
          {items.map(item => (
            <article key={item.id} className={styles.approvalRow} role="listitem">
              <span className={`${styles.statusRail} ${STATUS_CLASS[item.status] || ''}`} aria-hidden="true" />
              <div className={styles.approvalMain}>
                <div className={styles.rowTopline}>
                  <span className={`${styles.severity} ${SEVERITY_CLASS[item.incident.severity] || ''}`}>{SEVERITY_LABELS[item.incident.severity] || item.incident.severity}</span>
                  <span className={`${styles.status} ${STATUS_CLASS[item.status] || ''}`}>{STATUS_LABELS[item.status] || item.status}</span>
                  <span className={styles.expiry}><Clock3 size={13} aria-hidden="true" />{item.status === 'pending' ? `审批截止 ${formatDate(item.expires_at)}` : `审批于 ${formatDate(item.created_at)}`}</span>
                </div>
                <h2>{actionLabel(item.runbook_ref)}</h2>
                <div className={styles.targetLine}>
                  <span>目标服务</span>
                  <strong>{serviceLabel(item.target)}</strong>
                  <span className={styles.risk}>{riskLabel(item.risk_level)}</span>
                </div>
                <Link className={styles.incidentLink} to={`/incidents/${item.incident_id}`}>
                  {incidentDescription(item.incident.alert_name)}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              </div>
              <div className={styles.approvalMeta}>
                <div><span>故障状态</span><strong>{INCIDENT_STATUS_LABELS[item.incident.status] || item.incident.status}</strong></div>
                <div><span>提出时间</span><time dateTime={item.created_at}>{formatDate(item.created_at)}</time></div>
                <Link className={styles.detailButton} to={`/incidents/${item.incident_id}`}>
                  查看故障详情 <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
                <details className={styles.technicalDetails}>
                  <summary>查看技术字段</summary>
                  <code>动作编号：{item.runbook_ref}<br />计划校验：{item.plan_hash.slice(0, 16)}…</code>
                </details>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  )
}
