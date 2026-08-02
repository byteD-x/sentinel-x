import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ClipboardCheck, LoaderCircle, PlayCircle, RefreshCw, Search, ShieldCheck, Timer } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import styles from './DashboardPage.module.css'

interface Incident {
  id: string
  status: string
  severity: string
  alert_name: string
  description: string
  created_at: string
  updated_at: string
  resolved_at: string | null
}

const STATUS_LABELS: Record<string, string> = {
  DETECTED: '已发现', TRIAGING: '分诊中', DIAGNOSING: '调查中', PLAN_PROPOSED: '方案待审',
  AWAITING_APPROVAL: '等待审批', EXECUTING: '执行中', VERIFYING: '验证中', RESOLVED: '已恢复',
  ESCALATED: '已升级', FAILED: '失败',
}

const STATUS_CLASS: Record<string, string> = {
  DETECTED: styles.statusInfo, TRIAGING: styles.statusWorking, DIAGNOSING: styles.statusWorking,
  PLAN_PROPOSED: styles.statusWorking, AWAITING_APPROVAL: styles.statusPending, EXECUTING: styles.statusWorking,
  VERIFYING: styles.statusWorking, RESOLVED: styles.statusResolved, ESCALATED: styles.statusEscalated,
  FAILED: styles.statusFailed,
}

const SEVERITY_LABELS: Record<string, string> = { critical: '严重', warning: '警告', info: '提示' }
const SEVERITY_CLASS: Record<string, string> = { critical: styles.severityCritical, warning: styles.severityWarning, info: styles.severityInfo }
const STATUS_FILTERS = [
  { value: 'all', label: '全部' }, { value: 'AWAITING_APPROVAL', label: '待审批' },
  { value: 'DIAGNOSING', label: '调查中' }, { value: 'RESOLVED', label: '已恢复' }, { value: 'ESCALATED', label: '已升级' },
]

const FLOW_STEPS = [
  { key: 'detect', label: '发现', icon: AlertTriangle },
  { key: 'investigate', label: '调查', icon: Search },
  { key: 'approve', label: '审批', icon: ClipboardCheck },
  { key: 'execute', label: '执行', icon: PlayCircle },
  { key: 'verify', label: '验证', icon: ShieldCheck },
]

