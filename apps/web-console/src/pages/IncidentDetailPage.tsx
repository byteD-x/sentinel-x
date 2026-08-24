import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  FileClock,
  Gauge,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { EvidenceSpine } from '../features/incidents'
import type { ApprovalSummary, IncidentOverview } from '../features/incidents'
import { useSSE } from '../hooks/useSSE'
import type { SSEMessage } from '../hooks/useSSE'
import { apiFetch, currentRole } from '../lib/api'
import {
  INCIDENT_STATUS_LABELS,
  ROLE_LABELS,
  SEVERITY_LABELS,
  actionLabel,
  actorLabel,
  incidentDescription,
  riskLabel,
  serviceLabel,
} from '../lib/presentation'
import styles from './IncidentDetailPage.module.css'

interface TimelineEvent {
  id: string
  sequence: number
  event_type: string
  actor: string
  payload: Record<string, unknown>
  timestamp: string
}

interface ApprovalItem extends ApprovalSummary {
  incident_id: string
  plan_id: string
  parameters: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  created_at: string
  decided_at: string | null
  decided_by: string | null
  decision_reason: string | null
}

const EVENT_LABELS: Record<string, string> = {
  'incident.created': '告警接入',
  'incident.status_changed': '状态变更',
  'scenario.started': '演练启动',
  'evidence.collected': '调查证据',
  'hypothesis.generated': '调查判断',
  'plan.proposed': '恢复方案',
  'approval.requested': '提交审批',
  'approval.decided': '审批结果',
  'action.started': '开始执行',
  'action.completed': '执行结果',
  'recovery.verified': '恢复验证',
  'incident.escalated': '升级人工',
  'error.occurred': '处理失败',
}

const APPROVAL_STATUS: Record<ApprovalItem['status'], string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
}

