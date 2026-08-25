"""脱敏证据包生成与校验。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


SENSITIVE_PATTERNS = (
    re.compile(r"(?:Authorization\s*:\s*|[\"']?authorization[\"']?\s*:\s*[\"']?)Bearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*['\"]?[^\s,}\"']+", re.IGNORECASE),
    re.compile(r"(?:sk-|ghp_|xox[baprs]-)[A-Za-z0-9_-]{20,}"),
)


class EvidenceBundleError(ValueError):
    """证据包无法安全生成或校验。"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_sensitive_text(text: str) -> list[str]:
    return [pattern.pattern for pattern in SENSITIVE_PATTERNS if pattern.search(text)]


def verify_checksums(bundle_dir: Path) -> dict[str, object]:
    checksum_path = bundle_dir / "checksums.txt"
    if not checksum_path.is_file():
        raise EvidenceBundleError("checksums.txt 不存在")
    checked = 0
    mismatches: list[str] = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, name = line.split("  ", 1)
        path = bundle_dir / name
        if not path.is_file() or _sha256(path) != expected:
            mismatches.append(name)
        checked += 1
    return {"checked": checked, "mismatches": mismatches, "valid": not mismatches}


def build_evidence_bundle(
    output_dir: Path,
    artifacts: dict[str, Path],
    *,
    commit_sha: str | None,
    profile: str,
    limitations: list[str],
) -> Path:
    if not artifacts:
        raise EvidenceBundleError("证据包至少需要一个产物")
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    sensitive: dict[str, list[str]] = {}
    for name, source in sorted(artifacts.items()):
        if Path(name).name != name or Path(name).suffix not in {".json", ".md", ".txt"}:
            raise EvidenceBundleError(f"产物文件名非法: {name}")
        if not source.is_file():
            raise EvidenceBundleError(f"产物不存在: {source}")
        destination = output_dir / name
        shutil.copyfile(source, destination)
        copied.append(name)
        matches = scan_sensitive_text(destination.read_text(encoding="utf-8"))
        if matches:
            sensitive[name] = matches
    if sensitive:
        raise EvidenceBundleError(f"证据包包含敏感信息: {sorted(sensitive)}")

    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "profile": profile,
        "artifacts": copied,
        "limitations": limitations,
        "sensitive_scan": {"valid": True, "files_scanned": len(copied)},
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = sorted(path for path in output_dir.iterdir() if path.is_file() and path.name != "checksums.txt")
    (output_dir / "checksums.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    verification = verify_checksums(output_dir)
    (output_dir / "verification-report.md").write_text(
        "\n".join([
            "# Sentinel-X 证据包校验报告",
            "",
            f"- SHA-256 文件数：{verification['checked']}",
            f"- 校验结果：{'通过' if verification['valid'] else '失败'}",
            f"- 敏感扫描：通过（{len(copied)} 个产物）",
            "- 说明：该证据包只覆盖隔离 fixture，不代表真实 Kubernetes/PostgreSQL/观测栈运行。",
            "",
        ])
        + "\n",
        encoding="utf-8",
    )
    return manifest_path
