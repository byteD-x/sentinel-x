import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ClipboardCheck, LoaderCircle, PlayCircle, RefreshCw, Search, ShieldCheck, Timer } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { INCIDENT_STATUS_LABELS, SEVERITY_LABELS, incidentDescription } from '../lib/presentation'
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

const STATUS_CLASS: Record<string, string> = {
  DETECTED: styles.statusInfo,
  TRIAGING: styles.statusWorking,
  DIAGNOSING: styles.statusWorking,
  PLAN_PROPOSED: styles.statusWorking,
  AWAITING_APPROVAL: styles.statusPending,
  EXECUTING: styles.statusWorking,
  VERIFYING: styles.statusWorking,
  RESOLVED: styles.statusResolved,
  ESCALATED: styles.statusEscalated,
  FAILED: styles.statusFailed,
}

const SEVERITY_CLASS: Record<string, string> = {
  critical: styles.severityCritical,
  warning: styles.severityWarning,
  info: styles.severityInfo,
}

const STATUS_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'AWAITING_APPROVAL', label: '待审批' },
  { value: 'DIAGNOSING', label: '调查中' },
  { value: 'RESOLVED', label: '已恢复' },
  { value: 'ESCALATED', label: '已升级' },
]

const FLOW_STEPS = [
  { key: 'detect', label: '发现', icon: AlertTriangle },
  { key: 'investigate', label: '调查', icon: Search },
  { key: 'approve', label: '审批', icon: ClipboardCheck },
  { key: 'execute', label: '执行', icon: PlayCircle },
  { key: 'verify', label: '验证', icon: ShieldCheck },
]

