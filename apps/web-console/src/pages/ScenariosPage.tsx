import { useState, useEffect, useCallback } from 'react'
import styles from './ScenariosPage.module.css'

interface Scenario {
  id: string
  name: string
  version: number
  description: string
  category: string
}

const CATEGORY_LABELS: Record<string, string> = {
  network: '网络',
  application: '应用',
  database: '数据库',
  kubernetes: 'Kubernetes',
  resource: '资源',
}

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)

  const fetchScenarios = useCallback(async () => {
    try {
      const res = await fetch('/api/scenarios')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
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
    setRunningId(scenarioId)
    try {
      const res = await fetch(`/api/scenarios/${scenarioId}/run`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      alert(`场景已启动！事故 ID: ${data.incident_id}`)
    } catch (e) {
      alert(`启动失败: ${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setRunningId(null)
      fetchScenarios()
    }
  }

  return (
    <div>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>演练场景</h1>
          <p className={styles.subtitle}>{scenarios.length} 个已登记场景</p>
        </div>
      </div>

      {error && <div className={styles.error}>⚠️ {error}</div>}

      {loading ? (
        <div className={styles.empty}>加载中...</div>
      ) : (
        <div className={styles.grid}>
          {scenarios.map(scenario => (
            <div key={scenario.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={styles.cardName}>{scenario.name}</span>
                <span className={styles.cardCategory}>
                  {CATEGORY_LABELS[scenario.category] || scenario.category}
                </span>
              </div>
              <p className={styles.cardDesc}>{scenario.description}</p>
              <button
                className={styles.runBtn}
                onClick={() => handleRun(scenario.id)}
                disabled={runningId === scenario.id}
              >
                {runningId === scenario.id ? '启动中...' : '▶ 启动演练'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
