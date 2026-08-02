import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Clock3, FileCheck2, PlayCircle, Search, ShieldCheck, Sparkles, X } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useSSE } from '../hooks/useSSE'
import type { SSEMessage } from '../hooks/useSSE'
import { apiFetch, currentRole } from '../lib/api'
import { INCIDENT_STATUS_LABELS, ROLE_LABELS, SEVERITY_LABELS, actionLabel, actorLabel, countEvidence, evidenceSourceLabel, incidentDescription, riskLabel, serviceLabel } from '../lib/presentation'
import styles from './IncidentDetailPage.module.css'

interface TimelineEvent { id: string; sequence: number; event_type: string; actor: string; payload: Record<string, unknown>; timestamp: string }
interface IncidentDetail { id: string; status: string; severity: string; alert_name: string; description: string; created_at: string; updated_at: string; resolved_at: string | null; version: number }
interface ApprovalItem { id: string; incident_id: string; plan_id: string; runbook_ref: string; target: string; parameters: Record<string, unknown>; risk_level: string; plan_hash: string; status: string; created_at: string; expires_at: string; decided_at: string | null; decided_by: string | null; decision_reason: string | null }

const EVENT_LABELS: Record<string, string> = {
  'incident.created': '告警接入', 'incident.status_changed': '状态变更', 'scenario.started': '演练启动',
  'evidence.collected': '调查证据', 'hypothesis.generated': '初步诊断', 'plan.proposed': '恢复方案',
  'approval.requested': '提交审批', 'approval.decided': '审批结果', 'action.started': '开始执行',
  'action.completed': '执行结果', 'recovery.verified': '恢复验证', 'incident.escalated': '升级人工', 'error.occurred': '处理失败',
}
const APPROVAL_STATUS: Record<string, { label: string; className: string }> = { pending: { label: '待审批', className: styles.apPending }, approved: { label: '已批准', className: styles.apApproved }, rejected: { label: '已拒绝', className: styles.apRejected }, expired: { label: '已过期', className: styles.apExpired } }
const FLOW = [
  { key: 'discover', label: '发现', icon: AlertTriangle }, { key: 'investigate', label: '调查', icon: Search },
  { key: 'approve', label: '审批', icon: FileCheck2 }, { key: 'execute', label: '执行', icon: PlayCircle }, { key: 'verify', label: '验证', icon: ShieldCheck },
]

