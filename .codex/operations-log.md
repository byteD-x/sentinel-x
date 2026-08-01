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

### M0-03 模型结构化输出 spike ✅

- qwen2.5:7b 100% 成功率（12/12）
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
