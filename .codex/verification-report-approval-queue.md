# light 原型整改验证记录

- 日期：2026-08-02
- 范围：Action Gateway fail-closed、Alert Ingress HMAC、Control API 状态/审批/去重、Web Console 角色/审批/演练/SSE、质量门禁
- profile：local-demo / light

## 已验证

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q --tb=short --asyncio-mode=auto` | 通过，83 项 |
| `npm run lint`（`apps/web-console`） | 通过 |
| `npm run build`（`apps/web-console`） | 通过，TypeScript 与 Vite 构建成功 |
| `python -m pytest apps/action-gateway/tests -q --tb=short` | 通过，20 项 |
| `python -m pytest apps/control-api/tests -q --tb=short` | 通过，20 项 |
| `python -m pytest apps/incident-worker/tests -q --tb=short` | 通过，14 项 |
| `git diff --check` | 通过 |
| Playwright approver 桌面/移动回归 | 通过；审批确认弹窗可打开，浏览器错误 0，390px 视口横向溢出为 false |
| Playwright viewer 回归 | 通过；演练按钮禁用、系统页和 404 可达、390px 无横向溢出 |

Playwright 运行期间生成并检查了审批队列、事故详情、审批确认弹窗和移动审批队列截图；截图是一次性 QA 产物，不作为产品资源提交。approver 检查启动 Vite 前需设置 `VITE_SENTINEL_ROLE=approver`；可复现脚本保留在 `.codex/visual_qa_approvals.py`。

## 环境说明

演练服务测试现使用动态端口、readiness 与可靠 teardown，不再依赖 `8082–8084` 空闲。仓库当前只配置前端 ESLint；Python lint/format/type-check 仍未作为门禁接入。

## 边界

本次实现的是 light/prototype 安全与控制台整改。正式契约所要求的浏览器认证/CSRF/ETag、数据库持久化审批、TokenReview、PostgreSQL/Temporal replay、真实 Kubernetes 执行和完整 SSE 保留窗口仍未实现，不能据此宣称 full profile 或生产可用。