function mergeTimelineEvents(previous: TimelineEvent[], incoming: TimelineEvent[]) {
  const byKey = new Map<string, TimelineEvent>()
  for (const event of [...previous, ...incoming]) byKey.set(event.id || `${event.sequence}:${event.event_type}`, event)
  return Array.from(byKey.values()).sort((a, b) => a.sequence - b.sequence)
}
function formatConfidence(value: unknown) { const numeric = Number(value || 0); return `${Math.round((numeric <= 1 ? numeric * 100 : numeric))}%` }
function confidencePercent(value: unknown) { const numeric = Number(value || 0); return Math.min(100, Math.max(0, numeric <= 1 ? numeric * 100 : numeric)) }
function textValue(payload: Record<string, unknown>, key: string, fallback = '未记录') { const value = payload[key]; return value === undefined || value === null ? fallback : String(value) }
function readableEventValue(value: unknown, fallback = '未记录') {
  const text = incidentDescription(value || fallback)
  if (text === 'healthy') return '健康检查通过'
  if (text === 'recovered') return '服务已恢复'
  if (text === 'failed') return '服务未恢复'
  return text
}
function formatTimelineSummary(event: TimelineEvent) {
  const payload = event.payload
  switch (event.event_type) {
    case 'incident.created': return '告警已接入并创建故障记录'
    case 'incident.status_changed': return `${INCIDENT_STATUS_LABELS[textValue(payload, 'to')] || textValue(payload, 'to')} · ${textValue(payload, 'reason', '状态已更新')}`
    case 'scenario.started': return `演练启动 · 目标服务 ${serviceLabel(textValue(payload, 'target'))}`
    case 'evidence.collected': return `${evidenceSourceLabel(payload.source)}：${readableEventValue(payload.summary)}`
    case 'hypothesis.generated': return `${readableEventValue(payload.statement)} · 参考 ${countEvidence(payload.supporting_evidence)} 条证据`
    case 'approval.requested': return `提交恢复方案：${actionLabel(payload.runbook_ref)} · 目标服务 ${serviceLabel(textValue(payload, 'target'))}`
    case 'approval.decided': return `审批结果：${payload.approved ? '已批准' : '已拒绝'} · ${readableEventValue(payload.reason)}`
    case 'action.started': return `开始执行${actionLabel(payload.runbook_ref)} · 目标服务 ${serviceLabel(textValue(payload, 'target'))}`
    case 'action.completed': return `恢复结果：${textValue(payload, 'status') === 'succeeded' ? '已完成' : readableEventValue(payload.status)} · ${readableEventValue(payload.after_state, '等待检查')}`
    case 'recovery.verified': return `恢复验证：${readableEventValue(payload.result)} · 观察 ${textValue(payload, 'window_seconds', '0')} 秒`
    case 'incident.escalated': return `已升级人工处理 · ${readableEventValue(payload.reason)}`
    default: return '记录一次处理事件'
  }
}
function stageIndex(status: string) { if (status === 'DETECTED') return 0; if (['TRIAGING', 'DIAGNOSING'].includes(status)) return 1; if (['PLAN_PROPOSED', 'AWAITING_APPROVAL'].includes(status)) return 2; if (status === 'EXECUTING') return 3; if (status === 'RESOLVED') return 5; return 4 }

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

  const fetchData = useCallback(async () => {
    if (!id) return
    try {
      const [incidentResponse, timelineResponse, approvalsResponse] = await Promise.all([
        apiFetch(`/api/incidents/${id}`), apiFetch(`/api/incidents/${id}/timeline`), apiFetch(`/api/incidents/${id}/approvals`),
      ])
      setIncident(await incidentResponse.json())
      const timelineData = await timelineResponse.json()
      const approvalsData = await approvalsResponse.json()
      setTimeline(previous => mergeTimelineEvents(previous, timelineData.events || []))
      setApprovals(approvalsData.items || [])
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载故障详情失败')
    } finally { setLoading(false) }
  }, [id])

  const handleSSEMessage = useCallback((message: SSEMessage) => {
    if (message.type === 'timeline_event' && message.event) {
      setTimeline(previous => mergeTimelineEvents(previous, [message.event!]))
      if (['approval.requested', 'approval.decided'].includes(message.event.event_type)) fetchData()
    }
    if (message.type === 'status' && message.status) setIncident(previous => previous ? { ...previous, status: message.status! } : previous)
  }, [fetchData])
  const streamStatus = useSSE(id, handleSSEMessage, !!id)

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => {
    if (!confirmApproval) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setConfirmApproval(null) }
    document.addEventListener('keydown', onKeyDown)
    return () => { document.removeEventListener('keydown', onKeyDown); previousFocusRef.current?.focus() }
  }, [confirmApproval])

  const handleDecide = async (approvalId: string, approved: boolean, reason: string) => {
    if (!id) return
    setDecidingId(approvalId); setDecisionError(null)
    try {
      await apiFetch(`/api/incidents/${id}/approvals/${approvalId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved, reason }) })
      setConfirmApproval(null); setRejectReason(''); setRejectDetails(''); await fetchData()
    } catch (cause) { setDecisionError(cause instanceof Error ? cause.message : '提交审批失败') }
    finally { setDecidingId(null) }
  }

  const evidenceEvents = timeline.filter(event => event.event_type === 'evidence.collected')
  const hypothesisEvents = timeline.filter(event => event.event_type === 'hypothesis.generated')
  const pendingApprovals = approvals.filter(approval => approval.status === 'pending')
  const completedApprovals = approvals.filter(approval => approval.status !== 'pending')
  const latestHypothesis = hypothesisEvents[hypothesisEvents.length - 1]

  if (loading) return <div className={styles.loading}>正在加载故障详情…</div>
  if (error) return <div className={styles.error} role="alert"><AlertTriangle size={18} aria-hidden="true" /> {error}</div>
  if (!incident) return <div className={styles.error}>故障不存在</div>

  const currentStage = stageIndex(incident.status)
  const nextTitle = pendingApprovals.length ? '等待审批恢复操作' : incident.status === 'RESOLVED' ? '故障已恢复，查看验证结果' : currentStage === 1 ? '调查证据收集中' : currentStage === 3 ? '恢复操作执行中，等待验证' : '按处置流程继续'

  return (
    <div className={styles.page}>
      <Link to="/" className={styles.back}><ArrowLeft size={15} aria-hidden="true" /> 返回故障总览</Link>
      <header className={styles.header}>
        <div className={styles.headerTopline}><span className={styles.breadcrumb}>故障详情 / 处置</span><span className={styles.freshness}>最近更新 {new Date(incident.updated_at).toLocaleString('zh-CN')}</span></div>
        <h1 className={styles.title}>{incidentDescription(incident.alert_name)}</h1>
        <div className={styles.meta}>
          <span className={`${styles.statusBadge} ${styles[`status_${incident.status}`] || ''}`}>{INCIDENT_STATUS_LABELS[incident.status] || incident.status}</span>
          <span className={`${styles.severity} ${incident.severity === 'critical' ? styles.severityCritical : incident.severity === 'warning' ? styles.severityWarning : styles.severityInfo}`}>{SEVERITY_LABELS[incident.severity] || incident.severity}</span>
          <span>事件流：{streamStatus === 'connected' ? '已连接' : streamStatus === 'reconnecting' ? '重连中' : '待连接'}</span>
          <span>当前角色：{ROLE_LABELS[role] || '只读'}</span>
        </div>
      </header>

      <section className={styles.flowStrip} aria-label="故障处理流程">
        {FLOW.map((step, index) => { const Icon = step.icon; const state = currentStage === index ? 'current' : currentStage > index ? 'done' : 'upcoming'; return <div key={step.key} className={`${styles.flowStep} ${styles[`flow_${state}`]}`}><span className={styles.flowIcon}><Icon size={15} aria-hidden="true" /></span><span>{step.label}</span>{index < FLOW.length - 1 && <span className={styles.flowLine} aria-hidden="true" />}</div> })}
      </section>

      <section className={styles.nextAction}>
        <div><span className={styles.sectionKicker}>下一步</span><h2>{nextTitle}</h2><p>{pendingApprovals.length ? '核对目标服务、影响范围和恢复方案后提交审批。' : '状态变更、执行结果和验证结果都会记录在处置时间线中。'}</p></div>
        {pendingApprovals.length > 0 && <a href="#approval-section" className={styles.nextButton}>查看审批 <ArrowRight size={15} aria-hidden="true" /></a>}
      </section>

      <section className={styles.summaryGrid}>
        <div className={`${styles.card} ${styles.descriptionCard}`}><h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 故障描述</h2><p>{incidentDescription(incident.description)}</p></div>
        <div className={`${styles.card} ${styles.diagnosisCard}`}><div className={styles.diagnosisTitle}><Sparkles size={15} aria-hidden="true" /><span>初步诊断</span></div>{latestHypothesis ? <><strong className={styles.diagnosisStatement}>{readableEventValue(latestHypothesis.payload.statement, '等待调查证据')}</strong><div className={styles.diagnosisMeta}><span>{serviceLabel(latestHypothesis.payload.affected_service || '相关服务')}</span><b>置信度 {formatConfidence(latestHypothesis.payload.confidence)}</b></div><div className={styles.confidenceTrack} aria-label="初步诊断置信度"><span style={{ width: `${confidencePercent(latestHypothesis.payload.confidence)}%` }} /></div></> : <span className={styles.empty}>等待调查证据</span>}</div>
      </section>

      {pendingApprovals.length > 0 && <section className={`${styles.card} ${styles.approvalSection}`} id="approval-section"><div className={styles.sectionHeader}><div><h2 className={styles.cardTitle}><Clock3 size={15} aria-hidden="true" /> 恢复操作待审批</h2><p className={styles.cardIntro}>审批通过后执行，执行结果写入处置时间线。</p></div><span className={styles.pendingCount}>{pendingApprovals.length} 项待审批</span></div>{decisionError && <div className={styles.inlineError} role="alert"><AlertTriangle size={15} aria-hidden="true" /> {decisionError}</div>}{pendingApprovals.map(approval => <div key={approval.id} className={styles.approvalItem}><div className={styles.approvalHeader}><div className={styles.approvalInfo}><strong>{actionLabel(approval.runbook_ref)}</strong><span>目标服务：{serviceLabel(approval.target)}</span><span className={styles.approvalRisk}>{riskLabel(approval.risk_level)}</span></div><span className={styles.approvalExpiry}>审批截止 {new Date(approval.expires_at).toLocaleTimeString('zh-CN')}</span></div><div className={styles.approvalFacts}><div><span>操作</span><strong>{actionLabel(approval.runbook_ref)}，执行后进入恢复验证。</strong></div><div><span>目标服务</span><strong>{serviceLabel(approval.target)}</strong></div><div><span>审批决定</span><strong>核对操作、目标服务和风险级别后，选择“批准”或“拒绝”。</strong></div></div><details className={styles.technicalDetails}><summary>查看技术字段</summary><code>动作编号：{approval.runbook_ref}<br />计划校验：{approval.plan_hash.slice(0, 16)}…<br />附加参数：{Object.keys(approval.parameters).length ? JSON.stringify(approval.parameters) : '无'}</code></details><div className={styles.approvalActions}>{canApprove ? <><button className={styles.btnApprove} type="button" disabled={decidingId === approval.id} onClick={(event) => { previousFocusRef.current = event.currentTarget; setDecisionMode('approve'); setConfirmApproval(approval) }}>批准恢复</button><button className={styles.btnReject} type="button" disabled={decidingId === approval.id} onClick={(event) => { previousFocusRef.current = event.currentTarget; setDecisionMode('reject'); setRejectReason(''); setRejectDetails(''); setConfirmApproval(approval) }}>拒绝恢复</button></> : <span className={styles.readOnlyNotice}>当前角色为只读，无法提交审批决定。</span>}</div></div>)}</section>}

      {completedApprovals.length > 0 && <section className={styles.card}><h2 className={styles.cardTitle}>历史审批</h2><div className={styles.historyList}>{completedApprovals.map(approval => { const status = APPROVAL_STATUS[approval.status] || { label: approval.status, className: '' }; return <div key={approval.id} className={styles.historyItem}><span className={`${styles.apBadge} ${status.className}`}><CheckCircle2 size={12} aria-hidden="true" /> {status.label}</span><span>{actionLabel(approval.runbook_ref)} → {serviceLabel(approval.target)}</span>{approval.decided_by && <span className={styles.apBy}>由值班人员处理</span>}{approval.decision_reason && <span className={styles.apReason}>{incidentDescription(approval.decision_reason)}</span>}</div> })}</div></section>}

      {(evidenceEvents.length > 0 || hypothesisEvents.length > 0) && <div className={styles.analysisGrid}><section className={styles.card}><h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 调查证据 ({evidenceEvents.length})</h2><p className={styles.cardIntro}>证据来自监控指标、日志和调用链，原始内容可在技术字段中查看。</p>{evidenceEvents.length ? <div className={styles.evidenceList}>{evidenceEvents.map(event => <div key={event.id} className={styles.evidenceItem}><div className={styles.evidenceItemTopline}><span className={styles.evidenceSource}>{evidenceSourceLabel(event.payload.source)}</span><span className={styles.evidenceRef}>第 {event.sequence} 条</span></div><p className={styles.evidenceSummary}>{readableEventValue(event.payload.summary, '未提供说明')}</p><time className={styles.evidenceTime} dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString('zh-CN')}</time></div>)}</div> : <p className={styles.empty}>暂无调查证据</p>}</section><section className={styles.card}><h2 className={styles.cardTitle}><Sparkles size={15} aria-hidden="true" /> 初步诊断 ({hypothesisEvents.length})</h2><p className={styles.cardIntro}>根据当前证据生成的诊断，仍需结合恢复验证确认。</p>{hypothesisEvents.length ? <div className={styles.hypothesisList}>{hypothesisEvents.map((event, index) => <div key={event.id} className={styles.hypothesisItem}><div className={styles.hypothesisLead}><span className={styles.hypothesisIndex}>{index + 1}</span><strong>{readableEventValue(event.payload.statement, '暂无诊断')}</strong></div><div className={styles.hypothesisMeta}><span>{serviceLabel(event.payload.affected_service || '相关服务')}</span><b>置信度 {formatConfidence(event.payload.confidence)}</b></div><div className={styles.hypothesisEvidence}><div><span>支持证据</span><strong>{countEvidence(event.payload.supporting_evidence)} 条</strong></div><div><span>待确认事项</span><strong>{readableEventValue(event.payload.opposing_evidence, '无')}</strong></div></div></div>)}</div> : <p className={styles.empty}>暂无诊断</p>}</section></div>}

      <section className={styles.card}><h2 className={styles.cardTitle}><Clock3 size={15} aria-hidden="true" /> 处置时间线</h2>{timeline.length ? <div className={styles.timeline}>{timeline.map(event => <div key={event.id} className={styles.timelineItem}><div className={styles.timelineDot} /><div className={styles.timelineContent}><div className={styles.timelineHeader}><span className={styles.timelineType}>{EVENT_LABELS[event.event_type] || '处理事件'}</span><span className={styles.timelineActor}>{actorLabel(event.actor)}</span><span className={styles.timelineTime}>{new Date(event.timestamp).toLocaleTimeString('zh-CN')}</span></div><p className={styles.timelineSummary}>{formatTimelineSummary(event)}</p>{Object.keys(event.payload).length > 0 && <details className={styles.timelineDetails}><summary>查看技术字段</summary><pre className={styles.timelinePayload}>{JSON.stringify(event.payload, null, 2)}</pre></details>}</div></div>)}</div> : <p className={styles.empty}>暂无处置记录</p>}</section>

      {confirmApproval && <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmApproval(null) }}><div className={styles.confirmDialog} role="dialog" aria-modal="true" aria-labelledby="approval-confirm-title"><button type="button" className={styles.modalClose} aria-label="关闭对话框" title="关闭" onClick={() => setConfirmApproval(null)}><X size={16} aria-hidden="true" /></button><h2 id="approval-confirm-title" className={styles.confirmTitle}>{decisionMode === 'approve' ? '批准恢复操作' : '拒绝恢复操作'}</h2><dl className={styles.confirmDetails}><div><dt>操作</dt><dd>{actionLabel(confirmApproval.runbook_ref)}</dd></div><div><dt>目标服务</dt><dd>{serviceLabel(confirmApproval.target)}</dd></div><div><dt>风险级别</dt><dd>{riskLabel(confirmApproval.risk_level)}</dd></div><div><dt>审批截止</dt><dd>{new Date(confirmApproval.expires_at).toLocaleString('zh-CN')}</dd></div></dl><details className={styles.technicalDetails}><summary>查看技术字段</summary><code>动作编号：{confirmApproval.runbook_ref}<br />计划校验：{confirmApproval.plan_hash.slice(0, 16)}…</code></details>{decisionMode === 'reject' && <div className={styles.rejectForm}><label>拒绝原因<select value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}><option value="">请选择原因</option><option value="evidence_insufficient">证据不足</option><option value="risk_too_high">风险不可接受</option><option value="target_mismatch">目标服务不匹配</option><option value="approval_expired">审批已过期</option></select></label><label>补充说明<textarea value={rejectDetails} onChange={(event) => setRejectDetails(event.target.value)} rows={3} placeholder="记录审批依据，供后续值班人员查看" /></label></div>}<div className={styles.confirmActions}><button type="button" className={styles.cancelButton} onClick={() => setConfirmApproval(null)}>取消</button><button type="button" className={decisionMode === 'approve' ? styles.btnApprove : styles.btnReject} disabled={decidingId === confirmApproval.id || (decisionMode === 'reject' && !rejectReason)} onClick={() => handleDecide(confirmApproval.id, decisionMode === 'approve', decisionMode === 'approve' ? '已核对目标服务、影响范围和恢复方案，批准执行' : `${rejectReason}${rejectDetails ? `：${rejectDetails}` : ''}`)}>{decisionMode === 'approve' ? '批准恢复' : '拒绝恢复'}</button></div></div></div>}
    </div>
  )
}
