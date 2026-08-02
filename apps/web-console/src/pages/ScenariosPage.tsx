import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, CheckCircle2, FlaskConical, LoaderCircle, Play, ShieldAlert } from 'lucide-react'
import { apiFetch, currentRole } from '../lib/api'
import styles from './ScenariosPage.module.css'

interface Scenario {
  id: string
  name: string
  version: number
  description: string
  category: string
}

interface RunResult {
  scenario: string
  incidentId: string
  status: string
}

const CATEGORY_LABELS: Record<string, string> = {
  network: '网络',
  application: '应用',
  database: '数据库',
  kubernetes: 'Kubernetes',
  resource: '资源',
}

const CATEGORY_CLASS: Record<string, string> = {
  network: styles.network,
  application: styles.application,
  database: styles.database,
  kubernetes: styles.kubernetes,
  resource: styles.resource,
}

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RunResult | null>(null)
  const [preflightId, setPreflightId] = useState<string | null>(null)
  const role = currentRole()
  const canRun = role === 'scenario_operator'

  const fetchScenarios = useCallback(async () => {
    try {
      const res = await apiFetch('/api/scenarios')
      const data = await res.json()
      setScenarios(data.items || [])
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchScenarios() }, [fetchScenarios])

  const handleRun = async (scenarioId: string) => {
    setPreflightId(null)
    setRunningId(scenarioId)
    setRunResult(null)
    try {
      const res = await apiFetch(`/api/scenarios/${scenarioId}/run`, { method: 'POST' })
      const data = await res.json()
      setRunResult({ scenario: scenarioId, incidentId: data.incident_id, status: data.status })
    } catch (e) {
      setError(e instanceof Error ? e.message : '启动失败')
    } finally {
      setRunningId(null)
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}><FlaskConical size={14} aria-hidden="true" /> SCENARIO CATALOG</div>
          <h1 className={styles.title}>演练场景</h1>
          <p className={styles.subtitle}>固定故障、固定根因和固定恢复断言，用来验证调查链路而不是模型自评。当前角色：{role}。</p>
        </div>
        <div className={styles.catalogMeta}><strong>{scenarios.length}</strong><span>registered scenarios</span></div>
      </header>

      {runResult && (
        <div className={styles.runNotice} role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          <span><b>{runResult.scenario}</b> 已启动，状态 {runResult.status}，事故已写入控制面。</span>
          <Link to={`/incidents/${runResult.incidentId}`}>打开事故 <ArrowUpRight size={14} aria-hidden="true" /></Link>
        </div>
      )}

      {error && (
        <div className={styles.error} role="alert"><ShieldAlert size={16} aria-hidden="true" />{error}</div>
      )}

      {loading ? (
        <div className={styles.empty}><LoaderCircle className={styles.spin} size={20} />加载场景目录</div>
      ) : (
        <div className={styles.grid}>
          {scenarios.map(scenario => (
            <article key={scenario.id} className={styles.scenarioRow}>
              <div className={`${styles.categoryRail} ${CATEGORY_CLASS[scenario.category] || ''}`} />
              <div className={styles.scenarioBody}>
                <div className={styles.scenarioTopline}>
                  <span className={styles.scenarioId}>{scenario.name}</span>
                  <span className={styles.category}>{CATEGORY_LABELS[scenario.category] || scenario.category}</span>
                </div>
                <h2>{scenario.description}</h2>
              <div className={styles.scenarioMeta}>
                <span>schema / v{scenario.version}</span>
                <span>profile / light</span>
                <span>ground truth / fixed</span>
                <span>cleanup / fixture only</span>
              </div>
              <div className={styles.preflightLine}>目标：{scenario.id.split('-')[0]}-api · 写动作：R1 审批门控 · dirty gate：隔离环境</div>
              </div>
              <button
                className={styles.runButton}
                type="button"
                onClick={() => setPreflightId(scenario.id)}
                disabled={runningId === scenario.id || !canRun}
                title={canRun ? '打开演练预检' : '需要 scenario_operator 角色'}
              >
                {runningId === scenario.id ? <LoaderCircle className={styles.spin} size={16} /> : <Play size={15} fill="currentColor" aria-hidden="true" />}
                {runningId === scenario.id ? '启动中' : canRun ? '启动演练' : '仅限操作员'}
              </button>
            </article>
          ))}
        </div>
      )}
      {preflightId && (
        <div className={styles.preflightBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreflightId(null) }}>
          <div className={styles.preflightDialog} role="dialog" aria-modal="true" aria-labelledby="preflight-title">
            <h2 id="preflight-title">演练启动预检</h2>
            <p>确认目标、影响范围和清理策略后再注入故障。</p>
            <dl>
              <div><dt>场景</dt><dd>{preflightId}</dd></div>
              <div><dt>Profile</dt><dd>light fixture</dd></div>
              <div><dt>目标</dt><dd>{preflightId.split('-')[0]}-api</dd></div>
              <div><dt>影响 / cleanup</dt><dd>仅隔离演练数据；无真实生产写入</dd></div>
            </dl>
            <div className={styles.preflightActions}>
              <button type="button" className={styles.cancelButton} onClick={() => setPreflightId(null)}>取消</button>
              <button type="button" className={styles.confirmButton} onClick={() => handleRun(preflightId)}>确认启动</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
