# Sentinel-X 文档初始化操作记录

## 2026-08-01

### 上下文与规划

- 使用 sequential-thinking 明确“完整开发前资料，不写业务代码”的范围。
- 使用 shrimp-task-manager 拆分并验收四阶段：产品/演练、平台契约、部署运维、治理发布。
- 使用 scan-repo-write-agents 生成 AGENTS 初稿；初稿在当前 PowerShell 显示编码异常，完整重写为严格 UTF-8 项目规范。
- 三个子代理做只读缺口/架构/简历证据审计，主代理统一整合。

### 关键修正

- 修正 `Pod crash -> restart Deployment` 因果不成立：Pod crash 作为自动恢复；capacity overload 使用 scale；latched 5xx 使用 restart。
- 增加 `DIAGNOSING -> VERIFYING` 无动作验证分支。
- 分离 AI remediation、Kubernetes auto recovery 和 Scenario cleanup 计分。
- 明确 Worker ServiceAccount 身份与数据库绑定审批授权是两套校验。
- 明确 Action submit 超时进入协调，禁止生成新幂等键。
- 增加 dev/calibration/holdout 隔离和合法 R1 接受率，防止 prompt 背题与“拒绝一切”。

### 文件操作

- 只通过 apply_patch 创建/修改项目文件。
- 初始化完整 Markdown 体系、7 份 proposed ADR 和安全默认根配置模板。
- 未删除用户数据、未初始化 Git、未创建业务实现。

### 验证

- 第一次最终审计：42 份 Markdown，严格 UTF-8、单 H1、围栏、相对链接、尾随空格、冲突标记、旧术语、占位词和敏感模式通过。
- 写回本日志与最终报告后再次执行全量审计，结果见 `verification-report.md`。

## 2026-08-01（M0 启动）

### 环境检查

- Python 3.13.9 ✅、Node.js v22.21.1 ✅、Git 2.51.0 ✅
- Docker Desktop ❌（Git Bash 和 PowerShell 均找不到）
- kubectl ❌
- Ollama 0.17.7 ✅（但 4 个云端模型已退役）
- 拉取 qwen2.5:7b（4.7 GB）替代退役模型

### M0 工程基础

- `git init` + 首次 commit（49 文件，5858 行）
- 创建 `.env`（所有敏感变量为空）
- Python 虚拟环境 + `pyproject.toml`
- `shrimp-rules.md` AI Agent 开发守则
- `spikes/` 实验目录结构

### M0-03 模型结构化输出 spike（探索性）

- qwen2.5:7b 生成 12/12 个可解析 JSON；严格 Schema 通过率未完成正式统计
- 平均延迟 10.7s，平均 535 tokens/次
- 发现 Schema 校验缺口：模型返回 `confidence: 85` 而非 `0.85`
- 4 个 cloud 模型全部退役 — 需锁定模型版本策略

### M0-02 Temporal 持久工作流 spike ✅

- 10/10 测试通过（pytest + asyncio）
- 状态机确定性行为、Worker 重启恢复、Activity 重试全部验证
- 完整 Temporal Server 集成待 Docker 安装后补充

### 剩余 M0 任务（阻塞：Docker Desktop 缺失）

- M0-00: 安装 Docker Desktop + kubectl
- M0-01: k3d/kind 本机基准
- M0-04: 审批与服务身份 spike
- M0-05: OTel 关联与资源基准
- M0-06: 固化首批 ADR 与版本锁定

## 2026-08-02（代码增强）

### 新增模块

#### 场景加载器 (`demo/scenarios/loader.py`)
- 从 6 个 YAML 场景文件批量加载并解析为 Pydantic 模型
- 支持按名称、类别查询，场景完整性校验
- 提供 Markdown 格式场景清单输出
- 验证通过：6/6 场景正确解析

#### 诊断网关 (`packages/diagnostics/gateway.py`)
- 提供 4 类场景感知模拟查询（网络延迟、5xx、OOM、CPU饱和）
- 场景上下文替换模板变量，生成与故障一致的假数据
- 调用计数追踪、参数校验、结果脱敏
- 验证通过：正常状态和 3 种故障场景查询均正确

#### LLM 客户端 (`apps/incident-worker/llm_client.py`)
- OpenAI-compatible API 封装（支持 OpenAI、Ollama 等）
- 结构化输出（JSON Schema 约束）、自动重试（429/5xx）
- Token 消耗追踪、超时控制
- 预设 Hypothesis 和 Evidence Analysis 的 Schema 定义
- 更新 activities.py 集成真实 LLM 客户端

#### Web Console 增强
- 添加 SSE 实时更新 Hook (`useSSE`)
- 增强 IncidentDetailPage：审批界面（批准/拒绝）、审批历史、证据摘要、假设展示
- 完整 CSS 深色主题样式系统
- TypeScript 编译通过，Vite 构建成功（248KB JS + 11KB CSS）

### 修复
- 修复 `sanitize_result` 正则表达式 `\1` 引用非捕获组 bug
- 更新 pyproject.toml 添加 pytest `--import-mode=importlib` 默认配置

### 测试状态
- 核心测试：54/54 全部通过（状态机 19、API 10、Workflow 12、Gateway 13）
- Demo 服务测试：7/8 通过（1 个偶发服务间调用连接失败，属测试环境时序问题）

## 2026-08-02（审查整改）

### 代码与前端修正

- 根 `pytest` 默认门禁改为真实测试目录，当前 `python -m pytest -q --tb=short --asyncio-mode=auto` 为 67 passed。
- Demo services 加入根测试路径，修复 entry points，并移除支付基础链路随机失败。
- Action Gateway 增加审批凭证过期时间、未知字段拒绝和对应负向测试。
- Control API 输入模型拒绝未知字段，覆盖顶层与嵌套告警字段。
- Diagnostic Gateway 参数校验补齐 `maxLength`、`minimum`、`maximum`。
- Web Console 增加事故状态筛选、分页、审批二次确认、SSE 去重和移动端布局修复。

### 文档与证据修正

- README、docs/README、AGENTS、开发计划、本地部署、UX、API 契约、发布门禁和证据账本从 D0-only 更新为 D1-light prototype 状态。
- 明确当前 Gateway/Control API/Workflow 仍是 prototype 安全语义，数据库绑定审批、TokenReview、Temporal Server replay 和 full E2E 未完成。
- M0 模型 spike 降级为探索性证据，不再声明严格 Schema 稳定通过或小样本 p95/p99。
