.PHONY: help install test lint clean doctor demo-up demo-down

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

doctor: ## 检查本机依赖
	@echo "=== Sentinel-X 环境检查 ==="
	@python --version 2>/dev/null || echo "❌ Python 未安装"
	@node --version 2>/dev/null || echo "❌ Node.js 未安装"
	@git --version 2>/dev/null || echo "❌ Git 未安装"
	@docker --version 2>/dev/null || echo "⚠️ Docker 未安装（K8s 相关功能受限）"
	@echo "=== 检查完成 ==="

install: ## 安装所有依赖
	pip install -e packages/contracts -e packages/domain -e packages/diagnostics -e packages/policy
	pip install -e apps/control-api -e apps/incident-worker -e apps/action-gateway
	pip install -e demo/services
	cd apps/web-console && npm install
	cd apps/terminal-console && npm install

test: ## 运行快速质量门禁
	python -m pytest -v --tb=short --asyncio-mode=auto
	cd apps/terminal-console && npm test

test-e2e: ## 运行 E2E 测试
	python -m pytest tests/ -v --tb=short --asyncio-mode=auto

lint: ## 代码检查
	python -m ruff check packages/ apps/ demo/ --select E4,E7,E9
	cd apps/web-console && npx tsc --noEmit
	cd apps/terminal-console && npm run build

clean: ## 清理构建产物
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .local/ tmp/ artifacts/

eval: ## 运行固定评测
	python -m sentinel_x_evals.runner

demo-up: ## 启动演练环境（需要 Docker + k3d）
	@echo "启动 Sentinel-X 演练环境..."
	@echo "警告: 需要 Docker Desktop + k3d/kind"
	k3d cluster create sentinel-x-local --config infra/cluster/k3d-config.yaml

demo-down: ## 清理演练环境
	k3d cluster delete sentinel-x-local
