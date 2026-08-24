# 配置字典与秘密边界

## 1. 目标

本文是配置名称、来源、默认、安全性、校验和 profile 差异的唯一人工可读来源。`.env.example` 只提供无秘密模板，不重复解释语义。

终端控制台已类型化解析 `SENTINEL_API_URL` 和 `SENTINEL_ROLE`；其余尚未接入代码的名称仍为 `proposed`，后续由 Pydantic Settings/等价类型化配置和测试成为执行事实。

## 2. 配置优先级

从高到低：

1. 安全策略硬上限和编译/部署不变量，不能被环境变量降低。
2. Kubernetes Secret/ConfigMap 或本地 ignored env 文件。
3. profile 配置文件：`light`、`full`、`ci`。
4. 应用安全默认值。

命令行只允许开发任务选择 profile、日志级别等非敏感项，不提供 `--disable-approval`、`--allow-shell` 等安全绕过。

启动时完整校验配置，错误列出变量名和原因但不回显秘密值。配置来源和非敏感 hash 进入运行 metadata。

## 3. Profile 能力矩阵

| 能力 | `light` | `full` | `ci` |
| --- | --- | --- | --- |
| 控制 API/领域逻辑 | 本地进程/容器 | Kubernetes | 临时容器 |
| Temporal | 开发实例或测试环境 | 集群内服务 | Temporal test server |
| PostgreSQL | 本地容器 | 集群内 StatefulSet/容器 | 临时数据库 |
| Prometheus/Loki/Tempo | fixture 或裁剪组件 | 完整拟议栈 | fixture/目标集成组件 |
| Demo Shop | 可选 fixture | 三服务 + Redis/PostgreSQL | 按测试选择 |
| Scenario 注入 | 禁止真实注入 | 固定场景 | 模拟/隔离集成 |
| Action Gateway 写动作 | 默认关闭 | 显式开启 + kill switch | fake K8s/API server |
| 正式 benchmark | 不允许 | 允许 | 只做回归，不宣传效果 |

任何报告必须记录 profile；`light` 不能标为完整 E2E。

## 4. 核心运行配置

| 变量 | 默认/必填 | 敏感 | 校验与所有者 |
| --- | --- | --- | --- |
| `SENTINEL_PROFILE` | `light` | 否 | enum；启动任务 |
| `SENTINEL_ENVIRONMENT` | `local-demo` | 否 | 固定 allowlist；所有组件 |
| `SENTINEL_LOG_LEVEL` | `INFO` | 否 | enum；不得通过 DEBUG 打印秘密 |
| `SENTINEL_ACTIONS_ENABLED` | `false` | 否 | `full` 才可 true；policy 最终决定 |
| `SENTINEL_KILL_SWITCH` | `true` | 否 | 安全默认开启；权威状态最终存数据库/控制面 |
| `SENTINEL_DATA_DIR` | `.local/data` | 否 | 必须解析在项目本地数据根内 |
| `SENTINEL_APPROVAL_STORE_DB` | 未设置（内存） | 否 | Action Gateway local/full 可指向 SQLite；未设置时仅为 light 进程内存储 |
| `SENTINEL_ARTIFACTS_DIR` | `.local/artifacts` | 否 | 导出前脱敏；禁止根目录/用户目录 |

环境变量中的 kill switch 只是启动默认值；运行时权威状态、操作者和原因必须持久化，不依赖修改 Pod env 即时生效。

## 5. API 与会话

