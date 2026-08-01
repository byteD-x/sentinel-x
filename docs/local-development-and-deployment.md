# 本地开发、部署与环境生命周期

## 1. 当前状态

仓库当前没有代码、容器镜像、集群清单或可运行脚本。本文定义未来开发环境和部署接口，文中的 `make ...` 为 **目标任务名**，不是当前已实现命令。首次代码提交必须同步实际命令和验证输出。

## 2. 支持范围

主要开发环境：Windows 11 + WSL2/Docker Desktop 的 Linux 容器。Linux 原生为次要目标。macOS 可尝试但不作为 MVP 验收平台。

拟议依赖：

- Git
- Docker Desktop/兼容 Linux container runtime
- k3d 或 kind（二选一，M0 决策）
- kubectl（只供开发者管理环境，应用不调用）
- Python 与 Node.js（版本由首个锁文件固定）
- GNU Make 或统一任务运行器；Windows 提供薄 PowerShell wrapper

M0 前不写死运行时版本。选择后使用 `.python-version`/锁文件、`.nvmrc`/package manager 字段和镜像 digest 固定。

## 3. 主机资源目标

以下是初始规划，不是实测最低要求：

| Profile | CPU | 可用内存 | 可用磁盘 | 用途 |
| --- | --- | --- | --- | --- |
| `light` | 4 cores | 6 GB | 10 GB | API/Workflow/fixture 日常开发 |
| `full` | 8 cores | 12 GB | 30 GB | 完整 K8s/观测/演练/E2E |
| `ci` | 4–8 cores | 8 GB | 20 GB | 分层临时集成测试 |

`make doctor` 未来应检测 Docker、虚拟化、端口、内存、磁盘、工具版本、时钟和本地目录权限，并以非零退出码报告阻断项。

## 4. 网络与端口规划

| 服务 | 本地主机端口 | 暴露范围 |
| --- | --- | --- |
| Web Console | 5173（开发） | 127.0.0.1 |
| Control API | 8000 | 127.0.0.1 |
| Temporal frontend/UI | 7233 / 8233 | 127.0.0.1，开发者 |
| PostgreSQL | 5432 或动态 | 127.0.0.1，应用/开发者 |
| OTLP gRPC/HTTP | 4317 / 4318 | 集群内；可选 localhost |
| Prometheus | 9090 | 127.0.0.1，开发者 |
| Grafana | 3000 | 127.0.0.1 |
| Loki / Tempo | 3100 / 3200 | 默认不公开，仅 port-forward 调试 |

启动任务在端口冲突时停止并报告占用，不自动终止未知进程。CI 使用动态端口并从生成 metadata 读取。

## 5. Namespace 与故障域

```text
sentinel-system    Control API / Worker / Action Gateway
observability      OTel / Prometheus / Alertmanager / Loki / Tempo / Grafana
demo-shop          order / inventory / payment / PostgreSQL / Redis
sentinel-chaos     Scenario Runner / Toxiproxy / fault fixtures
```

- Scenario Runner 只写 `demo-shop` 中登记目标和自身代理规则。
- Action Gateway 只写 `demo-shop` allowlist Deployment 的有限字段。
- 两者使用不同 ServiceAccount，不能取得彼此凭据。
- Diagnostic Gateway 对 `demo-shop` 指定资源只读，不读 Secrets。
- 默认拒绝跨 namespace 网络；逐连接开放 API、Temporal、DB、OTel 和只读观测端点。

## 6. Profile 详细语义

### `light`

- Control API、Worker、PostgreSQL、Temporal 开发环境。
- 遥测通过固定脱敏 fixture 或裁剪组件提供。
- Kubernetes 写动作和真实故障注入强制关闭，kill switch 开启。
- 适合状态机、API、UI、prompt Schema、replay 和单元/契约测试。
- 结果标记 `profile=light`，不能声称完整 OTel/K8s E2E。

### `full`

- 单个本地 Kubernetes 集群和四 namespace。
- 完整 demo-shop、稳定负载、观测栈、Temporal 和 Action Gateway。
- 启动作业默认 kill switch 开启；通过安全预检后由授权操作者显式开启 R1。
- 只有该 profile 可运行正式场景和 benchmark。

### `ci`

- 按测试层创建最小依赖；不为单元测试启动完整栈。
- 使用临时数据库/Temporal test server/fake K8s 或选择性真实集群。
- 每个 job 生成唯一 environment/run IDs 并确保 finally cleanup。

## 7. 目标任务接口

| 任务 | 未来职责 | 成功证据 |
| --- | --- | --- |
| `make doctor` | 只读检查主机与依赖 | 机器可读 summary + 退出码 |
| `make bootstrap` | 安装项目依赖、生成本地非提交配置 | 锁文件一致、秘密文件被忽略 |
| `make cluster-create` | 创建固定本地集群 | 集群 metadata、namespace/RBAC 存在 |
| `make demo-up` | 按顺序部署 full 栈 | 逐组件 readiness + 基线 SLI |
| `make demo-down` | 停止服务并保留可复查数据 | 没有活动 run/action，卷策略明确 |
| `make demo-reset` | 清理场景残留并回到基线 | dirty gate 通过、版本/副本/规则一致 |
| `make demo-purge` | 删除项目专属集群和本地生成数据 | 精确目标确认；不触及其他 Docker/K8s 资源 |
| `make test` | 快速 lint/type/unit/contract | 汇总报告 |
| `make test-e2e` | 隔离完整闭环 | 事故包与测试结果 |
| `make eval` | 固定数据集评测 | JSON/Markdown 报告与 hash |

删除/清理任务必须先解析并显示项目专属绝对目标，拒绝空变量、用户主目录、磁盘根、未知集群和无 Sentinel 标签资源。

