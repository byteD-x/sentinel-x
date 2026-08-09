# 黄金链路契约切片验证记录

日期：2026-08-09

## 范围

- YAML 成为 Control API 与 loader 的唯一运行时场景来源，目录严格收敛为六个版本化场景。
- `ScenarioDefinition`、`FaultInjection`、根因分类与 `ExerciseRun` 使用严格、稳定的 contracts。
- Control API、Domain、Policy、Worker 与 Action Gateway 复用 Incident/Risk/Severity 枚举。
- `no_op` 直接验证；无允许动作和 R2/R3 分别升级人工；R1 保持审批门控。

## 可重复验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest demo/scenarios/tests/test_loader.py -q --tb=short` | `16 passed` |
| `python -m pytest apps/control-api/tests/test_api.py demo/scenarios/tests/test_loader.py -q --tb=short --asyncio-mode=auto` | `61 passed` |
| `python -m pytest packages/domain/tests apps/incident-worker/tests apps/action-gateway/tests -q --tb=short --asyncio-mode=auto` | `61 passed` |
| `python -m compileall -q apps/control-api/src packages/contracts/src packages/policy/src demo/scenarios` | 通过 |
| `git diff --check` | 通过 |

## 安全与限制

- 场景公共投影不含 ground truth、预期证据、清理命令或物理路径。
- cleanup 是 Scenario Runner 的独立职责，不能被计入 AI remediation；R2 与 R3 不会通过 YAML 许可绕过 policy。
- 本机没有 Docker、kind/k3d、Temporal 或 PostgreSQL 运行环境。本记录不证明真实注入、cleanup、Kubernetes R1 动作、Temporal replay、PostgreSQL 持久化或 SLO 因果恢复。
