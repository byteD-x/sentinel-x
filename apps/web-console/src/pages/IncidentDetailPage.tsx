import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock3, FileCheck2, Sparkles, X } from 'lucide-react'
import { useSSE } from '../hooks/useSSE'
import type { SSEMessage } from '../hooks/useSSE'
import { apiFetch, currentRole } from '../lib/api'
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

function confidencePercent(value: unknown) {
  const numeric = Number(value || 0)
  return Math.min(100, Math.max(0, numeric <= 1 ? numeric * 100 : numeric))
}

function textValue(payload: Record<string, unknown>, key: string, fallback = '未记录') {
  const value = payload[key]
  return value === undefined || value === null ? fallback : String(value)
}

function formatTimelineSummary(event: TimelineEvent) {
  const payload = event.payload
  switch (event.event_type) {
    case 'incident.created':
      return `由 ${textValue(payload, 'fingerprint', '告警入口')} 创建事故`
    case 'incident.status_changed':
      return `${textValue(payload, 'from')} -> ${textValue(payload, 'to')} · ${textValue(payload, 'reason', '系统状态更新')}`
    case 'scenario.started':
      return `启动 ${textValue(payload, 'scenario_id')} · 目标 ${textValue(payload, 'target')} · profile ${textValue(payload, 'profile')}`
    case 'evidence.collected':
      return `${textValue(payload, 'source')} 返回脱敏证据 · ${textValue(payload, 'summary')}`
    case 'hypothesis.generated':
      return `${textValue(payload, 'statement')} · 支持 ${textValue(payload, 'supporting_evidence', '0')} 条证据`
    case 'approval.requested':
      return `登记 ${textValue(payload, 'runbook_ref')} · 目标 ${textValue(payload, 'target')} · ${textValue(payload, 'risk_level')}`
    case 'approval.decided':
      return `审批 ${payload.approved ? '批准' : '拒绝'} · ${textValue(payload, 'reason')}`
    case 'action.started':
      return `开始执行 ${textValue(payload, 'runbook_ref')} · 目标 ${textValue(payload, 'target')}`
    case 'action.completed':
      return `动作结果：${textValue(payload, 'status')} · ${textValue(payload, 'after_state', '状态待核实')}`
    case 'recovery.verified':
      return `恢复窗口 ${textValue(payload, 'result')} · ${textValue(payload, 'window_seconds', '0')} 秒`
    case 'incident.escalated':
      return `升级人工处理 · ${textValue(payload, 'reason')}`
    default:
      return `事件载荷包含 ${Object.keys(payload).length} 个字段`
  }
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
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [decisionMode, setDecisionMode] = useState<'approve' | 'reject'>('approve')
  const [rejectReason, setRejectReason] = useState('')
  const [rejectDetails, setRejectDetails] = useState('')
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const role = currentRole()
  const canApprove = role === 'approver'

  // 加载数据
  const fetchData = useCallback(async () => {
    if (!id) return
    try {
      const [incRes, tlRes, apRes] = await Promise.all([
        apiFetch(`/api/incidents/${id}`),
        apiFetch(`/api/incidents/${id}/timeline`),
        apiFetch(`/api/incidents/${id}/approvals`),
      ])

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

  const streamStatus = useSSE(id, handleSSEMessage, !!id)

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    if (!confirmApproval) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfirmApproval(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previousFocusRef.current?.focus()
    }
  }, [confirmApproval])

  // 审批决定
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
    } catch (e) {
      setDecisionError(e instanceof Error ? e.message : '审批请求失败')
    } finally {
      setDecidingId(null)
    }
  }

  // 收集证据和假设
  const evidenceEvents = timeline.filter(e => e.event_type === 'evidence.collected')
  const hypothesisEvents = timeline.filter(e => e.event_type === 'hypothesis.generated')
  const pendingApprovals = approvals.filter(a => a.status === 'pending')
  const latestHypothesis = hypothesisEvents[hypothesisEvents.length - 1]
  const hasAnalysis = evidenceEvents.length > 0 || hypothesisEvents.length > 0

  if (loading) return <div className={styles.loading}>加载中...</div>
  if (error) return <div className={styles.error}>⚠️ {error}</div>
  if (!incident) return <div className={styles.error}>事故不存在</div>

  return (
    <div className={styles.page}>
      <Link to="/" className={styles.back}><ArrowLeft size={15} aria-hidden="true" /> 返回事故队列</Link>

      {/* 标题区 */}
      <div className={styles.header}>
        <div className={styles.headerTopline}>
          <span className={styles.eyebrow}>INCIDENT / CONTROL ROOM</span>
          <span className={styles.freshness}>最新更新 {new Date(incident.updated_at).toLocaleString('zh-CN')}</span>
        </div>
        <h1 className={styles.title}>{incident.alert_name}</h1>
        <div className={styles.meta}>
          <span className={`${styles.statusBadge} ${styles[`status_${incident.status}`] || ''}`}>
            {STATUS_LABELS[incident.status] || incident.status}
          </span>
          <span className={styles.severity}>{incident.severity}</span>
          <span>ID: {incident.id.slice(0, 8)}...</span>
          <span>版本: {incident.version}</span>
          <span className={styles.streamBadge}>实时流: {streamStatus}</span>
          <span className={styles.streamBadge}>角色: {role}</span>
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
                <span style={{ width: `${confidencePercent(latestHypothesis.payload.confidence)}%` }} />
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
          <p className={styles.cardIntro}>该动作只能按当前计划执行。请核对目标、参数、风险和计划哈希，审批决定会写入事故时间线。</p>
          {decisionError && (
            <div className={styles.inlineError} role="alert">
              <AlertTriangle size={15} aria-hidden="true" />
              <span>{decisionError}</span>
            </div>
          )}
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
                {canApprove ? (
                  <>
                    <button
                      className={styles.btnApprove}
                      disabled={decidingId === ap.id}
                      onClick={(event) => {
                        previousFocusRef.current = event.currentTarget
                        setDecisionMode('approve')
                        setConfirmApproval(ap)
                      }}
                    >
                      {decidingId === ap.id ? '处理中...' : '审核批准'}
                    </button>
                    <button
                      className={styles.btnReject}
                      disabled={decidingId === ap.id}
                      onClick={(event) => {
                        previousFocusRef.current = event.currentTarget
                        setDecisionMode('reject')
                        setRejectReason('')
                        setRejectDetails('')
                        setConfirmApproval(ap)
                      }}
                    >
                      {decidingId === ap.id ? '处理中...' : '拒绝'}
                    </button>
                  </>
                ) : (
                  <span className={styles.readOnlyNotice}>当前角色为只读，需切换为 approver 才能决定。</span>
                )}
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

      {/* 证据与假设 */}
      {hasAnalysis && (
        <div className={styles.analysisGrid}>
          <section className={styles.card}>
            <h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 证据收集 ({evidenceEvents.length})</h2>
            <p className={styles.cardIntro}>每条证据保留来源、事件序号和脱敏摘要，结论不会脱离证据单独展示。</p>
            {evidenceEvents.length === 0 ? (
              <p className={styles.empty}>暂无已收集证据</p>
            ) : (
              <div className={styles.evidenceList}>
                {evidenceEvents.map(e => (
                  <div key={e.id} className={styles.evidenceItem}>
                    <div className={styles.evidenceItemTopline}>
                      <span className={styles.evidenceSource}>{String(e.payload.source || 'unknown')}</span>
                      <span className={styles.evidenceRef}>#{e.sequence} / {String(e.payload.evidence_id || 'untracked')}</span>
                    </div>
                    <p className={styles.evidenceSummary}>{String(e.payload.summary || '未提供摘要')}</p>
                    <time className={styles.evidenceTime} dateTime={e.timestamp}>{new Date(e.timestamp).toLocaleString('zh-CN')}</time>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className={styles.card}>
            <h2 className={styles.cardTitle}><Sparkles size={15} aria-hidden="true" /> 根因假设 ({hypothesisEvents.length})</h2>
            <p className={styles.cardIntro}>置信度是模型输出，不等同于统计置信区间；支持与反对信号都保留。</p>
            {hypothesisEvents.length === 0 ? (
              <p className={styles.empty}>等待诊断假设</p>
            ) : (
              <div className={styles.hypothesisList}>
                {hypothesisEvents.map((e, index) => (
                  <div key={e.id} className={styles.hypothesisItem}>
                    <div className={styles.hypothesisLead}>
                      <span className={styles.hypothesisIndex}>{index + 1}</span>
                      <strong>{String(e.payload.statement || '未提供假设陈述')}</strong>
                    </div>
                    <div className={styles.hypothesisMeta}>
                      <span>{String(e.payload.category || 'unknown')}</span>
                      <span>{String(e.payload.affected_service || 'unknown')}</span>
                      <b>{formatConfidence(e.payload.confidence)} model output</b>
                    </div>
                    <div className={styles.hypothesisEvidence}>
                      <div><span>支持</span><strong>{String(e.payload.supporting_evidence || 0)} 条证据</strong></div>
                      <div><span>反对 / 未决</span><strong>{String(e.payload.opposing_evidence || '未记录')}</strong></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
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
                  <p className={styles.timelineSummary}>{formatTimelineSummary(event)}</p>
                  {Object.keys(event.payload).length > 0 && (
                    <details className={styles.timelineDetails}>
                      <summary>查看事件载荷</summary>
                      <pre className={styles.timelinePayload}>{JSON.stringify(event.payload, null, 2)}</pre>
                    </details>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {confirmApproval && (
        <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmApproval(null) }}>
          <div
            className={styles.confirmDialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="approval-confirm-title"
          >
            <button type="button" className={styles.modalClose} aria-label="关闭对话框" title="关闭" onClick={() => setConfirmApproval(null)}><X size={16} aria-hidden="true" /></button>
            <h2 id="approval-confirm-title" className={styles.confirmTitle}>
              {decisionMode === 'approve' ? '确认批准 R1 动作' : '填写拒绝理由'}
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
              <div><dt>策略门禁</dt><dd>R1 · 白名单 · plan hash</dd></div>
              <div><dt>回滚 / 超时</dt><dd>可逆 fixture · 过期后拒绝</dd></div>
            </dl>
            {Object.keys(confirmApproval.parameters).length > 0 && (
              <div className={styles.confirmParameters}>
                <span>规范化参数</span>
                <pre>{JSON.stringify(confirmApproval.parameters, null, 2)}</pre>
              </div>
            )}
            {decisionMode === 'reject' && (
              <div className={styles.rejectForm}>
                <label>拒绝原因
                  <select value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}>
                    <option value="">请选择原因</option>
                    <option value="evidence_insufficient">证据不足</option>
                    <option value="risk_too_high">风险不可接受</option>
                    <option value="target_mismatch">目标或参数不匹配</option>
                    <option value="approval_expired">审批已接近过期</option>
                  </select>
                </label>
                <label>补充说明
                  <textarea value={rejectDetails} onChange={(event) => setRejectDetails(event.target.value)} rows={3} placeholder="记录给后续值班人员的判断依据" />
                </label>
              </div>
            )}
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
                className={decisionMode === 'approve' ? styles.btnApprove : styles.btnReject}
                disabled={decidingId === confirmApproval.id || (decisionMode === 'reject' && !rejectReason)}
                onClick={() => handleDecide(confirmApproval.id, decisionMode === 'approve', decisionMode === 'approve'
                  ? '已核对动作、目标、风险和计划哈希，批准执行'
                  : `${rejectReason}${rejectDetails ? `：${rejectDetails}` : ''}`)}
              >
                {decisionMode === 'approve' ? '确认批准' : '确认拒绝'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
