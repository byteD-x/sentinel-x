import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Clock3, FileCheck2, Sparkles } from 'lucide-react'
import { useSSE } from '../hooks/useSSE'
import type { SSEMessage } from '../hooks/useSSE'
import styles from './IncidentDetailPage.module.css'

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface TimelineEvent {
  id: string
  sequence: number
  event_type: string
  actor: string
  payload: Record<string, unknown>
  timestamp: string
}

interface IncidentDetail {
  id: string
  status: string
  severity: string
  alert_name: string
  description: string
  created_at: string
  updated_at: string
  resolved_at: string | null
  version: number
}

interface ApprovalItem {
  id: string
  incident_id: string
  plan_id: string
  runbook_ref: string
  target: string
  parameters: Record<string, unknown>
  risk_level: string
  plan_hash: string
  status: string
  created_at: string
  expires_at: string
  decided_at: string | null
  decided_by: string | null
  decision_reason: string | null
}

// ---------------------------------------------------------------------------
// 标签映射
// ---------------------------------------------------------------------------

const EVENT_LABELS: Record<string, string> = {
  'incident.created': '事故创建',
  'incident.status_changed': '状态变更',
  'evidence.collected': '证据收集',
  'hypothesis.generated': '假设生成',
  'plan.proposed': '方案提出',
  'approval.requested': '审批请求',
  'approval.decided': '审批决定',
  'action.started': '动作执行',
  'action.completed': '动作完成',
  'recovery.verified': '恢复验证',
  'incident.escalated': '升级人工',
  'error.occurred': '发生错误',
}

const RISK_LABELS: Record<string, string> = {
  R0: '只读',
  R1: '可逆（需审批）',
  R2: '高风险（禁用）',
  R3: '永久禁止',
}

const APPROVAL_STATUS: Record<string, { label: string; className: string }> = {
  pending: { label: '待审批', className: styles.apPending },
  approved: { label: '已批准', className: styles.apApproved },
  rejected: { label: '已拒绝', className: styles.apRejected },
  expired: { label: '已过期', className: styles.apExpired },
}

const STATUS_LABELS: Record<string, string> = {
  DETECTED: '已发现',
  TRIAGING: '分诊中',
  DIAGNOSING: '调查中',
  PLAN_PROPOSED: '方案待审',
  AWAITING_APPROVAL: '等待审批',
  EXECUTING: '执行中',
  VERIFYING: '验证中',
  RESOLVED: '已恢复',
  ESCALATED: '已升级',
  FAILED: '失败',
}

function mergeTimelineEvents(prev: TimelineEvent[], incoming: TimelineEvent[]) {
  const byKey = new Map<string, TimelineEvent>()
  for (const event of [...prev, ...incoming]) {
    byKey.set(event.id || `${event.sequence}:${event.event_type}`, event)
  }
  return Array.from(byKey.values()).sort((a, b) => a.sequence - b.sequence)
}

