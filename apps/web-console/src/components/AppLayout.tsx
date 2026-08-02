import { Activity, BarChart3, Circle, ClipboardCheck, FlaskConical, LockKeyhole, Radio, ShieldCheck, TerminalSquare } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
import { ROLE_LABELS } from '../lib/presentation'
import styles from './AppLayout.module.css'

const navigation = [
  { to: '/', label: '故障总览', icon: Activity, end: true },
  { to: '/approvals', label: '恢复审批', icon: ClipboardCheck },
  { to: '/scenarios', label: '故障场景', icon: FlaskConical },
  { to: '/evaluations', label: '演练记录', icon: BarChart3 },
  { to: '/system', label: '环境', icon: TerminalSquare },
]

export function AppLayout() {
  const role = currentRole()
  const [health, setHealth] = useState<{ state: 'loading' | 'online' | 'offline'; profile?: string; actionsEnabled?: boolean }>({ state: 'loading' })

  useEffect(() => {
    let active = true
    const check = async () => {
      try {
        const response = await apiFetch('/health')
        const data = await response.json() as { profile?: string; actions_enabled?: boolean }
        if (active) setHealth({ state: 'online', profile: data.profile || 'light', actionsEnabled: data.actions_enabled })
      } catch {
        if (active) setHealth({ state: 'offline' })
      }
    }
    check()
    const timer = window.setInterval(check, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const healthLabel = health.state === 'online' ? '系统已连接' : health.state === 'loading' ? '正在连接系统' : '系统未连接'
  const healthClass = health.state === 'online' ? styles.streamOnline : health.state === 'loading' ? styles.streamChecking : styles.streamOffline

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true"><ShieldCheck size={20} strokeWidth={2.3} /></div>
          <div>
            <div className={styles.brandName}>Sentinel-X</div>
            <div className={styles.brandCaption}>故障处理台</div>
          </div>
          <span className={styles.brandBadge}>演练</span>
        </div>

        <div className={styles.navBlock}>
          <p className={styles.navLabel}>工作区</p>
          <nav className={styles.nav} aria-label="主导航">
            {navigation.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}
              >
                <Icon size={17} strokeWidth={2} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className={styles.sidebarFooter}>
          <div className={styles.environmentStatus}>
            <span className={`${styles.statusDot} ${health.state === 'offline' ? styles.statusDotOffline : ''}`} aria-hidden="true" />
            <div>
              <strong>演练环境</strong>
              <span>{ROLE_LABELS[role] || '只读'}</span>
            </div>
          </div>
          <div className={styles.safetyNote}>
            <LockKeyhole size={14} aria-hidden="true" />
            <span>{health.actionsEnabled ? '恢复操作需审批' : '恢复操作已关闭'}</span>
          </div>
        </div>
      </aside>

      <div className={styles.contentShell}>
        <header className={styles.topbar}>
          <div className={styles.topbarContext}>
            <span className={styles.topbarKicker}>故障处理台</span>
            <span className={styles.topbarDivider}>·</span>
            <span>演练环境</span>
          </div>
          <div className={`${styles.streamStatus} ${healthClass}`} role="status" aria-live="polite">
            <Radio size={14} aria-hidden="true" />
            <span>{healthLabel}</span>
            <Circle size={7} fill="currentColor" aria-hidden="true" />
            <span className={styles.roleBadge}>{ROLE_LABELS[role] || '只读'}</span>
          </div>
        </header>
        <main className={styles.main}><Outlet /></main>
      </div>
    </div>
  )
}
