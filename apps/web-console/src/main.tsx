import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import { AppLayout } from './components/AppLayout'
import { DashboardPage } from './pages/DashboardPage'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { ScenariosPage } from './pages/ScenariosPage'
import { EvaluationsPage } from './pages/EvaluationsPage'
import { SystemPage } from './pages/SystemPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/incidents" element={<DashboardPage />} />
          <Route path="/incidents/:id" element={<IncidentDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/scenarios" element={<ScenariosPage />} />
          <Route path="/exercises" element={<ScenariosPage />} />
          <Route path="/evaluations" element={<EvaluationsPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)

function NotFoundPage() {
  return (
    <section style={{ maxWidth: 640, margin: '12vh auto', textAlign: 'center' }}>
      <p style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>404 / ROUTE NOT FOUND</p>
      <h1 style={{ color: 'var(--color-text)', margin: '12px 0' }}>页面不存在</h1>
      <p style={{ color: 'var(--color-text-muted)' }}>请从控制面导航进入事故、审批、演练或评测视图。</p>
    </section>
  )
}
