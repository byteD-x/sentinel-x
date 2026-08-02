import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Clock3, ClipboardCheck, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
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
  { value: 'pending', label: '待处理' },
  { value: 'all', label: '全部记录' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'expired', label: '已过期' },
]

const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
}

const INCIDENT_STATUS_LABELS: Record<string, string> = {
  DETECTED: '已发现', TRIAGING: '分诊中', DIAGNOSING: '调查中', PLAN_PROPOSED: '方案待审',
  AWAITING_APPROVAL: '等待审批', EXECUTING: '执行中', VERIFYING: '验证中', RESOLVED: '已恢复',
  ESCALATED: '已升级', FAILED: '失败',
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
          <div className={styles.eyebrow}><ClipboardCheck size={14} aria-hidden="true" /> 待处理审批 / 恢复动作</div>
          <h1 className={styles.title}>审批队列</h1>
          <p className={styles.subtitle}>这里列出需要人工确认的恢复动作。决定前，请先打开事故详情，核对影响、证据和执行目标。当前角色：{role === 'approver' ? '审批人' : '只读观察员'}。</p>
        </div>
        <button className={styles.refreshButton} type="button" onClick={fetchApprovals} disabled={loading} title="刷新审批队列">
          <RefreshCw size={15} className={loading ? styles.spin : ''} aria-hidden="true" />
          刷新队列
        </button>
      </header>

      <section className={styles.queueSummary} aria-label="审批队列摘要">
        <div className={styles.summaryLead}>
          <span className={styles.summaryIcon}><ShieldCheck size={17} aria-hidden="true" /></span>
          <div>
            <strong>{statusFilter === 'pending' ? `${items.length} 项等待人工判断` : `${items.length} 条审批记录`}</strong>
          <span>{statusFilter === 'pending' ? '恢复动作会在审批后才会执行' : '这里只展示已经留下记录的决定'}</span>
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
          <span>审批队列暂时不可用：{error}。已有页面不会提交写操作。</span>
        </div>
      )}

      {loading ? (
        <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} />加载审批记录</div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>
          <ClipboardCheck size={24} aria-hidden="true" />
          <strong>{statusFilter === 'pending' ? '当前没有待处理审批' : '没有匹配的审批记录'}</strong>
          <span>{statusFilter === 'pending' ? '新的 R1 计划进入控制面后，会出现在这里。' : '尝试切换状态筛选，或返回事故指挥室查看活跃事故。'}</span>
        </div>
      ) : (
        <section className={styles.queue} aria-label="审批记录" role="list">
          {items.map(item => (
            <article key={item.id} className={styles.approvalRow} role="listitem">
              <span className={`${styles.statusRail} ${STATUS_CLASS[item.status] || ''}`} aria-hidden="true" />
              <div className={styles.approvalMain}>
                <div className={styles.rowTopline}>
                  <span className={`${styles.severity} ${SEVERITY_CLASS[item.incident.severity] || ''}`}>{item.incident.severity}</span>
                  <span className={`${styles.status} ${STATUS_CLASS[item.status] || ''}`}>{STATUS_LABELS[item.status] || item.status}</span>
                  <span className={styles.expiry}><Clock3 size={13} aria-hidden="true" />{item.status === 'pending' ? `过期 ${formatDate(item.expires_at)}` : `决定于 ${formatDate(item.created_at)}`}</span>
                </div>
                <h2>{item.runbook_ref}</h2>
                <div className={styles.targetLine}>
                  <span>目标</span>
                  <strong>{item.target}</strong>
                  <span className={styles.risk}>可逆恢复动作</span>
                </div>
                <Link className={styles.incidentLink} to={`/incidents/${item.incident_id}`}>
                  {item.incident.alert_name}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              </div>
              <div className={styles.approvalMeta}>
                <div><span>事故状态</span><strong>{INCIDENT_STATUS_LABELS[item.incident.status] || item.incident.status}</strong></div>
                <div><span>计划哈希</span><code>{item.plan_hash.slice(0, 16)}…</code></div>
                <div><span>请求时间</span><time dateTime={item.created_at}>{formatDate(item.created_at)}</time></div>
                <Link className={styles.detailButton} to={`/incidents/${item.incident_id}`}>
                  查看上下文 <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  )
}
