# Sentinel-X D0 文档基线验证报告（历史）

- 验证日期：2026-08-01
- 范围：完整开发前文档、ADR 与根工程准备模板
- D0 结论：静态资料就绪
- 运行时结论（历史）：D0 当时未覆盖业务代码或运行命令。

> 现状备注：仓库已进入 D1-light 原型建设阶段。当前代码、测试和构建证据以 `docs/evidence-ledger.md`、`README.md` 和最新本地命令输出为准；本文件仅保留 2026-08-01 的 D0 静态基线记录。

文件摘要：47 个预期文件全部存在且非空，包括 40 份公开 Markdown、3 份 `.codex` 审计 Markdown 和 4 个根配置模板；Markdown 总计约 283 KB。`.env.example` 含 40 个无重复配置键，敏感值均为空。

## 静态检查

| 检查 | 结果 |
| --- | --- |
| 所有 Markdown 严格 UTF-8 解码 | 通过 |
| Unicode replacement character | 0 |
| 每文件 H1 数量 | 全部为 1 |
| fenced code block | 全部成对 |
| 相对 Markdown 文件链接 | 全部可解析 |
| 尾随空格与冲突标记 | 0 |
| 旧场景/旧认证/旧状态词 | 0 |
| TODO/TBD/待补充/待完善占位 | 0 |
| 非空敏感 `.env.example` 值 | 0；40 个变量 key 无重复 |
| 常见 token/Bearer/带凭据连接串模式 | 0 |
| D0 技术/指标表述 | 保持 proposed/目标/待测，无虚构实现 |

## 一致性检查

- 状态、R0–R3、六场景、两个 R1 Runbook 和 recovery actor 语义一致。
- Pod 自动恢复、capacity scale、latched 5xx restart 因果分离。
- Scenario cleanup 不进入 AI remediation 成功率。
- Worker 服务身份和 Gateway 审批授权分离。
- API/数据/Workflow/LLM/观测/UX/安全/测试均有唯一详细事实来源并互相链接。
- FR/NFR 映射到组件、契约、测试集、报告字段和演示步骤。

## 限制

- 目录未初始化 Git，无法运行 `git diff --check` 或绑定 commit；进入代码阶段前必须补齐。
- 未选择许可证、代码托管平台和私有安全报告渠道，需要用户/维护者决定。
- 未安装 Markdown 专用 linter；使用严格编码、结构、链接、术语、占位和秘密扫描补偿。
- 未执行任何 runtime/build/unit/integration/E2E/security/performance/evaluation；文档不能作为这些结果的替代。