function mergeTimelineEvents(previous: TimelineEvent[], incoming: TimelineEvent[]) {
  const byKey = new Map<string, TimelineEvent>()
  for (const event of [...previous, ...incoming]) {
    byKey.set(event.id || `${event.sequence}:${event.event_type}`, event)
  }
  return Array.from(byKey.values()).sort((left, right) => left.sequence - right.sequence)
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatConfidence(value: number | null) {
  if (value === null) return '待评估'
  return `${Math.round((value <= 1 ? value * 100 : value))}%`
}

function eventSummary(event: TimelineEvent) {
  const payload = event.payload
  const value = (key: string, fallback: string) => String(payload[key] ?? fallback)
  switch (event.event_type) {
    case 'incident.status_changed':
      return `${INCIDENT_STATUS_LABELS[value('to', '')] || value('to', '状态已更新')} · ${value('reason', '阶段推进')}`
    case 'evidence.collected':
      return incidentDescription(value('summary', '新增调查证据'))
    case 'hypothesis.generated':
      return incidentDescription(value('statement', '形成调查判断'))
    case 'approval.requested':
      return `${actionLabel(payload.runbook_ref)} · ${serviceLabel(payload.target)}`
    case 'approval.decided':
      return `${payload.approved ? '已批准' : '已拒绝'} · ${value('reason', '未提供原因')}`
    case 'action.started':
      return `${actionLabel(payload.runbook_ref)}开始执行`
    case 'action.completed':
      return `执行状态：${value('status', '未记录')}`
    case 'recovery.verified':
      return `验证结果：${value('result', '未记录')} · 观察 ${value('window_seconds', '0')} 秒`
    default:
      return value('reason', value('summary', '处置记录已更新'))
  }
}

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [overview, setOverview] = useState<IncidentOverview | null>(null)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [decidingId, setDecidingId] = useState<string | null>(null)
  const [confirmApproval, setConfirmApproval] = useState<ApprovalSummary | null>(null)
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [decisionMode, setDecisionMode] = useState<'approve' | 'reject'>('approve')
  const [rejectReason, setRejectReason] = useState('')
  const [rejectDetails, setRejectDetails] = useState('')
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const refreshTimerRef = useRef<number | null>(null)
  const role = currentRole()

  const fetchData = useCallback(async () => {
    if (!id) return
    try {
      const [overviewResponse, timelineResponse, approvalsResponse] = await Promise.all([
        apiFetch(`/api/incidents/${id}`),
        apiFetch(`/api/incidents/${id}/timeline`),
        apiFetch(`/api/incidents/${id}/approvals`),
      ])
      const [overviewData, timelineData, approvalsData] = await Promise.all([
        overviewResponse.json() as Promise<IncidentOverview>,
        timelineResponse.json() as Promise<{ events?: TimelineEvent[] }>,
        approvalsResponse.json() as Promise<{ items?: ApprovalItem[] }>,
      ])
      setOverview(overviewData)
      // 首次加载或路由切换以服务端快照为准，避免把上一个事故的证据带入当前页面。
      setTimeline(timelineData.events || [])
      setApprovals(approvalsData.items || [])
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载故障详情失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current !== null) return
    refreshTimerRef.current = window.setTimeout(() => {
      refreshTimerRef.current = null
      void fetchData()
    }, 100)
  }, [fetchData])

  const handleSSEMessage = useCallback((message: SSEMessage) => {
    if (message.type === 'timeline_event' && message.event) {
      setTimeline(previous => mergeTimelineEvents(previous, [message.event!]))
    }
    if (message.type === 'timeline_event' || message.type === 'status') scheduleRefresh()
  }, [scheduleRefresh])

  const streamStatus = useSSE(id, handleSSEMessage, Boolean(id))

  useEffect(() => {
    setOverview(null)
    setTimeline([])
    setApprovals([])
    void fetchData()
  }, [fetchData])
  useEffect(() => () => {
    if (refreshTimerRef.current !== null) window.clearTimeout(refreshTimerRef.current)
  }, [])
  useEffect(() => {
    if (!confirmApproval) return
    const dialog = dialogRef.current
    const focusTarget = dialog?.querySelector<HTMLElement>('[data-modal-autofocus]')
    focusTarget?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfirmApproval(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previousFocusRef.current?.focus()
    }
  }, [confirmApproval])

  const handleDecide = async (approvalId: string, approved: boolean, reason: string) => {
    if (!id) return
    setDecidingId(approvalId)
    setDecisionError(null)
    try {
      await apiFetch(`/api/incidents/${id}/approvals/${approvalId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, reason }),
      })
      setConfirmApproval(null)
      setRejectReason('')
      setRejectDetails('')
      await fetchData()
    } catch (cause) {
      setDecisionError(cause instanceof Error ? cause.message : '提交审批失败')
    } finally {
      setDecidingId(null)
    }
  }

  if (loading) return <div className={styles.loading}>正在读取事故指挥面板…</div>
  if (error) return <div className={styles.error} role="alert"><AlertTriangle size={18} aria-hidden="true" /> {error}</div>
  if (!overview) return <div className={styles.error}>故障不存在</div>

  const activeApproval = overview.active_approval
  const canApprove = overview.capabilities.can_decide_approval
  const completedApprovals = approvals.filter(approval => approval.status !== 'pending')
  const sourceLabel = overview.environment.source_mode === 'fixture' ? '演练数据' : '观测数据'

  return (
    <div className={styles.page}>
      <Link to="/" className={styles.back}><ArrowLeft size={15} aria-hidden="true" /> 返回故障总览</Link>

      <header className={styles.commandHeader}>
        <div className={styles.headerTopline}>
          <span className={styles.eyebrow}>事故指挥台 · {overview.environment.profile.toUpperCase()}</span>
          <span className={styles.freshness}>更新于 {formatDate(overview.updated_at)}</span>
        </div>
        <div className={styles.identityRow}>
          <h1>{incidentDescription(overview.alert_name)}</h1>
          <span className={styles.boundaryBadge}>{sourceLabel} · {overview.environment.data_scope === 'exercise' ? '隔离演练' : overview.environment.data_scope}</span>
        </div>
        <div className={styles.meta}>
          <span className={`${styles.statusBadge} ${styles[`status_${overview.status}`] || ''}`}>{INCIDENT_STATUS_LABELS[overview.status] || overview.status}</span>
          <span className={`${styles.severity} ${styles[`severity_${overview.severity}`] || ''}`}>{SEVERITY_LABELS[overview.severity] || overview.severity}</span>
          <span>事件流 {streamStatus === 'connected' ? '已连接' : streamStatus === 'reconnecting' ? '重连中' : '待连接'}</span>
          <span>角色 {ROLE_LABELS[role] || role}</span>
          <code>INC {overview.id.slice(0, 8)}</code>
        </div>
      </header>

      <section className={styles.signalGrid} aria-label="事故摘要">
        <article className={styles.signalPanel}>
          <div className={styles.panelLabel}><Gauge size={15} aria-hidden="true" /> 当前影响</div>
          <p className={styles.impactText}>{incidentDescription(overview.impact?.summary || overview.description)}</p>
          <span className={styles.sourceNote}>{overview.impact ? `${sourceLabel} · ${formatDate(overview.impact.observed_at)}` : '尚无独立影响观测'}</span>
        </article>
        <article className={styles.signalPanel}>
          <div className={styles.panelLabel}><Search size={15} aria-hidden="true" /> 首要判断</div>
          {overview.top_hypothesis ? (
            <>
              <p className={styles.hypothesisText}>{incidentDescription(overview.top_hypothesis.statement)}</p>
              <div className={styles.hypothesisMeta}>
                <span>证据 {overview.top_hypothesis.supporting_evidence_count} 条</span>
                <strong>置信度 {formatConfidence(overview.top_hypothesis.confidence)}</strong>
                <span>{sourceLabel}</span>
              </div>
            </>
          ) : (
            <p className={styles.emptySignal}>证据尚不足，等待调查阶段形成判断。</p>
          )}
        </article>
      </section>

      <section className={styles.decisionBand} data-kind={overview.next_decision.kind}>
        <span className={styles.decisionIcon}><ArrowRight size={18} aria-hidden="true" /></span>
        <div>
          <span className={styles.decisionLabel}>当前唯一决策</span>
          <h2>{overview.next_decision.title}</h2>
          <p>{overview.next_decision.reason}</p>
        </div>
        {overview.next_decision.target_href && (
          <a className={styles.decisionLink} href={overview.next_decision.target_href}>进入决策 <ArrowRight size={15} aria-hidden="true" /></a>
        )}
      </section>

      <div className={styles.workbench}>
        <section className={styles.spineSection} aria-labelledby="evidence-spine-title">
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionKicker}>Evidence Spine</span>
              <h2 id="evidence-spine-title">处置证据链</h2>
            </div>
            <span>{overview.milestones.length} 个阶段记录</span>
          </div>
          <EvidenceSpine milestones={overview.milestones} />
        </section>

        <aside className={styles.decisionPanel} id="approval-section" aria-label="决策上下文">
          {activeApproval ? (
            <>
              <div className={styles.panelLabel}><ShieldCheck size={15} aria-hidden="true" /> R1 恢复审批</div>
              <h2>{actionLabel(activeApproval.runbook_ref)}</h2>
              <dl className={styles.approvalFacts}>
                <div><dt>目标服务</dt><dd>{serviceLabel(activeApproval.target)}</dd></div>
                <div><dt>风险级别</dt><dd>{riskLabel(activeApproval.risk_level)}</dd></div>
                <div><dt>审批截止</dt><dd>{formatDate(activeApproval.expires_at)}</dd></div>
              </dl>
              <details className={styles.technicalDetails}>
                <summary>计划完整性校验</summary>
                <code>{activeApproval.plan_hash}</code>
              </details>
              {decisionError && <div className={styles.inlineError} role="alert"><AlertTriangle size={15} aria-hidden="true" /> {decisionError}</div>}
              {canApprove ? (
                <div className={styles.approvalActions}>
                  <button
                    className={styles.btnApprove}
                    type="button"
                    disabled={decidingId === activeApproval.id}
                    onClick={event => {
                      previousFocusRef.current = event.currentTarget
                      setDecisionMode('approve')
                      setConfirmApproval(activeApproval)
                    }}
                  >批准恢复</button>
                  <button
                    className={styles.btnReject}
                    type="button"
                    disabled={decidingId === activeApproval.id}
                    onClick={event => {
                      previousFocusRef.current = event.currentTarget
                      setDecisionMode('reject')
                      setRejectReason('')
                      setRejectDetails('')
                      setConfirmApproval(activeApproval)
                    }}
                  >拒绝恢复</button>
                </div>
              ) : (
                <p className={styles.permissionNotice}>{overview.capabilities.denial_reason || '当前角色不能提交审批决定'}</p>
              )}
            </>
          ) : overview.latest_verification ? (
            <>
              <div className={styles.panelLabel}><CheckCircle2 size={15} aria-hidden="true" /> 恢复验证</div>
              <h2>{overview.latest_verification.passed ? '验证窗口已通过' : '验证窗口未通过'}</h2>
              <dl className={styles.approvalFacts}>
                <div><dt>观察窗口</dt><dd>{overview.latest_verification.window_seconds ?? 0} 秒</dd></div>
                <div><dt>恢复执行方</dt><dd>{overview.latest_verification.recovery_actor || '未记录'}</dd></div>
                <div><dt>数据来源</dt><dd>{sourceLabel}</dd></div>
              </dl>
            </>
          ) : (
            <>
              <div className={styles.panelLabel}><ShieldCheck size={15} aria-hidden="true" /> 执行边界</div>
              <h2>自动动作保持关闭</h2>
              <p className={styles.boundaryCopy}>当前没有待审批恢复操作。R2 高风险动作禁用，R3 动作永久禁止。</p>
            </>
          )}
        </aside>
      </div>

      {completedApprovals.length > 0 && (
        <section className={styles.historySection} aria-labelledby="approval-history-title">
          <div className={styles.sectionHeader}>
            <h2 id="approval-history-title">历史审批</h2>
            <span>{completedApprovals.length} 条记录</span>
          </div>
          <div className={styles.historyList}>
            {completedApprovals.map(approval => (
              <div key={approval.id} className={styles.historyItem}>
                <span data-status={approval.status}>{APPROVAL_STATUS[approval.status]}</span>
                <strong>{actionLabel(approval.runbook_ref)} → {serviceLabel(approval.target)}</strong>
                <time dateTime={approval.decided_at || approval.created_at}>{formatDate(approval.decided_at || approval.created_at)}</time>
                {approval.decision_reason && <p>{incidentDescription(approval.decision_reason)}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      <details className={styles.technicalLedger}>
        <summary><span><FileClock size={15} aria-hidden="true" /> 技术事件账本</span><span>{timeline.length} 条事件</span></summary>
        {timeline.length > 0 ? (
          <ol className={styles.timeline}>
            {timeline.map(event => (
              <li key={event.id} className={styles.timelineItem}>
                <div className={styles.timelineHeader}>
                  <strong>{EVENT_LABELS[event.event_type] || '处理事件'}</strong>
                  <span>{actorLabel(event.actor)}</span>
                  <time dateTime={event.timestamp}>{formatDate(event.timestamp)}</time>
                </div>
                <p>{eventSummary(event)}</p>
                {overview.capabilities.can_view_raw_evidence && Object.keys(event.payload).length > 0 && (
                  <details className={styles.eventPayload}>
                    <summary>原始字段</summary>
                    <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.emptyLedger}>暂无技术事件。</p>
        )}
      </details>

      {confirmApproval && (
        <div className={styles.modalBackdrop} role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setConfirmApproval(null) }}>
          <div ref={dialogRef} className={styles.confirmDialog} role="dialog" aria-modal="true" aria-labelledby="approval-confirm-title">
            <button type="button" className={styles.modalClose} aria-label="关闭对话框" title="关闭" onClick={() => setConfirmApproval(null)}><X size={17} aria-hidden="true" /></button>
            <span className={styles.sectionKicker}>R1 人工门禁</span>
            <h2 id="approval-confirm-title">{decisionMode === 'approve' ? '批准恢复操作' : '拒绝恢复操作'}</h2>
            <dl className={styles.confirmDetails}>
              <div><dt>操作</dt><dd>{actionLabel(confirmApproval.runbook_ref)}</dd></div>
              <div><dt>目标服务</dt><dd>{serviceLabel(confirmApproval.target)}</dd></div>
              <div><dt>风险级别</dt><dd>{riskLabel(confirmApproval.risk_level)}</dd></div>
              <div><dt>审批截止</dt><dd>{formatDate(confirmApproval.expires_at)}</dd></div>
            </dl>
            {decisionMode === 'reject' && (
              <div className={styles.rejectForm}>
                <label>拒绝原因
                  <select data-modal-autofocus value={rejectReason} onChange={event => setRejectReason(event.target.value)}>
                    <option value="">请选择原因</option>
                    <option value="evidence_insufficient">证据不足</option>
                    <option value="risk_too_high">风险不可接受</option>
                    <option value="target_mismatch">目标服务不匹配</option>
                    <option value="approval_expired">审批已过期</option>
                  </select>
                </label>
                <label>补充说明
                  <textarea value={rejectDetails} onChange={event => setRejectDetails(event.target.value)} rows={3} placeholder="记录审批依据，供后续值班人员查看" />
                </label>
              </div>
            )}
            <div className={styles.confirmActions}>
              <button type="button" className={styles.cancelButton} onClick={() => setConfirmApproval(null)}>取消</button>
              <button
                type="button"
                data-modal-autofocus={decisionMode === 'approve' ? '' : undefined}
                className={decisionMode === 'approve' ? styles.btnApprove : styles.btnReject}
                disabled={decidingId === confirmApproval.id || (decisionMode === 'reject' && !rejectReason)}
                onClick={() => handleDecide(
                  confirmApproval.id,
                  decisionMode === 'approve',
                  decisionMode === 'approve'
                    ? '已核对目标服务、影响范围和恢复方案，批准执行'
                    : `${rejectReason}${rejectDetails ? `：${rejectDetails}` : ''}`,
                )}
              >{decisionMode === 'approve' ? '批准恢复' : '拒绝恢复'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
