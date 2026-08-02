import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Database,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  Server,
  ShieldCheck,
  TimerReset,
  Zap,
} from 'lucide-react'
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

interface ServiceNodeProps {
  name: string
  role: string
  metric: string
  detail: string
  tone: 'healthy' | 'watch' | 'degraded' | 'unknown'
  icon: typeof Server
}

function ServiceNode({ name, role, metric, detail, tone, icon: Icon }: ServiceNodeProps) {
  return (
    <div className={`${styles.serviceNode} ${styles[`node_${tone}`]}`}>
      <div className={styles.nodeTopline}>
        <span className={styles.nodeIcon}><Icon size={16} aria-hidden="true" /></span>
        <span className={styles.nodeStatus}><CircleDot size={10} fill="currentColor" aria-hidden="true" /> {tone === 'healthy' ? 'healthy' : tone === 'watch' ? 'watch' : tone === 'degraded' ? 'degraded' : 'unknown'}</span>
      </div>
      <strong>{name}</strong>
      <span className={styles.nodeRole}>{role}</span>
      <div className={styles.nodeMetric}>
        <b>{metric}</b>
        <span>{detail}</span>
      </div>
    </div>
  )
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
      const res = await apiFetch(`/api/incidents?${params.toString()}`)
      const data = await res.json()
      setIncidents(data.items || [])
      setNextCursor(data.next_cursor || null)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [cursor, statusFilter])

  useEffect(() => { fetchIncidents() }, [fetchIncidents])

  const handleFilterChange = (value: string) => {
    setCursor(null)
    setCursorStack([])
    setNextCursor(null)
    setSearchParams(value === 'all' ? {} : { status: value })
  }

  const handleNextPage = () => {
    if (!nextCursor) return
    setCursorStack(prev => [...prev, cursor])
    setCursor(nextCursor)
  }

  const handlePrevPage = () => {
    setCursorStack(prev => {
      if (prev.length === 0) return prev
      setCursor(prev[prev.length - 1])
      return prev.slice(0, -1)
    })
  }

  const handleSeed = async () => {
    try {
      setLoading(true)
      await apiFetch('/api/demo/seed', { method: 'POST' })
      setSeeded(true)
      setCursor(null)
      setCursorStack([])
      await fetchIncidents()
    } catch (e) {
      setError(e instanceof Error ? e.message : '载入演示数据失败')
      setLoading(false)
    }
  }

  const hasData = !loading && !error
  const activeCount = incidents.filter(i => !['RESOLVED', 'ESCALATED', 'FAILED'].includes(i.status)).length
  const resolvedCount = incidents.filter(i => i.status === 'RESOLVED').length
  const criticalCount = incidents.filter(i => i.severity === 'critical').length
  const approvalCount = incidents.filter(i => i.status === 'AWAITING_APPROVAL').length
  const topologyTone: ServiceNodeProps['tone'] = !hasData ? 'unknown' : activeCount > 0 ? 'degraded' : 'healthy'

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div className={styles.titleGroup}>
          <div className={styles.eyebrow}><span className={styles.livePulse} /> INCIDENT DESK / LOCAL EXERCISE</div>
          <h1 className={styles.title}>事故指挥室</h1>
          <p className={styles.subtitle}>从异常信号到人工批准的恢复动作，所有调查证据都在同一条链路上。</p>
        </div>
        <div className={styles.actions}>
          <button className={styles.btnSecondary} type="button" onClick={fetchIncidents} title="刷新事故数据">
            <RefreshCw size={15} aria-hidden="true" />
            刷新
          </button>
          {!seeded && (
            <button className={styles.btnPrimary} type="button" onClick={handleSeed}>
              <Zap size={15} aria-hidden="true" />
              载入演示事故
            </button>
          )}
        </div>
      </header>

      <section className={styles.metricStrip} aria-label="事故状态摘要">
        <div className={styles.metricItem}>
          <span><Activity size={14} aria-hidden="true" /> 活跃事故</span>
          <strong>{hasData ? activeCount : '—'}</strong>
          <small>当前结果集</small>
        </div>
        <div className={styles.metricItem}>
          <span><AlertTriangle size={14} aria-hidden="true" /> 待审批</span>
          <strong className={hasData && approvalCount > 0 ? styles.metricAccent : ''}>{hasData ? approvalCount : '—'}</strong>
          <small>需要值班工程师确认</small>
        </div>
        <div className={styles.metricItem}>
          <span><ShieldCheck size={14} aria-hidden="true" /> 严重事故</span>
          <strong className={hasData && criticalCount > 0 ? styles.metricDanger : ''}>{hasData ? criticalCount : '—'}</strong>
          <small>critical severity</small>
        </div>
        <div className={styles.metricItem}>
          <span><CheckCircle2 size={14} aria-hidden="true" /> 已恢复</span>
          <strong className={styles.metricSuccess}>{hasData ? resolvedCount : '—'}</strong>
          <small>通过恢复窗口验证</small>
        </div>
      </section>

      <div className={styles.workspaceGrid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <div className={styles.panelEyebrow}>SERVICE TOPOLOGY</div>
              <h2>演练业务链路</h2>
            </div>
            <span className={styles.panelMeta}><GitBranch size={14} aria-hidden="true" /> 3 services / 1 data path</span>
          </div>
          <div className={styles.topology} aria-label="订单、库存、支付服务拓扑">
            <ServiceNode name="order-api" role="入口 / checkout" metric={!hasData ? '—' : topologyTone === 'healthy' ? '99.98%' : '12.4%'} detail={hasData ? 'success rate' : 'unavailable'} tone={topologyTone} icon={Server} />
            <ChevronRight className={styles.topologyArrow} size={22} aria-hidden="true" />
            <ServiceNode name="inventory-api" role="dependency / stock" metric={!hasData ? '—' : topologyTone === 'healthy' ? '180 ms' : '3.2 s'} detail={hasData ? 'p99 latency' : 'unavailable'} tone={!hasData ? 'unknown' : activeCount > 0 ? 'watch' : 'healthy'} icon={Database} />
            <ChevronRight className={styles.topologyArrow} size={22} aria-hidden="true" />
            <ServiceNode name="payment-api" role="dependency / charge" metric={!hasData ? '—' : topologyTone === 'healthy' ? '0.3%' : '12.0%'} detail={hasData ? 'error rate' : 'unavailable'} tone={!hasData ? 'unknown' : activeCount > 0 ? 'degraded' : 'healthy'} icon={Zap} />
          </div>
          <div className={styles.topologyFooter}>
            <span><span className={styles.legendDot} /> request path</span>
            <span><TimerReset size={14} aria-hidden="true" /> {hasData ? 'last signal 12s ago' : 'signal unavailable'}</span>
            <span>profile: <b>light</b></span>
          </div>
        </section>

        <section className={`${styles.panel} ${styles.attentionPanel}`}>
          <div className={styles.panelHeader}>
            <div>
              <div className={styles.panelEyebrow}>CURRENT ATTENTION</div>
              <h2>值班关注</h2>
            </div>
            <span className={styles.signalCount}>{approvalCount} pending</span>
          </div>
          {approvalCount > 0 ? (
            <div className={styles.attentionLead}>
              <span className={styles.attentionIcon}><AlertTriangle size={19} aria-hidden="true" /></span>
              <div>
                <strong>有恢复动作等待确认</strong>
                <p>先检查目标、参数、风险等级和计划哈希，再决定是否批准。</p>
              </div>
            </div>
          ) : (
            <div className={styles.attentionLead}>
              <span className={`${styles.attentionIcon} ${styles.attentionIconClear}`}><CheckCircle2 size={19} aria-hidden="true" /></span>
              <div>
                <strong>当前没有待审批动作</strong>
                <p>可以从演练场景启动一次固定故障调查。</p>
              </div>
            </div>
          )}
          <div className={styles.signalRows}>
            <div><span>Telemetry</span><b className={error ? styles.warnText : styles.okText}>{error ? 'unavailable' : 'connected'}</b></div>
            <div><span>Diagnostic tools</span><b className={error ? styles.warnText : styles.okText}>{error ? 'unavailable' : 'read-only'}</b></div>
            <div><span>Action Gateway</span><b className={styles.warnText}>{error ? 'unknown' : 'approval gated'}</b></div>
          </div>
        </section>
      </div>

      <section className={styles.incidentSection}>
        <div className={styles.sectionHeader}>
          <div>
            <div className={styles.panelEyebrow}>INCIDENT QUEUE</div>
            <h2>事故队列</h2>
          </div>
          <div className={styles.filterBar} aria-label="事故筛选">
            {STATUS_FILTERS.map(filter => (
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
        </div>

        {error && (
          <div className={styles.errorBanner} role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>{error}。请先启动 Control API。</span>
          </div>
        )}

        {loading ? (
          <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} />加载事故队列</div>
        ) : error ? (
          <div className={styles.emptyState} role="status">
            <AlertTriangle size={24} aria-hidden="true" />
            <strong>事故队列不可用</strong>
            <span>当前没有可靠数据，不显示“暂无事故”。请确认 Control API 已启动。</span>
          </div>
        ) : incidents.length === 0 ? (
          <div className={styles.emptyState}>
            <CircleDot size={24} aria-hidden="true" />
            <strong>暂无事故记录</strong>
            <span>载入演示事故，或从演练场景启动一次故障。</span>
          </div>
        ) : (
          <div className={styles.table} role="table" aria-label="事故队列">
            <div className={styles.tableHeader} role="row">
              <span>状态</span><span>级别</span><span>告警名称</span><span>当前描述</span><span>时间</span><span aria-hidden="true" />
            </div>
            {incidents.map(inc => (
              <Link key={inc.id} to={`/incidents/${inc.id}`} className={styles.tableRow} role="row">
                <span className={styles.statusCell} data-label="状态">
                  <span className={`${styles.statusBadge} ${STATUS_CLASS[inc.status] || ''}`}>
                    <CircleDot size={10} fill="currentColor" aria-hidden="true" />
                    {STATUS_LABELS[inc.status] || inc.status}
                  </span>
                </span>
                <span className={`${styles.severityCell} ${SEVERITY_CLASS[inc.severity] || ''}`} data-label="级别">{inc.severity}</span>
                <span className={styles.nameCell} data-label="告警名称">{inc.alert_name}</span>
                <span className={styles.descriptionCell} data-label="当前描述">{inc.description}</span>
                <span className={styles.timeCell} data-label="时间">{new Date(inc.created_at).toLocaleTimeString('zh-CN')}</span>
                <span className={styles.rowArrow}><ArrowUpRight size={16} aria-hidden="true" /></span>
              </Link>
            ))}
          </div>
        )}

        {!loading && incidents.length > 0 && (
          <div className={styles.pagination}>
            <button className={styles.btnGhost} type="button" disabled={cursorStack.length === 0} onClick={handlePrevPage}>上一页</button>
            <button className={styles.btnGhost} type="button" disabled={!nextCursor} onClick={handleNextPage}>下一页</button>
          </div>
        )}
      </section>
    </div>
  )
}