function stepIndex(status: string) {
  if (status === 'DETECTED') return 0
  if (['TRIAGING', 'DIAGNOSING'].includes(status)) return 1
  if (['PLAN_PROPOSED', 'AWAITING_APPROVAL'].includes(status)) return 2
  if (status === 'EXECUTING') return 3
  return 4
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const statusFilter = searchParams.get('status') || 'all'
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [seeded, setSeeded] = useState(false)
  const [cursor, setCursor] = useState<string | null>(null)
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)

  const fetchIncidents = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '20' })
      if (statusFilter !== 'all') params.set('status', statusFilter)
      if (cursor) params.set('cursor', cursor)
      const response = await apiFetch(`/api/incidents?${params.toString()}`)
      const data = await response.json()
      setIncidents(data.items || [])
      setNextCursor(data.next_cursor || null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载事故失败')
    } finally {
      setLoading(false)
    }
  }, [cursor, statusFilter])

  useEffect(() => { fetchIncidents() }, [fetchIncidents])

  const activeIncidents = useMemo(() => incidents.filter(item => !['RESOLVED', 'ESCALATED', 'FAILED'].includes(item.status)), [incidents])
  const pendingApproval = useMemo(() => incidents.find(item => item.status === 'AWAITING_APPROVAL'), [incidents])
  const priorityIncident = pendingApproval || [...activeIncidents].sort((a, b) => (a.severity === 'critical' ? -1 : 1) - (b.severity === 'critical' ? -1 : 1))[0]
  const resolvedCount = incidents.filter(item => item.status === 'RESOLVED').length
  const criticalCount = incidents.filter(item => item.severity === 'critical').length
  const approvalCount = incidents.filter(item => item.status === 'AWAITING_APPROVAL').length

  const handleFilterChange = (value: string) => {
    setCursor(null)
    setCursorStack([])
    setNextCursor(null)
    setSearchParams(value === 'all' ? {} : { status: value })
  }

  const handleSeed = async () => {
    try {
      setLoading(true)
      await apiFetch('/api/demo/seed', { method: 'POST' })
      setSeeded(true)
      setCursor(null)
      setCursorStack([])
      await fetchIncidents()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '载入演示事故失败')
      setLoading(false)
    }
  }

  const handleNextPage = () => {
    if (!nextCursor) return
    setCursorStack(prev => [...prev, cursor])
    setCursor(nextCursor)
  }

  const handlePrevPage = () => {
    setCursorStack(prev => {
      if (!prev.length) return prev
      setCursor(prev[prev.length - 1])
      return prev.slice(0, -1)
    })
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.breadcrumb}>事故响应工作台 / 总览</p>
          <h1 className={styles.title}>现在先处理什么？</h1>
          <p className={styles.subtitle}>从最新事故开始，按步骤完成调查、审批和恢复。这里显示的是本地隔离环境。</p>
        </div>
        <div className={styles.actions}>
          <button className={styles.secondaryButton} type="button" onClick={fetchIncidents} disabled={loading}>
            <RefreshCw size={15} className={loading ? styles.spin : ''} aria-hidden="true" /> 刷新
          </button>
          {!seeded && <button className={styles.primaryButton} type="button" onClick={handleSeed}><Activity size={15} aria-hidden="true" /> 载入演示事故</button>}
        </div>
      </header>

      <section className={styles.flowSection} aria-label="事故处理流程">
        <div className={styles.sectionHeading}>
          <div><span className={styles.sectionKicker}>处理流程</span><h2>每一步都能回到证据</h2></div>
          <span className={styles.flowHint}>当前环境：本地演练</span>
        </div>
        <div className={styles.flow}>
          {FLOW_STEPS.map((step, index) => {
            const current = priorityIncident ? stepIndex(priorityIncident.status) : -1
            const Icon = step.icon
            const state = current === index ? 'current' : current > index ? 'done' : 'upcoming'
            return (
              <div key={step.key} className={`${styles.flowStep} ${styles[`flow_${state}`]}`}>
                <span className={styles.flowIcon}><Icon size={16} aria-hidden="true" /></span>
                <span>{step.label}</span>
                {index < FLOW_STEPS.length - 1 && <span className={styles.flowLine} aria-hidden="true" />}
              </div>
            )
          })}
        </div>
      </section>

      <section className={styles.focusGrid} aria-label="当前重点">
        <div className={styles.focusPanel}>
          <div className={styles.sectionHeading}>
            <div><span className={styles.sectionKicker}>下一步</span><h2>{priorityIncident ? (pendingApproval ? '审核恢复动作' : '打开最重要的事故') : '先载入一条演示事故'}</h2></div>
            {priorityIncident && <span className={`${styles.statusBadge} ${STATUS_CLASS[priorityIncident.status] || ''}`}>{STATUS_LABELS[priorityIncident.status] || priorityIncident.status}</span>}
          </div>
          {priorityIncident ? (
            <>
              <p className={styles.focusTitle}>{priorityIncident.alert_name}</p>
              <p className={styles.focusDescription}>{priorityIncident.description}</p>
              <div className={styles.focusMeta}>
                <span className={SEVERITY_CLASS[priorityIncident.severity] || ''}>{SEVERITY_LABELS[priorityIncident.severity] || priorityIncident.severity}</span>
                <span>最近更新 {formatTime(priorityIncident.updated_at)}</span>
              </div>
              <Link className={styles.actionLink} to={`/incidents/${priorityIncident.id}`}>
                {pendingApproval ? '查看证据并处理审批' : '打开事故详情'} <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </>
          ) : (
            <>
              <p className={styles.focusDescription}>没有事故时，先载入演示数据，或进入“故障演练”选择一个固定场景。</p>
              <div className={styles.emptyActions}><button className={styles.primaryButton} type="button" onClick={handleSeed}><Activity size={15} aria-hidden="true" /> 载入演示事故</button><Link className={styles.textLink} to="/scenarios">去选择故障演练 <ArrowRight size={15} aria-hidden="true" /></Link></div>
            </>
          )}
        </div>
        <div className={styles.contextPanel}>
          <div className={styles.sectionHeading}><div><span className={styles.sectionKicker}>当前环境</span><h2>系统可以安全演练</h2></div><CheckCircle2 size={20} className={styles.contextIcon} aria-hidden="true" /></div>
          <p>数据来自隔离 fixture。诊断工具只读，恢复动作需要人工审批。</p>
          <div className={styles.contextRows}>
            <div><span>信号接入</span><strong className={styles.good}>已连接</strong></div>
            <div><span>诊断工具</span><strong className={styles.good}>只读</strong></div>
            <div><span>恢复动作</span><strong className={styles.waiting}>需要审批</strong></div>
          </div>
        </div>
      </section>

      <section className={styles.summaryBar} aria-label="事故摘要">
        <div><span>活跃事故</span><strong>{loading ? '—' : activeIncidents.length}</strong></div>
        <div><span>待处理审批</span><strong className={approvalCount ? styles.numberWarning : ''}>{loading ? '—' : approvalCount}</strong></div>
        <div><span>严重事故</span><strong className={criticalCount ? styles.numberDanger : ''}>{loading ? '—' : criticalCount}</strong></div>
        <div><span>已恢复</span><strong className={styles.numberSuccess}>{loading ? '—' : resolvedCount}</strong></div>
      </section>

      <section className={styles.queueSection}>
        <div className={styles.sectionHeader}>
          <div><span className={styles.sectionKicker}>事故列表</span><h2>所有事故</h2></div>
          <div className={styles.filterBar} aria-label="事故筛选">
            {STATUS_FILTERS.map(filter => <button key={filter.value} className={filter.value === statusFilter ? styles.filterActive : styles.filterButton} type="button" aria-pressed={filter.value === statusFilter} onClick={() => handleFilterChange(filter.value)}>{filter.label}</button>)}
          </div>
        </div>

        {error && <div className={styles.errorBanner} role="alert"><AlertTriangle size={16} aria-hidden="true" /> {error}。请确认控制面已启动。</div>}
        {loading ? <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} /> 正在加载事故</div> : error ? <div className={styles.emptyState}><AlertTriangle size={22} aria-hidden="true" /><strong>暂时无法读取事故</strong><span>数据不完整时不会显示“暂无事故”。</span></div> : incidents.length === 0 ? <div className={styles.emptyState}><Timer size={22} aria-hidden="true" /><strong>没有符合条件的事故</strong><span>可以切换筛选，或去故障演练创建一条新的事故。</span></div> : (
          <div className={styles.table} role="table" aria-label="事故列表">
            <div className={styles.tableHeader} role="row"><span>状态</span><span>事故</span><span>影响描述</span><span>级别</span><span>时间</span><span aria-hidden="true" /></div>
            {incidents.map(incident => <Link key={incident.id} to={`/incidents/${incident.id}`} className={styles.tableRow} role="row">
              <span className={styles.statusCell} data-label="状态"><span className={`${styles.statusBadge} ${STATUS_CLASS[incident.status] || ''}`}><span className={styles.statusDotSmall} />{STATUS_LABELS[incident.status] || incident.status}</span></span>
              <span className={styles.nameCell} data-label="事故">{incident.alert_name}</span>
              <span className={styles.descriptionCell} data-label="影响描述">{incident.description}</span>
              <span className={`${styles.severityCell} ${SEVERITY_CLASS[incident.severity] || ''}`} data-label="级别">{SEVERITY_LABELS[incident.severity] || incident.severity}</span>
              <span className={styles.timeCell} data-label="时间">{formatTime(incident.created_at)}</span>
              <span className={styles.rowArrow}><ArrowRight size={16} aria-hidden="true" /></span>
            </Link>)}
          </div>
        )}
        {!loading && incidents.length > 0 && <div className={styles.pagination}><button className={styles.pageButton} type="button" disabled={!cursorStack.length} onClick={handlePrevPage}>上一页</button><button className={styles.pageButton} type="button" disabled={!nextCursor} onClick={handleNextPage}>下一页</button></div>}
      </section>
    </div>
  )
}
