# MVP 当前进度记录

更新时间：2026-08-25

本文件记录基于 `project-assessment-and-roadmap.md` 的最新可验证进度。它不把
fixture、静态契约或本地测试升级成真实 full profile 证据。

## 已完成的可验证切片

| 区域 | 状态 | 证据 |
| --- | --- | --- |
| Control API | TESTED | `/api/v1` local HMAC session、ETag/If-Match、版本化 SSE、Alertmanager HMAC webhook、body limit；`python -m pytest -q apps/control-api/tests` |
| Local persistence | TESTED | SQLite snapshot v2、outbox 恢复/发布确认、审批原子消费 |
| PostgreSQL | IMPLEMENTED/STATIC-TESTED | `migrations/versions/0001_domain.sql`、down migration、7 项 SQL contract tests；未连接 PostgreSQL |
| Scenario Runner | TESTED | 6 场景 × 3 轮注入/观测/幂等 cleanup、dirty gate；`python scripts/run_scenario_matrix.py` |
| Action Gateway | TESTED | fixture 默认 fail-closed、显式 `fake-k8s` profile、目标身份/失败注入 |
| Diagnostics | TESTED | 固定 Prometheus/Loki/Tempo endpoint 的只读 source、查询边界、响应大小与脱敏 |
| Observability manifests | STATIC-TESTED | Prometheus/Loki/Tempo/OTel Kustomize stack；固定镜像、非 root、资源上限 |
| Security | TESTED | 10 个固定攻击样本，危险拦截率 100%，合法 R1 接受率 100% |
| Evidence | TESTED | manifest/checksums/敏感扫描/verification report |

## 仍未达到 full MVP DoD

- 本机没有 Docker、kubectl、kind、k3d、psql；真实 PostgreSQL migration、Kubernetes
  注入/清理、OTel 查询和第二环境 cold run 未验证。
- Temporal 仍是单场景 thin slice；多场景 full replay、Workflow/DB 对账和跨服务
  PostgreSQL projector/dispatcher 未完成。
- 当前真实遥测 source 已有受限 HTTP 代码路径，但没有真实 Prometheus/Loki/Tempo
  服务运行证据；默认 light 仍使用 fixture。
- 当前身份仍是 local-only HMAC session，不是 OIDC/CSRF/TokenReview/mTLS。
- 固定 benchmark runner 已具备，但 C1 仍是本地 fixture，不支持生产准确率、恢复率或成本声明。

## 可重复命令

```text
python -m pytest -q
python scripts/run_scenario_matrix.py --cycles 3 --output evidence/scenario-matrix.json
python scripts/run_security_attack_set.py evidence/security-attack-set.json
python scripts/build_evidence_bundle.py --output evidence/bundle --artifact evidence/scenario-matrix.json --artifact evidence/security-attack-set.json
```
