import { useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, LockKeyhole, RefreshCw, ServerCog } from 'lucide-react'
import { apiFetch } from '../lib/api'
import styles from './SystemPage.module.css'

interface HealthData { status?: string; version?: string; environment?: string; profile?: string; actions_enabled?: boolean; registered_runbooks?: number }

export function SystemPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true)
    try { const response = await apiFetch('/health'); setHealth(await response.json()); setError(null) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '检查系统状态失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div><div className={styles.eyebrow}><ServerCog size={14} aria-hidden="true" /> 演练环境</div><h1>演练环境</h1><p>用于确认控制面连接和恢复操作开关。所有数据均为演练数据。</p></div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新环境状态"><RefreshCw size={15} aria-hidden="true" /> 刷新</button>
      </header>
      {error ? <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div> : <div className={styles.grid}>
        <StatusRow label="控制面连接" value={health?.status === 'ok' ? '已连接' : '未知'} ok={health?.status === 'ok'} />
        <StatusRow label="运行模式" value="演练环境" ok />
        <StatusRow label="恢复操作" value={health?.actions_enabled ? '需审批' : '已关闭'} ok={!health?.actions_enabled} />
        <StatusRow label="可用恢复方式" value={String(health?.registered_runbooks ?? '暂未提供')} ok />
      </div>}
      <div className={styles.safety}><LockKeyhole size={17} aria-hidden="true" /><span>高风险操作禁止，生产写操作不会在演练环境执行。</span></div>
    </div>
  )
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return <div className={styles.row}><span>{ok ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}</span><strong>{label}</strong><span className={styles.value}>{value}</span></div>
}
