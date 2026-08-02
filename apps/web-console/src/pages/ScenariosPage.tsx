import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowRight, CheckCircle2, ClipboardCheck, FlaskConical, LoaderCircle, Play, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
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

const CATEGORY_LABELS: Record<string, string> = { network: '网络', application: '应用', database: '数据库', kubernetes: '容器', resource: '资源' }
const CATEGORY_CLASS: Record<string, string> = { network: styles.network, application: styles.application, database: styles.database, kubernetes: styles.kubernetes, resource: styles.resource }

function targetFor(scenarioId: string) {
  if (scenarioId.startsWith('payment')) return 'payment-api'
  if (scenarioId.startsWith('inventory')) return 'inventory-api'
  return 'order-api'
}

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RunResult | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
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
      setRunResult({ scenario: selected.name, incidentId: data.incident_id, status: data.status })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '启动演练失败')
    } finally {
      setRunningId(null)
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.breadcrumb}>事故响应工作台 / 故障演练</p>
          <h1 className={styles.title}>选择一个故障，练习完整响应</h1>
          <p className={styles.subtitle}>每个场景都有固定信号、固定证据和固定恢复预期。选择后先看预检，再进入事故详情。</p>
        </div>
        <div className={styles.catalogCount}><strong>{scenarios.length}</strong><span>个可回放场景</span></div>
      </header>

      {runResult && <div className={styles.runNotice} role="status"><CheckCircle2 size={17} aria-hidden="true" /><span><b>{runResult.scenario}</b> 已启动，系统已创建事故。</span><Link to={`/incidents/${runResult.incidentId}`}>进入事故详情 <ArrowRight size={14} aria-hidden="true" /></Link></div>}
      {error && <div className={styles.error} role="alert"><ShieldAlert size={16} aria-hidden="true" />{error}</div>}

      <div className={styles.workspace}>
        <section className={styles.catalog} aria-label="故障场景列表">
          <div className={styles.sectionHeading}><div><span className={styles.sectionKicker}>第一步</span><h2>选择故障场景</h2></div><span className={styles.sectionHint}>点击场景查看影响和安全边界</span></div>
          {loading ? <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} /> 正在加载场景</div> : scenarios.length === 0 ? <div className={styles.emptyState}><FlaskConical size={24} aria-hidden="true" /><strong>暂无可用场景</strong><span>请确认控制面已启动。</span></div> : <div className={styles.scenarioList}>
            {scenarios.map(scenario => <button key={scenario.id} type="button" className={`${styles.scenarioRow} ${scenario.id === selectedId ? styles.scenarioSelected : ''}`} onClick={() => setSelectedId(scenario.id)} aria-pressed={scenario.id === selectedId}>
              <span className={`${styles.categoryRail} ${CATEGORY_CLASS[scenario.category] || ''}`} aria-hidden="true" />
              <span className={styles.scenarioContent}>
                <span className={styles.scenarioTopline}><span className={styles.scenarioName}>{scenario.name.replace('@1', '')}</span><span className={styles.category}>{CATEGORY_LABELS[scenario.category] || scenario.category}</span></span>
                <strong>{scenario.description}</strong>
                <span className={styles.scenarioMeta}>影响目标：{targetFor(scenario.id)} · {scenario.allowlisted_runbooks?.[0] === 'no_op' ? '自动恢复' : '需要审批的恢复动作'}</span>
              </span>
              <ArrowRight className={styles.scenarioArrow} size={16} aria-hidden="true" />
            </button>)}
          </div>}
        </section>

        <aside className={styles.preflight} aria-label="演练预检">
          <div className={styles.sectionHeading}><div><span className={styles.sectionKicker}>第二步</span><h2>启动前预检</h2></div><ClipboardCheck size={19} className={styles.preflightIcon} aria-hidden="true" /></div>
          {selected ? <>
            <p className={styles.preflightTitle}>{selected.description}</p>
            <p className={styles.preflightIntro}>确认下面的信息后，系统会在隔离环境创建一条新事故，并自动进入调查阶段。</p>
            <dl className={styles.preflightDetails}>
              <div><dt>影响目标</dt><dd>{targetFor(selected.id)}</dd></div>
              <div><dt>故障类型</dt><dd>{CATEGORY_LABELS[selected.category] || selected.category}</dd></div>
              <div><dt>恢复方式</dt><dd>{selected.allowlisted_runbooks?.[0] === 'no_op' ? '系统自动恢复' : '人工审批后执行'}</dd></div>
              <div><dt>数据范围</dt><dd>仅隔离演练数据</dd></div>
            </dl>
            <div className={styles.checkList}>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>不会连接真实生产环境</span></div>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>调查证据会保存在事故时间线</span></div>
              <div><CheckCircle2 size={15} aria-hidden="true" /><span>写动作仍受安全审批门控</span></div>
            </div>
            {!canRun && <div className={styles.permissionNote}><ShieldAlert size={15} aria-hidden="true" /><span>当前角色是只读观察员。切换为“演练操作员”后才能启动。</span></div>}
            <button className={styles.startButton} type="button" onClick={handleRun} disabled={!canRun || runningId === selected.id}>
              {runningId === selected.id ? <LoaderCircle className={styles.spin} size={16} /> : <Play size={15} fill="currentColor" aria-hidden="true" />}
              {runningId === selected.id ? '正在创建事故' : '确认并开始演练'}
            </button>
          </> : <div className={styles.preflightEmpty}><ClipboardCheck size={28} aria-hidden="true" /><strong>先选择左侧的场景</strong><span>这里会显示影响目标、恢复方式和安全检查。</span></div>}
        </aside>
      </div>
    </div>
  )
}
