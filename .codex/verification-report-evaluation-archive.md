# 评测归档切片验证记录

日期：2026-08-09

## 范围

- `EvalRunner` 生成脱敏、版本化的 `schema_version: "1.0"` 归档。
- Control API 以只读方式提供 `/api/evaluations` 和 `/api/evaluations/{report_id}`。
- Web Console 展示真实归档列表和报告详情，不生成未提供的指标或 baseline 提升。

## 安全边界

- 浏览器响应不含 `raw_report`、ground truth、执行异常原文、原始遥测或物理路径。
- 报告 ID、UTC 时间、严格 schema、聚合总数、符号链接、文件大小和不可读目录均有测试覆盖。
- API 只读取 `SENTINEL_EVAL_ARCHIVE_DIR`，不提供重跑、下载、删除或客户端路径参数。

## 可重复验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q apps/control-api/tests/test_api.py evals/tests/test_runner.py --tb=short --asyncio-mode=auto` | `44 passed` |
| `python -m pytest -q --tb=short --asyncio-mode=auto` | `116 passed` |
| `npm test`（`apps/web-console`） | `20 passed` |
| `npm run lint && npm run build && npm run test:ui-contract`（`apps/web-console`） | 全部通过 |
| 独立 `8010` Control API + runner 归档 HTTP 校验 | 列表、详情、SHA-256 和脱敏断言通过 |
| Playwright 1440x900、390x844 | 3 张截图；无横向溢出、无控制台错误 |

## 协作记录

- `frontend_product_audit`：实现评测页面、详情路由、类型契约和 10 个前端用例；主代理复核并完成全量前端/浏览器验证。
- `eval_api_design`：审计归档契约与安全读取边界；主代理采用其脱敏、固定目录、严格 schema 和 hash 建议。
- `golden_path_audit`：完成下一切片的只读审计，未改动本切片文件。

## 限制

本记录证明本地 light runner 与只读归档链路，不证明 holdout benchmark、Temporal replay、PostgreSQL 持久化、Kubernetes 演练或对外指标。
