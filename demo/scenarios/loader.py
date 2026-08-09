"""从 YAML 加载并严格校验演练场景。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from sentinel_x_contracts.scenario import FaultCategory, ScenarioDefinition

logger = logging.getLogger(__name__)


class ScenarioLoadError(Exception):
    """场景目录或文件无法加载。"""


class ScenarioValidationError(Exception):
    """YAML 内容不符合场景契约。"""


class ScenarioLoader:
    """从一个目录加载作为唯一解析事实源的 YAML 场景定义。

    loader 只负责读取、解析和校验；包括 ``cleanup_command`` 在内的所有
    场景字段都是数据，绝不由此模块执行。
    """

    def __init__(self, scenarios_dir: str | Path):
        self._dir = Path(scenarios_dir)
        if not self._dir.is_dir():
            raise ScenarioLoadError(f"场景目录不存在: {self._dir}")
        self._cache: dict[str, ScenarioDefinition] = {}

    def load_all(self, force_reload: bool = False) -> list[ScenarioDefinition]:
        """加载目录中的全部 YAML，并返回通过严格契约校验的场景。"""
        if self._cache and not force_reload:
            return list(self._cache.values())

        yaml_files = sorted(self._dir.glob("*.yaml"))
        if not yaml_files:
            raise ScenarioLoadError(f"目录 {self._dir} 中没有 .yaml 文件")

        scenarios: list[ScenarioDefinition] = []
        scenario_ids: set[str] = set()
        errors: list[str] = []
        for filepath in yaml_files:
            try:
                scenario = self._parse_file(filepath)
                if scenario.id in scenario_ids:
                    raise ScenarioValidationError(f"重复的场景 ID: {scenario.id}")
                scenario_ids.add(scenario.id)
                scenarios.append(scenario)
            except (ScenarioLoadError, ScenarioValidationError) as error:
                errors.append(f"{filepath.name}: {error}")

        if errors:
            details = "\n".join(f"  - {error}" for error in errors)
            raise ScenarioLoadError(f"加载 {len(errors)} 个场景失败\n{details}")

        self._cache = {scenario.id: scenario for scenario in scenarios}
        logger.info("成功加载 %d 个场景", len(scenarios))
        return scenarios

    def get(self, scenario_id: str) -> Optional[ScenarioDefinition]:
        """按稳定 ``name@version`` 场景 ID 获取定义。"""
        if not self._cache:
            self.load_all()
        return self._cache.get(scenario_id)

    def get_by_category(self, category: FaultCategory) -> list[ScenarioDefinition]:
        """按故障分类筛选场景。"""
        return [scenario for scenario in self.load_all() if scenario.category == category]

    def list_names(self) -> list[str]:
        """返回稳定场景 ID 列表。"""
        return sorted(scenario.id for scenario in self.load_all())

    def count(self) -> int:
        """返回通过校验的场景数量。"""
        return len(self.load_all())

    def invalidate_cache(self) -> None:
        """清除缓存，供下次读取重新解析 YAML。"""
        self._cache.clear()

    def _parse_file(self, filepath: Path) -> ScenarioDefinition:
        try:
            with filepath.open("r", encoding="utf-8") as file:
                raw = yaml.safe_load(file)
        except (OSError, yaml.YAMLError) as error:
            raise ScenarioLoadError(f"YAML 读取失败: {error}") from error

        if raw is None:
            raise ScenarioLoadError("文件为空")
        if not isinstance(raw, dict):
            raise ScenarioLoadError(f"期望 YAML 对象，实际为 {type(raw).__name__}")

        try:
            return ScenarioDefinition.model_validate(raw)
        except ValidationError as error:
            raise ScenarioValidationError(str(error)) from error

    def summary(self) -> dict[str, object]:
        """生成场景目录的基础统计。"""
        scenarios = self.load_all()
        by_category: dict[str, int] = {}
        for scenario in scenarios:
            category = scenario.category.value
            by_category[category] = by_category.get(category, 0) + 1
        return {
            "total": len(scenarios),
            "by_category": by_category,
            "names": sorted(scenario.id for scenario in scenarios),
        }

    def to_markdown(self) -> str:
        """生成场景清单的 Markdown 摘要。"""
        scenarios = self.load_all()
        lines = [
            "# 场景清单",
            "",
            f"共 **{len(scenarios)}** 个场景",
            "",
            "| ID | 分类 | 故障类型 | 持续时间 |",
            "|---|---|---|---|",
        ]
        for scenario in scenarios:
            fault_types = ", ".join(fault.fault_type for fault in scenario.faults)
            duration = max(fault.duration_seconds for fault in scenario.faults)
            lines.append(
                f"| {scenario.id} | {scenario.category.value} | {fault_types} | {duration}s |"
            )
        return "\n".join(lines)


def create_default_loader() -> ScenarioLoader:
    """创建指向仓库 ``demo/scenarios`` 的默认加载器。"""
    return ScenarioLoader(Path(__file__).resolve().parent)
