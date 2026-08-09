import { useEffect, useState } from 'react'
import {
  Archive,
  BarChart3,
  ChevronRight,
  CircleAlert,
  Hash,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import type { EvaluationDetailResponse, EvaluationListResponse, EvaluationMetric } from '../features/evaluations/contracts'
import { apiFetch, ApiError } from '../lib/api'
import styles from './EvaluationsPage.module.css'

const METRIC_LABELS: Record<string, string> = {
  top1_accuracy: 'Top-1 根因命中率',
  mrr: '平均倒数排名',
  evidence_precision: '证据准确率',
  time_to_diagnose_sec: '诊断用时',
  time_to_recover_sec: '恢复用时',
  recovery_success_rate: '恢复成功率',
  safety_violations: '安全违规数',
  r2_rejection_rate: 'R2 拒绝率',
  prompt_injection_blocked: '提示注入拦截数',
  tokens_consumed: 'Token 消耗',
  llm_calls_per_incident: '单事故模型调用数',
  total_cost_estimate: '成本估算',
}

function metricLabel(name: string) {
  return METRIC_LABELS[name] || name
}

function metricValue(metric: EvaluationMetric) {
  return `${metric.value}${metric.unit}`
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function EvaluationDetail({ detail }: { detail: EvaluationDetailResponse }) {
  const { report, artifact } = detail
  return (
    <div className={styles.detailBody}>
      <header className={styles.detailHeader}>
        <div>
          <span>报告 ID</span>
          <h2>{report.report_id}</h2>
        </div>
        <time dateTime={report.created_at}>{formatDate(report.created_at)}</time>
      </header>

      <dl className={styles.reportFacts}>
        <div><dt>数据集</dt><dd>{report.metadata.dataset_ref}</dd></div>
        <div><dt>模型</dt><dd>{report.metadata.model_ref}</dd></div>
        <div><dt>完成</dt><dd>{report.aggregate.completed_runs}</dd></div>
        <div><dt>失败</dt><dd>{report.aggregate.failed_runs}</dd></div>
      </dl>

      <section className={styles.detailSection} aria-labelledby="comparability-title">
        <div className={styles.sectionHeading}>
          <h3 id="comparability-title">可比性</h3>
          <strong className={report.comparability.comparable ? styles.comparable : styles.notComparable}>
            {report.comparability.comparable ? '可比较' : '不可比较'}
          </strong>
        </div>
        {report.comparability.baseline_ref && <code className={styles.baseline}>{report.comparability.baseline_ref}</code>}
        {report.comparability.reasons.length > 0 && (
          <ul className={styles.reasons}>
            {report.comparability.reasons.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}
          </ul>
        )}
      </section>

      {report.aggregate.metrics.length > 0 && (
        <section className={styles.detailSection} aria-labelledby="metrics-title">
          <div className={styles.sectionHeading}>
            <h3 id="metrics-title">汇总指标</h3>
            <span>{report.aggregate.metrics.length} 项</span>
          </div>
          <div className={styles.metrics}>
            {report.aggregate.metrics.map(metric => (
              <article key={`${metric.category}:${metric.name}`} className={styles.metric}>
                <div className={styles.metricName}>
                  <span>{metricLabel(metric.name)}</span>
                  <code>{metric.name}</code>
                </div>
                <strong>{metricValue(metric)}</strong>
                <div className={styles.metricMeta}>
                  {metric.target !== null && <span>目标 {metric.target}{metric.unit}</span>}
                  {metric.sample_count !== undefined && <span>样本 {metric.sample_count}</span>}
                  {metric.passed !== null && (
                    <span className={metric.passed ? styles.metricPassed : styles.metricFailed}>
                      {metric.passed ? '达标' : '未达标'}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {report.failures.length > 0 && (
        <section className={styles.detailSection} aria-labelledby="failures-title">
          <div className={styles.sectionHeading}>
            <h3 id="failures-title">失败记录</h3>
            <span>{report.failures.length} 条</span>
          </div>
          <div className={styles.failures}>
            {report.failures.map(failure => (
              <article key={`${failure.scenario_ref}:${failure.run_index}`}>
                <div><strong>{failure.scenario_ref}</strong><code>{failure.code}</code></div>
                <p>{failure.message}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className={styles.artifact} aria-label="报告校验">
        <Hash size={15} aria-hidden="true" />
        <div><span>SHA-256</span><code>{artifact.sha256}</code></div>
      </section>
    </div>
  )
}

export function EvaluationsPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [archive, setArchive] = useState<EvaluationListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<EvaluationDetailResponse | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch('/api/evaluations')
      setArchive(await response.json() as EvaluationListResponse)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '评测归档暂时不可用')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!reportId) {
      setDetail(null)
      setDetailError(null)
      setDetailLoading(false)
      return
    }

    let active = true
    setDetailLoading(true)
    setDetailError(null)
    apiFetch(`/api/evaluations/${encodeURIComponent(reportId)}`)
      .then(response => response.json() as Promise<EvaluationDetailResponse>)
      .then(data => { if (active) setDetail(data) })
      .catch(cause => {
        const message = cause instanceof Error ? cause.message : '评测报告加载失败'
        if (active) setDetailError(`无法读取这份评测报告：${message}`)
      })
      .finally(() => { if (active) setDetailLoading(false) })

    return () => { active = false }
  }, [reportId])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}><BarChart3 size={14} aria-hidden="true" /> 评测归档</div>
          <h1>评测报告</h1>
          <p>查看本地隔离环境生成的脱敏结果。</p>
        </div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新评测报告">
          <RefreshCw className={loading ? styles.spin : ''} size={15} aria-hidden="true" /> 刷新
        </button>
      </header>

      <div className={styles.workspace}>
        <section className={styles.archivePanel} aria-labelledby="archive-list-title">
          <div className={styles.panelHeading}>
            <div><span>报告队列</span><h2 id="archive-list-title">归档记录</h2></div>
            {archive && <strong>{archive.items.length}</strong>}
          </div>

          {loading && !archive ? (
            <div className={styles.state} role="status" aria-live="polite">
              <LoaderCircle className={styles.spin} size={18} aria-hidden="true" />正在读取评测归档…
            </div>
          ) : error && !archive ? (
            <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div>
          ) : archive?.items.length === 0 ? (
            <div className={styles.state} role="status">
              <Archive size={19} aria-hidden="true" />{archive.unavailable_reason || '尚无已归档的评测报告'}
            </div>
          ) : archive ? (
            <div className={styles.archiveList}>
              {archive.items.map(item => item.archive_status === 'invalid' ? (
                <article key={item.report_id} className={styles.invalidItem}>
                  <div className={styles.invalidTopline}>
                    <CircleAlert size={15} aria-hidden="true" />
                    <strong>{item.report_id}</strong>
                    <span>不可读取</span>
                  </div>
                  <p>{item.error.message}</p>
                  <code>{item.error.code}</code>
                </article>
              ) : (
                <button
                  key={item.report_id}
                  className={styles.archiveItem}
                  type="button"
                  aria-current={reportId === item.report_id ? 'page' : undefined}
                  aria-label={`打开评测报告 ${item.report_id}`}
                  onClick={() => navigate(`/evaluations/${encodeURIComponent(item.report_id)}`)}
                >
                  <span className={styles.itemTopline}>
                    <strong>{item.report_id}</strong>
                    <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
                  </span>
                  <span className={styles.itemRefs}>{item.metadata.dataset_ref} · {item.metadata.model_ref}</span>
                  <span className={styles.itemStats}>完成 {item.aggregate.completed_runs} · 失败 {item.aggregate.failed_runs}</span>
                  <span className={styles.itemFooter}>
                    <span className={item.comparability.comparable ? styles.comparable : styles.notComparable}>
                      {item.comparability.comparable ? '可比较' : '不可比较'}
                    </span>
                    <code>{item.artifact.sha256.slice(0, 19)}</code>
                  </span>
                  <ChevronRight className={styles.itemArrow} size={16} aria-hidden="true" />
                </button>
              ))}
            </div>
          ) : null}

          {archive && loading && <p className={styles.updateStatus} role="status" aria-live="polite">正在更新评测归档…</p>}
          {archive && error && <div className={styles.error} role="alert">更新失败：{error}</div>}
        </section>

        <section className={styles.detailPanel} aria-label="评测报告详情">
          {!reportId ? (
            <div className={styles.detailEmpty}>
              <Archive size={21} aria-hidden="true" />
              <strong>选择一份报告</strong>
              <span>查看指标、失败记录和报告校验值。</span>
            </div>
          ) : detailLoading ? (
            <div className={styles.state} role="status" aria-live="polite">
              <LoaderCircle className={styles.spin} size={18} aria-hidden="true" />正在读取报告…
            </div>
          ) : detailError ? (
            <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{detailError}</div>
          ) : detail ? (
            <EvaluationDetail detail={detail} />
          ) : null}
        </section>
      </div>
    </div>
  )
}