## 8. 首次启动顺序

1. `doctor` 验证主机，不修改状态。
2. `bootstrap` 创建 `.venv`/node 依赖和 ignored `.env.local`；敏感值随机生成或由开发者注入。
3. 创建集群并记录 provider/version/config hash。
4. 创建 namespace、ResourceQuota、ServiceAccount、RBAC 和 NetworkPolicy。
5. 启动 PostgreSQL/Temporal，运行数据库 migration 和 Workflow 注册检查。
6. 启动观测栈，验证 OTLP、查询和时钟。
7. 部署 demo-shop 和负载，等待 baseline window。
8. 部署 Control API/Worker/Diagnostic Gateway；Action Gateway 保持 kill switch。
9. 运行跨信号 smoke、场景注入/cleanup 自检和权限负向检查。
10. 明确操作后才启用 R1 演示。

任一步失败都停止后续步骤；不要用重启所有组件掩盖具体失败。

## 9. 配置与秘密

- `.env.example` 可提交，所有敏感值为空。
- `.env.local`、证书和本地密钥必须被 `.gitignore` 覆盖。
- 集群 Secret 由 bootstrap 从安全本地来源创建，不通过命令参数或日志输出值。
- Worker ServiceAccount token 使用 projected volume 和短 TTL，不保存在 env 文件。
- Action Gateway 的 DB role、Worker 的 DB role、模型 key、Alert HMAC 和 session key彼此独立。
- 正式评测 metadata 只记录非敏感配置 hash/版本和“secret configured”布尔值。

详细变量见 [配置字典](configuration-reference.md)。

## 10. 构建与镜像

- Python/Node 依赖使用锁文件和可重复安装。
- 多阶段容器构建；运行镜像使用非 root、只读根文件系统和最小 capabilities。
- 应用镜像不包含 kubectl、Shell 调试工具、源码秘密或开发依赖；若基础镜像必须有 shell，也不向模型暴露且通过安全评审。
- 镜像使用不可变 tag + digest；Scenario good/bad 版本必须固定 digest。
- 构建产出 SBOM 和漏洞扫描报告；未设定实际门禁前不声称通过。
- 本地源代码 mount 仅限开发 profile，full benchmark 使用固定镜像。

## 11. 健康与启动门禁

### 基础设施

- PostgreSQL 可连接且 migration version 正确。
- Temporal namespace/task queue 可见，Worker build ID 兼容。
- Prometheus/Loki/Tempo 能写入并查询带测试 correlation 的信号。
- 时钟偏移在场景允许范围内。

### 应用

- liveness 只看进程；readiness 按组件职责检查依赖。
- demo-shop 基线窗口满足目标，trace 贯穿三服务。
- Control API 能写/读一次无副作用 health fixture。
- Action Gateway 在 kill switch 下正确拒绝 R1，并无法执行 R2/R3。
- Scenario Runner 注入/cleanup 自检后环境 CLEAN。

只有全部阻断项通过，演练中心才显示场景可启动。

## 12. 数据卷与产物

本地生成目录全部在项目 `.local/` 下：

```text
.local/
├─ data/          # 本地持久卷/备份索引，不提交
├─ artifacts/     # 原始测试与评测产物，不提交
├─ support/       # 脱敏支持包，不提交
└─ metadata/      # 集群、端口、版本和配置 hash
```

选定的脱敏报告若需要版本化，复制到未来明确的 evidence 目录并经过审查；不要直接解除整个 artifacts 忽略规则。

## 13. 日常开发循环

1. 选择最小 profile 和测试层。
2. 只启动受影响依赖。
3. 修改契约时先更新 Schema/test fixture，再实现消费者。
4. 运行最近测试，然后受影响的 Workflow/security/E2E。
5. 检查日志脱敏、资源和 outbox/Workflow 无残留。
6. 更新事实来源文档和验证记录。

不要把 full 栈作为所有开发任务的默认前提，也不要用 light fixture 代替最终 E2E。

## 14. 停止、重置与删除

- **down**：停止项目服务，保留卷/报告以便排查；先确认没有 RUNNING/RECONCILING action。
- **reset**：运行精确 Scenario cleanup、恢复 demo 镜像/副本/代理规则、清空可安全重建的演练数据；保留审计和报告。
- **purge**：删除只属于当前 Sentinel metadata 的集群/卷/本地 `.local`，需要明确确认；不可枚举并删除其他项目资源。

动作最终状态未知、数据库/Temporal 不一致或环境 DIRTY 时禁止直接 purge，先导出脱敏支持包并完成对账。

## 15. Windows 与 Docker Desktop 注意

- 源码放在性能合适的文件系统；M0 比较 Windows bind mount 与 WSL2 文件系统 I/O。
- Docker Desktop 内存/CPU 配额不足时 `doctor` 明确报告，不自动改系统设置。
- k3d/kind 网络、host.docker.internal 和端口转发差异通过 spike 决定，不在代码里散落特判。
- PowerShell wrapper 使用 `-LiteralPath` 和已验证的项目绝对路径；删除不跨 shell 拼接。
- CRLF 仅用于 `.cmd/.bat/.ps1`，容器脚本和代码保持 LF。

## 16. 环境验收

- 干净主机按锁定版本和文档完成 light/full 启停。
- `doctor/up/down/reset/purge` 幂等性和失败退出码可测试。
- full 连续创建/销毁目标至少 3 次并记录资源峰值；这是环境稳定性门槛，不是生产可靠性结论。
- namespace/RBAC/NetworkPolicy 负向测试证明 Scenario、Diagnostic、Action 身份无法越界。
- full 基线、六场景注入/cleanup、跨信号关联和报告产物可复现。
- Windows 路径、端口冲突、Docker 不可用、内存不足和清理失败都有明确诊断。