| 变量 | 默认/必填 | 敏感 | 规则 |
| --- | --- | --- | --- |
| `CONTROL_API_HOST` | `127.0.0.1` | 否 | 本地默认不监听所有网卡 |
| `CONTROL_API_PORT` | `8000` | 否 | 1–65535，启动时端口冲突检查 |
| `WEB_CONSOLE_PORT` | `5173` | 否 | 开发端口，发布构建由 API/静态服务托管策略决定 |
| `SENTINEL_API_URL` | `http://127.0.0.1:8000` | 否 | 终端控制台基址；仅允许无路径、query 和 fragment 的 HTTP(S) URL |
| `SENTINEL_ROLE` | `viewer` | 否 | 终端 local-demo 角色；enum，不能视为生产身份认证 |
| `SENTINEL_EVAL_ARCHIVE_DIR` | `evals/results` | 否 | Control API 仅从该服务端固定目录读取脱敏评测归档；不接受客户端指定路径 |
| `SENTINEL_EVAL_ARCHIVE_MAX_BYTES` | `2097152` | 否 | 单份评测归档的读取上限（字节）；超限报告不返回内容 |
| `LOCAL_SESSION_SIGNING_KEY` | full 必填 | 是 | 最少 32 随机字节；不写日志/报告 |
| `ALERT_INGRESS_HMAC_KEY` | full 必填 | 是 | 与 session key 独立；支持轮换双 key 窗口 |
| `ALERT_INGRESS_REPLAY_TTL_SECONDS` | `300` | 否 | 30–3600；nonce 重放缓存保留时间 |
| `ALERT_INGRESS_REPLAY_MAX_ENTRIES` | `10000` | 否 | 100–100000；local profile 的有界重放缓存容量 |
| `LOCAL_SESSION_TTL_MINUTES` | 目标 60 | 否 | 5–480；实现后加入模板 |
| `ALERT_MAX_CLOCK_SKEW_SECONDS` | 目标 300 | 否 | 30–600；实现后加入模板 |

local-only 身份不能由客户端 header 提供。未来 OIDC 增加新的配置组，不复用 session signing key。

## 6. 数据库与 Temporal

| 变量 | 默认/必填 | 敏感 | 规则 |
| --- | --- | --- | --- |
| `DATABASE_URL` | 必填 | 是 | PostgreSQL；不在错误中回显 user/password |
| `DATABASE_POOL_SIZE` | 目标 10 | 否 | 1–50；按 profile 约束 |
| `DATABASE_POOL_TIMEOUT_SECONDS` | 目标 10 | 否 | 1–60 |
| `TEMPORAL_ADDRESS` | `127.0.0.1:7233` | 否/视 TLS | host:port |
| `TEMPORAL_NAMESPACE` | `sentinel-local` | 否 | 非空固定命名 |
| `TEMPORAL_TASK_QUEUE` | `sentinel-incidents` | 否 | Worker/API 一致 |
| `TEMPORAL_TLS_CA/CERT/KEY` | 本地空 | 是 | 启用 TLS 时成组提供；不进 `.env.example` 内容值 |

Control API/Worker 使用领域 DB 角色；Action Gateway 使用更小的 approval/action 专用角色，连接凭据必须分开。

## 7. 可观测性

| 变量 | 默认 | 敏感 | 规则 |
| --- | --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://127.0.0.1:4317` | 否/视认证 | allowlist scheme/host |
| `PROMETHEUS_BASE_URL` | `http://127.0.0.1:9090` | 否 | Diagnostic Gateway 固定来源 |
| `LOKI_BASE_URL` | `http://127.0.0.1:3100` | 否 | 不接受模型覆盖 |
| `TEMPO_BASE_URL` | `http://127.0.0.1:3200` | 否 | 不接受模型覆盖 |
| `GRAFANA_BASE_URL` | `http://127.0.0.1:3000` | 可能 | 仅 UI allowlist 链接 |
| `SLO_POLICY_VERSION` | `slo@dev` | 否 | 报告必填；正式 run 禁止 `@dev` |

如果数据源需要 token，使用独立 Secret 变量并在客户端封装；不把 token 拼接到 URL。

## 8. LLM 与调查预算

