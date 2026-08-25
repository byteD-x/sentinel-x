from pathlib import Path

import pytest

from sentinel_x_evals.evidence_bundle import EvidenceBundleError, build_evidence_bundle, verify_checksums


def test_evidence_bundle_copies_artifacts_scans_and_verifies(tmp_path: Path):
    source = tmp_path / "scenario.json"
    source.write_text('{"status":"clean"}\n', encoding="utf-8")
    bundle = tmp_path / "bundle"

    manifest = build_evidence_bundle(
        bundle,
        {"scenario.json": source},
        commit_sha="a" * 40,
        profile="light-fixture",
        limitations=["fixture only"],
    )

    assert manifest.is_file()
    assert verify_checksums(bundle)["valid"] is True
    assert (bundle / "verification-report.md").is_file()


def test_evidence_bundle_rejects_secret_like_artifact(tmp_path: Path):
    source = tmp_path / "secret.json"
    source.write_text('{"authorization":"Bearer abcdefghijklmnop"}\n', encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="敏感"):
        build_evidence_bundle(
            tmp_path / "bundle",
            {"secret.json": source},
            commit_sha=None,
            profile="light-fixture",
            limitations=[],
        )
