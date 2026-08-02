import { Activity, Circle, ClipboardCheck, FlaskConical, LockKeyhole, Radio, ShieldCheck, TerminalSquare, BarChart3 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
import styles from './AppLayout.module.css'

const navigation = [
  { to: '/', label: '事故指挥室', icon: Activity, end: true, shortcut: '01' },
  { to: '/approvals', label: '审批队列', icon: ClipboardCheck, shortcut: '02' },
  { to: '/scenarios', label: '演练场景', icon: FlaskConical, shortcut: '03' },
  { to: '/evaluations', label: '评测证据', icon: BarChart3, shortcut: '04' },
  { to: '/system', label: '系统状态', icon: TerminalSquare, shortcut: '05' },
]

const ROLE_LABELS: Record<string, string> = {
  viewer: '只读观察员',
  approver: '审批人',
  scenario_operator: '演练操作员',
  planner: '方案规划员',
  system: '系统服务',
}

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

  const healthLabel = health.state === 'online' ? 'Control API connected' : health.state === 'loading' ? 'Checking Control API' : 'Control API offline'
  const healthClass = health.state === 'online' ? styles.streamOnline : health.state === 'loading' ? styles.streamChecking : styles.streamOffline

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true">
            <ShieldCheck size={22} strokeWidth={2.4} />
          </div>
          <div>
            <div className={styles.brandName}>Sentinel-X</div>
            <div className={styles.brandCaption}>incident control</div>
          </div>
          <span className={styles.brandBadge}>D1</span>
        </div>

        <div className={styles.navBlock}>
          <p className={styles.navLabel}>WORKSPACE</p>
          <nav className={styles.nav} aria-label="主导航">
            {navigation.map(({ to, label, icon: Icon, end, shortcut }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}
              >
                <Icon size={17} strokeWidth={2} aria-hidden="true" />
                <span>{label}</span>
                <span className={styles.navShortcut}>{shortcut}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className={styles.sidebarFooter}>
          <div className={styles.environmentStatus}>
            <span className={`${styles.statusDot} ${health.state === 'offline' ? styles.statusDotOffline : ''}`} aria-hidden="true" />
            <div>
              <strong>LOCAL LAB</strong>
              <span>Profile / {health.profile || 'light'} · {ROLE_LABELS[role] || role}</span>
            </div>
          </div>
          <div className={styles.safetyNote}>
            <LockKeyhole size={14} aria-hidden="true" />
            <span>{health.actionsEnabled ? 'R1 actions require approval' : 'Actions disabled by kill switch'}</span>
          </div>
        </div>
      </aside>

      <div className={styles.contentShell}>
        <header className={styles.topbar}>
          <div className={styles.topbarContext}>
            <span className={styles.topbarKicker}>SENTINEL-X / CONTROL PLANE</span>
            <span className={styles.topbarDivider}>/</span>
            <span>Local exercise environment</span>
          </div>
          <div className={`${styles.streamStatus} ${healthClass}`} role="status" aria-live="polite">
            <Radio size={14} aria-hidden="true" />
            <span>{healthLabel}</span>
            <Circle size={7} fill="currentColor" aria-hidden="true" />
            <span className={styles.roleBadge}>{ROLE_LABELS[role] || role}</span>
          </div>
        </header>
        <main className={styles.main}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
