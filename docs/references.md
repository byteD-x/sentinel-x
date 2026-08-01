# 官方资料与设计依据

## 1. 使用说明

本项目优先依据官方文档和标准。本列表用于解释设计来源，不证明本仓库已经实现对应能力。链接核对日期：2026-08-01。

## 2. OpenTelemetry 与可观测性

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)：metrics、logs、traces 和 Collector 总览。
- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)：HTTP、资源、日志和 Trace 语义约定。
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)：`traceparent`/`tracestate` 传播。
- [Prometheus Documentation](https://prometheus.io/docs/introduction/overview/)：指标、PromQL、告警规则和 Alertmanager。
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)：日志存储与查询。
- [Grafana Tempo Documentation](https://grafana.com/docs/tempo/latest/)：分布式 Trace 后端。
- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)：Dashboard 与数据源。

采用影响：统一 OTel Resource/Trace Context，Prometheus/Loki/Tempo 作为原始信号事实来源，领域库只保存引用和脱敏摘要。

## 3. Temporal

- [Temporal Documentation](https://docs.temporal.io/)：durable execution、Workflow、Activity、Signal、Query 和 Worker。
- [Temporal Workflow Definition](https://docs.temporal.io/workflows)：确定性、重放和 Workflow 约束。
- [Temporal Activities](https://docs.temporal.io/activities)：外部 I/O、retry、timeout 和 heartbeat。
- [Temporal Production Deployment / Worker Versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning)：兼容部署与运行中 Workflow。

采用影响：Workflow 不直接执行网络/数据库/模型/Kubernetes I/O；外部副作用放 Activity，并使用业务幂等和协调。

## 4. Kubernetes 与本地集群

- [Kubernetes Documentation](https://kubernetes.io/docs/home/)：资源、控制器、RBAC、NetworkPolicy、health probes。
- [Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/)：工作负载身份与 projected token。
- [TokenRequest / TokenReview API](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)：短时 audience token 和验证。
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)：官方客户端，避免应用调用 `kubectl`。
- [kind](https://kind.sigs.k8s.io/) 与 [k3d](https://k3d.io/)：本地 Kubernetes 候选；最终选择待 M0 实测。
- [Toxiproxy](https://github.com/Shopify/toxiproxy)：受控网络故障候选。
- [Chaos Mesh Documentation](https://chaos-mesh.org/docs/)：后续 Kubernetes 故障注入候选，不作为 MVP 硬依赖。

采用影响：namespace/ServiceAccount 分离、最小 RBAC、官方 Client、场景目标 allowlist，provider 选择保持 proposed。

## 5. API、Schema 与 Web

- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)：HTTP 契约与生成类型。
- [JSON Schema](https://json-schema.org/specification)：严格结构化输入输出。
- [Server-Sent Events - HTML Standard](https://html.spec.whatwg.org/multipage/server-sent-events.html)：SSE 帧与重连基础。
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)：Web Console 可访问性目标。
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)：local session 写请求保护。

## 6. AI 与安全

- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/)：Prompt Injection、敏感信息和过度代理等风险。
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)：AI 风险识别、测量与治理参考。
- [OpenAI API Documentation](https://platform.openai.com/docs/)：OpenAI-compatible provider 适配的一个参考；具体 provider/模型待评测。

采用影响：遥测视为不可信输入、结构化工具和输出、最小数据外发、确定性 policy/Gateway 作为最终控制。

## 7. SRE 与事故响应

- [Google SRE Book: Managing Incidents](https://sre.google/sre-book/managing-incidents/)：事故角色、统一指挥、实时状态与恢复优先。
- [Google SRE Workbook](https://sre.google/workbook/table-of-contents/)：SLO、监控和事故响应实践。

采用影响：先止血/恢复再复盘，清晰角色和时间线，恢复由 SLI 窗口验证而不是动作返回值。

## 8. 数据与供应链

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)：事务、锁、约束、索引、备份恢复。
- [Alembic Documentation](https://alembic.sqlalchemy.org/)：SQLAlchemy migration 候选。
- [SLSA](https://slsa.dev/)：构建来源与供应链完整性参考。
- [CycloneDX](https://cyclonedx.org/)：SBOM 格式候选。

## 9. 证据使用规则

- 外部资料只能支撑设计选择，不能替代当前仓库的实测。
- 版本敏感的 API 在实现时重新核对官方文档，并在 ADR/锁文件记录版本。
- 社区示例只借鉴边界和测试方式，不直接复制到安全关键路径。
- 链接失效或官方建议变化时更新本文件，并评估对应 ADR、契约和风险。