function formatConfidence(value: unknown) {
  const numeric = Number(value || 0)
  const normalized = numeric <= 1 ? numeric * 100 : numeric
  return `${Math.round(normalized)}%`
}

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [incident, setIncident] = useState<IncidentDetail | null>(null)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [decidingId, setDecidingId] = useState<string | null>(null)
  const [confirmApproval, setConfirmApproval] = useState<ApprovalItem | null>(null)

  // 加载数据
  const fetchData = useCallback(async () => {
    if (!id) return
    try {
      const [incRes, tlRes, apRes] = await Promise.all([
        fetch(`/api/incidents/${id}`),
        fetch(`/api/incidents/${id}/timeline`),
        fetch(`/api/incidents/${id}/approvals`),
      ])

      if (!incRes.ok) throw new Error(`HTTP ${incRes.status}`)
      setIncident(await incRes.json())

      if (tlRes.ok) {
        const tlData = await tlRes.json()
        setTimeline(prev => mergeTimelineEvents(prev, tlData.events || []))
      }

      if (apRes.ok) {
        const apData = await apRes.json()
        setApprovals(apData.items || [])
      }

      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  // SSE 实时更新
  const handleSSEMessage = useCallback((msg: SSEMessage) => {
    if (msg.type === 'timeline_event' && msg.event) {
      setTimeline(prev => mergeTimelineEvents(prev, [msg.event!]))
      if (
        msg.event.event_type === 'approval.requested'
        || msg.event.event_type === 'approval.decided'
      ) {
        fetchData()
      }
    }
    if (msg.type === 'status' && msg.status) {
      setIncident(prev => prev ? { ...prev, status: msg.status! } : prev)
    }
  }, [fetchData])

  useSSE(id, handleSSEMessage, !!id)

  useEffect(() => { fetchData() }, [fetchData])

  // 审批决定
  const handleDecide = async (approvalId: string, approved: boolean, reason: string) => {
    if (!id) return
    setDecidingId(approvalId)
    try {
      const res = await fetch(`/api/incidents/${id}/approvals/${approvalId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, reason }),
      })
      if (!res.ok) {
        const err = await res.json()
        alert(`操作失败: ${err.detail || '未知错误'}`)
        return
      }
      setConfirmApproval(null)
      await fetchData()
    } catch (e) {
      alert(`操作失败: ${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setDecidingId(null)
    }
  }

  // 收集证据和假设
  const evidenceEvents = timeline.filter(e => e.event_type === 'evidence.collected')
  const hypothesisEvents = timeline.filter(e => e.event_type === 'hypothesis.generated')
  const pendingApprovals = approvals.filter(a => a.status === 'pending')
  const latestHypothesis = hypothesisEvents[hypothesisEvents.length - 1]

  if (loading) return <div className={styles.loading}>加载中...</div>
  if (error) return <div className={styles.error}>⚠️ {error}</div>
  if (!incident) return <div className={styles.error}>事故不存在</div>

  return (
    <div>
      <Link to="/" className={styles.back}><ArrowLeft size={15} aria-hidden="true" /> 返回事故队列</Link>

      {/* 标题区 */}
      <div className={styles.header}>
        <h1 className={styles.title}>{incident.alert_name}</h1>
        <div className={styles.meta}>
          <span className={`${styles.statusBadge} ${styles[`status_${incident.status}`] || ''}`}>
            {STATUS_LABELS[incident.status] || incident.status}
          </span>
          <span className={styles.severity}>{incident.severity}</span>
          <span>ID: {incident.id.slice(0, 8)}...</span>
          <span>版本: {incident.version}</span>
        </div>
      </div>

      <div className={styles.summaryGrid}>
        <div className={`${styles.card} ${styles.descriptionCard}`}>
          <h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 事故摘要</h2>
          <p>{incident.description}</p>
        </div>
        <div className={`${styles.card} ${styles.diagnosisCard}`}>
          <div className={styles.diagnosisTitle}><Sparkles size={15} aria-hidden="true" /><span>当前根因假设</span></div>
          {latestHypothesis ? (
            <>
              <strong className={styles.diagnosisStatement}>
                {String(latestHypothesis.payload.statement || '已收敛到主要异常信号')}
              </strong>
              <div className={styles.diagnosisMeta}>
                <span>{String(latestHypothesis.payload.affected_service || latestHypothesis.payload.category || 'unknown')}</span>
                <b>{formatConfidence(latestHypothesis.payload.confidence)} confidence</b>
              </div>
              <div className={styles.confidenceTrack} aria-label="根因置信度">
                <span style={{ width: `${Math.min(100, Number(latestHypothesis.payload.confidence || 0) * 100)}%` }} />
              </div>
            </>
          ) : (
            <span className={styles.empty}>等待诊断证据</span>
          )}
        </div>
      </div>

      {/* 待审批卡片 — 最重要的交互 */}
      {pendingApprovals.length > 0 && (
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>
            <Clock3 size={15} aria-hidden="true" /> 待审批动作 ({pendingApprovals.length})
          </h2>
          {pendingApprovals.map(ap => (
            <div key={ap.id} className={styles.approvalItem}>
              <div className={styles.approvalHeader}>
                <div className={styles.approvalInfo}>
                  <span className={styles.approvalRunbook}>{ap.runbook_ref}</span>
                  <span className={styles.approvalTarget}>→ {ap.target}</span>
                  <span className={styles.approvalRisk}>
                    {RISK_LABELS[ap.risk_level] || ap.risk_level}
                  </span>
                </div>
                <span className={styles.approvalHash}>
                  hash: {ap.plan_hash.slice(0, 12)}
                </span>
                <span className={styles.approvalExpiry}>
                  过期: {new Date(ap.expires_at).toLocaleTimeString('zh-CN')}
                </span>
              </div>

              {Object.keys(ap.parameters).length > 0 && (
                <pre className={styles.timelinePayload}>
                  {JSON.stringify(ap.parameters, null, 2)}
                </pre>
              )}

              <div className={styles.approvalActions}>
                <button
                  className={styles.btnApprove}
                  disabled={decidingId === ap.id}
                  onClick={() => setConfirmApproval(ap)}
                >
                  {decidingId === ap.id ? '处理中...' : '审核批准'}
                </button>
                <button
                  className={styles.btnReject}
                  disabled={decidingId === ap.id}
                  onClick={() => handleDecide(ap.id, false, '证据不足或风险过高')}
                >
                  {decidingId === ap.id ? '处理中...' : '拒绝'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 审批历史 */}
      {approvals.filter(a => a.status !== 'pending').length > 0 && (
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>审批记录</h2>
          {approvals.filter(a => a.status !== 'pending').map(ap => {
            const st = APPROVAL_STATUS[ap.status] || { label: ap.status, className: '' }
            return (
              <div key={ap.id} className={styles.historyItem}>
                <span className={`${styles.apBadge} ${st.className}`}><CheckCircle2 size={12} aria-hidden="true" /> {st.label}</span>
                <span className={styles.apRunbook}>{ap.runbook_ref} → {ap.target}</span>
                {ap.decided_by && <span className={styles.apBy}>操作人: {ap.decided_by}</span>}
                {ap.decision_reason && (
                  <span className={styles.apReason}>原因: {ap.decision_reason}</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* 证据摘要 */}
      {evidenceEvents.length > 0 && (
        <div className={styles.card}>
          <h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 证据收集 ({evidenceEvents.length})</h2>
          {evidenceEvents.map(e => (
            <div key={e.id} className={styles.evidenceItem}>
              <span className={styles.evidenceSource}>
                {String(e.payload.source || 'unknown')}
              </span>
              <span className={styles.evidenceSummary}>
                {String(e.payload.summary || '')}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 假设摘要 */}
      {hypothesisEvents.length > 0 && (
        <div className={styles.card}>
          <h2 className={styles.cardTitle}><Sparkles size={15} aria-hidden="true" /> 根因假设 ({hypothesisEvents.length})</h2>
          {hypothesisEvents.map(e => (
            <div key={e.id} className={styles.hypothesisItem}>
              <div className={styles.hypothesisMeta}>
                <span className={styles.hypothesisCategory}>
                  {String(e.payload.category || 'unknown')}
                </span>
                <span className={styles.hypothesisConfidence}>
                  置信度: {formatConfidence(e.payload.confidence)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 时间线 */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}><Clock3 size={15} aria-hidden="true" /> 调查时间线</h2>
        {timeline.length === 0 ? (
          <p className={styles.empty}>暂无事件</p>
        ) : (
          <div className={styles.timeline}>
            {timeline.map(event => (
              <div key={event.id} className={styles.timelineItem}>
                <div className={styles.timelineDot} />
                <div className={styles.timelineContent}>
                  <div className={styles.timelineHeader}>
                    <span className={styles.timelineType}>
                      {EVENT_LABELS[event.event_type] || event.event_type}
                    </span>
                    <span className={styles.timelineActor}>{event.actor}</span>
                    <span className={styles.timelineTime}>
                      {new Date(event.timestamp).toLocaleTimeString('zh-CN')}
                    </span>
                  </div>
                  {Object.keys(event.payload).length > 0 && (
                    <pre className={styles.timelinePayload}>
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {confirmApproval && (
        <div className={styles.modalBackdrop} role="presentation">
          <div
            className={styles.confirmDialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="approval-confirm-title"
          >
            <h2 id="approval-confirm-title" className={styles.confirmTitle}>
              确认批准 R1 动作
            </h2>
            <dl className={styles.confirmDetails}>
              <div>
                <dt>Runbook</dt>
                <dd>{confirmApproval.runbook_ref}</dd>
              </div>
              <div>
                <dt>目标</dt>
                <dd>{confirmApproval.target}</dd>
              </div>
              <div>
                <dt>风险</dt>
                <dd>{RISK_LABELS[confirmApproval.risk_level] || confirmApproval.risk_level}</dd>
              </div>
              <div>
                <dt>Plan hash</dt>
                <dd>{confirmApproval.plan_hash.slice(0, 16)}</dd>
              </div>
              <div>
                <dt>过期时间</dt>
                <dd>{new Date(confirmApproval.expires_at).toLocaleString('zh-CN')}</dd>
              </div>
            </dl>
            <div className={styles.confirmActions}>
              <button
                type="button"
                className={styles.btnReject}
                onClick={() => setConfirmApproval(null)}
              >
                取消
              </button>
              <button
                type="button"
                className={styles.btnApprove}
                disabled={decidingId === confirmApproval.id}
                onClick={() => handleDecide(
                  confirmApproval.id,
                  true,
                  '已核对动作、目标、风险和计划哈希，批准执行',
                )}
              >
                确认批准
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
