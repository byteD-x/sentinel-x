"""
场景加载器 — 从 YAML 文件加载场景定义并解析为契约模型。

提供：
- 批量加载所有场景
- 按名称、类别查询
- 验证场景完整性
- 缓存已加载场景（避免重复解析）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from sentinel_x_contracts.scenario import (
    FaultCategory,
    FaultInjection,
    ScenarioDefinition,
)

logger = logging.getLogger(__name__)

# YAML 字段到 FaultCategory 的映射
CATEGORY_MAP: dict[str, FaultCategory] = {
    "network": FaultCategory.NETWORK,
    "application": FaultCategory.APPLICATION,
    "database": FaultCategory.DATABASE,
    "kubernetes": FaultCategory.KUBERNETES,
    "resource": FaultCategory.RESOURCE,
}


class ScenarioLoadError(Exception):
    """场景加载错误。"""


class ScenarioValidationError(Exception):
    """场景校验错误。"""


class ScenarioLoader:
    """
    场景加载器 — 从目录中加载 YAML 场景文件。

    用法：
        loader = ScenarioLoader("demo/scenarios")
        scenarios = loader.load_all()
        scenario = loader.get("payment-latency@1")
        network_scenarios = loader.get_by_category(FaultCategory.NETWORK)

    加载器内部缓存已解析的场景，调用 invalidate_cache() 可强制重新加载。
    """

    def __init__(self, scenarios_dir: str | Path):
        self._dir = Path(scenarios_dir)
        if not self._dir.is_dir():
            raise ScenarioLoadError(f"场景目录不存在: {self._dir}")
        self._cache: dict[str, ScenarioDefinition] = {}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def load_all(self, force_reload: bool = False) -> list[ScenarioDefinition]:
        """加载全部场景文件并返回已验证的场景列表。"""
        if self._cache and not force_reload:
            return list(self._cache.values())

        yaml_files = sorted(self._dir.glob("*.yaml"))
        if not yaml_files:
            raise ScenarioLoadError(f"目录 {self._dir} 中没有 .yaml 文件")

        scenarios: list[ScenarioDefinition] = []
        errors: list[str] = []

        for yf in yaml_files:
            try:
                scenario = self._parse_file(yf)
                self._validate_scenario(scenario)
                scenarios.append(scenario)
            except (ScenarioLoadError, ScenarioValidationError) as e:
                errors.append(f"{yf.name}: {e}")

        if errors:
            raise ScenarioLoadError(
                f"加载 {len(errors)} 个场景失败:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        self._cache = {s.name: s for s in scenarios}
        logger.info(f"成功加载 {len(scenarios)} 个场景")
        return scenarios

    def get(self, name: str) -> Optional[ScenarioDefinition]:
        """按名称获取场景。"""
        if not self._cache:
            self.load_all()
        return self._cache.get(name)

    def get_by_category(self, category: FaultCategory) -> list[ScenarioDefinition]:
        """按类别筛选场景。"""
        return [s for s in self.load_all() if s.category == category]

    def list_names(self) -> list[str]:
        """列出所有场景名称。"""
        return sorted(s.name for s in self.load_all())

    def count(self) -> int:
        """获取场景数量。"""
        return len(self.load_all())

    def invalidate_cache(self) -> None:
        """清除缓存，下次访问时重新加载。"""
        self._cache.clear()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _parse_file(self, filepath: Path) -> ScenarioDefinition:
        """解析单个 YAML 场景文件。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ScenarioLoadError(f"YAML 解析错误: {e}")

        if raw is None:
            raise ScenarioLoadError("文件为空")

        if not isinstance(raw, dict):
            raise ScenarioLoadError(f"期望字典，实际为 {type(raw).__name__}")

        return self._dict_to_scenario(raw)

    def _dict_to_scenario(self, raw: dict) -> ScenarioDefinition:
        """将原始字典转换为 ScenarioDefinition。"""
        # 解析故障列表
        faults: list[FaultInjection] = []
        for f_raw in raw.get("faults", []):
            faults.append(
                FaultInjection(
                    fault_type=str(f_raw.get("fault_type", "")),
                    target_service=str(f_raw.get("target_service", "")),
                    parameters=f_raw.get("parameters", {}) or {},
                    duration_seconds=int(f_raw.get("duration_seconds", 300)),
                    cleanup_command=str(f_raw.get("cleanup_command", "")),
                )
            )

        # 解析类别
        category_str = str(raw.get("category", "")).lower()
        category = CATEGORY_MAP.get(category_str, FaultCategory.APPLICATION)

        return ScenarioDefinition(
            name=str(raw.get("name", "")),
            version=int(raw.get("version", 1)),
            description=str(raw.get("description", "")),
            category=category,
            faults=faults,
            ground_truth=str(raw.get("ground_truth", "")),
            expected_root_cause_category=str(raw.get("expected_root_cause_category", "")),
            expected_evidence=raw.get("expected_evidence", []) or [],
            recovery_assertions=raw.get("recovery_assertions", []) or [],
            allowlisted_runbooks=raw.get("allowlisted_runbooks", []) or [],
        )

    @staticmethod
    def _validate_scenario(scenario: ScenarioDefinition) -> None:
        """验证场景定义完整性。"""
        if not scenario.name:
            raise ScenarioValidationError("场景名称不能为空")

        if not scenario.description:
            raise ScenarioValidationError(f"场景 {scenario.name}: 缺少描述")

        if not scenario.ground_truth:
            raise ScenarioValidationError(f"场景 {scenario.name}: 缺少 ground_truth")

        if not scenario.faults:
            raise ScenarioValidationError(f"场景 {scenario.name}: 至少需要一个故障注入")

        if not scenario.expected_root_cause_category:
            raise ScenarioValidationError(
                f"场景 {scenario.name}: 缺少 expected_root_cause_category"
            )

        if not scenario.recovery_assertions:
            raise ScenarioValidationError(
                f"场景 {scenario.name}: 至少需要一个恢复断言"
            )

        # 验证每个故障注入
        for i, fault in enumerate(scenario.faults):
            if not fault.fault_type:
                raise ScenarioValidationError(
                    f"场景 {scenario.name}: 第 {i + 1} 个故障缺少 fault_type"
                )
            if not fault.target_service:
                raise ScenarioValidationError(
                    f"场景 {scenario.name}: 第 {i + 1} 个故障缺少 target_service"
                )
            if fault.duration_seconds < 10:
                raise ScenarioValidationError(
                    f"场景 {scenario.name}: 第 {i + 1} 个故障 duration_seconds 不能小于 10"
                )

    # ------------------------------------------------------------------
    # 统计与报告
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """生成场景摘要统计。"""
        scenarios = self.load_all()
        by_category: dict[str, int] = {}
        for s in scenarios:
            cat = s.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total": len(scenarios),
            "by_category": by_category,
            "names": sorted(s.name for s in scenarios),
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式的场景清单。"""
        scenarios = self.load_all()
        lines = [
            "# 场景清单",
            "",
            f"共 **{len(scenarios)}** 个场景",
            "",
            "| 名称 | 类别 | 故障类型 | 持续时间 |",
            "|------|------|----------|----------|",
        ]
        for s in scenarios:
            fault_types = ", ".join(f.fault_type for f in s.faults)
            duration = max(f.duration_seconds for f in s.faults)
            lines.append(
                f"| {s.name} | {s.category.value} | {fault_types} | {duration}s |"
            )

        return "\n".join(lines)


def create_default_loader() -> ScenarioLoader:
    """创建指向 demo/scenarios 目录的默认加载器。"""
    # 从当前文件所在目录向上查找
    default_dir = Path(__file__).resolve().parent
    if not list(default_dir.glob("*.yaml")):
        # 如果当前目录没有 YAML，尝试相对于仓库根目录
        repo_root = Path(__file__).resolve().parents[3]
        default_dir = repo_root / "demo" / "scenarios"
    return ScenarioLoader(default_dir)