| 变量 | 默认/必填 | 敏感 | 规则 |
| --- | --- | --- | --- |
| `LLM_BASE_URL` | Investigator 启用时必填 | 视部署 | endpoint allowlist，禁止任意请求覆盖 |
| `LLM_API_KEY` | provider 需要时必填 | 是 | 仅 Investigator Activity 可见 |
| `LLM_MODEL` | 启用时必填 | 否 | 使用固定 alias/版本 |
| `LLM_TIMEOUT_SECONDS` | 60 | 否 | 5–120，不超过 Activity timeout |
| `LLM_MAX_INPUT_TOKENS` | 60000 | 否 | policy 可降低，不能超过硬上限 |
| `LLM_MAX_OUTPUT_TOKENS` | 8000 | 否 | 256–硬上限 |
| `PROMPT_BUNDLE_VERSION` | `prompt@dev` | 否 | 正式 run 固定 hash |
| `INVESTIGATION_MAX_SECONDS` | 480 | 否 | 60–900 |
| `INVESTIGATION_MAX_LLM_CALLS` | 8 | 否 | 1–12 |
| `INVESTIGATION_MAX_TOOL_CALLS` | 20 | 否 | 1–30 |
| `INVESTIGATION_MAX_QUERY_MINUTES` | 30 | 否 | 1–30 |

模型看不到 key、base URL、硬预算和 ground-truth 配置。

## 9. Action Gateway 与 Kubernetes

| 变量 | 默认/必填 | 敏感 | 规则 |
| --- | --- | --- | --- |
| `POLICY_VERSION` | `policy@dev` | 否 | 正式 run 固定版本/hash |
| `ACTION_GATEWAY_URL` | 集群内部 URL | 否 | Worker 固定 allowlist |
| `ACTION_GATEWAY_AUDIENCE` | `sentinel-action-gateway` | 否 | projected SA token audience |
| `K8S_TARGET_NAMESPACE` | `demo-shop` | 否 | 不能与 system/observability 相同 |
| `K8S_SYSTEM_NAMESPACE` | `sentinel-system` | 否 | 故障/动作禁止目标 |
| `K8S_OBSERVABILITY_NAMESPACE` | `observability` | 否 | 故障/动作禁止目标 |
| `K8S_SCENARIO_NAMESPACE` | `sentinel-chaos` | 否 | Scenario Runner 身份边界 |

不提供 kubeconfig path、Shell、任意 namespace 或 `ALLOW_R3` 类配置。Runbook 副本上限和动作 allowlist 来自版本化 policy，不从普通 env 临时扩大。

## 10. 秘密生成、存储和轮换

- 本地 bootstrap 未来生成到 ignored `.env.local` 或 Kubernetes Secret，不写入 shell history。
- 每个用途使用独立随机秘密，不复用 session/HMAC/DB/model key。
- 应用日志只记录变量名、是否已设置和非敏感配置 hash。
- HMAC/session key 轮换允许短双 key 验证窗口；旧 key 到期后删除。
- LLM/DB token 暴露时先禁用/轮换，再清理历史和评估影响。
- 示例、fixture 和 CI 使用合成值；secret scanner 允许 `.env.example` 空值。

## 11. 动态配置

运行时仅允许动态改变：kill switch、调查软预算（不超过硬上限）、非安全展示设置。Runbook、policy、prompt、SLO、工具模板和 RBAC 变化必须版本化发布，不热改。

动态改变产生 Timeline/Audit，包含 actor、old/new 安全摘要、原因和时间。加载失败保留上一有效版本并告警，不使用部分配置。

## 12. 配置验收

- `.env.example` 所有变量在配置模型中存在，敏感值为空。
- 缺失必填、非法 enum/URL/范围、namespace 重叠、full actions + kill switch 配置矛盾均启动失败。
- 安全硬上限不能被 env/CLI 提高，R2/R3 无开关。
- 日志、错误、health、导出和评测 metadata 不包含秘密值。
- light/full/ci 的 capability 与报告标识一致，light 不能运行正式 benchmark。
- 配置 hash 在相同规范配置下稳定，秘密变化不泄露到 hash 输入/输出。