const severityRank: Record<string, number> = { critical: 0, warning: 1, info: 2 }

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
  const severityFilter = searchParams.get('severity') || 'all'
  const searchFilter = searchParams.get('search') || ''
  const [searchInput, setSearchInput] = useState(searchFilter)
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [seeded, setSeeded] = useState(false)
  const [cursor, setCursor] = useState<string | null>(null)
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)

  const fetchIncidents = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '20' })
      if (statusFilter !== 'all') params.set('status', statusFilter)
      if (severityFilter !== 'all') params.set('severity', severityFilter)
      if (searchFilter) params.set('search', searchFilter)
      if (cursor) params.set('cursor', cursor)
      const response = await apiFetch(`/api/incidents?${params.toString()}`)
      const data = await response.json() as { items?: Incident[]; next_cursor?: string | null }
      setIncidents(data.items || [])
      setNextCursor(data.next_cursor || null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载故障失败')
    } finally {
      setLoading(false)
    }
  }, [cursor, searchFilter, severityFilter, statusFilter])

  useEffect(() => { fetchIncidents() }, [fetchIncidents])

  const activeIncidents = useMemo(() => incidents.filter(item => !['RESOLVED', 'ESCALATED', 'FAILED'].includes(item.status)), [incidents])
  const pendingApproval = useMemo(() => incidents.find(item => item.status === 'AWAITING_APPROVAL'), [incidents])
  const priorityIncident = useMemo(() => {
    if (pendingApproval) return pendingApproval
    return [...activeIncidents].sort((a, b) => (severityRank[a.severity] ?? 9) - (severityRank[b.severity] ?? 9))[0]
  }, [activeIncidents, pendingApproval])
  const resolvedCount = incidents.filter(item => item.status === 'RESOLVED').length
  const criticalCount = incidents.filter(item => item.severity === 'critical').length
  const approvalCount = incidents.filter(item => item.status === 'AWAITING_APPROVAL').length

  const handleFilterChange = (value: string) => {
    setCursor(null)
    setCursorStack([])
    setNextCursor(null)
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('status')
    else next.set('status', value)
    next.delete('cursor')
    setSearchParams(next)
  }

  const handleSeverityChange = (value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('severity')
    else next.set('severity', value)
    next.delete('cursor')
    setSearchParams(next)
  }

  const handleSearchSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = new URLSearchParams(searchParams)
    const value = searchInput.trim()
    if (value) next.set('search', value)
    else next.delete('search')
    next.delete('cursor')
    setSearchParams(next)
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
      setError(cause instanceof Error ? cause.message : '加载演练数据失败')
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
          <p className={styles.breadcrumb}>故障控制台 / 总览</p>
          <h1 className={styles.title}>故障总览</h1>
          <p className={styles.subtitle}>集中查看处理中、待审批和已恢复的故障。数据来自本地演练环境。</p>
        </div>
        <div className={styles.actions}>
          <button className={styles.secondaryButton} type="button" onClick={fetchIncidents} disabled={loading} aria-label="刷新故障列表">
            <RefreshCw size={15} className={loading ? styles.spin : ''} aria-hidden="true" /> 刷新
          </button>
          {!seeded && <button className={styles.primaryButton} type="button" onClick={handleSeed}><Activity size={15} aria-hidden="true" /> 导入演练数据</button>}
        </div>
      </header>

      <section className={styles.commandDeck} aria-label="当前处置状态">
        <div className={styles.deckIntro}>
          <span className={styles.sectionKicker}>当前处置阶段</span>
          <h2>{priorityIncident ? '按流程推进' : '暂无故障'}</h2>
          <p>{priorityIncident ? '优先处理待审批项，再按严重级别查看其他故障。' : '导入演练数据后，这里会显示待处理事项。'}</p>
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
            <div><span className={styles.sectionKicker}>优先处理</span><h2>{priorityIncident ? (pendingApproval ? '待处理审批' : '待处理故障') : '开始一次演练'}</h2></div>
            {priorityIncident && <span className={`${styles.statusBadge} ${STATUS_CLASS[priorityIncident.status] || ''}`}>{INCIDENT_STATUS_LABELS[priorityIncident.status] || priorityIncident.status}</span>}
          </div>
          {priorityIncident ? (
            <>
              <p className={styles.focusTitle}>{incidentDescription(priorityIncident.alert_name)}</p>
              <p className={styles.focusDescription}>{incidentDescription(priorityIncident.description)}</p>
              <div className={styles.focusMeta}>
                <span className={SEVERITY_CLASS[priorityIncident.severity] || ''}>{SEVERITY_LABELS[priorityIncident.severity] || priorityIncident.severity}</span>
                <span>最近更新 {formatTime(priorityIncident.updated_at)}</span>
              </div>
              <Link className={styles.actionLink} to={`/incidents/${priorityIncident.id}`}>
                查看详情 <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </>
          ) : (
            <>
              <p className={styles.focusDescription}>当前没有故障。可以导入一组演练数据，或从故障场景开始。</p>
              <div className={styles.emptyActions}>
                <button className={styles.primaryButton} type="button" onClick={handleSeed}><Activity size={15} aria-hidden="true" /> 导入演练数据</button>
                <Link className={styles.textLink} to="/scenarios">选择故障场景 <ArrowRight size={15} aria-hidden="true" /></Link>
              </div>
            </>
          )}
        </div>
        <div className={styles.contextPanel}>
          <div className={styles.sectionHeading}>
            <div><span className={styles.sectionKicker}>安全边界</span><h2>不写入生产</h2></div>
            <CheckCircle2 size={20} className={styles.contextIcon} aria-hidden="true" />
          </div>
          <p>所有动作都在隔离环境内运行。R2/R3 禁止执行；R1 需核对审批凭证和参数校验。</p>
          <div className={styles.contextRows}>
            <div><span>数据范围</span><strong className={styles.good}>仅演练数据</strong></div>
          <div><span>恢复操作</span><strong className={styles.waiting}>审批后执行</strong></div>
            <div><span>失败处理</span><strong>保留原因</strong></div>
          </div>
        </div>
      </section>

      <section className={styles.summaryBar} aria-label="故障摘要">
        <div><span>处理中</span><strong>{loading ? '-' : activeIncidents.length}</strong></div>
        <div><span>待审批</span><strong className={approvalCount ? styles.numberWarning : ''}>{loading ? '-' : approvalCount}</strong></div>
          <div><span>严重故障</span><strong className={criticalCount ? styles.numberDanger : ''}>{loading ? '-' : criticalCount}</strong></div>
        <div><span>已恢复</span><strong className={styles.numberSuccess}>{loading ? '-' : resolvedCount}</strong></div>
      </section>

      <section className={styles.queueSection}>
        <div className={styles.sectionHeader}>
          <div><span className={styles.sectionKicker}>故障列表</span><h2>全部故障</h2></div>
          <div className={styles.filterBar} aria-label="故障筛选">
            {STATUS_FILTERS.map(filter => <button key={filter.value} className={filter.value === statusFilter ? styles.filterActive : styles.filterButton} type="button" aria-pressed={filter.value === statusFilter} onClick={() => handleFilterChange(filter.value)}>{filter.label}</button>)}
            <select className={styles.filterSelect} aria-label="按严重度筛选" value={severityFilter} onChange={event => handleSeverityChange(event.target.value)}>
              <option value="all">全部级别</option>
              <option value="critical">严重</option>
              <option value="warning">警告</option>
              <option value="info">提示</option>
            </select>
            <form className={styles.searchForm} role="search" onSubmit={handleSearchSubmit}>
              <Search size={14} aria-hidden="true" />
              <input aria-label="搜索故障" value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="搜索故障或服务" />
            </form>
          </div>
        </div>

        {error && <div className={styles.errorBanner} role="alert"><AlertTriangle size={16} aria-hidden="true" /> {error}。请确认控制面在线后重试。</div>}
        {loading ? <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} /> 正在加载故障</div> : error ? <div className={styles.emptyState}><AlertTriangle size={22} aria-hidden="true" /><strong>无法读取故障</strong><span>启动控制面后重试。</span></div> : incidents.length === 0 ? <div className={styles.emptyState}><Timer size={22} aria-hidden="true" /><strong>没有匹配的故障</strong><span>切换筛选，或从故障场景启动演练。</span></div> : (
          <div className={styles.table} role="table" aria-label="故障列表">
            <div className={styles.tableHeader} role="row"><span>状态</span><span>故障</span><span>影响描述</span><span>级别</span><span>时间</span><span aria-hidden="true" /></div>
            {incidents.map(incident => <Link key={incident.id} to={`/incidents/${incident.id}`} className={styles.tableRow} role="row">
              <span className={styles.statusCell} data-label="状态"><span className={`${styles.statusBadge} ${STATUS_CLASS[incident.status] || ''}`}><span className={styles.statusDotSmall} />{INCIDENT_STATUS_LABELS[incident.status] || incident.status}</span></span>
              <span className={styles.nameCell} data-label="故障">{incidentDescription(incident.alert_name)}</span>
              <span className={styles.descriptionCell} data-label="影响描述">{incidentDescription(incident.description)}</span>
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
