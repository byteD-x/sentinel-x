import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, CheckCircle2, ClipboardCheck, FlaskConical, LoaderCircle, Play, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
import { CATEGORY_LABELS, ROLE_LABELS, scenarioDescription, scenarioLabel, serviceLabel } from '../lib/presentation'
import styles from './ScenariosPage.module.css'

interface Scenario {
  id: string
  name: string
  version: number
  description: string
  category: string
  allowlisted_runbooks?: string[]
}

interface RunResult { scenario: string; incidentId: string; status: string }

const CATEGORY_CLASS: Record<string, string> = { network: styles.network, application: styles.application, database: styles.database, kubernetes: styles.kubernetes, resource: styles.resource }

function targetFor(scenarioId: string) {
  if (scenarioId.startsWith('payment')) return serviceLabel('payment-api')
  if (scenarioId.startsWith('inventory')) return serviceLabel('inventory-api')
  return serviceLabel('order-api')
}

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RunResult | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const preflightRef = useRef<HTMLElement | null>(null)
  const role = currentRole()
  const canRun = role === 'scenario_operator'
  const selected = useMemo(() => scenarios.find(item => item.id === selectedId) || null, [scenarios, selectedId])

  const fetchScenarios = useCallback(async () => {
    try {
      const response = await apiFetch('/api/scenarios')
      const data = await response.json()
      setScenarios(data.items || [])
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载故障场景失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchScenarios() }, [fetchScenarios])

  const handleRun = async () => {
    if (!selected) return
    setRunningId(selected.id)
    setRunResult(null)
    try {
      const response = await apiFetch(`/api/scenarios/${selected.id}/run`, { method: 'POST' })
      const data = await response.json()
      setRunResult({ scenario: scenarioLabel(selected.name), incidentId: data.incident_id, status: data.status })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '启动演练失败')
    } finally {
      setRunningId(null)
    }
  }

  const handleSelectScenario = (scenarioId: string) => {
    setSelectedId(scenarioId)
    if (window.matchMedia('(max-width: 980px)').matches) {
      window.setTimeout(() => preflightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0)
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.breadcrumb}>故障处理台 / 故障场景</p>
          <h1 className={styles.title}>故障场景</h1>
          <p className={styles.subtitle}>在隔离环境复现故障，先检查影响范围和恢复条件，再启动演练。</p>
        </div>
        <div className={styles.catalogCount}><strong>{scenarios.length}</strong><span>个可用场景</span></div>
      </header>

      {runResult && <div className={styles.runNotice} role="status"><CheckCircle2 size={17} aria-hidden="true" /><span><b>{runResult.scenario}</b> 已启动，故障记录已创建。</span><Link to={`/incidents/${runResult.incidentId}`}>查看故障 <ArrowRight size={14} aria-hidden="true" /></Link></div>}
      {error && <div className={styles.error} role="alert"><ShieldAlert size={16} aria-hidden="true" />{error}</div>}

      <div className={styles.workspace}>
        <section className={styles.catalog} aria-label="故障场景列表">
          <div className={styles.sectionHeading}><div><span className={styles.sectionKicker}>1. 选择</span><h2>故障场景</h2></div><span className={styles.sectionHint}>查看影响范围和恢复条件</span></div>
          {loading ? <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} /> 正在加载场景</div> : scenarios.length === 0 ? <div className={styles.emptyState}><FlaskConical size={24} aria-hidden="true" /><strong>暂无可用场景</strong><span>请检查控制面是否已启动。</span></div> : <div className={styles.scenarioList}>
            {scenarios.map(scenario => <button key={scenario.id} type="button" className={`${styles.scenarioRow} ${scenario.id === selectedId ? styles.scenarioSelected : ''}`} onClick={() => handleSelectScenario(scenario.id)} aria-pressed={scenario.id === selectedId}>
              <span className={`${styles.categoryRail} ${CATEGORY_CLASS[scenario.category] || ''}`} aria-hidden="true" />
              <span className={styles.scenarioContent}>
                <span className={styles.scenarioTopline}><span className={styles.scenarioName}>{scenarioLabel(scenario.name)}</span><span className={styles.category}>{CATEGORY_LABELS[scenario.category] || scenario.category}</span></span>
                <strong>{scenarioDescription(scenario.id, scenario.description)}</strong>
                <span className={styles.scenarioMeta}>目标：{targetFor(scenario.id)} · {scenario.allowlisted_runbooks?.[0] === 'no_op' ? '自动恢复' : '需审批'}</span>
              </span>
              <ArrowRight className={styles.scenarioArrow} size={16} aria-hidden="true" />
            </button>)}
          </div>}
        </section>

        <aside ref={preflightRef} className={styles.preflight} aria-label="演练启动条件">
          <div className={styles.sectionHeading}><div><span className={styles.sectionKicker}>2. 检查</span><h2>启动前检查</h2></div><ClipboardCheck size={19} className={styles.preflightIcon} aria-hidden="true" /></div>
          {selected ? <>
            <p className={styles.preflightTitle}>{scenarioLabel(selected.name)}</p>
            <p className={styles.preflightIntro}>核对影响范围和恢复条件后启动。系统会创建对应的故障记录。</p>
            <dl className={styles.preflightDetails}>
              <div><dt>目标服务</dt><dd>{targetFor(selected.id)}</dd></div>
              <div><dt>故障表现</dt><dd>{scenarioDescription(selected.id, selected.description)}</dd></div>
              <div><dt>恢复方式</dt><dd>{selected.allowlisted_runbooks?.[0] === 'no_op' ? '自动恢复' : '审批后执行'}</dd></div>
              <div><dt>是否写入生产</dt><dd>不会，仅使用演练数据</dd></div>
            </dl>
            <div className={styles.checkList}>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>不写入生产系统</span></div>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>处理过程写入时间线</span></div>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>恢复操作需要审批</span></div>
            </div>
            {!canRun && <div className={styles.permissionNote}><ShieldAlert size={15} aria-hidden="true" /><span>当前角色为“{ROLE_LABELS[role] || '只读'}”，无权启动演练。</span></div>}
            <button className={styles.startButton} type="button" onClick={handleRun} disabled={!canRun || runningId === selected.id}>
              {runningId === selected.id ? <LoaderCircle className={styles.spin} size={16} /> : <Play size={15} fill="currentColor" aria-hidden="true" />}
              {runningId === selected.id ? '启动中' : '启动演练'}
            </button>
          </> : <div className={styles.preflightEmpty}><ClipboardCheck size={28} aria-hidden="true" /><strong>选择一个场景</strong><span>这里显示目标服务、故障表现和恢复条件。</span></div>}
        </aside>
      </div>
    </div>
  )
}
