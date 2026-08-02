import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Clock3, FileCheck2, PlayCircle, Search, ShieldCheck, Sparkles, X } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useSSE } from '../hooks/useSSE'
import type { SSEMessage } from '../hooks/useSSE'
import { apiFetch, currentRole } from '../lib/api'
import styles from './IncidentDetailPage.module.css'

interface TimelineEvent { id: string; sequence: number; event_type: string; actor: string; payload: Record<string, unknown>; timestamp: string }
interface IncidentDetail { id: string; status: string; severity: string; alert_name: string; description: string; created_at: string; updated_at: string; resolved_at: string | null; version: number }
interface ApprovalItem { id: string; incident_id: string; plan_id: string; runbook_ref: string; target: string; parameters: Record<string, unknown>; risk_level: string; plan_hash: string; status: string; created_at: string; expires_at: string; decided_at: string | null; decided_by: string | null; decision_reason: string | null }

const EVENT_LABELS: Record<string, string> = {
  'incident.created': '事故创建', 'incident.status_changed': '阶段更新', 'scenario.started': '演练启动',
  'evidence.collected': '证据收集', 'hypothesis.generated': '原因判断', 'plan.proposed': '恢复方案',
  'approval.requested': '提交审批', 'approval.decided': '审批决定', 'action.started': '开始执行',
  'action.completed': '动作完成', 'recovery.verified': '恢复验证', 'incident.escalated': '升级人工', 'error.occurred': '发生错误',
}
const STATUS_LABELS: Record<string, string> = { DETECTED: '已发现', TRIAGING: '分诊中', DIAGNOSING: '调查中', PLAN_PROPOSED: '方案待审', AWAITING_APPROVAL: '等待审批', EXECUTING: '执行中', VERIFYING: '验证中', RESOLVED: '已恢复', ESCALATED: '已升级', FAILED: '失败' }
const RISK_LABELS: Record<string, string> = { R0: '只读动作', R1: '可逆动作（需审批）', R2: '高风险动作（禁用）', R3: '永久禁止' }
const APPROVAL_STATUS: Record<string, { label: string; className: string }> = { pending: { label: '待处理', className: styles.apPending }, approved: { label: '已批准', className: styles.apApproved }, rejected: { label: '已拒绝', className: styles.apRejected }, expired: { label: '已过期', className: styles.apExpired } }
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
function formatTimelineSummary(event: TimelineEvent) {
  const payload = event.payload
  switch (event.event_type) {
    case 'incident.created': return `由 ${textValue(payload, 'fingerprint', '告警入口')} 创建事故`
    case 'incident.status_changed': return `${textValue(payload, 'from')} → ${textValue(payload, 'to')} · ${textValue(payload, 'reason', '系统状态更新')}`
    case 'scenario.started': return `启动 ${textValue(payload, 'scenario_id')} · 目标 ${textValue(payload, 'target')}`
    case 'evidence.collected': return `${textValue(payload, 'source')} 返回证据 · ${textValue(payload, 'summary')}`
    case 'hypothesis.generated': return `${textValue(payload, 'statement')} · 支持 ${textValue(payload, 'supporting_evidence', '0')} 条证据`
    case 'approval.requested': return `登记 ${textValue(payload, 'runbook_ref')} · 目标 ${textValue(payload, 'target')} · ${textValue(payload, 'risk_level')}`
    case 'approval.decided': return `审批${payload.approved ? '已批准' : '已拒绝'} · ${textValue(payload, 'reason')}`
    case 'action.started': return `开始执行 ${textValue(payload, 'runbook_ref')} · 目标 ${textValue(payload, 'target')}`
    case 'action.completed': return `动作结果：${textValue(payload, 'status')} · ${textValue(payload, 'after_state', '状态待核实')}`
    case 'recovery.verified': return `恢复窗口 ${textValue(payload, 'result')} · ${textValue(payload, 'window_seconds', '0')} 秒`
    case 'incident.escalated': return `升级人工处理 · ${textValue(payload, 'reason')}`
    default: return `事件载荷包含 ${Object.keys(payload).length} 个字段`
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
      setError(cause instanceof Error ? cause.message : '加载事故详情失败')
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
    } catch (cause) { setDecisionError(cause instanceof Error ? cause.message : '审批请求失败') }
    finally { setDecidingId(null) }
  }

  const evidenceEvents = timeline.filter(event => event.event_type === 'evidence.collected')
  const hypothesisEvents = timeline.filter(event => event.event_type === 'hypothesis.generated')
  const pendingApprovals = approvals.filter(approval => approval.status === 'pending')
  const completedApprovals = approvals.filter(approval => approval.status !== 'pending')
  const latestHypothesis = hypothesisEvents[hypothesisEvents.length - 1]

  if (loading) return <div className={styles.loading}>正在加载事故详情…</div>
  if (error) return <div className={styles.error} role="alert"><AlertTriangle size={18} aria-hidden="true" /> {error}</div>
  if (!incident) return <div className={styles.error}>事故不存在</div>

  const currentStage = stageIndex(incident.status)
  const nextTitle = pendingApprovals.length ? '请先审核恢复动作' : incident.status === 'RESOLVED' ? '事故已恢复，查看验证结果' : currentStage === 1 ? '等待调查证据汇总' : currentStage === 3 ? '动作执行中，等待恢复验证' : '按时间线继续推进'

  return (
    <div className={styles.page}>
      <Link to="/" className={styles.back}><ArrowLeft size={15} aria-hidden="true" /> 返回事故总览</Link>
      <header className={styles.header}>
        <div className={styles.headerTopline}><span className={styles.breadcrumb}>事故详情 / 处理工作区</span><span className={styles.freshness}>最近更新 {new Date(incident.updated_at).toLocaleString('zh-CN')}</span></div>
        <h1 className={styles.title}>{incident.alert_name}</h1>
        <div className={styles.meta}>
          <span className={`${styles.statusBadge} ${styles[`status_${incident.status}`] || ''}`}>{STATUS_LABELS[incident.status] || incident.status}</span>
          <span className={`${styles.severity} ${incident.severity === 'critical' ? styles.severityCritical : incident.severity === 'warning' ? styles.severityWarning : styles.severityInfo}`}>{incident.severity === 'critical' ? '严重' : incident.severity === 'warning' ? '警告' : '提示'}</span>
          <span>实时更新：{streamStatus === 'connected' ? '已连接' : streamStatus === 'reconnecting' ? '重连中' : '待连接'}</span>
          <span>角色：{role === 'approver' ? '审批人' : '只读观察员'}</span>
        </div>
      </header>

      <section className={styles.flowStrip} aria-label="事故处理流程">
        {FLOW.map((step, index) => { const Icon = step.icon; const state = currentStage === index ? 'current' : currentStage > index ? 'done' : 'upcoming'; return <div key={step.key} className={`${styles.flowStep} ${styles[`flow_${state}`]}`}><span className={styles.flowIcon}><Icon size={15} aria-hidden="true" /></span><span>{step.label}</span>{index < FLOW.length - 1 && <span className={styles.flowLine} aria-hidden="true" />}</div> })}
      </section>

      <section className={styles.nextAction}>
        <div><span className={styles.sectionKicker}>当前建议</span><h2>{nextTitle}</h2><p>{pendingApprovals.length ? '确认目标、参数、风险和计划后，再决定是否允许执行。' : '所有判断都会写入下方时间线，方便下一位值班人员接手。'}</p></div>
        {pendingApprovals.length > 0 && <a href="#approval-section" className={styles.nextButton}>跳到审批 <ArrowRight size={15} aria-hidden="true" /></a>}
      </section>

      <section className={styles.summaryGrid}>
        <div className={`${styles.card} ${styles.descriptionCard}`}><h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 发生了什么</h2><p>{incident.description}</p><div className={styles.summaryNote}>事故编号：{incident.id.slice(0, 8)} · 版本 {incident.version}</div></div>
        <div className={`${styles.card} ${styles.diagnosisCard}`}><div className={styles.diagnosisTitle}><Sparkles size={15} aria-hidden="true" /><span>目前的原因判断</span></div>{latestHypothesis ? <><strong className={styles.diagnosisStatement}>{String(latestHypothesis.payload.statement || '已收敛到主要异常信号')}</strong><div className={styles.diagnosisMeta}><span>{String(latestHypothesis.payload.affected_service || latestHypothesis.payload.category || '待确认')}</span><b>置信度 {formatConfidence(latestHypothesis.payload.confidence)}</b></div><div className={styles.confidenceTrack} aria-label="原因判断置信度"><span style={{ width: `${confidencePercent(latestHypothesis.payload.confidence)}%` }} /></div></> : <span className={styles.empty}>等待调查证据</span>}</div>
      </section>

      {pendingApprovals.length > 0 && <section className={`${styles.card} ${styles.approvalSection}`} id="approval-section"><div className={styles.sectionHeader}><div><h2 className={styles.cardTitle}><Clock3 size={15} aria-hidden="true" /> 需要你决定的动作</h2><p className={styles.cardIntro}>这是可逆恢复动作。批准后才会交给动作网关执行。</p></div><span className={styles.pendingCount}>{pendingApprovals.length} 项待处理</span></div>{decisionError && <div className={styles.inlineError} role="alert"><AlertTriangle size={15} aria-hidden="true" /> {decisionError}</div>}{pendingApprovals.map(approval => <div key={approval.id} className={styles.approvalItem}><div className={styles.approvalHeader}><div className={styles.approvalInfo}><strong>{approval.runbook_ref}</strong><span>目标：{approval.target}</span><span className={styles.approvalRisk}>{RISK_LABELS[approval.risk_level] || approval.risk_level}</span></div><span className={styles.approvalExpiry}>过期 {new Date(approval.expires_at).toLocaleTimeString('zh-CN')}</span></div><div className={styles.approvalFacts}><div><span>动作说明</span><strong>按当前计划执行一次可逆恢复</strong></div><div><span>计划校验</span><code>{approval.plan_hash.slice(0, 16)}…</code></div><div><span>参数</span><code>{Object.keys(approval.parameters).length ? JSON.stringify(approval.parameters) : '无额外参数'}</code></div></div><div className={styles.approvalActions}>{canApprove ? <><button className={styles.btnApprove} type="button" disabled={decidingId === approval.id} onClick={(event) => { previousFocusRef.current = event.currentTarget; setDecisionMode('approve'); setConfirmApproval(approval) }}>批准执行</button><button className={styles.btnReject} type="button" disabled={decidingId === approval.id} onClick={(event) => { previousFocusRef.current = event.currentTarget; setDecisionMode('reject'); setRejectReason(''); setRejectDetails(''); setConfirmApproval(approval) }}>拒绝</button></> : <span className={styles.readOnlyNotice}>当前角色只能查看。需要审批人角色才能决定。</span>}</div></div>)}</section>}

      {completedApprovals.length > 0 && <section className={styles.card}><h2 className={styles.cardTitle}>审批结果</h2><div className={styles.historyList}>{completedApprovals.map(approval => { const status = APPROVAL_STATUS[approval.status] || { label: approval.status, className: '' }; return <div key={approval.id} className={styles.historyItem}><span className={`${styles.apBadge} ${status.className}`}><CheckCircle2 size={12} aria-hidden="true" /> {status.label}</span><span>{approval.runbook_ref} → {approval.target}</span>{approval.decided_by && <span className={styles.apBy}>操作人：{approval.decided_by}</span>}{approval.decision_reason && <span className={styles.apReason}>{approval.decision_reason}</span>}</div> })}</div></section>}

      {(evidenceEvents.length > 0 || hypothesisEvents.length > 0) && <div className={styles.analysisGrid}><section className={styles.card}><h2 className={styles.cardTitle}><FileCheck2 size={15} aria-hidden="true" /> 调查证据 ({evidenceEvents.length})</h2><p className={styles.cardIntro}>先看摘要，来源和事件编号用于复查。</p>{evidenceEvents.length ? <div className={styles.evidenceList}>{evidenceEvents.map(event => <div key={event.id} className={styles.evidenceItem}><div className={styles.evidenceItemTopline}><span className={styles.evidenceSource}>{String(event.payload.source || '监控')}</span><span className={styles.evidenceRef}>第 {event.sequence} 条</span></div><p className={styles.evidenceSummary}>{String(event.payload.summary || '未提供摘要')}</p><time className={styles.evidenceTime} dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString('zh-CN')}</time></div>)}</div> : <p className={styles.empty}>暂无证据</p>}</section><section className={styles.card}><h2 className={styles.cardTitle}><Sparkles size={15} aria-hidden="true" /> 原因判断 ({hypothesisEvents.length})</h2><p className={styles.cardIntro}>这是模型辅助判断，仍需结合证据复核。</p>{hypothesisEvents.length ? <div className={styles.hypothesisList}>{hypothesisEvents.map((event, index) => <div key={event.id} className={styles.hypothesisItem}><div className={styles.hypothesisLead}><span className={styles.hypothesisIndex}>{index + 1}</span><strong>{String(event.payload.statement || '未提供判断')}</strong></div><div className={styles.hypothesisMeta}><span>{String(event.payload.affected_service || '待确认')}</span><b>置信度 {formatConfidence(event.payload.confidence)}</b></div><div className={styles.hypothesisEvidence}><div><span>支持</span><strong>{String(event.payload.supporting_evidence || 0)} 条证据</strong></div><div><span>待确认</span><strong>{String(event.payload.opposing_evidence || '未记录')}</strong></div></div></div>)}</div> : <p className={styles.empty}>暂无判断</p>}</section></div>}

      <section className={styles.card}><h2 className={styles.cardTitle}><Clock3 size={15} aria-hidden="true" /> 处理时间线</h2>{timeline.length ? <div className={styles.timeline}>{timeline.map(event => <div key={event.id} className={styles.timelineItem}><div className={styles.timelineDot} /><div className={styles.timelineContent}><div className={styles.timelineHeader}><span className={styles.timelineType}>{EVENT_LABELS[event.event_type] || event.event_type}</span><span className={styles.timelineActor}>{event.actor}</span><span className={styles.timelineTime}>{new Date(event.timestamp).toLocaleTimeString('zh-CN')}</span></div><p className={styles.timelineSummary}>{formatTimelineSummary(event)}</p>{Object.keys(event.payload).length > 0 && <details className={styles.timelineDetails}><summary>查看详细记录</summary><pre className={styles.timelinePayload}>{JSON.stringify(event.payload, null, 2)}</pre></details>}</div></div>)}</div> : <p className={styles.empty}>暂无事件</p>}</section>

      {confirmApproval && <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmApproval(null) }}><div className={styles.confirmDialog} role="dialog" aria-modal="true" aria-labelledby="approval-confirm-title"><button type="button" className={styles.modalClose} aria-label="关闭对话框" title="关闭" onClick={() => setConfirmApproval(null)}><X size={16} aria-hidden="true" /></button><h2 id="approval-confirm-title" className={styles.confirmTitle}>{decisionMode === 'approve' ? '确认批准恢复动作' : '填写拒绝理由'}</h2><dl className={styles.confirmDetails}><div><dt>动作</dt><dd>{confirmApproval.runbook_ref}</dd></div><div><dt>目标</dt><dd>{confirmApproval.target}</dd></div><div><dt>风险</dt><dd>{RISK_LABELS[confirmApproval.risk_level] || confirmApproval.risk_level}</dd></div><div><dt>计划校验</dt><dd>{confirmApproval.plan_hash.slice(0, 16)}…</dd></div><div><dt>过期时间</dt><dd>{new Date(confirmApproval.expires_at).toLocaleString('zh-CN')}</dd></div></dl>{decisionMode === 'reject' && <div className={styles.rejectForm}><label>拒绝原因<select value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}><option value="">请选择原因</option><option value="evidence_insufficient">证据不足</option><option value="risk_too_high">风险不可接受</option><option value="target_mismatch">目标或参数不匹配</option><option value="approval_expired">审批已接近过期</option></select></label><label>补充说明<textarea value={rejectDetails} onChange={(event) => setRejectDetails(event.target.value)} rows={3} placeholder="记录给后续值班人员的判断依据" /></label></div>}<div className={styles.confirmActions}><button type="button" className={styles.cancelButton} onClick={() => setConfirmApproval(null)}>取消</button><button type="button" className={decisionMode === 'approve' ? styles.btnApprove : styles.btnReject} disabled={decidingId === confirmApproval.id || (decisionMode === 'reject' && !rejectReason)} onClick={() => handleDecide(confirmApproval.id, decisionMode === 'approve', decisionMode === 'approve' ? '已核对动作、目标、风险和计划，批准执行' : `${rejectReason}${rejectDetails ? `：${rejectDetails}` : ''}`)}>{decisionMode === 'approve' ? '确认批准' : '确认拒绝'}</button></div></div></div>}
    </div>
  )
}
