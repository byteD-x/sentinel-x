"""Read-only access to versioned evaluation archives."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sentinel_x_contracts import EvaluationArchive
from sentinel_x_contracts.evaluation import EVALUATION_REPORT_ID_PATTERN


REPORT_ID_PATTERN = re.compile(EVALUATION_REPORT_ID_PATTERN)


@dataclass(frozen=True)
class EvaluationArchiveError(Exception):
    code: str
    detail: str
    status_code: int


def _artifact(path: Path, content: bytes) -> dict[str, str | int]:
    return {
        "sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "size_bytes": len(content),
        "media_type": "application/json",
    }


def _validate_root(root: Path) -> Path:
    if root.exists() and not root.is_dir():
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_UNAVAILABLE",
            detail="评测归档目录不可用",
            status_code=503,
        )
    return root.resolve()


def _load_archive(path: Path, max_bytes: int) -> tuple[EvaluationArchive, dict[str, str | int]]:
    if path.is_symlink():
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_INVALID",
            detail="评测归档无效",
            status_code=422,
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_UNAVAILABLE",
            detail="评测归档不可读取",
            status_code=503,
        ) from exc
    if len(content) > max_bytes:
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_TOO_LARGE",
            detail="评测归档超过读取上限",
            status_code=413,
        )
    try:
        archive = EvaluationArchive.model_validate_json(content)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_INVALID",
            detail="评测归档无效",
            status_code=422,
        ) from exc
    return archive, _artifact(path, content)


def _summary(archive: EvaluationArchive, artifact: dict[str, str | int]) -> dict:
    return {
        "report_id": archive.report_id,
        "created_at": archive.created_at.isoformat(),
        "archive_status": "valid",
        "metadata": archive.metadata.model_dump(mode="json"),
        "comparability": archive.comparability.model_dump(mode="json"),
        "aggregate": archive.aggregate.model_dump(mode="json"),
        "artifact": artifact,
    }


def list_evaluation_archives(root: Path, max_bytes: int) -> dict:
    root = _validate_root(root)
    if not root.exists():
        return {
            "available": False,
            "unavailable_reason": "尚无已归档的评测报告",
            "items": [],
        }

    items: list[dict] = []
    valid_count = 0
    try:
        paths = list(root.iterdir())
    except OSError as exc:
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_UNAVAILABLE",
            detail="评测归档目录不可用",
            status_code=503,
        ) from exc

    for path in paths:
        if path.suffix != ".json" or (not path.is_file() and not path.is_symlink()):
            continue
        try:
            archive, artifact = _load_archive(path, max_bytes)
            if archive.report_id != path.stem:
                raise EvaluationArchiveError(
                    code="EVALUATION_ARCHIVE_INVALID",
                    detail="评测归档无效",
                    status_code=422,
                )
        except EvaluationArchiveError as exc:
            items.append({
                "report_id": path.stem,
                "archive_status": "invalid",
                "error": {"code": exc.code, "message": exc.detail},
            })
        else:
            valid_count += 1
            items.append(_summary(archive, artifact))

    items.sort(key=lambda item: (item.get("created_at", ""), item["report_id"]), reverse=True)
    if valid_count == 0:
        return {
            "available": False,
            "unavailable_reason": (
                "尚无已归档的评测报告" if not items else "没有可读取的评测报告"
            ),
            "items": items,
        }
    return {"available": True, "items": items}


def get_evaluation_archive(root: Path, report_id: str, max_bytes: int) -> dict:
    if not REPORT_ID_PATTERN.fullmatch(report_id):
        raise EvaluationArchiveError(
            code="INVALID_EVALUATION_ID",
            detail="评测报告标识无效",
            status_code=422,
        )
    root = _validate_root(root)
    path = root / f"{report_id}.json"
    if path.is_symlink():
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_INVALID",
            detail="评测归档无效",
            status_code=422,
        )
    if not path.exists():
        raise EvaluationArchiveError(
            code="EVALUATION_NOT_FOUND",
            detail="评测报告不存在",
            status_code=404,
        )
    archive, artifact = _load_archive(path, max_bytes)
    if archive.report_id != report_id:
        raise EvaluationArchiveError(
            code="EVALUATION_ARCHIVE_INVALID",
            detail="评测归档无效",
            status_code=422,
        )
    return {"report": archive.model_dump(mode="json"), "artifact": artifact}
